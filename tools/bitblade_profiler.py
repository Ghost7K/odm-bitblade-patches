#!/usr/bin/env python3
"""
bitblade-patch 16 (08.10.2026): Auslastungs-Profil eines ODM-Laufs (Ziel: jeden Prozessschritt gegen die
Auslastung vergleichen, um Engpaesse zu finden). Laeuft im NodeODM-Container, alle INTERVAL Sekunden eine Zeile CSV:
  zeit, schritt (Programm + Unterbefehl des rechenstaerksten ODM-Prozesses), kerne_genutzt (von N), iowait_%,
  ram_gb, swap_gb, disk_lesen_mb_s, disk_schreiben_mb_s, prozesse (Top 3: name:kerne:rss_gb)
Auswertung: bitblade_profile_report.py. Datei: /var/www/data/bitblade_profile.csv. Nur /proc, keine Abhaengigkeiten.
"""
import os, re, sys, time

OUT = sys.argv[1] if len(sys.argv) > 1 else "/var/www/data/bitblade_profile.csv"
INTERVAL = float(os.environ.get("BB_PROFILE_INTERVAL", "20"))
HZ = os.sysconf("SC_CLK_TCK")
NCPU = os.cpu_count()
DISK = re.compile(r"^(sd[a-z]+|vd[a-z]+|nvme\d+n\d+)$")
SKIP = {"bitblade_profiler.py", "sh", "bash", "sleep", "node", "tail", "ps", "top"}


def cpu_times():
    with open("/proc/stat") as f:
        v = list(map(int, f.readline().split()[1:]))
    return sum(v), v[3] + v[4], v[4]  # total, idle+iowait, iowait


def disk():
    r = w = 0
    with open("/proc/diskstats") as f:
        for l in f:
            p = l.split()
            if len(p) > 9 and DISK.match(p[2]):
                r += int(p[5]); w += int(p[9])
    return r * 512, w * 512


def mem():
    m = {}
    with open("/proc/meminfo") as f:
        for l in f:
            k, v = l.split(":"); m[k] = int(v.split()[0])
    return (m["MemTotal"] - m["MemAvailable"]) / 2**20, (m.get("SwapTotal", 0) - m.get("SwapFree", 0)) / 2**20


def procs():
    out = {}
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/stat") as f:
                s = f.read()
            name = s[s.index("(") + 1:s.rindex(")")]
            rest = s[s.rindex(")") + 2:].split()
            t = int(rest[11]) + int(rest[12])
            rss = int(rest[21]) * 4096
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                cmd = f.read().split(b"\0")
            out[pid] = (name, t, rss, cmd)
        except Exception:
            pass
    return out


def label(name, cmd):
    args = [c.decode(errors="replace") for c in cmd if c]
    base = os.path.basename(args[0]) if args else name
    if base.startswith("python") and len(args) > 1:
        base = os.path.basename(args[1])
        if base in ("opensfm", "opensfm.real", "opensfm_main.py") and len(args) > 2:
            return "opensfm " + args[2]
        if base == "run.py":
            return "odm"
    if base in ("opensfm", "opensfm.real") and len(args) > 1:
        return "opensfm " + args[1]
    return base.replace(".real", "")


def main():
    new = not os.path.exists(OUT)
    f = open(OUT, "a", buffering=1)
    if new:
        f.write("zeit;schritt;kerne_genutzt;kerne_gesamt;iowait_pct;ram_gb;swap_gb;disk_lesen_mb_s;disk_schreiben_mb_s;top3\n")
    t0, i0, w0 = cpu_times(); r0, wr0 = disk(); p0 = procs(); ts0 = time.time()
    while True:
        time.sleep(INTERVAL)
        t1, i1, w1 = cpu_times(); r1, wr1 = disk(); p1 = procs(); ts1 = time.time()
        dt = max(1e-3, ts1 - ts0); dtot = max(1, t1 - t0)
        used = (dtot - (i1 - i0)) / dtot * NCPU
        iow = (w1 - w0) / dtot * 100
        agg = {}
        for pid, (name, t, rss, cmd) in p1.items():
            if name in SKIP and not (cmd and b"opensfm" in b" ".join(cmd)):
                continue
            dtp = t - p0[pid][1] if pid in p0 else 0
            lab = label(name, cmd)
            a = agg.setdefault(lab, [0.0, 0])
            a[0] += dtp / HZ / dt; a[1] += rss
        top = sorted(agg.items(), key=lambda kv: -kv[1][0])[:3]
        step = top[0][0] if top and top[0][1][0] > 0.2 else "-"
        ram, swap = mem()
        f.write("%s;%s;%.1f;%d;%.1f;%.1f;%.1f;%.0f;%.0f;%s\n" % (
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), step, used, NCPU, iow, ram, swap,
            (r1 - r0) / dt / 2**20, (wr1 - wr0) / dt / 2**20,
            " ".join("%s:%.1f:%.1f" % (k, v[0], v[1] / 2**30) for k, v in top)))
        t0, i0, w0, r0, wr0, p0, ts0 = t1, i1, w1, r1, wr1, p1, ts1


if __name__ == "__main__":
    main()
