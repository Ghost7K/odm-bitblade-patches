#!/usr/bin/env python3
"""
odm_scalebar_check.py - check (and measure) the scale of an ODM / OpenSfM reconstruction with a scale bar
that carries two AprilTags.

It reads an ODM project (opensfm/reconstruction.json + images/), detects the two tags in the photos,
triangulates each tag center through the solved cameras (lens distortion included), and compares the
distance between the two tags with the known bar length.

    pip install numpy opencv-python          # OpenCV >= 4.7 (AprilTag dictionaries are in cv2.aruco)
    python3 odm_scalebar_check.py /path/to/odm/project --tags 476 283 --length 1.99628

Output: tag positions, number of photos per tag, reprojection error, measured distance, scale error
(mm and %) and the factor the model would have to be multiplied by. --json writes the same as JSON.

Coordinates in reconstruction.json are local metric coordinates (east/north/up) when the photos have
GPS, otherwise in arbitrary units. In the GPS case the result is a scale CHECK; without GPS the factor is
the scale you would apply to the outputs.

License: AGPL-3.0 (same as ODM). https://github.com/Ghost7K/odm-bitblade-patches
"""
import argparse
import json
import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor

import numpy as np

try:
    import cv2
except ImportError:
    sys.exit("OpenCV is missing: pip install opencv-python  (version 4.7 or newer)")

DICTS = {"36h11": "DICT_APRILTAG_36h11", "25h9": "DICT_APRILTAG_25h9", "16h5": "DICT_APRILTAG_16h5", "36h10": "DICT_APRILTAG_36h10"}


# ---------------------------------------------------------------- camera models (OpenSfM conventions)
def _rot(rvec):
    R, _ = cv2.Rodrigues(np.asarray(rvec, dtype=np.float64))
    return R


class Camera:
    """Pixel <-> bearing for the OpenSfM camera models ODM uses (perspective, brown, fisheye, fisheye_opencv)."""

    def __init__(self, d):
        self.d = d
        self.type = d.get("projection_type", "perspective")
        self.w, self.h = int(d["width"]), int(d["height"])
        self.s = float(max(self.w, self.h))
        if self.type not in ("perspective", "brown", "fisheye", "fisheye_opencv", "simple_radial", "radial"):
            raise ValueError("camera model %s is not supported" % self.type)

    # normalized image coordinates as in opensfm.features.normalized_image_coordinates
    def pix2norm(self, uv):
        uv = np.asarray(uv, dtype=np.float64)
        return np.stack([(uv[..., 0] + 0.5 - self.w / 2.0) / self.s, (uv[..., 1] + 0.5 - self.h / 2.0) / self.s], -1)

    def norm2pix(self, xy):
        return np.stack([xy[..., 0] * self.s - 0.5 + self.w / 2.0, xy[..., 1] * self.s - 0.5 + self.h / 2.0], -1)

    def _focal_c(self):
        d = self.d
        if self.type in ("brown", "fisheye_opencv", "simple_radial", "radial"):
            fx = d.get("focal_x", d.get("focal")); fy = d.get("focal_y", fx)
            return fx, fy, d.get("c_x", 0.0), d.get("c_y", 0.0)
        return d["focal"], d["focal"], 0.0, 0.0

    def _distort(self, x, y):
        """undistorted normalized point on z=1 plane -> distorted (before focal/principal point)"""
        d = self.d
        k1, k2 = d.get("k1", 0.0), d.get("k2", 0.0)
        if self.type in ("fisheye", "fisheye_opencv"):
            r = math.hypot(x, y)
            if r < 1e-12:
                return x, y
            th = math.atan(r); th2 = th * th
            if self.type == "fisheye":
                f = th * (1 + k1 * th2 + k2 * th2 * th2) / r
            else:
                k3, k4 = d.get("k3", 0.0), d.get("k4", 0.0)
                f = th * (1 + k1 * th2 + k2 * th2 ** 2 + k3 * th2 ** 3 + k4 * th2 ** 4) / r
            return x * f, y * f
        r2 = x * x + y * y
        radial = 1 + k1 * r2 + k2 * r2 * r2
        if self.type == "brown":
            k3, p1, p2 = d.get("k3", 0.0), d.get("p1", 0.0), d.get("p2", 0.0)
            radial += k3 * r2 ** 3
            return x * radial + 2 * p1 * x * y + p2 * (r2 + 2 * x * x), y * radial + 2 * p2 * x * y + p1 * (r2 + 2 * y * y)
        return x * radial, y * radial

    def project(self, Xc):
        """3D point in camera frame -> pixel"""
        if Xc[2] <= 0:
            return None
        fx, fy, cx, cy = self._focal_c()
        xd, yd = self._distort(Xc[0] / Xc[2], Xc[1] / Xc[2])
        return self.norm2pix(np.array([fx * xd + cx, fy * yd + cy]))

    def bearing(self, uv):
        """pixel -> unit bearing in camera frame (undistortion by Newton iteration)"""
        fx, fy, cx, cy = self._focal_c()
        n = self.pix2norm(np.asarray(uv, dtype=np.float64))
        xd, yd = (n[0] - cx) / fx, (n[1] - cy) / fy
        x, y = xd, yd
        for _ in range(30):
            ex, ey = self._distort(x, y)
            rx, ry = ex - xd, ey - yd
            if rx * rx + ry * ry < 1e-24:
                break
            e = 1e-7
            ax, ay = self._distort(x + e, y); bx, by = self._distort(x, y + e)
            J = np.array([[(ax - ex) / e, (bx - ex) / e], [(ay - ey) / e, (by - ey) / e]])
            dx, dy = np.linalg.solve(J, [rx, ry])
            x, y = x - dx, y - dy
        b = np.array([x, y, 1.0])
        return b / np.linalg.norm(b)


