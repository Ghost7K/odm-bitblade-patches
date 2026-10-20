#!/bin/bash
# Wrapper around PoissonRecon (the original is renamed to PoissonRecon.real).
#
# Patch 13: PoissonRecon.bb = the same code ODM builds (OpenDroneMap/PoissonRecon branch 290, v13.8) but compiled
#   with BIG_DATA (64-bit node indices). Without it, octree depth 13 on dense, "volumetric" clouds (buildings,
#   vegetation) creates more than 2^31 octree nodes -> int overflow of the node index -> deterministic segfault
#   (exit 139), independent of thread count. See build-poissonrecon.sh.
#   BIG_DATA needs roughly 45-60 % more RAM (measured: depth 11 8.5 -> 13.4 GB, depth 12 21.9 GB -> OOM at 32 GB),
#   so it is only used as a FALLBACK after the normal build crashed. Disable: /var/www/data/bitblade_poisson_orig
# Patch 9: safety net. If PoissonRecon still crashes (exit >= 128, e.g. OOM), retry with --depth -1, then -2
#   (a coarser mesh instead of losing the whole task).
DIR="$(dirname "$0")"
BIN="$DIR/PoissonRecon.real"
"$BIN" "$@"; rc=$?
[ $rc -lt 128 ] && exit $rc
if [ -x "$DIR/PoissonRecon.bb" ] && [ ! -e /var/www/data/bitblade_poisson_orig ]; then
  echo "[bitblade] PoissonRecon crashed (rc=$rc) - retrying with PoissonRecon.bb (Patch 13: 64-bit node indices)"
  "$DIR/PoissonRecon.bb" "$@"; rc=$?
  [ $rc -lt 128 ] && exit $rc
fi
args=("$@"); d=""
for i in "${!args[@]}"; do [ "${args[$i]}" = "--depth" ] && d=$((i+1)); done
[ -z "$d" ] && exit $rc
orig=${args[$d]}
for red in 1 2; do
  args[$d]=$((orig-red))
  echo "[bitblade] PoissonRecon crashed (rc=$rc) - retrying with --depth ${args[$d]}"
  "$BIN" "${args[@]}"; rc=$?
  [ $rc -lt 128 ] && exit $rc
done
exit $rc
