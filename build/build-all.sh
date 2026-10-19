#!/bin/bash
# Build the native parts (texrecon.bb, PoissonRecon.bb, FPCFilter.p41) into <repo>/bin.
# Run inside the ODM image so the binaries match its OS and libraries, e.g.:
#   docker run --rm -v "$PWD":/patches --entrypoint bash opendronemap/nodeodm:3.6.2 /patches/build/build-all.sh
set -euo pipefail
R="$(cd "$(dirname "$0")/.." && pwd)"
W="${WORK:-/tmp/odm-patches-build}"
mkdir -p "$R/bin" "$W"
if command -v apt-get >/dev/null; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq >/dev/null
  apt-get install -y -qq --no-install-recommends git curl ca-certificates build-essential cmake python3 \
    libtbb-dev libpng-dev libjpeg-dev libtiff-dev libeigen3-dev >/dev/null
fi
bash "$R/patches/poissonrecon/build-poissonrecon.sh" "$W/poisson" && cp "$W/poisson/PoissonRecon.bb" "$R/bin/"
bash "$R/patches/fpcfilter/build-fpcfilter.sh" "$W/fpcfilter" && cp "$W/fpcfilter/FPCFilter.p41" "$R/bin/"
bash "$R/patches/texrecon/build-texrecon.sh" "$W/texrecon" && cp "$W/texrecon/texrecon.bb" "$R/bin/"
ls -la "$R/bin"