# ---------------------------------------------------------------- tag detection
def _detector(family):
    if not hasattr(cv2, "aruco") or not hasattr(cv2.aruco, "ArucoDetector"):
        raise SystemExit("This OpenCV has no cv2.aruco.ArucoDetector - install opencv-python >= 4.7")
    p = cv2.aruco.DetectorParameters()
    p.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_APRILTAG if hasattr(cv2.aruco, "CORNER_REFINE_APRILTAG") else cv2.aruco.CORNER_REFINE_SUBPIX
    return cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, DICTS[family])), p)


def _center(c):
    """center of a tag = intersection of its diagonals (perspective-correct)"""
    p1, p2, p3, p4 = [np.append(x, 1.0) for x in c]
    q = np.cross(np.cross(p1, p3), np.cross(p2, p4))
    return q[:2] / q[2] if abs(q[2]) > 1e-12 else c.mean(0)


def _detect(job):
    path, family, ids, shape = job
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE | cv2.IMREAD_IGNORE_ORIENTATION)
    if img is None:
        return path, None, "cannot read"
    note = None
    if shape and (img.shape[1], img.shape[0]) != shape:
        if (img.shape[0], img.shape[1]) == shape:
            note = "image is rotated relative to the camera model - skipped"
            return path, {}, note
        note = "size %dx%d differs from camera %dx%d - skipped" % (img.shape[1], img.shape[0], shape[0], shape[1])
        return path, {}, note
    corners, found, _ = _detector(family).detectMarkers(img)
    out = {}
    if found is not None:
        for c, i in zip(corners, found.ravel()):
            if int(i) in ids:
                # OpenCV returns tag corners in pixel-edge coordinates (pixel i spans i..i+1); OpenSfM uses pixel centers
                c = c.reshape(4, 2).astype(np.float64) - 0.5
                out[int(i)] = {"center": _center(c).tolist(), "corners": c.tolist(), "size_px": float(np.linalg.norm(c[0] - c[2]))}
    return path, out, note


# ---------------------------------------------------------------- triangulation
def triangulate(obs, max_px):
    """obs: list of (name, camera, R, origin, pixel). Least-squares ray intersection, then drop views with
    reprojection error > max_px (worst first) and solve again."""
    obs = list(obs)
    while len(obs) >= 2:
        A = np.zeros((3, 3)); b = np.zeros(3)
        for _, cam, R, o, uv in obs:
            d = R.T @ cam.bearing(uv)
            P = np.eye(3) - np.outer(d, d)
            A += P; b += P @ o
        X = np.linalg.solve(A, b)
        errs = []
        for name, cam, R, o, uv in obs:
            p = cam.project(R @ (X - o))
            errs.append(float("inf") if p is None else float(np.linalg.norm(p - uv)))
        worst = int(np.argmax(errs))
        if errs[worst] <= max_px or len(obs) <= 2:
            if errs[worst] > max_px:
                return None, [], errs
            return X, [o[0] for o in obs], errs
        obs.pop(worst)
    return None, [], []


