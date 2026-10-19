#!/bin/bash
# Build the parallel FPCFilter (Patch 41) from OpenDroneMap/FPCFilter @ c1467cb (master; contains branch 331 that
# ODM 3.6.2 pins). The patch was developed and verified against this commit.
# patch41_fpcfilter.py also upgrades the vendored nanoflann 1.3.2 -> 1.6.1 (parallel kd-tree build).
# Output is byte-identical to the original FPCFilter (verified with MD5 on a 537 M point cloud).
#
# Usage: build-fpcfilter.sh [workdir]  -> <workdir>/FPCFilter.p41
# Build deps: git cmake g++ (OpenMP); same OS release as the ODM image.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
W="${1:-$PWD/fpcfilter-build}"
J="${JOBS:-$(nproc)}"
mkdir -p "$W/nf" && cd "$W"
rm -rf FPCFilter
git clone -q https://github.com/OpenDroneMap/FPCFilter.git
(cd FPCFilter && git checkout -q c1467cb)
curl -fsSL -o nf/nanoflann.hpp https://raw.githubusercontent.com/jlblancoc/nanoflann/v1.6.1/include/nanoflann.hpp
python3 "$HERE/patch41_fpcfilter.py" "$W/FPCFilter"
cmake -S FPCFilter -B FPCFilter/build -DCMAKE_BUILD_TYPE=Release >/dev/null
cmake --build FPCFilter/build -j"$J" >/dev/null
cp FPCFilter/build/FPCFilter "$W/FPCFilter.p41" && strip "$W/FPCFilter.p41"
echo "OK: $W/FPCFilter.p41"
