#!/bin/bash
# Wrapper around OpenSfM's bin/opensfm (the original is renamed to opensfm.real).
#
# Patch 15 – extra OpenSfM config: lines "key: value" in /var/www/data/bitblade_osfm_extra are written into
#   config.yaml before detect_features (existing keys are replaced). ODM does not expose every OpenSfM option.
#   Example (dataset without GPS, all pairs were matched with the Python BoW matcher, ~30 h):
#     matcher_type: FLANN
#     matching_bow_neighbors: 40
#     matching_order_neighbors: 20
#   -> ~70 min.
# Patch 5/31 – reuse poses from an earlier run: if /var/www/data/bitblade_prior/shots.geojson (+ cameras.json)
#   exists, "reconstruct" imports the optimised poses of a previous run with the SAME images instead of the
#   incremental reconstruction (bitblade_prior.py). If the quality check fails, the standard reconstruct runs.
#   Disable: create /var/www/data/bitblade_prior/AUS.
# Patch 11 – pitch check after every successful reconstruction (bitblade_pitchcheck.py): photos whose computed
#   pitch differs by > 10 deg from the gimbal pitch in the DJI XMP are removed from reconstruction.json.
DIR=$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )
P=/var/www/data/bitblade_prior
check(){ python3 "$DIR/bitblade_pitchcheck.py" "$1" || true; }
X=/var/www/data/bitblade_osfm_extra
if [ "$1" = "detect_features" ] && [ -s "$X" ] && [ -f "$2/config.yaml" ]; then
  # ODM writes config.yaml without a trailing newline
  [ -n "$(tail -c1 "$2/config.yaml")" ] && echo >> "$2/config.yaml"
  while IFS= read -r line; do
    k="${line%%:*}"; [ -z "$k" ] && continue
    sed -i "/^${k}:/d" "$2/config.yaml"; echo "$line" >> "$2/config.yaml"
    echo "[bitblade] OpenSfM setting: $line"
  done < "$X"
fi
if [ "$1" = "reconstruct" ]; then
  if [ -s "$P/shots.geojson" ] && [ ! -e "$P/AUS" ]; then
    echo "[bitblade] reconstruct with poses from a previous run ($P)"
    if PYTHONPATH="$DIR/..${PYTHONPATH:+:$PYTHONPATH}" python3 "$DIR/bitblade_prior.py" "$2" "$P"; then check "$2"; exit 0; fi
    echo "[bitblade] pose import failed -> standard reconstruct"
  fi
  "$DIR/opensfm.real" "$@"; rc=$?
  [ $rc -eq 0 ] && check "$2"
  exit $rc
fi
exec "$DIR/opensfm.real" "$@"
