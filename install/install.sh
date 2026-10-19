#!/bin/sh
# Install the patches into an ODM / NodeODM 3.6.x container (paths as in the official opendronemap images).
# Idempotent. Every patch checks its anchor in the original code and falls back to the original on any error,
# so an ODM version where an anchor no longer matches simply runs unpatched.
#
# Usage (inside the container, repo copied/mounted to /tmp/odm-patches):
#   sh /tmp/odm-patches/install/install.sh
# Optional prebuilt binaries (see build/build-all.sh) are picked up from $BB_BIN (default: <repo>/bin):
#   texrecon.bb  PoissonRecon.bb  FPCFilter.p41
# Optional switches (environment):
#   BB_ORIENTATION_PRIOR=1   Patch 1: always use OpenSfM align_method orientation_prior (see README before using!)
#   BB_SKIP="8 34 ..."       skip individual patches by number
set -e
R="$(cd "$(dirname "$0")/.." && pwd)"
BIN="${BB_BIN:-$R/bin}"
B=/code/SuperBuild/install/bin
O=$B/opensfm/bin
P=$B/opensfm/opensfm
PY=/code/venv/bin/python3; [ -x "$PY" ] || PY=python3
skip(){ case " $BB_SKIP " in *" $1 "*) echo "  Patch $1 skipped (BB_SKIP)"; return 0;; esac; return 1; }
orig(){ [ -e "$1.orig" ] || cp "$1" "$1.orig"; }
# wrap <binary in $B> <wrapper script>: rename the original to .real once, install the wrapper atomically
wrap(){ [ -e "$B/$1.real" ] || mv "$B/$1" "$B/$1.real"; cp "$2" "$B/$1.neu"; chmod 755 "$B/$1.neu"; mv -f "$B/$1.neu" "$B/$1"; }
echo "odm-patches: installing from $R"

# --- ODM (Python) ---------------------------------------------------------------------------------------------
if ! skip 8; then
  # whole-file replacement, based on ODM 3.6.2's opendm/gltf.py -> only if the original is exactly that file
  G=/code/opendm/gltf.py; src="$G"; [ -e "$G.orig" ] && src="$G.orig"
  if [ "$(md5sum < "$src" | cut -d' ' -f1)" != 765c373d58903923a49f301b30ab6b7f ]; then echo "  Patch 8  skipped (gltf.py differs from ODM 3.6.2)"
  else orig "$G"; cp "$R/patches/odm/gltf_fast.py" "$G"
    if $PY -m py_compile "$G"; then echo "  Patch 8  fast GLB export"; else cp "$G.orig" "$G"; echo "  Patch 8  NOT active"; fi
  fi
fi
if ! skip 3; then
  C=/code/opendm/dem/commands.py
  cp "$R/patches/odm/bitblade_smrf.py" /code/opendm/dem/bitblade_smrf.py
  if ! grep -q 'bitblade-patch 3' "$C"; then
    orig "$C"
    sed -i 's/pdal.run_pdaltranslate_smrf(lasFile, lasFile, scalar, slope, threshold, window)/from opendm.dem import bitblade_smrf; bitblade_smrf.run(lasFile, lasFile, scalar, slope, threshold, window)  # bitblade-patch 3/' "$C"
  fi
  if grep -q 'bitblade-patch 3' "$C" && $PY -m py_compile "$C" /code/opendm/dem/bitblade_smrf.py; then echo "  Patch 3  parallel SMRF ground classification"
  else [ -e "$C.orig" ] && cp "$C.orig" "$C"; echo "  Patch 3  NOT active"; fi
fi
if ! skip 40c; then
  D=/code/stages/dataset.py; orig "$D"
  cp "$R/patches/odm/bitblade_photos.py" /code/opendm/bitblade_photos.py
  if $PY "$R/patches/odm/bitblade_dataset_patch.py" "$D" >/dev/null && $PY -m py_compile "$D"; then echo "  Patch 40c parallel image metadata"
  else cp "$D.orig" "$D"; echo "  Patch 40c NOT active"; fi
fi
if ! skip 42; then
  F=/code/opendm/photo.py; orig "$F"
  if $PY "$R/patches/odm/patch42_photo.py" "$F" >/dev/null && $PY -m py_compile "$F"; then echo "  Patch 42 corrupt EXIF MakerNote tolerated"
  else cp "$F.orig" "$F"; echo "  Patch 42 NOT active"; fi
fi
if ! skip 44; then
  M=/code/opendm/multispectral.py; orig "$M"
  if $PY "$R/patches/odm/patch44_bands.py" "$M" >/dev/null && $PY -m py_compile "$M"; then echo "  Patch 44 DJI CalibratedHMatrix band alignment"
  else cp "$M.orig" "$M"; echo "  Patch 44 NOT active"; fi
fi
if [ "$BB_ORIENTATION_PRIOR" = 1 ] && ! skip 1; then
  if grep -q 'if has_alt or gcp_path:' /code/opendm/osfm.py; then
    orig /code/opendm/osfm.py
    sed -i 's/if has_alt or gcp_path:/if gcp_path:  # bitblade-patch orientation_prior/' /code/opendm/osfm.py
  fi
  grep -q 'bitblade-patch orientation_prior' /code/opendm/osfm.py && echo "  Patch 1  orientation_prior alignment"
fi

