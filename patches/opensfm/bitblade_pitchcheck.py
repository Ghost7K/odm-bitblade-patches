#!/usr/bin/env python3
"""
bitblade-patch 11 (08.10.2026): Pitch-Pruefung nach OpenSfM reconstruct.

Problem (Datensaetze A und B): einzelne Fotos (v. a. Horizont-/Schraegfotos
mit wenig Ueberlappung) bekommen in der Rekonstruktion eine um 40-80 Grad falsche Neigung.
Ihre Tiefenkarten erzeugen dann "Geister"-Gebaeude weit unter/neben dem Modell.

Pruefung: berechnete Neigung der optischen Achse (Topozentrik, z oben) gegen die
Gimbal-Neigung aus den XMP-Daten des Fotos (DJI: GimbalPitchDegree). Fotos mit
|Abweichung| > MAX_DEG werden aus reconstruction.json entfernt -> nicht in Undistort/
Densify/Texturierung. Sicherung: reconstruction.json.vor_pitchcheck.
Schutz: werden mehr als MAX_SHARE der Fotos auffaellig, wird nichts entfernt (Verdacht
auf abweichende XMP-Semantik) - nur Warnung.
Abschalten: Datei /var/www/data/bitblade_pitchcheck_aus.

bitblade-patch 46 (13.10.2026): zusaetzlich Lage- und Richtungspruefung (Ursache der Geister in Datensatz A: 15 Fotos
24-36 m versetzt bzw. um ~145 Grad verdreht, Pitch unauffaellig). Je Flugsegment (Zeitluecke > 90 s) wird der
Median-Versatz Kamera-GPS abgezogen; Fotos mit Rest-Lagefehler > BB_POSE_MAX_M (8 m, horizontal oder vertikal) oder
- bei Schraegfotos - Gier-Abweichung > BB_YAW_MAX_DEG (30 Grad) zur Gimbal-Gier werden ebenfalls entfernt.
Segmente < 10 Fotos werden fuer die Lage nicht bewertet. BB_POSE_DRYRUN=1: nur berichten.
Abschalten nur Lage/Richtung: /var/www/data/bitblade_posecheck_aus.
"""
import json, math, os, re, shutil, sys

MAX_DEG = float(os.environ.get("BB_PITCH_MAX_DEG", "10"))
MAX_SHARE = float(os.environ.get("BB_PITCH_MAX_SHARE", "0.15"))
POSE_MAX_M = float(os.environ.get("BB_POSE_MAX_M", "8"))
YAW_MAX_DEG = float(os.environ.get("BB_YAW_MAX_DEG", "30"))
DRYRUN = os.environ.get("BB_POSE_DRYRUN") == "1"


def xmp_yaw(path):
    try:
        with open(path, "rb") as f:
            b = f.read(200000).decode("latin1")
    except OSError:
        return None
    m = re.search(r'GimbalYawDegree="([-+0-9.]+)"', b) or re.search(r"<drone-dji:GimbalYawDegree>([-+0-9.]+)<", b)
    return float(m.group(1)) if m else None


