"""Bitblade Patch 44 (11.10.2026): Bandausrichtung DJI Mavic 3M (und andere DJI-Multispektral) ueber die
Werkskalibrierung im XMP (drone-dji:CalibratedHMatrix) statt ueber Bildabgleich.

Befund (Forum 26614, M3M, 29 Aufnahmen Getreide-Parzellen): ODM schaetzt die NIR-Ausrichtung per Merkmals-/ECC-Abgleich
gegen Gruen. Bei periodischen Pflanzreihen rastet der Abgleich eine Reihe daneben ein (NIR-Warp x -20,9 px); im
Orthofoto liegt NIR dadurch ~20 px (40 cm) neben den anderen Baendern (gemessen in 67 Kacheln). DJI liefert je Band
eine Homographie in ein gemeinsames Bezugsbild. M = inv(H_primaer) * H_band bildet Band- auf Primaerbild ab
(Test an Aufnahme 0376: Kantenkorrelation NIR/Gruen 0,20 statt 0,06).

Fix: Haben Band- und Primaerbilder CalibratedHMatrix, wird je Band der Median von M ueber bis zu 12 Aufnahmen
verwendet (Plausibilitaet: Determinante 0,8..1,25), danach Feinkorrektur der Restverschiebung (+-8 px,
Kantenkorrelation an bis zu 6 Aufnahmen; Test RedEdge: 2,2 px Rest ohne Feinkorrektur). Sonst unveraendert (ODM-Abgleich). Not-Aus:
/var/www/data/bitblade_p44_aus.
Aufruf: python3 patch44_bands.py /code/opendm/multispectral.py
"""
import sys
p = sys.argv[1]
s = open(p).read()
if "bitblade Patch 44" in s:
    print("schon gepatcht"); sys.exit(0)

helper = '''

# bitblade Patch 44: DJI-Werkskalibrierung (CalibratedHMatrix) fuer die Bandausrichtung
def _bb_dji_hmatrix(path):
    import re
    try:
        with open(path, 'rb') as f:
            data = f.read()
        m = re.search(rb'CalibratedHMatrix(?:="|>)\\s*([-0-9eE.,+\\s]+)', data)
        if not m:
            return None
        v = [float(x) for x in m.group(1).decode().replace(' ', '').strip(',').split(',') if x]
        if len(v) != 9:
            return None
        return np.array(v, dtype=np.float64).reshape(3, 3)
    except Exception:
        return None


def _bb_dji_alignment(band, images_path, s2p, max_samples=12):
    if os.path.exists('/var/www/data/bitblade_p44_aus'):
        return None
    ms, dim = [], None
    for p in band['photos'][:max_samples * 3]:
        if len(ms) >= max_samples:
            break
        prim = s2p.get(p.filename)
        if prim is None:
            continue
        hb = _bb_dji_hmatrix(os.path.join(images_path, p.filename))
        hp = _bb_dji_hmatrix(os.path.join(images_path, prim.filename))
        if hb is None or hp is None:
            return None
        m = np.linalg.inv(hp) @ hb
        m = m / m[2, 2]
        d = np.linalg.det(m[:2, :2])
        if not (0.8 < d < 1.25):
            return None
        ms.append(m)
        if dim is None:
            try:
                im = imread(os.path.join(images_path, prim.filename), unchanged=True, anydepth=True)
                dim = (im.shape[1], im.shape[0])
            except Exception:
                return None
    if not ms or dim is None:
        return None
    wm = np.median(np.array(ms), axis=0)
    # Feinkorrektur: Restverschiebung (max. +-8 px) per Kantenkorrelation an bis zu 6 Aufnahmen, Median
    try:
        sh = []
        for p in band['photos'][:6]:
            prim = s2p.get(p.filename)
            if prim is None:
                continue
            a = imread(os.path.join(images_path, prim.filename), unchanged=True, anydepth=True)
            b = imread(os.path.join(images_path, p.filename), unchanged=True, anydepth=True)
            a = a[:, :, 0] if a.ndim == 3 else a
            b = b[:, :, 0] if b.ndim == 3 else b
            b = cv2.warpPerspective(b.astype(np.float32), wm, dim)
            def _g(x):
                x = cv2.GaussianBlur(x.astype(np.float32), (0, 0), 1.5)
                return cv2.magnitude(cv2.Sobel(x, cv2.CV_32F, 1, 0), cv2.Sobel(x, cv2.CV_32F, 0, 1))
            ga, gb = _g(a), _g(b)
            h, w = ga.shape
            c = (slice(h // 4, 3 * h // 4), slice(w // 4, 3 * w // 4))
            A = ga[c]; A = (A - A.mean()) / (A.std() + 1e-9)
            best = None
            for dy in range(-8, 9):
                for dx in range(-8, 9):
                    B = gb[h // 4 - dy:3 * h // 4 - dy, w // 4 - dx:3 * w // 4 - dx]
                    B = (B - B.mean()) / (B.std() + 1e-9)
                    v = float((A * B).mean())
                    if best is None or v > best[0]:
                        best = (v, dx, dy)
            sh.append(best[1:])
        if sh:
            dx, dy = np.median(np.array(sh), axis=0)
            wm = np.array([[1, 0, dx], [0, 1, dy], [0, 0, 1]], dtype=np.float64) @ wm
            log.ODM_INFO("[bitblade P44] %s Feinkorrektur dx=%.1f dy=%.1f px (%d Aufnahmen)" % (band['name'], dx, dy, len(sh)))
    except Exception as e:
        log.ODM_WARNING("[bitblade P44] Feinkorrektur %s uebersprungen: %s" % (band['name'], e))
    wm = wm.astype(np.float32)
    return {'warp_matrix': wm, 'eigvals': np.linalg.eigvals(wm), 'dimension': dim, 'algo': 'dji-calib', 'score': 0.0}
'''
anchor = "\n\ndef compute_alignment_matrices("
assert s.count(anchor) == 1
s = s.replace(anchor, helper + anchor, 1)

old = """    for band in multi_camera:
        if band['name'] != primary_band_name:
            matrices = []
"""
new = """    for band in multi_camera:
        if band['name'] != primary_band_name:
            _bb_m = _bb_dji_alignment(band, images_path, s2p)  # bitblade Patch 44
            if _bb_m is not None:
                alignment_info[band['name']] = _bb_m
                log.ODM_INFO("[bitblade P44] %s band will be aligned using DJI CalibratedHMatrix %s" % (band['name'], _bb_m['warp_matrix']))
                continue
            matrices = []
"""
assert s.count(old) == 1
s = s.replace(old, new, 1)
open(p, "w").write(s)
print("Patch 44 eingespielt")
