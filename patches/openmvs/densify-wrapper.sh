#!/bin/sh
# Wrapper around OpenMVS DensifyPointCloud (the original is renamed to DensifyPointCloud.real).
#
# Patch 6 – force tiling up front: with the flag file /var/www/data/bitblade_pctile, the FIRST full (untiled)
#   densify call exits immediately with 137. ODM treats that like an out-of-memory kill and switches to its
#   tiled path (--fusion-mode 1 + sub-scenes) right away, instead of running for hours into a real OOM.
#   This is a workaround; the clean fix would be for ODM to choose tiling based on an estimated RAM need.
# Patch 12 – skip the OpenMVS visibility filter: with /var/www/data/bitblade_novisfilter the
#   --filter-point-cloud step is skipped and the unfiltered X.ply is passed on as X_dense_filtered.ply (what ODM
#   does for pc-filter 0). Reason: the filter removes thin structures (bridge decks, railings, masts). The
#   statistical filter in FPCFilter (pc-filter) and the boundary stay active.
REAL="$(dirname "$0")/DensifyPointCloud.real"
F=/var/www/data/bitblade_pctile
case " $* " in
  *" --filter-point-cloud "*)
    if [ -e /var/www/data/bitblade_novisfilter ]; then
      IN=""; prev=""
      for a in "$@"; do
        case "$a" in *.mvs) [ -z "$IN" ] && IN="$a";; esac
        [ "$prev" = "-i" ] && IN="$a"
        prev="$a"
      done
      SRC="${IN%.mvs}.ply"; OUT="${IN%.mvs}_dense_filtered.ply"
      if [ -n "$IN" ] && [ -s "$SRC" ]; then
        echo "[bitblade] OpenMVS visibility filter skipped: $(basename "$SRC") -> $(basename "$OUT")"
        ln -f "$SRC" "$OUT" 2>/dev/null || cp "$SRC" "$OUT"
        exit 0
      fi
      echo "[bitblade] novisfilter: input not found ($IN) - filter runs normally"
    fi;;
  *" --dense-config-file "*)
    case " $* " in *" --fusion-mode "*|*"--sub-scene"*) ;; *)
      if [ -e "$F" ] && [ ! -e "$F.benutzt" ]; then
        touch "$F.benutzt"; echo "[bitblade] tiling forced up front (exit 137, ODM switches to tiled densify)"; exit 137
      fi;; esac;;
esac
exec "$REAL" "$@"
