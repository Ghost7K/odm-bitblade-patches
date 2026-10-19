import logging
import os

from opensfm import io
from opensfm import stats
from opensfm.dataset import DataSet

# Bitblade Patch 40 (11.10.2026): Die Kennzahlen (stats.json) rechnet ein geforkter Prozess, waehrend der
# Hauptprozess die Diagramme in Original-Reihenfolge zeichnet -> gleiche Dateien (Heatmap/Draufsicht beruhen
# wie im Original auf zufaelliger Ausduennung). Merkmalszahlen werden aus dem npz-Kopf gelesen statt alle
# Merkmale zu entpacken (gleicher Wert). Not-Aus: /var/www/data/bitblade_p40_aus.
try:
    from opensfm.bitblade_forkmap import enabled as _p40
except Exception:
    _p40 = lambda: False

logger: logging.Logger = logging.getLogger(__name__)
logging.getLogger('matplotlib.font_manager').disabled = True


def _count_features_fast():
    """features_statistics zaehlt nur len(points) je Bild: Kopf der npz lesen statt alles zu entpacken."""
    import numpy as np
    import zipfile
    from concurrent.futures import ThreadPoolExecutor
    from opensfm import feature_loader
    orig = feature_loader.instance.load_all_data

    def count(data, im):
        p = data._feature_file(im) if hasattr(data, "_feature_file") else None
        if not p or not os.path.isfile(p):
            return None
        try:
            with zipfile.ZipFile(p) as z:
                with z.open("points.npy") as f:
                    v = np.lib.format.read_magic(f)
                    shape = np.lib.format._read_array_header(f, v)[0]
            return shape[0]
        except Exception:
            return None

    def features_statistics(data, tracks_manager, reconstructions):
        images = list({s for r in reconstructions for s in r.shots})
        with ThreadPoolExecutor(16) as ex:
            counts = list(ex.map(lambda im: count(data, im), images))
        if any(c is None for c in counts):  # Format unbekannt -> Original
            return _orig_fs(data, tracks_manager, reconstructions)

        class _F:  # Platzhalter mit len(points)
            def __init__(self, n):
                self.points = range(n)

        cache = {im: _F(c) for im, c in zip(images, counts) if c > 0}
        feature_loader.instance.load_all_data = lambda d, im, *a, **k: cache.get(im)
        try:
            return _orig_fs(data, tracks_manager, reconstructions)
        finally:
            feature_loader.instance.load_all_data = orig

    _orig_fs = stats.features_statistics
    stats.features_statistics = features_statistics


def run_dataset(data: DataSet, diagram_max_points: int=-1) -> None:
    """Compute various staistics of a datasets and write them to 'stats' folder

    Args:
        data: dataset object

    """
    reconstructions = data.load_reconstruction()
    tracks_manager = data.load_tracks_manager()

    output_path = os.path.join(data.data_path, "stats")
    data.io_handler.mkdir_p(output_path)

    if not _p40():
        return _run_serial(data, tracks_manager, reconstructions, output_path, diagram_max_points)

    _count_features_fast()

    # Kennzahlen (schwerster Teil, ohne Diagramme) in einem geforkten Prozess; die Diagramme laufen im Hauptprozess
    # in exakt der Original-Reihenfolge (matplotlib-Zustand wie Figurgroesse wird zwischen den Diagrammen vererbt).
    import pickle
    rfd, wfd = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(rfd)
        rc = 0
        try:
            d = pickle.dumps(stats.compute_all_statistics(data, tracks_manager, reconstructions))
            with os.fdopen(wfd, "wb") as w:
                w.write(d)
        except BaseException:
            logger.exception("compute_statistics: Kennzahlen")
            rc = 1
        os._exit(rc)
    os.close(wfd)
    stats.save_residual_grids(data, tracks_manager, reconstructions, output_path, data.io_handler)
    stats.save_matchgraph(data, tracks_manager, reconstructions, output_path, data.io_handler)
    with os.fdopen(rfd, "rb") as r:
        raw = r.read()
    _, st = os.waitpid(pid, 0)
    if st != 0 or not raw:
        raise RuntimeError("compute_statistics: Kennzahlen-Prozess fehlgeschlagen")
    stats_dict = pickle.loads(raw)
    stats.save_residual_histogram(stats_dict, output_path, data.io_handler)

    if diagram_max_points > 0:
        stats.decimate_points(reconstructions, diagram_max_points)

    stats.save_heatmap(data, tracks_manager, reconstructions, output_path, data.io_handler)
    stats.save_topview(data, tracks_manager, reconstructions, output_path, data.io_handler)

    with data.io_handler.open_wt(os.path.join(output_path, "stats.json")) as fout:
        io.json_dump(stats_dict, fout)


def _run_serial(data, tracks_manager, reconstructions, output_path, diagram_max_points):
    stats_dict = stats.compute_all_statistics(data, tracks_manager, reconstructions)

    stats.save_residual_grids(
        data, tracks_manager, reconstructions, output_path, data.io_handler
    )
    stats.save_matchgraph(
        data, tracks_manager, reconstructions, output_path, data.io_handler
    )
    stats.save_residual_histogram(stats_dict, output_path, data.io_handler)

    if diagram_max_points > 0:
        stats.decimate_points(reconstructions, diagram_max_points)

    stats.save_heatmap(
        data, tracks_manager, reconstructions, output_path, data.io_handler
    )
    stats.save_topview(
        data, tracks_manager, reconstructions, output_path, data.io_handler
    )

    with data.io_handler.open_wt(os.path.join(output_path, "stats.json")) as fout:
        io.json_dump(stats_dict, fout)
