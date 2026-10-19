"""
bitblade-patch 5 (07.10.2026): OpenSfM "reconstruct" aus bekannten Kameraposen eines frueheren Laufs.
Statt der inkrementellen Rekonstruktion (Bild fuer Bild, bei 4700 Bildern ~22 h) werden die fertig
optimierten Posen + Kamerakalibrierung eines frueheren Laufs mit DENSELBEN Bildern uebernommen,
dann wie am Ende von grow_reconstruction: triangulieren -> ausrichten -> Bundle -> Retriangulation ->
Bundle -> Ausreisser -> (fehlende Bilder inkrementell anfuegen) -> ausrichten -> Bundle mit GCP -> faerben.
Qualitaetspruefung am Ende; bei Nichtbestehen Exit 3 -> Wrapper faellt auf Standard-reconstruct zurueck.

Aufruf: python3 bitblade_prior.py <opensfm-dir> <prior-dir> [ausgabe.json]
  prior-dir: shots.geojson (WebODM assets/odm_report/shots.geojson) + cameras.json (assets/cameras.json)
Patch 31 (10.10.2026): Ein-Bundle-Modus (Standard). Abschalten: /var/www/data/bitblade_prior_einbundle_aus.
"""
import sys, os, json, time, logging
import numpy as np
from opensfm import dataset, io, types, pygeometry
from opensfm import reconstruction as R
from opensfm import rig
from pyproj import Transformer

logging.basicConfig(format='%(asctime)s %(levelname)s: %(message)s', level=logging.INFO)
log = logging.getLogger('bitblade_prior')
t0 = time.time(); laps = {}
def lap(k):
    laps[k] = time.time() - t0 - sum(laps.values())

path, prior_dir = sys.argv[1], sys.argv[2]
out = sys.argv[3] if len(sys.argv) > 3 else None
data = dataset.DataSet(path)
cfg = data.config
tm = data.load_tracks_manager()
images = set(tm.get_shot_ids())
ref = data.load_reference()
gj = json.load(open(os.path.join(prior_dir, 'shots.geojson')))
pcams = json.load(open(os.path.join(prior_dir, 'cameras.json'))) if os.path.exists(os.path.join(prior_dir, 'cameras.json')) else {}