def pose_check(osfm_dir, rec, paths):
    """Patch 46: [(ri, name, grund)] fuer Fotos mit grobem Lage- oder Gierfehler."""
    if os.path.exists("/var/www/data/bitblade_posecheck_aus"):
        print("[bitblade] Lage-/Richtungspruefung abgeschaltet"); return []
    lla = json.load(open(os.path.join(osfm_dir, "reference_lla.json")))
    la0, lo0, h0 = math.radians(lla["latitude"]), math.radians(lla["longitude"]), lla["altitude"]
    a, e2 = 6378137.0, 6.69437999014e-3
    def ecef(la, lo, h):
        la, lo = math.radians(la), math.radians(lo); N = a / math.sqrt(1 - e2 * math.sin(la) ** 2)
        return ((N + h) * math.cos(la) * math.cos(lo), (N + h) * math.cos(la) * math.sin(lo), (N * (1 - e2) + h) * math.sin(la))
    O = ecef(lla["latitude"], lla["longitude"], h0)
    E = (-math.sin(lo0), math.cos(lo0), 0.0)
    Nn = (-math.sin(la0) * math.cos(lo0), -math.sin(la0) * math.sin(lo0), math.cos(la0))
    U = (math.cos(la0) * math.cos(lo0), math.cos(la0) * math.sin(lo0), math.sin(la0))
    def enu(la, lo, h):
        p = ecef(la, lo, h); d = [p[i] - O[i] for i in range(3)]
        return [sum(d[i] * v[i] for i in range(3)) for v in (E, Nn, U)]
    rows = []
    for ri, r in enumerate(rec):
        for name, shot in r.get("shots", {}).items():
            try:
                ex = json.load(open(os.path.join(osfm_dir, "exif", name + ".exif")))
                g = ex.get("gps") or {}
                if "latitude" not in g or "altitude" not in g: continue
                t = float(ex.get("capture_time") or 0)
            except Exception:
                continue
            R = rodrigues(shot["rotation"]); tv = shot["translation"]
            C = [-(R[0][i] * tv[0] + R[1][i] * tv[1] + R[2][i] * tv[2]) for i in range(3)]
            G = enu(g["latitude"], g["longitude"], g["altitude"])
            ax = R[2]; az = math.degrees(math.atan2(ax[0], ax[1])) % 360
            pr = math.degrees(math.asin(max(-1.0, min(1.0, ax[2]))))
            img = paths.get(name, os.path.join(osfm_dir, "images", name))
            rows.append(dict(ri=ri, n=name, t=t, d=[C[i] - G[i] for i in range(3)], az=az, pr=pr,
                             xp=xmp_pitch(img), xy=xmp_yaw(img)))
    if len(rows) < 10:
        return []
    rows.sort(key=lambda x: x["t"]); seg = 0; last = None
    for x in rows:
        if last is not None and x["t"] - last > 90: seg += 1
        x["seg"] = seg; last = x["t"]
    med = lambda v: sorted(v)[len(v) // 2]
    bad = []
    segs = {}
    for x in rows: segs.setdefault(x["seg"], []).append(x)
    for sl in segs.values():
        if len(sl) < 10: continue
        m = [med([x["d"][i] for x in sl]) for i in range(3)]
        for x in sl:
            dh = math.hypot(x["d"][0] - m[0], x["d"][1] - m[1]); dv = abs(x["d"][2] - m[2])
            if dh > POSE_MAX_M or dv > POSE_MAX_M:
                bad.append((x["ri"], x["n"], "Lage %.1f m / Hoehe %.1f m" % (dh, dv)))
    # Gier: je Segment gegen den Segment-Median (Kompass/Gimbal-Gier hat je Flug einen eigenen Versatz, v4: bis 47 Grad)
    dif = lambda x: (x["az"] - x["xy"] + 180) % 360 - 180
    seen = set(n for _, n, _ in bad)
    for sl in segs.values():
        obl = [x for x in sl if x["xp"] is not None and x["xy"] is not None and -80 < x["xp"] <= -10]
        if len(obl) < 10: continue
        # Kreis-Median: Versatz als Mittelwert der Einheitsvektoren, dann robust nachziehen
        sx = sum(math.sin(math.radians(dif(x))) for x in obl); cx = sum(math.cos(math.radians(dif(x))) for x in obl)
        off = math.degrees(math.atan2(sx, cx))
        off = off + med([(dif(x) - off + 180) % 360 - 180 for x in obl])
        for x in obl:
            r = (dif(x) - off + 180) % 360 - 180
            if abs(r) > YAW_MAX_DEG and x["n"] not in seen:
                bad.append((x["ri"], x["n"], "Gier %.0f Grad" % r)); seen.add(x["n"])
    print("[bitblade] Lage-/Richtungspruefung: %d Fotos, %d Segmente, %d auffaellig (> %.0f m bzw. > %.0f Grad)"
          % (len(rows), len(segs), len(bad), POSE_MAX_M, YAW_MAX_DEG))
    for _, n, w in bad[:50]: print("[bitblade]   %s %s" % (n, w))
    return bad


def rodrigues(r):
    t = math.sqrt(sum(x * x for x in r))
    if t < 1e-12:
        return [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    k = [x / t for x in r]
    c, s, v = math.cos(t), math.sin(t), 1 - math.cos(t)
    kx, ky, kz = k
    return [[c + kx * kx * v, kx * ky * v - kz * s, kx * kz * v + ky * s],
            [ky * kx * v + kz * s, c + ky * ky * v, ky * kz * v - kx * s],
            [kz * kx * v - ky * s, kz * ky * v + kx * s, c + kz * kz * v]]


def xmp_pitch(path):
    try:
        with open(path, "rb") as f:
            b = f.read(200000).decode("latin1")
    except OSError:
        return None
    m = re.search(r'GimbalPitchDegree="([-+0-9.]+)"', b) or \
        re.search(r"<drone-dji:GimbalPitchDegree>([-+0-9.]+)<", b)
    return float(m.group(1)) if m else None


def fit_tilt(rows):
    """Systematische Modellneigung schaetzen: dev = c + a*sin(yaw) + b*cos(yaw) (kleinste Quadrate, 3x3)."""
    n = len(rows)
    if n < 8:
        return (0.0, 0.0, 0.0)
    X = [(1.0, math.sin(y), math.cos(y)) for _, _, _, _, y, _ in rows]
    Y = [d for _, _, _, _, _, d in rows]
    A = [[sum(X[k][i] * X[k][j] for k in range(n)) for j in range(3)] for i in range(3)]
    v = [sum(X[k][i] * Y[k] for k in range(n)) for i in range(3)]
    # Gauss-Elimination
    M = [A[i] + [v[i]] for i in range(3)]
    for i in range(3):
        piv = max(range(i, 3), key=lambda r: abs(M[r][i]))
        M[i], M[piv] = M[piv], M[i]
        if abs(M[i][i]) < 1e-9:
            return (0.0, 0.0, 0.0)
        for r in range(3):
            if r != i:
                f = M[r][i] / M[i][i]
                M[r] = [M[r][c] - f * M[i][c] for c in range(4)]
    return tuple(M[i][3] / M[i][i] for i in range(3))


def main(osfm_dir):
    if os.path.exists("/var/www/data/bitblade_pitchcheck_aus"):
        print("[bitblade] Pitch-Pruefung abgeschaltet")
        return 0
    rec_p = os.path.join(osfm_dir, "reconstruction.json")
    rec = json.load(open(rec_p))
    paths = {}
    il = os.path.join(osfm_dir, "image_list.txt")
    if os.path.exists(il):
        for line in open(il, encoding="utf-8", errors="surrogateescape"):
            p = line.strip()
            if p:
                paths[os.path.basename(p)] = p
    total, nox, rows = 0, 0, []
    for ri, r in enumerate(rec):
        for name, shot in r.get("shots", {}).items():
            total += 1
            xp = xmp_pitch(paths.get(name, os.path.join(osfm_dir, "images", name)))
            if xp is None:
                nox += 1
                continue
            R = rodrigues(shot["rotation"])
            ax = R[2]  # optische Achse in Weltkoordinaten (Topozentrik, z oben)
            pr = math.degrees(math.asin(max(-1.0, min(1.0, ax[2]))))
            yaw = math.atan2(ax[0], ax[1])
            rows.append((ri, name, xp, pr, yaw, pr - xp))
    if not rows:
        print("[bitblade] Pitch-Pruefung: keine XMP-Neigung vorhanden")
        return 0
    zeros = sum(1 for r in rows if r[2] == 0.0)
    if zeros > 0.5 * len(rows):
        print("[bitblade] Pitch-Pruefung uebersprungen: %d/%d Fotos mit Gimbal-Neigung 0.0 (Kamera schreibt keine Neigung)"
              % (zeros, len(rows)))
        return 0
    # nur echte Schraeg-/Nadirfotos fuer die Neigungsschaetzung (Gimbal <= -10 und > -85: Gier definiert)
    fitrows = [r for r in rows if -85 < r[2] <= -10]

    def resid(r, m):
        c, a, b = m
        e = c + a * math.sin(r[4]) + b * math.cos(r[4]) if -85 < r[2] <= -10 else c
        return r[5] - e

    # robust: anpassen, Ausreisser weglassen, erneut anpassen
    model = fit_tilt(fitrows)
    for _ in range(3):
        inl = [r for r in fitrows if abs(resid(r, model)) <= MAX_DEG]
        model = fit_tilt(inl)
    n_fit = sum(1 for r in rows if abs(resid(r, model)) > MAX_DEG)
    n_raw = sum(1 for r in rows if abs(r[5]) > MAX_DEG)
    if n_raw <= n_fit:
        model = (0.0, 0.0, 0.0)  # Korrektur bringt nichts -> Rohvergleich
    c, a, b = model
    tilt = math.hypot(a, b)
    print("[bitblade] Pitch-Pruefung: %d Fotos, %d ohne XMP; systematisch: Versatz %.1f Grad, Modellneigung %.1f Grad"
          % (total, nox, c, tilt))
    bad = []
    for r in rows:
        if abs(resid(r, model)) > MAX_DEG:
            bad.append((r[0], r[1], r[2], r[3]))
    print("[bitblade] Pitch-Pruefung: %d Fotos mit Abweichung > %.0f Grad (nach Abzug der systematischen Neigung)"
          % (len(bad), MAX_DEG))
    try:
        pb = pose_check(osfm_dir, rec, paths)
    except Exception as e:
        print("[bitblade] Lage-/Richtungspruefung Fehler (ignoriert): %s" % e); pb = []
    have = set(n for _, n, _, _ in bad)
    for ri, n, w in pb:
        if n not in have: bad.append((ri, n, float("nan"), float("nan"))); have.add(n)
    if DRYRUN:
        print("[bitblade] Probelauf (BB_POSE_DRYRUN): %d Fotos waeren entfernt worden - nichts geaendert" % len(bad)); return 0
    if tilt > 5:
        print("[bitblade] HINWEIS: Gesamtmodell wirkt um %.1f Grad geneigt (Ausrichtung pruefen)" % tilt)
    for _, n, xp, pr in bad[:50]:
        print("[bitblade]   %s Gimbal %.1f, berechnet %.1f" % (n, xp, pr))
    if not bad:
        return 0
    if len(bad) > MAX_SHARE * len(rows):
        print("[bitblade] WARNUNG: zu viele Abweichungen (%d) - nichts entfernt (XMP-Semantik pruefen)" % len(bad))
        return 0
    shutil.copy(rec_p, rec_p + ".vor_pitchcheck")
    removed = set()
    for ri, n, _, _ in bad:
        rec[ri]["shots"].pop(n, None)
        removed.add(n)
    # Punkte ohne verbleibende Beobachtung entfernen (sonst "Accessing invalid track ID" beim Export).
    # 08.10.2026: tracks.csv ist im ODM-OpenSfM BINAER (OPENSFM_TRACKS_VERSION_v102). Die fruehere Textauswertung fand
    # keine Spuren und loeschte ALLE Punkte (Datensatz D: Auftrag fehlgeschlagen; Datensatz E: Abbruch mit UTF-8-Fehler).
    # Jetzt ueber den TracksManager von OpenSfM; bei Fehler oder unplausibel vielen Loeschungen wird NICHTS geaendert.
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from opensfm import dataset
        tm = dataset.DataSet(osfm_dir).load_tracks_manager()
        total_pts = sum(len(r.get("points", {})) for r in rec)
        drops, dropped = [], 0
        for r in rec:
            keep = set()
            for sname in r.get("shots", {}):
                keep.update(tm.get_shot_observations(sname).keys())
            drop = [pid for pid in r.get("points", {}) if pid not in keep]
            drops.append(drop)
            dropped += len(drop)
        if total_pts and dropped > MAX_SHARE * total_pts:
            raise RuntimeError("unplausibel: %d von %d Punkten waeren entfernt worden" % (dropped, total_pts))
        for r, drop in zip(rec, drops):
            for pid in drop:
                del r["points"][pid]
        print("[bitblade] %d von %d Punkten ohne verbleibende Beobachtung entfernt" % (dropped, total_pts))
    except Exception as e:
        print("[bitblade] Pitch-Pruefung: Punktbereinigung nicht moeglich (%s) - NICHTS entfernt, Rekonstruktion unveraendert" % e)
        return 0
    # Teilrekonstruktionen ohne Fotos entfernen
    rec = [r for r in rec if len(r.get("shots", {})) > 0]
    with open(rec_p, "w") as f:
        json.dump(rec, f, indent=4)
    with open(os.path.join(osfm_dir, "bitblade_pitch_entfernt.txt"), "w") as f:
        f.write("\n".join("%s\t%.1f\t%.1f" % (n, xp, pr) for _, n, xp, pr in bad) + "\n")
    print("[bitblade] %d Fotos aus der Rekonstruktion entfernt" % len(bad))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1]))
    except Exception as e:
        print("[bitblade] Pitch-Pruefung Fehler (ignoriert): %s" % e)
        sys.exit(0)
