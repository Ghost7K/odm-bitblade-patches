#!/bin/sh
# Wrapper around ODM's FPCFilter (the original is renamed to FPCFilter.real).
# Patch 41: prefer the parallel build FPCFilter.p41 (block-wise read, parallel crop/kd-tree/write).
#   Output is byte-identical to the original. If it fails, the original runs with the same arguments.
#   Disable: create /var/www/data/bitblade_p41_aus.
REAL="$(dirname "$0")/FPCFilter.real"
P41="$(dirname "$0")/FPCFilter.p41"
if [ -x "$P41" ] && [ ! -e /var/www/data/bitblade_p41_aus ]; then
  echo "[bitblade] FPCFilter Patch 41 (parallel)"
  "$P41" "$@" && exit 0
  echo "[bitblade] FPCFilter Patch 41 failed -> original"
fi
exec "$REAL" "$@"
