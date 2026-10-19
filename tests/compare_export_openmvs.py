"""Labor P40: export_openmvs Original vs. Patch 40 mit aufzeichnendem Exporter vergleichen (gleiche Eingabe, gleicher Prozess).
Aufruf (im osfm-Baum mit P40): python3 cmp_openmvs.py <opensfm-dir> <pfad-zur-original-export_openmvs.py>"""
import hashlib, importlib.util, sys, time
import numpy as np
from opensfm import dataset, pydense

path, orig_file = sys.argv[1], sys.argv[2]


class Rec:
    def __init__(self):
        self.h = hashlib.sha256(); self.n = {"cam": 0, "shot": 0, "point": 0}

    def add_camera(self, cid, K, w, h):
        self.n["cam"] += 1; self.h.update(repr((cid, np.asarray(K).tobytes(), w, h)).encode())

    def add_shot(self, img, mask, sid, cid, R, o):
        self.n["shot"] += 1; self.h.update(repr((img, mask, sid, cid, np.asarray(R).tobytes(), np.asarray(o).tobytes())).encode())

    def add_point(self, X, shots):
        self.n["point"] += 1; self.h.update(np.asarray(X, np.float64).tobytes()); self.h.update(("|".join(shots) + ";").encode())

    def export(self, p):
        pass


data = dataset.DataSet(path); udata = data.undistorted_dataset()
recs = udata.load_undistorted_reconstruction(); tm = udata.load_undistorted_tracks_manager()
spec = importlib.util.spec_from_file_location("orig_export_openmvs", orig_file); orig = importlib.util.module_from_spec(spec); spec.loader.exec_module(orig)
from opensfm.actions import export_openmvs as p40

out = {}
for name, mod, args in [("p40", p40, (None, 48)), ("original", orig, (None,))]:
    r = Rec(); mod.pydense.OpenMVSExporter = lambda r=r: r
    t = time.time(); mod.export(recs[0], tm, udata, *args)
    out[name] = (r.n, r.h.hexdigest()); print(name, "%.0f s" % (time.time() - t), r.n, r.h.hexdigest()[:16], flush=True)
print("INHALT IDENTISCH" if out["p40"] == out["original"] else "INHALT ANDERS")
