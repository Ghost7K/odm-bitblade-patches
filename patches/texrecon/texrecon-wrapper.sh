#!/bin/sh
# Wrapper around texrecon (mvs-texturing). The original is renamed to texrecon.real; texrecon.bb is the patched
# build from build-texrecon.sh (Patch 10, 22-29). If texrecon.bb fails, the original runs automatically.
#
# Defaults set here (each can be switched off with a flag file in /var/www/data):
#   Patch 28  view selection (MRF) in 48 parallel tiles      off: bitblade_tex_mrf_aus   (env BITBLADE_TEX_MRF_TILES)
#   Patch 27  top-K 32 candidate views per face, 2.5D only   off: bitblade_tex_topk_aus  (env BITBLADE_TEX_TOPK)
#             (in 3D top-K was measurably worse, so it is only used with --nadir_mode)
#   Patch 29  visibility/quality normalisation fix           off: bitblade_tex_visfix_aus (env BITBLADE_TEX_VISFIX=0)
#   Patch 22  second pass for faces without any view (glass) off: bitblade_tex_fallback_aus (env BITBLADE_TEX_FALLBACK)
#   everything: use the original texrecon                    flag: bitblade_texrecon_orig
if [ ! -e /var/www/data/bitblade_tex_mrf_aus ] && [ -z "$BITBLADE_TEX_MRF_TILES" ]; then
  export BITBLADE_TEX_MRF_TILES=48
  echo "[bitblade] texrecon Patch 28: view selection in 48 parallel tiles"
fi
case " $* " in
  *" --nadir_mode "*)
    if [ ! -e /var/www/data/bitblade_tex_topk_aus ] && [ -z "$BITBLADE_TEX_TOPK" ]; then
      export BITBLADE_TEX_TOPK=32
      echo "[bitblade] texrecon Patch 27: 2.5D with top-K 32 views per face"
    fi;;
esac
if [ -e /var/www/data/bitblade_tex_visfix_aus ]; then
  export BITBLADE_TEX_VISFIX=0
  echo "[bitblade] texrecon Patch 29 disabled"
fi
if [ ! -e /var/www/data/bitblade_tex_fallback_aus ]; then
  export BITBLADE_TEX_FALLBACK=1
  echo "[bitblade] texrecon Patch 22: second pass for otherwise deleted faces (glass) enabled"
fi
DIR="$(dirname "$0")"
REAL="$DIR/texrecon.real"
BB="$DIR/texrecon.bb"
if [ -x "$BB" ] && [ ! -e /var/www/data/bitblade_texrecon_orig ]; then
  echo "[bitblade] texrecon.bb (Patch 10/22-29)"
  "$BB" "$@"
  rc=$?
  [ $rc -eq 0 ] && exit 0
  echo "[bitblade] texrecon.bb failed (rc=$rc) - falling back to the original texrecon"
fi
exec "$REAL" "$@"
