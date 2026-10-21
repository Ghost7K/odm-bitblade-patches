# Scale bar check for ODM

`odm_scalebar_check.py` checks the scale of an ODM reconstruction with a scale bar that carries two
AprilTags. ODM has no scale-bar input (only GCPs with real coordinates), so the tool works on ODM's output:

1. reads the solved cameras from `opensfm/reconstruction.json`,
2. detects the two tags in the photos (OpenCV, AprilTag 36h11 by default),
3. triangulates each tag center through the cameras, lens distortion included, and drops views with a
   large reprojection error,
4. compares the distance between the two tag centers with the known bar length.

With GPS photos the reconstruction is already metric, so the result is a **check** of the GPS-derived scale.
Without GPS the printed factor is the scale to apply to the outputs.

## Install

```sh
pip install numpy opencv-python      # OpenCV 4.7 or newer
```

It does not need ODM itself, only the project folder. It runs on Linux, macOS and Windows.

## Run

After ODM has finished, or at least after the `opensfm` stage (`--end-with opensfm`):

```sh
python3 odm_scalebar_check.py /path/to/project --tags 476 283 --length 1.99628
```

`/path/to/project` is the ODM project folder that contains `images/` and `opensfm/`. In WebODM that is the
task folder (`app/media/project/<project id>/task/<task id>`). Running it on a copy of `images/` plus
`opensfm/reconstruction.json` also works.

Options:

| Option | Meaning |
|---|---|
| `--tags A B` | the two tag IDs on the bar (official AprilTag IDs as OpenCV reports them) |
| `--length` | center-to-center distance of the two tags in meters |
| `--family` | `36h11` (default), `36h10`, `25h9`, `16h5` |
| `--max-px` | drop photos whose reprojection error is above this (default 4 px) |
| `--min-views` | minimum photos per tag (default 3) |
| `--json out.json` | also write the result, tag coordinates and the photos used |

Example output:

```
tag 476: detected in 31 photos, used 31, reprojection median 1.27 px / max 2.18 px
tag 283: detected in 36 photos, used 35, reprojection median 1.16 px / max 3.67 px

known length      1.9963 m
model distance    1.9971
difference        +0.9 mm  (+0.043 %)
scale factor      0.999573  (multiply the model by this to match the bar)
```

Supported camera models: `perspective`, `brown`, `fisheye`, `fisheye_opencv` (the ones ODM uses).

## Tested on

Abandoned Graffiti Mill dataset (DJI Mini 5 Pro, CC BY 4.0, bar with tags 476/283, 1.99628 m):

| Reconstruction | Photos per tag (used) | Reprojection median | Distance | Difference |
|---|---|---|---|---|
| Published RealityScan/COLMAP poses (scaled to the bar by its author, who measured 1.99648 m) | 31 / 35 | 1.3 / 1.2 px | 1.9971 m | +0.9 mm |
| ODM 3.6.2, only the 196 photos within 20 m of the bar, GPS only | 35 / 37 | 1.4 / 1.4 px | 2.0938 | +97.5 mm (+4.9 %) |

The camera math matches OpenSfM's own camera model (bearing difference 2·10⁻⁵ °). The second line shows
why a bar is useful: on a small patch, consumer GPS alone can leave the scale several percent off.

## Limits

- Only checks the scale. It does not change the reconstruction. A real distance constraint inside OpenSfM's
  bundle adjustment would be an upstream feature.
- The tags must be visible in at least 3 photos each. Small tags far away are not detected; low passes help.
- Photos with EXIF rotation (portrait) are skipped when their size does not match the camera.

License AGPL-3.0, like ODM.
