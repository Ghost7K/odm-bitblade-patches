"""
bitblade-patch 3 (06.10.2026): parallele SMRF-Bodenklassifizierung fuer ODM 3.6.x.

Original-ODM ruft einen einzigen `pdal translate ... smrf` ueber die gesamte Punktwolke auf
(1 CPU-Kern, bei ~300 Mio. Punkten > 1 h). Hier:
  1. Punktwolke einmal in Kernkacheln (Kantenlaenge L) zerlegen (filters.splitter, ohne Puffer).
  2. Pro Kachel parallel: eigene Kachel (Core=1) + Nachbarkacheln (Core=0) lesen, auf
     Kachel + Puffer B zuschneiden, SMRF rechnen, nur Core=1-Punkte behalten.
     Puffer B = 2x SMRF-Fenster. Test 06.10.: Abweichung zum Gesamtlauf 0,8 % der Punkte,
     kleiner als die natuerliche SMRF-Streuung bei 0,37 m verschobenem Ausschnitt (2,2 %).
  3. Ergebnis zusammenfuehren, Punktzahl pruefen.
Bei jedem Fehler oder abweichender Punktzahl: Fallback auf den Original-Aufruf (unveraendertes Verhalten).
Abschalten: Umgebungsvariable BITBLADE_SMRF_PARALLEL=0.
"""
import os, json, math, shutil, subprocess, tempfile, glob
from concurrent.futures import ThreadPoolExecutor

try:
    from opendm import log
    def _info(m): log.ODM_INFO("[bitblade-smrf] " + m)
    def _warn(m): log.ODM_WARNING("[bitblade-smrf] " + m)
except Exception:  # Testbetrieb ausserhalb ODM
    def _info(m): print("[bitblade-smrf] " + m, flush=True)
    def _warn(m): print("[bitblade-smrf] WARN " + m, flush=True)


def _sh(args):
    r = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0:
        raise RuntimeError("%s -> rc %s: %s" % (args[:3], r.returncode, r.stderr[-500:]))
    return r.stdout


def _meta(f):
    m = json.loads(_sh(["pdal", "info", "--metadata", f]))["metadata"]
    return m["count"], m["minx"], m["miny"], m["maxx"], m["maxy"]


def _pipeline(stages, tmpdir):
    fd, p = tempfile.mkstemp(suffix=".json", dir=tmpdir)
    with os.fdopen(fd, "w") as f:
        json.dump({"pipeline": stages}, f)
    _sh(["pdal", "pipeline", p])
    os.remove(p)


def _original(fin, fout, scalar, slope, threshold, window):
    _sh(["pdal", "translate", "-i", fin, "-o", fout, "smrf", "--overwrite",
         "--filters.smrf.scalar=%s" % scalar, "--filters.smrf.slope=%s" % slope,
         "--filters.smrf.threshold=%s" % threshold, "--filters.smrf.window=%s" % window,
         "--writers.las.forward=scale,offset"])


