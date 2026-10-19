#!/bin/bash
# Build the patched texrecon (mvs-texturing) used by ODM 3.6.x.
#
# Sources are the same commits ODM 3.6 builds from:
#   - OpenDroneMap/mve          @ 356      (ODM fork of MVE)
#   - OpenDroneMap/mvs-texturing @ c5a4d0c
#   - mapmap (fetched by mvs-texturing's CMake as ext_mapmap)
#
# Patches are applied cumulatively in this order:
#   mvstexturing-bitblade.patch   (Patch 10: parallel/deterministic texture patches, atlas, seam leveling)
#   glass-fallback-patch.py       (Patch 22: second view-selection pass for faces that would be deleted, e.g. glass)
#   mapmap-bitblade.patch         (Patch 10: no quadratic reserve() in mapmap multilevel)
#   patch23 .. patch29            (memory log, compact 8-bit patches, stream atlases, compact data costs,
#                                  top-K candidates, tiled MRF, visibility normalisation fix)
#
# Usage: build-texrecon.sh [workdir]   -> produces <workdir>/texrecon.bb
# Build deps (Ubuntu 24.04): git build-essential cmake libtbb-dev libpng-dev libjpeg-dev libtiff-dev libeigen3-dev
# Build inside the ODM image (or the same Ubuntu release) so the binary links against the same libraries.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
W="${1:-$PWD/texrecon-build}"
J="${JOBS:-$(nproc)}"
mkdir -p "$W" && cd "$W"

[ -d mve ] || git clone -q https://github.com/OpenDroneMap/mve.git
(cd mve && git checkout -q 356 && for l in util math mve sfm dmrecon; do make -j"$J" -C libs/$l >/dev/null; done)

rm -rf mvs-texturing
git clone -q https://github.com/OpenDroneMap/mvs-texturing.git
cd mvs-texturing && git checkout -q c5a4d0c
# portable binary: drop -march=native (later ODM versions do the same in SuperBuild/cmake/mvstexturing.patch)
sed -i 's/ -march=native//' CMakeLists.txt
git apply "$HERE/mvstexturing-bitblade.patch"
python3 "$HERE/glass-fallback-patch.py" "$W/mvs-texturing"
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release -DMVE_ROOT="$W/mve" -DCMAKE_CXX_FLAGS="-march=x86-64-v2 -O3" >/dev/null
make -j"$J" ext_mapmap ext_rayint ext_eigen >/dev/null 2>&1 || true
(cd "$W/mvs-texturing/elibs/mapmap" && git apply "$HERE/mapmap-bitblade.patch")
cd "$W/mvs-texturing"
for p in patch23-memory-log patch24-compact-8bit-patches patch25-write-atlases-immediately \
         patch26-compact-data-costs patch27-topk-candidates patch28-tiled-mrf patch29-visibility-normalization; do
  git apply "$HERE/$p.patch"; echo "applied $p"
done
cd build && make -j"$J" texrecon >/dev/null
cp apps/texrecon/texrecon "$W/texrecon.bb" && strip "$W/texrecon.bb"
echo "OK: $W/texrecon.bb"
