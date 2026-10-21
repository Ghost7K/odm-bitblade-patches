# Upstream status

Patches we have submitted to the OpenDroneMap projects, and the ones we plan to submit next.

## Submitted

| Patch | Pull request | Status |
|---|---|---|
| 44 – DJI multispectral band alignment via `CalibratedHMatrix` | [OpenDroneMap/ODM#2080](https://github.com/OpenDroneMap/ODM/pull/2080) | open; independently confirmed on three M3M sites ([forum](https://community.opendronemap.org/t/follow-up-large-raw-nir-misalignment-dji-m3m-cause-found-and-fixed/26988)) |
| 42 – tolerate a corrupt EXIF MakerNote | [OpenDroneMap/ODM#2081](https://github.com/OpenDroneMap/ODM/pull/2081) | open |
| OPK for DJI images with a rolled gimbal (253/253 instead of 64/253 images reconstructed) | [OpenDroneMap/ODM#2082](https://github.com/OpenDroneMap/ODM/pull/2082) | open |
| 45 – JSON option quoting in NodeODM | [OpenDroneMap/NodeODM#275](https://github.com/OpenDroneMap/NodeODM/pull/275) | open |
| Issue #4 – PoissonRecon BIG_DATA build as crash fallback (Patch 13) | [OpenDroneMap/ODM#2084](https://github.com/OpenDroneMap/ODM/pull/2084) | open |
| Issue #1 – split-merge: don't pass `--split-image-groups` / `--copy-to` to submodels (E2E: 263 → 0 nested submodels) | [OpenDroneMap/ODM#2085](https://github.com/OpenDroneMap/ODM/pull/2085) | open |
| Issue #7 – 3D Tiles: pass `--y-up-to-z-up` to Obj2Tiles (E2E: model flat instead of upright) | [OpenDroneMap/ODM#2086](https://github.com/OpenDroneMap/ODM/pull/2086) | open |
| Issue #2 – odm_report: don't fail when the DEM preview cannot be generated | [OpenDroneMap/ODM#2087](https://github.com/OpenDroneMap/ODM/pull/2087) | open |
| Issue #3 – video2dataset: keep RTK altitude precision, decimal/negative RTK altitude | [OpenDroneMap/ODM#2088](https://github.com/OpenDroneMap/ODM/pull/2088) | open |
| Issue #6 – rasterio fallback for TIFFs without PhotometricInterpretation | [OpenDroneMap/ODM#2089](https://github.com/OpenDroneMap/ODM/pull/2089) | open |
| Issue #5 – pairs_selection: all-nadir altitude search, relative_altitude sanitizing | [OpenDroneMap/OpenSfM#55](https://github.com/OpenDroneMap/OpenSfM/pull/55) | open |
| Issue #13 – NoData = 0 on float (multispectral/thermal) orthophotos, clamp negative edge reflectance (NDVI −153…+146 → −1…1) | [OpenDroneMap/ODM#2090](https://github.com/OpenDroneMap/ODM/pull/2090) | open |

## Planned (in this order)

1. **OpenSfM exports** (Patch 40) – start with the list→set fix in `export_visualsfm` (byte-identical, ×5.9),
   then `export_openmvs` and `create_tracks`.
2. **OpenSfM undistort with processes** (Patch 34) – ×12.5, bit-identical.
3. **mvs-texturing / mapmap** – Patch 29 (quality normalisation clamped to 0) and the mapmap `reserve()` fix
   first (bug fixes), then the memory patches 24–26 and the tiled MRF (28).
4. **Fast GLB export** (Patch 8) – plus a separate one-line fix: `jpeg_quality=90` is ignored by GDAL in
   `opendm/gltf.py` (the effective default is 75); the GDAL option is `quality`.

Runner-up: parallel FPCFilter (Patch 41).
