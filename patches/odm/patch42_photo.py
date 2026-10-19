"""Bitblade Patch 42 (11.10.2026): ODM bricht ab, wenn exifread die DJI-MakerNote eines einzelnen Bildes nicht lesen kann.

Befund (Forum 26034, DJI M3E, 253 Bilder): ein Bild (DJI_20260401160350_0101_V.jpg) hat ein defektes MakerNote-Feld
(Tag 0x3B9A); exifread 3.5.1 wirft mit details=True IndexError -> "Cannot process dataset" fuer den ganzen Auftrag.
Fix: exifread.process_file mit details=True versuchen; bei Fehler erneut mit details=False (ohne MakerNote) lesen und
warnen. Aus der MakerNote nutzt ODM nur SpeedX/Y/Z; dafuer liest photo.py bereits die XMP-Werte FlightX/Y/ZSpeed.
Fuer alle lesbaren Bilder aendert sich nichts (gleicher Aufruf wie vorher).
Aufruf: python3 patch42_photo.py /code/opendm/photo.py
"""
import sys
p = sys.argv[1]
s = open(p).read()
old = "            tags = exifread.process_file(f, details=True, extract_thumbnail=False)\n"
new = ("            # bitblade Patch 42: defekte MakerNote (z. B. DJI) darf nicht den ganzen Auftrag abbrechen\n"
       "            try:\n"
       "                tags = exifread.process_file(f, details=True, extract_thumbnail=False)\n"
       "            except Exception as _bb_e:\n"
       "                log.ODM_WARNING(\"[bitblade] %s: EXIF-MakerNote nicht lesbar (%s: %s), lese ohne MakerNote\" % (_path_file, type(_bb_e).__name__, _bb_e))\n"
       "                f.seek(0)\n"
       "                tags = exifread.process_file(f, details=False, extract_thumbnail=False)\n")
if "bitblade Patch 42" in s:
    print("schon gepatcht"); sys.exit(0)
assert s.count(old) == 1, "Zeile nicht gefunden"
open(p, "w").write(s.replace(old, new))
print("Patch 42 eingespielt")
