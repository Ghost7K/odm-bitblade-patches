#!/usr/bin/env python3
"""Bitblade Patch 40c (11.10.2026): ODM-Stufe "dataset" liest die Bild-Metadaten (EXIF/XMP) auf allen Kernen.

Original: Schleife `types.ODM_Photo(f)` Bild fuer Bild (reines Python, v3: ~2 min auf 1 Kern).
Neu: vorab in einem Prozess-Pool (fork) einlesen, Reihenfolge und Fehlerbehandlung unveraendert:
ein beschaedigtes Bild loest in der Original-Schleife weiterhin PhotoCorruptedException aus (dort neu gelesen).
Aufruf: bitblade_dataset_patch.py <pfad zu stages/dataset.py>   (idempotent)
Not-Aus zur Laufzeit: /var/www/data/bitblade_p40_aus
"""
import sys

p = sys.argv[1]
s = open(p).read()
if "bitblade Patch 40c" in s:
    print("bereits gepatcht"); sys.exit(0)
old = """                photos = []
                with open(tree.dataset_list, 'w') as dataset_list:
                    log.ODM_INFO("Loading %s images" % len(path_files))
                    for f in path_files:
                        try:
                            p = types.ODM_Photo(f)"""
new = """                photos = []
                # bitblade Patch 40c: Metadaten parallel vorab lesen (Reihenfolge/Fehler wie Original)
                _bb_pre = {}
                if not os.path.exists('/var/www/data/bitblade_p40_aus') and len(path_files) > 64:
                    try:
                        import multiprocessing as _mp
                        from opendm.bitblade_photos import read as _bb_read
                        with _mp.get_context('fork').Pool(min(os.cpu_count() or 1, 32)) as _pool:
                            _bb_pre = dict(zip(path_files, _pool.map(_bb_read, path_files, chunksize=16)))
                        log.ODM_INFO("[bitblade] Metadaten von %s Bildern parallel gelesen" % len(path_files))
                    except Exception as _e:
                        log.ODM_WARNING("[bitblade] paralleles Lesen fehlgeschlagen (%s), seriell" % _e)
                        _bb_pre = {}
                with open(tree.dataset_list, 'w') as dataset_list:
                    log.ODM_INFO("Loading %s images" % len(path_files))
                    for f in path_files:
                        try:
                            p = _bb_pre.get(f) or types.ODM_Photo(f)"""
assert s.count(old) == 1, "Stelle nicht gefunden"
s = s.replace(old, new)
open(p, "w").write(s)
print("Patch 40c angewendet")
