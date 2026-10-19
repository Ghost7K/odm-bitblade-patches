"""
bitblade-patch 34 (10.10.2026): OpenSfM-Entzerrung (undistort) mit Prozessen statt Threads.
OpenSfM verteilt die Bild-Entzerrung mit joblib-Threads; das GIL begrenzt das auf ~2,3 Kerne
(Datensatz A: 68 min; Labor 1,26 Bilder/s, fork-Pool 24 Prozesse: 10,98 Bilder/s).
Umsetzung: Aufgabenliste (Bild-ID + Kameras als JSON) -> eigener Prozess bitblade_undistort_worker.py mit fork-Pool.
Nur fuer perspective/brown/fisheye ohne Bildfilter (ODM-Pipeline leer); sonst unveraendert (Threads).
Kamera-Abbildungen fuer camera_mappings.npz (Bericht) berechnet der Elternprozess ohne OpenCV.
Anwendung: python3 bitblade_undistort_patch.py <opensfm/undistort.py>  (idempotent; Worker nach opensfm/bin/ kopieren)
Abschalten zur Laufzeit: Datei /var/www/data/bitblade_undistort_fork_aus.
"""
import sys
p = sys.argv[1]
s = open(p).read()
if 'bitblade-patch 34' in s:
    print('Patch 34 bereits vorhanden'); sys.exit(0)
old = "        parallel_map(undistort_image_and_masks, arguments, processes)\n"
assert s.count(old) == 1, 'Ankerzeile nicht gefunden'
s = s.replace(old, "        _bb_parallel_undistort(arguments, processes)  # bitblade-patch 34\n")
s += '''

# bitblade-patch 34: Entzerrung in eigenem Prozess mit fork-Pool (siehe bitblade_undistort_worker.py)
def _bb_filter_empty(f):
    if f is None:
        return True
    try:
        for c in (f.__closure__ or ()):
            v = c.cell_contents
            if isinstance(v, list):
                return len(v) == 0
    except Exception:
        pass
    return False

def _bb_parallel_undistort(arguments, processes):
    import os, sys, json, subprocess, tempfile
    from opensfm import io as _io
    W = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'bin', 'bitblade_undistort_worker.py')  # nicht im Paketordner: types.py verdeckt sonst die stdlib
    ok = (processes > 1 and len(arguments) > 1 and os.path.exists(W)
          and not os.path.exists('/var/www/data/bitblade_undistort_fork_aus'))
    tasks = []
    if ok:
        for shot, subs, data, udata, f in arguments:
            if shot.camera.projection_type not in ("perspective", "brown", "fisheye", "fisheye_opencv") or not _bb_filter_empty(f):
                ok = False; break
            tasks.append([shot.id, shot.camera.id, _io.camera_to_json(shot.camera),
                          [[u.id, u.camera.id, _io.camera_to_json(u.camera)] for u in subs]])
    if not ok:
        return parallel_map(undistort_image_and_masks, arguments, processes)
    shot0, subs0, data, udata, _ = arguments[0]
    # Abbildungen je Kamera fuer camera_mappings.npz (ohne OpenCV, Groesse wie Kamera)
    seen = set()
    for shot, subs, _d, _u, _f in arguments:
        if shot.camera.id not in seen:
            seen.add(shot.camera.id)
            compute_camera_mapping_cached(shot.camera, subs[0].camera, shot.camera.width, shot.camera.height)
    T = {'data_path': data.data_path, 'udata_path': udata.data_path,
         'max_size': data.config["undistorted_image_max_size"], 'processes': int(processes), 'tasks': tasks}
    fd, tf = tempfile.mkstemp(suffix='.json', prefix='bb_undist_', dir=data.data_path)
    with os.fdopen(fd, 'w') as fh:
        json.dump(T, fh)
    logger.info("[bitblade] Patch 34: Entzerrung in eigenem Prozess, %d Prozesse, %d Bilder" % (processes, len(tasks)))
    try:
        r = subprocess.run([sys.executable, W, tf])
        if r.returncode != 0:
            raise RuntimeError("Worker rc=%s" % r.returncode)
    except Exception as e:
        logger.warning("[bitblade] Patch 34 fehlgeschlagen (%s) -> Threads" % e)
        parallel_map(undistort_image_and_masks, arguments, processes)
    finally:
        try: os.remove(tf)
        except Exception: pass
'''
open(p, 'w').write(s)
print('Patch 34 eingespielt')