def parallel_smrf(fin, fout, scalar, slope, threshold, window, workers=None, tile=None, buffer=None, tmp=None):
    window = float(window)
    B = float(buffer) if buffer else max(2.0 * window, 20.0)
    L = float(tile) if tile else max(2.5 * B, 100.0)
    workers = int(workers or os.cpu_count() or 4)
    total, minx, miny, maxx, maxy = _meta(fin)
    tmpdir = tempfile.mkdtemp(prefix="smrf_", dir=tmp or os.path.dirname(os.path.abspath(fout)))
    try:
        _info("%d Punkte, Kachel %.0f m, Puffer %.0f m, %d Threads" % (total, L, B, workers))
        # 1) Kernkacheln
        _pipeline([fin, {"type": "filters.splitter", "length": L, "origin_x": minx, "origin_y": miny},
                   {"type": "writers.las", "filename": os.path.join(tmpdir, "core_#.las"),
                    "forward": "all", "extra_dims": "all", "minor_version": 4}], tmpdir)
        cores = {}
        for f in glob.glob(os.path.join(tmpdir, "core_*.las")):
            n, x0, y0, _, _ = _meta(f)
            ix = int(math.floor((x0 - minx) / L + 1e-9)); iy = int(math.floor((y0 - miny) / L + 1e-9))
            if (ix, iy) in cores:
                raise RuntimeError("Kachelindex doppelt: %s" % ((ix, iy),))
            cores[(ix, iy)] = (f, n)
        _info("%d belegte Kacheln" % len(cores))
        nb = int(math.ceil(B / L))

        # 2) SMRF je Kachel
        def job(key):
            ix, iy = key
            f, n = cores[key]
            out = f.replace("core_", "out_")
            st = [{"type": "readers.las", "filename": f, "tag": "c"},
                  {"type": "filters.ferry", "dimensions": "=>BbCore", "inputs": ["c"], "tag": "cf"},
                  {"type": "filters.assign", "value": "BbCore = 1", "inputs": ["cf"], "tag": "ca"}]
            ins = ["ca"]
            for dx in range(-nb, nb + 1):
                for dy in range(-nb, nb + 1):
                    k = (ix + dx, iy + dy)
                    if (dx or dy) and k in cores:
                        t = "n%d_%d" % (dx + nb, dy + nb)
                        st += [{"type": "readers.las", "filename": cores[k][0], "tag": t},
                               {"type": "filters.ferry", "dimensions": "=>BbCore", "inputs": [t], "tag": t + "f"},
                               {"type": "filters.assign", "value": "BbCore = 0", "inputs": [t + "f"], "tag": t + "a"}]
                        ins.append(t + "a")
            x0 = minx + ix * L; y0 = miny + iy * L
            st += [{"type": "filters.merge", "inputs": ins, "tag": "m"},
                   {"type": "filters.crop", "bounds": "([%.4f,%.4f],[%.4f,%.4f])" % (x0 - B, x0 + L + B, y0 - B, y0 + L + B)},
                   {"type": "filters.smrf", "scalar": scalar, "slope": slope, "threshold": threshold, "window": window},
                   {"type": "filters.range", "limits": "BbCore[1:1]"},
                   {"type": "writers.las", "filename": out, "forward": "all", "minor_version": 4}]
            _pipeline(st, tmpdir)
            m = _meta(out)[0]
            if m != n:
                raise RuntimeError("Kachel %s: %d statt %d Punkte" % (key, m, n))
            return out

        # Patch 3b (11.10.2026): RAM-Budget statt blind alle Kacheln gleichzeitig. Datensatz A: 11 gleichzeitige SMRF-Jobs
        # = 182 GB RAM + ~90 GB Swap. Jeder Job reserviert vorab seinen geschaetzten Bedarf (Punkte im Ausschnitt
        # x BYTES_PER_PT); passt er nicht mehr ins Budget (75 % MemAvailable), wartet er. Ergebnis unveraendert.
        import threading
        bpp = float(os.environ.get("BITBLADE_SMRF_BPP", "130"))
        try:
            avail = int([l.split()[1] for l in open("/proc/meminfo") if l.startswith("MemAvailable")][0]) * 1024
        except Exception:
            avail = 64 << 30
        budget = float(os.environ.get("BITBLADE_SMRF_BUDGET_GB", "0")) * (1 << 30) or 0.75 * avail
        def need(key):   # PDAL liest die ganze 3x3-Nachbarschaft ein, bevor zugeschnitten wird
            ix, iy = key
            return bpp * sum(cores[(ix + dx, iy + dy)][1] for dx in range(-nb, nb + 1) for dy in range(-nb, nb + 1)
                             if (ix + dx, iy + dy) in cores)

        cond = threading.Condition(); used = [0.0]

        def job_budget(key):
            n = min(need(key), budget)
            with cond:
                while used[0] > 0 and used[0] + n > budget:
                    cond.wait()
                used[0] += n
            try:
                return job(key)
            finally:
                with cond:
                    used[0] -= n
                    cond.notify_all()

        keys = sorted(cores)
        _info("RAM-Budget %.0f GB, groesster Job geschaetzt %.0f GB" % (budget / 2**30, max(need(k) for k in keys) / 2**30))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            outs = list(ex.map(job_budget, keys))

        # 3) Zusammenfuehren (wie Original: forward=scale,offset)
        tmpout = os.path.join(tmpdir, "merged" + os.path.splitext(fout)[1])
        _sh(["pdal", "merge"] + outs + [tmpout, "--writers.las.forward=scale,offset"])
        m = _meta(tmpout)[0]
        if m != total:
            raise RuntimeError("Gesamt: %d statt %d Punkte" % (m, total))
        shutil.move(tmpout, fout)
        _info("fertig, %d Punkte" % m)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def run(fin, fout, scalar, slope, threshold, window):
    if os.environ.get("BITBLADE_SMRF_PARALLEL", "1") != "0":
        try:
            return parallel_smrf(fin, fout, scalar, slope, threshold, window)
        except Exception as e:
            _warn("parallel fehlgeschlagen (%s) -> Original-SMRF" % e)
    _original(fin, fout, scalar, slope, threshold, window)


if __name__ == "__main__":  # Test: bitblade_smrf.py in out scalar slope threshold window [workers]
    import sys
    a = sys.argv[1:]
    parallel_smrf(a[0], a[1], a[2], a[3], a[4], a[5], workers=(a[6] if len(a) > 6 else None))