# --- OpenSfM ----------------------------------------------------------------------------------------------------
if ! skip 5; then
  [ -e "$O/opensfm.real" ] || mv "$O/opensfm" "$O/opensfm.real"
  cp "$R/patches/opensfm/opensfm-wrapper.sh" "$O/opensfm.neu"; chmod 755 "$O/opensfm.neu"; mv -f "$O/opensfm.neu" "$O/opensfm"
  cp "$R/patches/opensfm/bitblade_prior.py" "$R/patches/opensfm/bitblade_pitchcheck.py" "$O/"
  echo "  Patch 5/11/15 opensfm wrapper (prior poses, pitch check, extra config)"
fi
if ! skip 34; then
  cp "$R/patches/opensfm/undistort/bitblade_undistort_worker.py" "$O/"
  U=$P/undistort.py; orig "$U"
  if $PY "$R/patches/opensfm/undistort/bitblade_undistort_patch.py" "$U" >/dev/null && $PY -m py_compile "$U"; then echo "  Patch 34 undistort with processes"
  else cp "$U.orig" "$U"; echo "  Patch 34 NOT active"; fi
fi
if ! skip 40; then
  A=$P/actions
  # Patch 40 replaces whole action files. They are based on the OpenSfM commit pinned by ODM 3.6.2 (c532843);
  # only install if the originals are exactly those files (newer ODM/OpenSfM versions are left untouched).
  ok40=1
  for x in d864c80686d458567121529e643d3704:export_visualsfm 96bb70798c222946d705c005365d2f3d:export_openmvs \
           e3b46ba35e0fac6e059a2289f8d2f6bb:compute_statistics ddedf08c337c087b42d99f7d5140d8b3:create_tracks; do
    f=${x#*:}; m=${x%%:*}; src="$A/$f.py"; [ -e "$src.orig" ] && src="$src.orig"
    [ "$(md5sum < "$src" | cut -d' ' -f1)" = "$m" ] || ok40=0
  done
  if [ $ok40 = 0 ]; then echo "  Patch 40 skipped (OpenSfM version differs from ODM 3.6.2)"; else
  cp "$R"/patches/opensfm/p40/bitblade_forkmap.py "$R"/patches/opensfm/p40/bitblade_tracks.py "$P/"
  for f in export_visualsfm export_openmvs compute_statistics create_tracks; do orig "$A/$f.py"; cp "$R/patches/opensfm/p40/$f.py" "$A/$f.py"; done
  if (cd "$B/opensfm" && $PY -c "import opensfm.actions.export_visualsfm, opensfm.actions.export_openmvs, opensfm.actions.compute_statistics, opensfm.actions.create_tracks") >/dev/null 2>&1; then
    echo "  Patch 40 OpenSfM tracks/exports/statistics on all cores"
  else for f in export_visualsfm export_openmvs compute_statistics create_tracks; do cp "$A/$f.py.orig" "$A/$f.py"; done; echo "  Patch 40 NOT active"; fi
  fi
fi

# --- OpenMVS / meshing ------------------------------------------------------------------------------------------
if ! skip 6; then wrap DensifyPointCloud "$R/patches/openmvs/densify-wrapper.sh"; echo "  Patch 6/12 densify wrapper (opt-in flags)"; fi
if ! skip 32; then
  if $PY -c "import fast_simplification" 2>/dev/null || $PY -m pip install -q fast_simplification==0.2.0 >/dev/null 2>&1; then
    cp "$R/patches/openmvs/bitblade_fastdecimate.py" "$B/"; wrap ReconstructMesh "$R/patches/openmvs/reconstructmesh-wrapper.sh"
    echo "  Patch 32 fast mesh decimation"
  else echo "  Patch 32 NOT active (fast_simplification not installable)"; fi
fi
if ! skip 9; then
  wrap PoissonRecon "$R/patches/poissonrecon/poisson-wrapper.sh"
  if [ -x "$BIN/PoissonRecon.bb" ] && ! skip 13; then cp "$BIN/PoissonRecon.bb" "$B/PoissonRecon.bb"; chmod 755 "$B/PoissonRecon.bb"; echo "  Patch 13 PoissonRecon BIG_DATA"; fi
  echo "  Patch 9  PoissonRecon safety net"
fi
if [ -x "$BIN/FPCFilter.p41" ] && ! skip 41; then
  wrap FPCFilter "$R/patches/fpcfilter/fpcfilter-wrapper.sh"
  cp "$BIN/FPCFilter.p41" "$B/FPCFilter.p41"; chmod 755 "$B/FPCFilter.p41"; echo "  Patch 41 parallel FPCFilter"
fi
if [ -x "$BIN/texrecon.bb" ] && ! skip 10; then
  wrap texrecon "$R/patches/texrecon/texrecon-wrapper.sh"
  cp "$BIN/texrecon.bb" "$B/texrecon.bb"; chmod 755 "$B/texrecon.bb"; echo "  Patch 10/22-29 texrecon"
fi

# --- NodeODM ----------------------------------------------------------------------------------------------------
if [ -f /var/www/libs/odmRunner.js ] && ! skip 45; then
  $PY "$R/patches/nodeodm/patch45_nodeodm_quote.py" /var/www/libs/odmRunner.js || true
  echo "  (restart NodeODM for Patch 45 to take effect)"
fi
echo "odm-patches: done"
