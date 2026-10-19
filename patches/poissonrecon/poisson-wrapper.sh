#!/bin/bash
# Wrapper around PoissonRecon (the original is renamed to PoissonRecon.real).
#
# Patch 13: PoissonRecon.bb = the same code ODM builds (OpenDroneMap/PoissonRecon tag 290, v13.8) but compiled
#   with BIG_DATA (64-bit node indices). Without it, octree depth 13 on dense, "volumetric" clouds (buildings,
#   vegetation) creates more than 2^31 octree nodes -> int overflow of the node index -> deterministic segfault
#   (exit 139), independent of thread count. See build-poissonrecon.sh. Disable: /var/www/data/bitblade_poisson_orig
# Patch 9: safety net. If PoissonRecon crashes (exit >= 128, e.g. OOM), retry with --depth -1, then -2
#   (a coarser mesh instead of losing the whole task).
DIR="$(dirname "$0")"
BIN="$DIR/PoissonRecon.real"
if [ -x "$DIR/PoissonRecon.bb" ] && [ ! -e /var/www/data/bitblade_poisson_orig ]; then
  BIN="$DIR/PoissonRecon.bb"; echo "[bitblade] PoissonRecon.bb (Patch 13: 64-bit node indices)"
fi
"$BIN" "$@"; rc=$?
[ $rc -lt 128 ] && exit $rc
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
