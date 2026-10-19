# Tried, but not included

Things we tried in the lab that either did not help, made results worse, or are superseded upstream.
Listed so others don't have to repeat the experiments.

| Idea | Result |
|---|---|
| GLOMAP global SfM instead of incremental OpenSfM (with COLMAP verification, 300 tracks/image) | fast, but on a multi-year dataset (8,300 images) the GPS residual was 57–65 m; our quality gate fell back to standard reconstruction every time |
| Ceres solver selection / SPARSE_SCHUR in OpenSfM bundles (Ceres 2.0) | single-threaded in Ceres 2.0, slower |
| Ceres 2.2 rebuild of the OpenSfM C++ modules | numerically identical, only small bundles slightly faster – not worth a custom build |
| Removing outliers *before* the first full bundle | needs reprojection errors that only exist after the bundle |
| Distributed depth maps (split DensifyPointCloud across servers) | worked, but measurably increased duplicated surfaces ("ghost layers") |
| Pair pre-filter by OPK view angle (> 75°) | −10 % pairs; superseded by OpenSfM's relative-altitude handling and the gimbal-roll fix (ODM#2082) |
| texrecon: prefer frontal views + stronger seam weight | no visible effect |
| texrecon top-K candidates in full 3D | worse than full candidate set (we use top-K only for 2.5D) |
| PoissonRecon race-condition fix | the race exists in the code, but was **not** the cause of the depth-13 crashes (that is the 32-bit index overflow, see Patch 13) |
| Running stages in the background (3D texturing parallel to DEM/ortho, parallel sub-scene fusion) | runs in production, but we have no clean before/after measurement yet |

## Note on ghost layers (duplicated surfaces)

The most effective lever we found against duplicated roofs/walls in the dense cloud was OpenMVS fusion strictness:
ODM uses `--number-views-fuse 2` and `Min Views Filter = 1`. With 4 / 3 the floating duplicate layers disappeared
in our cross-sections and the share of 0.5 m cells with multiple layers dropped from 41 % to 24 % – at the cost of
slightly patchier small structures. We are still validating this on full datasets before turning it into a patch.