def main():
    ap = argparse.ArgumentParser(description="Check the scale of an ODM reconstruction with a two-AprilTag scale bar.")
    ap.add_argument("project", help="ODM project folder (contains opensfm/ and images/)")
    ap.add_argument("--tags", type=int, nargs=2, required=True, metavar=("ID_A", "ID_B"), help="the two tag IDs on the bar")
    ap.add_argument("--length", type=float, required=True, help="known center-to-center distance of the two tags (m)")
    ap.add_argument("--family", default="36h11", choices=sorted(DICTS), help="AprilTag family (default 36h11)")
    ap.add_argument("--images", help="image folder (default: <project>/images)")
    ap.add_argument("--reconstruction", help="reconstruction file (default: <project>/opensfm/reconstruction.json)")
    ap.add_argument("--max-px", type=float, default=4.0, help="drop views with a reprojection error above this (px, default 4)")
    ap.add_argument("--min-views", type=int, default=3, help="minimum photos per tag (default 3)")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--json", help="write the result to this JSON file")
    a = ap.parse_args()

    rec_path = a.reconstruction or os.path.join(a.project, "opensfm", "reconstruction.json")
    img_dir = a.images or os.path.join(a.project, "images")
    recs = json.load(open(rec_path))
    rec = max(recs, key=lambda r: len(r["shots"]))
    if len(recs) > 1:
        print("note: %d partial reconstructions, using the largest (%d photos)" % (len(recs), len(rec["shots"])))
    cams = {k: Camera(v) for k, v in rec["cameras"].items()}
    shots = {}
    for name, s in rec["shots"].items():
        R = _rot(s["rotation"]); t = np.asarray(s["translation"], dtype=np.float64)
        shots[name] = (cams[s["camera"]], R, -R.T @ t)
    print("reconstruction: %s, %d photos, camera model(s): %s" % (rec_path, len(shots), ", ".join(sorted({c.type for c in cams.values()}))))

    jobs = []
    for name, (cam, _, _) in shots.items():
        p = os.path.join(img_dir, name)
        if os.path.isfile(p):
            jobs.append((p, a.family, set(a.tags), (cam.w, cam.h)))
    if not jobs:
        sys.exit("no images of the reconstruction found in " + img_dir)
    print("detecting %s tags %d and %d in %d photos ..." % (a.family, a.tags[0], a.tags[1], len(jobs)))
    det, notes = {}, {}
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        for path, res, note in ex.map(_detect, jobs, chunksize=4):
            if note:
                notes[os.path.basename(path)] = note
            if res:
                det[os.path.basename(path)] = res
    for k, v in list(notes.items())[:5]:
        print("  %s: %s" % (k, v))

    result = {"length_known_m": a.length, "tags": {}}
    pts = {}
    for tid in a.tags:
        obs = [(n, shots[n][0], shots[n][1], shots[n][2], np.array(d[tid]["center"])) for n, d in det.items() if tid in d]
        X, used, errs = triangulate(obs, a.max_px)
        info = {"photos_detected": len(obs), "photos_used": len(used)}
        if X is not None and len(used) >= a.min_views:
            pts[tid] = X
            info.update({"xyz": [round(float(v), 4) for v in X], "reproj_px_median": round(float(np.median(errs)), 2),
                         "reproj_px_max": round(float(np.max(errs)), 2), "photos": sorted(used)})
        result["tags"][str(tid)] = info
        print("tag %d: detected in %d photos, used %d%s" % (tid, len(obs), len(used),
              ", reprojection median %.2f px / max %.2f px" % (np.median(errs), np.max(errs)) if X is not None and used else ""))

    if len(pts) < 2:
        print("\nNot enough views to triangulate both tags (need %d photos per tag)." % a.min_views)
        result["ok"] = False
    else:
        dist = float(np.linalg.norm(pts[a.tags[0]] - pts[a.tags[1]]))
        err = dist - a.length
        result.update({"ok": True, "length_model": round(dist, 5), "error_mm": round(err * 1000, 1),
                       "error_percent": round(100 * err / a.length, 3), "scale_factor": round(a.length / dist, 6)})
        print("\nknown length      %.4f m" % a.length)
        print("model distance    %.4f" % dist)
        print("difference        %+.1f mm  (%+.3f %%)" % (err * 1000, 100 * err / a.length))
        print("scale factor      %.6f  (multiply the model by this to match the bar)" % (a.length / dist))
        if rec.get("reference_lla"):
            print("The photos are georeferenced (GPS), so this is a check of the GPS-derived scale.")
    if a.json:
        json.dump(result, open(a.json, "w"), indent=2)
        print("written:", a.json)


if __name__ == "__main__":
    main()
