#!/bin/bash
# Build PoissonRecon exactly as ODM 3.6 uses it (OpenDroneMap/PoissonRecon, branch 290 = commit 97caa6d, v13.8),
# but with BIG_DATA (64-bit octree node indices). This is the PoissonRecon author's own switch for large scenes.
#
# Why: at --depth 13 on dense, volumetric point clouds (buildings + vegetation, ~550 M points) the octree gets more
# than 2^31 nodes. Without BIG_DATA the node index is a 32-bit int, overflows to a negative value and PoissonRecon
# segfaults (exit 139) - deterministically, with any thread count. With BIG_DATA the same cloud finishes
# (depth 13: 26 min, 102 GB peak, 114 M vertices). The PLY still uses 32-bit face indices ("list int int"), so
# OpenMVS reads it unchanged. Cross-check on a smaller cloud: vertex count differs by 1e-6 (parallel rounding).
#
# Usage: build-poissonrecon.sh [workdir]  -> <workdir>/PoissonRecon.bb
# Note: compiling PoissonRecon.cpp needs > 8 GB RAM per compiler job (template-heavy code).
set -euo pipefail
W="${1:-$PWD/poissonrecon-build}"
J="${JOBS:-$(nproc)}"
mkdir -p "$W" && cd "$W"
rm -rf PoissonRecon
git clone -q https://github.com/OpenDroneMap/PoissonRecon.git
cd PoissonRecon && git checkout -q 97caa6d
# Src/PreProcessor.h unconditionally does "#undef BIG_DATA" in this version, so -DBIG_DATA on the command line has
# no effect - the switch has to be flipped in the header itself (this also enables USE_DEEP_TREE_NODES).
grep -q '^#undef BIG_DATA' Src/PreProcessor.h
sed -i 's|^#undef BIG_DATA|#define BIG_DATA|' Src/PreProcessor.h
grep -q '^#define BIG_DATA' Src/PreProcessor.h
make -j"$J" poissonrecon CFLAGS_RELEASE="-O3 -DRELEASE -ffast-math -g" >/dev/null
cp Bin/Linux/PoissonRecon "$W/PoissonRecon.bb" && strip "$W/PoissonRecon.bb"
echo "OK: $W/PoissonRecon.bb"
