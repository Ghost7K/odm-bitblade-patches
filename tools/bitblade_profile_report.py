#!/usr/bin/env python3
"""Patch 16 Auswertung: bitblade_profile_report.py <profil.csv> [...]
Fasst je Schritt zusammen (Dauer, mittlere/max. genutzte Kerne, iowait, RAM/Swap, Plattendurchsatz) und markiert Engpaesse:
  SERIELL  = < 25 % der Kerne bei > 10 min Dauer (Kandidat fuer Parallelisierung)
  IO       = iowait > 20 % (Platte bremst)
  SPEICHER = Swap > 5 GB (RAM zu knapp)
"""
import sys, collections

for path in sys.argv[1:]:
    rows = [l.rstrip("\n").split(";") for l in open(path) if not l.startswith("zeit;")]
    if not rows:
        continue
    n = int(rows[0][3])
    st = collections.OrderedDict()
    for r in rows:
        s = st.setdefault(r[1], {"n": 0, "k": [], "io": [], "ram": [], "swap": [], "rd": [], "wr": []})
        s["n"] += 1
        s["k"].append(float(r[2])); s["io"].append(float(r[4])); s["ram"].append(float(r[5])); s["swap"].append(float(r[6]))
        s["rd"].append(float(r[7])); s["wr"].append(float(r[8]))
    iv = 20
    tot = sum(s["n"] for s in st.values()) * iv / 3600
    print("== %s  (%d Kerne, %.1f h erfasst)" % (path, n, tot))
    print("%-34s %7s %6s %6s %6s %6s %7s %8s  %s" % ("Schritt", "Dauer", "Kerne", "max", "io%", "RAMmax", "Swapmax", "Plat MB/s", "Befund"))
    for k, s in sorted(st.items(), key=lambda kv: -kv[1]["n"]):
        d = s["n"] * iv / 60
        mk = sum(s["k"]) / len(s["k"]); io = sum(s["io"]) / len(s["io"])
        f = []
        if d > 10 and mk < 0.25 * n: f.append("SERIELL")
        if io > 20: f.append("IO")
        if max(s["swap"]) > 5: f.append("SPEICHER")
        print("%-34s %5.0fmin %6.1f %6.1f %6.1f %6.0f %7.0f %8.0f  %s" % (k[:34], d, mk, max(s["k"]), io, max(s["ram"]), max(s["swap"]),
              (sum(s["rd"]) + sum(s["wr"])) / len(s["rd"]), ",".join(f) or "ok"))
