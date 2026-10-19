"""Bitblade Patch 40c (11.10.2026): Hilfsfunktion fuer paralleles Lesen der Bild-Metadaten (stages/dataset.py)."""
from opendm import types


def read(fp):
    try:
        return types.ODM_Photo(fp)
    except Exception:
        return None   # Original-Schleife liest dieses Bild erneut und behandelt den Fehler wie bisher
