"""
bitblade-patch 34 (10.10.2026): Arbeitsprozess fuer die Bild-Entzerrung. Wird von opensfm/undistort.py
(_bb_parallel_undistort) als eigener Python-Prozess gestartet, damit vor dem fork() noch kein OpenCV-Threadpool
existiert (fork nach OpenCV-Nutzung blockiert sonst die Kinder - im Labor beobachtet).
Aufruf: python3 bitblade_undistort_worker.py <aufgaben.json>
"""
import sys, os, json, multiprocessing as mp
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
T = json.load(open(sys.argv[1]))
import numpy as np
from opensfm import dataset, io, pygeometry

data = dataset.DataSet(T['data_path'])
udata = dataset.UndistortedDataSet(data, T['udata_path'], io_handler=data.io_handler)
MAX = T['max_size']
_maps = {}

def _cam(cid, js):
    return io.camera_from_json(cid, js)

def _undist(shot_cam, sub, img, interp):
    import cv2
    from opensfm.undistort import scale_image
    h, w = img.shape[:2]
    out = {}
    for uid, ucid, ujs in sub:
        key = (shot_cam.id, ucid, w, h)
        if key not in _maps:
            _maps[key] = pygeometry.compute_camera_mapping(shot_cam, _cam(ucid, ujs), w, h)
        m1, m2 = _maps[key]
        out[uid] = scale_image(cv2.remap(img, m1, m2, interp), MAX)
    return out

def work(t):
    import cv2
    cv2.setNumThreads(1)
    sid, cid, cjs, sub = t
    cam = _cam(cid, cjs)
    img = data.load_image(sid, unchanged=True, anydepth=True)
    if img is not None:
        for k, v in _undist(cam, sub, img, cv2.INTER_AREA).items(): udata.save_undistorted_image(k, v)
    m = data.load_mask(sid)
    if m is not None:
        for k, v in _undist(cam, sub, m, cv2.INTER_NEAREST).items(): udata.save_undistorted_mask(k, v)
    s = data.load_segmentation(sid)
    if s is not None:
        for k, v in _undist(cam, sub, s, cv2.INTER_NEAREST).items(): udata.save_undistorted_segmentation(k, v)
    return sid

if __name__ == '__main__':
    n = 0
    with mp.get_context('fork').Pool(T['processes']) as pool:
        for _ in pool.imap_unordered(work, T['tasks'], chunksize=1):
            n += 1
    print('[bitblade] Patch 34: %d Bilder entzerrt' % n, flush=True)