# UTM-Zone aus erster Kamera (Translation = UTM absolut, Geometrie = WGS84)
lon0, lat0 = gj['features'][0]['geometry']['coordinates'][:2]
zone = int((lon0 + 180) // 6) + 1
epsg = (32600 if lat0 >= 0 else 32700) + zone
u2g = Transformer.from_crs(epsg, 4326, always_xy=True)
def to_topo(X):
    lon, lat, alt = u2g.transform(X[0], X[1], X[2])
    return np.array(ref.to_topocentric(lat, lon, alt))

rec = types.Reconstruction()
rec.reference = ref
camera_priors = data.load_camera_models()
rig_camera_priors = data.load_rig_cameras()
rig_assignments = rig.rig_assignments_per_image(data.load_rig_assignments())
for cid, cam in camera_priors.items():
    k = cid[3:] if cid.startswith('v2 ') else cid
    if k in pcams:
        c = io.camera_from_json(cid, pcams[k]); log.info('Kamera %s: Kalibrierung aus Vorlauf', cid)
    elif cid in pcams:
        c = io.camera_from_json(cid, pcams[cid])
    else:
        c = cam; log.info('Kamera %s: EXIF-Startwerte', cid)
    rec.add_camera(c)

added = set(); skipped = 0
for f in gj['features']:
    sid = f['properties']['filename']
    if sid not in images or sid in rig_assignments:
        skipped += 1; continue
    C_u = np.array(f['properties']['translation'], float)
    R_u = pygeometry.Pose(np.array(f['properties']['rotation'], float)).get_rotation_matrix()
    C_t = to_topo(C_u)
    J = np.column_stack([to_topo(C_u + e) - C_t for e in np.eye(3)])   # d topo / d utm
    U, S, Vt = np.linalg.svd(J); Q = U @ Vt                              # reine Drehung (Meridiankonvergenz)
    R_t = R_u @ Q.T
    pose = pygeometry.Pose(); pose.set_rotation_matrix(R_t); pose.set_origin(C_t)
    added |= R.add_shot(data, rec, rig_assignments, sid, pose)
remaining = images - set(rec.shots)
log.info('Posen uebernommen: %d, nicht im Vorlauf: %d, Vorlauf-Bilder nicht im Datensatz: %d', len(added), len(remaining), skipped)
if len(added) < 0.8 * len(images):
    log.error('Zu wenige bekannte Posen (%d von %d) -> Standard-Rekonstruktion', len(added), len(images)); sys.exit(3)
lap('posen')

gcp = data.load_ground_control_points()
R.triangulate_shot_features(tm, rec, set(rec.shots), cfg)
log.info('Trianguliert: %d Punkte', len(rec.points)); lap('triangulation')
R.align_reconstruction(rec, gcp, cfg)
# Nur wenn wenige Bilder fehlen (<=10 %): lange Resektionsketten ohne Bundle koennten sonst driften (z. B. v3 mit 2022er Schraegbildern).
EIN = not os.path.exists('/var/www/data/bitblade_prior_einbundle_aus') and len(remaining) <= 0.1 * len(added)
if EIN:
    # Patch 31 (10.10.2026): nur EIN globales Bundle. Die Vorlauf-Posen sind bereits global optimiert;
    # fehlende Bilder werden per Resektion (+ Einzel-Posen-Bundle) eingehaengt, ohne die zwei vollen
    # Zwischen-Bundles (bundle1 + Start von grow_reconstruction, Datensatz A: 32 + 36 min).
    log.info('Patch 31: Ein-Bundle-Modus, %d fehlende Bilder per Resektion', len(remaining))
    todo = set(remaining); nres = 0
    while todo:
        cands = R.reconstructed_points_for_images(tm, rec, todo)
        if not cands: break
        added_any = False
        for image, _ in cands:
            ok, new_shots, _rr = R.resect(data, tm, rec, image, cfg['resection_threshold'], cfg['resection_min_inliers'])
            if not ok: continue
            todo -= new_shots; nres += len(new_shots); added_any = True
            R.bundle_shot_poses(rec, new_shots, camera_priors, rig_camera_priors, cfg)
            R.triangulate_shot_features(tm, rec, new_shots, cfg)
        if not added_any: break
    log.info('Resektion: %d angefuegt, %d nicht anfuegbar', nres, len(todo)); lap('resektion')
    ar = R.align_reconstruction(rec, gcp, cfg, bias_override=True)
    if not ar and cfg['bundle_compensate_gps_bias']:
        cfg = dict(cfg); cfg['bundle_compensate_gps_bias'] = False
    R.bundle(rec, camera_priors, rig_camera_priors, gcp, cfg)
    R.remove_outliers(rec, cfg)
    # Patch 31c: kurzes Nach-Bundle nach der Ausreisser-Entfernung (wie v2: Bundle -> Ausreisser -> Bundle),
    # aber mit wenigen Iterationen, da die Loesung schon am Optimum liegt. BITBLADE_PRIOR_REBUNDLE=0 schaltet ab.
    it = int(os.environ.get('BITBLADE_PRIOR_REBUNDLE', '10'))
    if it > 0:
        lap('bundle')
        c2 = dict(cfg); c2['bundle_max_iterations'] = it
        R.bundle(rec, camera_priors, rig_camera_priors, gcp, c2)
        R.remove_outliers(rec, c2)
        log.info('Patch 31c: Nach-Bundle (%d Iterationen) fertig', it)
    R.paint_reconstruction(data, tm, rec)
else:
    # Punkte wurden frisch mit den endgueltigen Posen trianguliert -> eine Retriangulation waere redundant.
    b1 = R.bundle(rec, camera_priors, rig_camera_priors, None, cfg)
    R.remove_outliers(rec, cfg); lap('bundle1')
    log.info('Nach Bundle: %d Bilder, %d Punkte', len(rec.shots), len(rec.points))
    if remaining:
        log.info('Fuege %d fehlende Bilder inkrementell an', len(remaining))
        rec, grow = R.grow_reconstruction(data, tm, rec, set(remaining), gcp)   # endet mit align+bundle(gcp)+outliers+paint
    else:
        ar = R.align_reconstruction(rec, gcp, cfg, bias_override=True)
        if not ar and cfg['bundle_compensate_gps_bias']:
            cfg = dict(cfg); cfg['bundle_compensate_gps_bias'] = False
        R.bundle(rec, camera_priors, rig_camera_priors, gcp, cfg)
        R.remove_outliers(rec, cfg)
        R.paint_reconstruction(data, tm, rec)
lap('abschluss')

# Qualitaetspruefung: Reprojektionsfehler (Pixel) auf Stichprobe
rng = np.random.default_rng(0)
pids = list(rec.points.keys()); errs = []
for pid in rng.choice(pids, size=min(30000, len(pids)), replace=False):
    p = rec.points[pid]
    for sid, obs in tm.get_track_observations(pid).items():
        if sid in rec.shots:
            sh = rec.shots[sid]; px = sh.project(p.coordinates)
            errs.append(np.linalg.norm(px - obs.point) * max(sh.camera.width, sh.camera.height))
errs = np.array(errs)
med, p90 = float(np.median(errs)), float(np.percentile(errs, 90))
gps = [np.linalg.norm(s.pose.get_origin() - s.metadata.gps_position.value) for s in rec.shots.values() if s.metadata.gps_position.has_value]
log.info('ERGEBNIS: %d/%d Bilder, %d Punkte, Reproj. Median %.2f px / p90 %.2f px, GPS-Abw. Median %.2f m, Zeiten %s',
         len(rec.shots), len(images), len(rec.points), med, p90, float(np.median(gps)) if gps else -1,
         {k: round(v) for k, v in laps.items()})
if len(rec.shots) < 0.95 * len(added) or med > 1.5 or len(rec.points) < 1000:
    log.error('Qualitaetspruefung NICHT bestanden -> Standard-Rekonstruktion'); sys.exit(3)

report = {'wall_times': dict(laps), 'not_reconstructed_images': list(images - set(rec.shots)),
          'bitblade_prior': {'prior_shots': len(added), 'reproj_median_px': med, 'reproj_p90_px': p90}}
if out:
    data.save_reconstruction([rec], out); log.info('Test-Ausgabe: %s', out)
else:
    data.save_reconstruction([rec])
    data.save_report(io.json_dumps(report), 'reconstruction.json')
log.info('fertig in %.0f s', time.time() - t0)
