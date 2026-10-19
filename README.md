# ODM performance & robustness patches

Patches for [OpenDroneMap](https://github.com/OpenDroneMap/ODM) 3.6.x that we developed while running large
drone-photogrammetry jobs (1,000–8,000 images, up to ~550 M points) on a ClusterODM/NodeODM setup.
Every patch listed here has been running in production and has a measured effect. Lab experiments that did not
pay off are listed in [docs/NOT-INCLUDED.md](docs/NOT-INCLUDED.md) so nobody has to repeat them.

Most patches keep the **output identical** to stock ODM (byte- or MD5-identical where noted) and only change
*how* the work is done. Each one checks its anchor in the original code, falls back to the original on any
error, and can be switched off at runtime with a flag file.

The strongest patches are being submitted upstream as well – see [docs/UPSTREAM.md](docs/UPSTREAM.md).

## Results at a glance

| Patch | Stage / component | What it fixes | Measured effect |
|---|---|---|---|
| **13** PoissonRecon `BIG_DATA` | odm_meshing | 32-bit octree node index overflows at depth 13 → deterministic segfault | 554 M points, depth 13: crash → **completes** (26 min, 102 GB peak) |
| **9** Poisson safety net | odm_meshing | a Poisson crash kills the whole task | retries with depth −1/−2 instead of failing |
| **10, 22–29** texrecon | mvs_texturing | quadratic `reserve()` in mapmap, serial patch/atlas code, all atlases held in RAM, quality normalisation clamped to 0 | 4,700 images / 19.4 M faces: 3D **45 → 26 min, RAM 191 → 108 GB**; 2.5D ~3 h 50 / ~450 GB → **15–20 min / ~105 GB**; visibly better ortho view selection |
| **22** glass fallback | mvs_texturing | glass/window faces get no view and are deleted → holes | deleted faces on a glass-facade dataset **416,648 → 2,921**, same runtime |
| **8** fast GLB export | odm_texturing / 3D model | Python OBJ parsing + quadratic `bytes +=` | 23.6 M faces: **2 h 38 → 4 min 36 (×34), SHA-256 identical** |
| **34** undistort with processes | opensfm undistort | joblib threads + GIL use ~2 cores | 240 images **×12.5, bit-identical**; 4,700 images 68 → ~5 min |
| **40** OpenSfM on all cores | opensfm | `shot in list` (quadratic), serial loops | export_visualsfm **860 → 147 s, byte-identical**; tracks 569 → 209 s; export_openmvs 268 → 176 s (byte-identical); statistics 990 → 622 s |
| **40c** parallel image metadata | dataset | EXIF/XMP read one image at a time | 8,000 images: 80 → 10 s, identical photo objects |
| **41** FPCFilter parallel | odm_filterpoints | serial read/crop/kd-tree/write | 537 M points: **809 → 305 s (×2.65), output MD5-identical** |
| **32** fast mesh decimation | odm_meshing (ReconstructMesh) | single-core vcglib quadric decimation | 507 → 130 s, RAM 21 → 16 GB, same cloud-to-mesh distance |
| **3 / 3b** parallel SMRF | odm_dem (DTM) | one `pdal smrf` over the whole cloud on one core | 296 M points: **4,013 → 457 s (×8.8)**; 3b caps RAM: 182 GB + swap → ~71 GB |
| **5 / 31** reuse poses | opensfm reconstruct | re-running a job redoes incremental SfM | 4,680 images: **21 h 43 → 2 h 15**, later 46 min, same reprojection error |
| **15** extra OpenSfM config | opensfm | not every OpenSfM option is exposed by ODM | dataset without GPS: matching **~30 h → ~70 min** |
| **11** pitch check | opensfm reconstruct | single mis-oriented photos (horizon shots) create ghost geometry | removes photos whose solved pitch is > 10° off the DJI gimbal pitch |
| **6 / 12** densify wrapper | openmvs | (6) hours lost before ODM's OOM→tiling fallback; (12) visibility filter removes thin structures | opt-in flags |
| **42** corrupt EXIF MakerNote | dataset | one broken DJI MakerNote aborts the whole task | task runs; other images unchanged (upstream PR #2081) |
| **44** DJI band alignment | multispectral | feature/ECC alignment locks onto the neighbouring crop row | NIR offset vs. green **20 px → 1 px** (upstream PR #2080) |
| **45** NodeODM JSON options | NodeODM | JSON options (`--boundary`, crop polygon) lose their quotes | boundary parsed instead of exit 2 (upstream PR NodeODM #275) |
| **1** orientation_prior | opensfm align | GPS altitude + "naive" alignment flips the model (negative GSD) | public Bad Wurzach dataset: GPS error 5.4 → 1.7 m. **Opt-in only – wrong for handheld/horizontal imagery** |
| **2** OpenBLAS | opensfm bundle | CHOLMOD uses reference BLAS on one core | bundle uses 17–22 cores (small total gain) |

Timings are from Hetzner dedicated-vCPU servers (32–48 cores, 128–384 GB RAM) with ODM 3.6.2.

## Requirements

* ODM / NodeODM **3.6.x** (tested on 3.6.2, `opendronemap/nodeodm:3.6.2`). Patches that replace whole files
  (8, 40) check the original file's checksum and skip themselves on other versions.
* For the compiled patches (texrecon, PoissonRecon, FPCFilter): build them once inside
  the ODM image (same OS/compiler), see below.

## Installation

```sh
# 1) optional: build the native parts inside the ODM image (results go to ./bin)
docker run --rm -v "$PWD":/patches --entrypoint bash opendronemap/nodeodm:3.6.2 /patches/build/build-all.sh

# 2) install into a running NodeODM/ODM container
docker cp . <container>:/tmp/odm-patches
docker exec <container> sh /tmp/odm-patches/install/install.sh
```

Or bake it into your own image:

```dockerfile
FROM opendronemap/nodeodm:3.6.2
COPY . /tmp/odm-patches
RUN sh /tmp/odm-patches/install/install.sh
# Patch 2 (optional): multi-threaded BLAS for the OpenSfM bundle adjustment
RUN apt-get update && apt-get install -y --no-install-recommends libopenblas0-pthread && rm -rf /var/lib/apt/lists/*
```

`install.sh` prints one line per patch (`active` / `NOT active` / `skipped`). Skip patches with
`BB_SKIP="8 34"`; Patch 1 is only installed with `BB_ORIENTATION_PRIOR=1`.

## Switching patches off at runtime

Create the flag file in `/var/www/data/` (the NodeODM data volume) – no restart needed:

| Flag file | Effect |
|---|---|
| `bitblade_texrecon_orig` | original texrecon (all texturing patches off) |
| `bitblade_tex_mrf_aus`, `bitblade_tex_topk_aus`, `bitblade_tex_visfix_aus`, `bitblade_tex_fallback_aus` | individual texrecon patches 28 / 27 / 29 / 22 off |
| `bitblade_poisson_orig` | original PoissonRecon (safety net stays) |
| `bitblade_p41_aus` | original FPCFilter |
| `bitblade_p40_aus` | OpenSfM parallel exports/tracks/statistics and parallel EXIF reading off |
| `bitblade_undistort_fork_aus` | undistort with threads again |
| `bitblade_fastdecimate_aus` | original ReconstructMesh decimation |
| `bitblade_pitchcheck_aus` / `bitblade_posecheck_aus` | pitch check / position+heading check off |
| `bitblade_p44_aus` | ODM's own band alignment |
| env `BITBLADE_SMRF_PARALLEL=0` | original SMRF |

Opt-in features: `bitblade_pctile` (Patch 6), `bitblade_novisfilter` (Patch 12),
`bitblade_osfm_extra` (Patch 15, `key: value` lines), `bitblade_prior/{shots.geojson,cameras.json}` (Patch 5,
take both files from a previous task's assets).

## Repository layout

```
install/install.sh        installs everything into an ODM/NodeODM container
build/build-all.sh        builds texrecon.bb, PoissonRecon.bb, FPCFilter.p41 into ./bin
patches/odm/              ODM Python patches (3, 8, 40c, 42, 44)
patches/opensfm/          OpenSfM wrapper (5, 11, 15), Patch 40, Patch 34
patches/openmvs/          DensifyPointCloud wrapper (6, 12), fast decimation (32)
patches/poissonrecon/     BIG_DATA build (13) + safety net (9)
patches/fpcfilter/        parallel FPCFilter (41)
patches/texrecon/         mvs-texturing/mapmap patches (10, 22–29) + build script
patches/nodeodm/          JSON option quoting (45)
tools/                    per-stage CPU/RAM/IO profiler used to find the single-core stages (16)
tests/                    helpers we used to verify identical output
docs/                     details, upstream status, what did not work
```

Code comments are partly in German (the patches were written for our own pipeline); the docs are in English.
Pull requests with translations are welcome.

## License

AGPL-3.0, like ODM itself. The texrecon patches apply to mvs-texturing (BSD-3-Clause) and mapmap (BSD-3-Clause),
the PoissonRecon build uses PoissonRecon (MIT); those projects keep their own licenses.

Developed by [Bitblade](https://bitblade.io). Feedback and results on other datasets are very welcome – please
open an issue or post in the [OpenDroneMap community forum](https://community.opendronemap.org/).
