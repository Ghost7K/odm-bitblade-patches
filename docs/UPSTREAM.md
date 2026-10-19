# Upstream status

Patches we have submitted to the OpenDroneMap projects, and the ones we plan to submit next.

## Submitted

| Patch | Pull request | Status |
|---|---|---|
| 44 – DJI multispectral band alignment via `CalibratedHMatrix` | [OpenDroneMap/ODM#2080](https://github.com/OpenDroneMap/ODM/pull/2080) | open; independently confirmed on three M3M sites ([forum](https://community.opendronemap.org/t/follow-up-large-raw-nir-misalignment-dji-m3m-cause-found-and-fixed/26988)) |
| 42 – tolerate a corrupt EXIF MakerNote | [OpenDroneMap/ODM#2081](https://github.com/OpenDroneMap/ODM/pull/2081) | open |
| OPK for DJI images with a rolled gimbal (253/253 instead of 64/253 images reconstructed) | [OpenDroneMap/ODM#2082](https://github.com/OpenDroneMap/ODM/pull/2082) | open |
| 45 – JSON option quoting in NodeODM | [OpenDroneMap/NodeODM#275](https://github.com/OpenDroneMap/NodeODM/pull/275) | open |

## Planned (in this order)

1. **PoissonRecon `BIG_DATA`** (Patch 13) – a one-flag change in ODM's SuperBuild; fixes a deterministic segfault
   at depth 13 on dense scenes, output unchanged.
2. **OpenSfM exports** (Patch 40) – start with the list→set fix in `export_visualsfm` (byte-identical, ×5.9),
   then `export_openmvs` and `create_tracks`.
3. **OpenSfM undistort with processes** (Patch 34) – ×12.5, bit-identical.
4. **mvs-texturing / mapmap** – Patch 29 (quality normalisation clamped to 0) and the mapmap `reserve()` fix
   first (bug fixes), then the memory patches 24–26 and the tiled MRF (28).
5. **Fast GLB export** (Patch 8) – plus a separate one-line fix: `jpeg_quality=90` is ignored by GDAL in
   `opendm/gltf.py` (the effective default is 75); the GDAL option is `quality`.

Runner-up: parallel FPCFilter (Patch 41).
