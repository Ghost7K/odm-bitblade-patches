"""Bitblade Patch 40 (11.10.2026): Hilfsfunktion fuer OpenSfM-Exporte auf allen Kernen.

forkmap(fn, n_items, procs) teilt range(n_items) in zusammenhaengende Bloecke und rechnet sie in
geforkten Prozessen. Die Prozesse erben alle bereits geladenen Daten (Rekonstruktion, TracksManager)
ohne Kopieren (copy-on-write). Ergebnisse kommen in der Original-Reihenfolge zurueck -> Ausgaben
bleiben bitgleich zum seriellen Original.

Abschalten: Datei /var/www/data/bitblade_p40_aus oder BITBLADE_P40=0 -> serielle Ausfuehrung im
selben Prozess (gleiches Ergebnis, nur langsamer).
"""
import multiprocessing as mp
import os

_FN = None


def enabled():
    return os.environ.get("BITBLADE_P40", "1") != "0" and not os.path.exists("/var/www/data/bitblade_p40_aus")


def procs(cfg_processes=None):
    n = os.cpu_count() or 1
    if cfg_processes:
        n = min(n, int(cfg_processes))
    return max(1, n)


def _run(rng):
    return _FN(rng[0], rng[1])


def forkmap(fn, n_items, nproc, min_chunk=20000):
    """fn(start, stop) -> Ergebnis eines Blocks. Liefert Liste der Block-Ergebnisse in Reihenfolge."""
    global _FN
    if n_items == 0:
        return []
    if not enabled() or nproc <= 1 or n_items < 2 * min_chunk:
        return [fn(0, n_items)]
    nchunks = min(nproc * 4, max(1, n_items // min_chunk))
    step = (n_items + nchunks - 1) // nchunks
    ranges = [(a, min(a + step, n_items)) for a in range(0, n_items, step)]
    _FN = fn
    ctx = mp.get_context("fork")
    with ctx.Pool(min(nproc, len(ranges))) as pool:
        out = pool.map(_run, ranges, chunksize=1)
    _FN = None
    return out
