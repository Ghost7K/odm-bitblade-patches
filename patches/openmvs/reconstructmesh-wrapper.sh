#!/bin/bash
# bitblade-patch 32 (10.10.2026): Wrapper um ReconstructMesh (Original: ReconstructMesh.real).
# Bei "-i <netz.ply> ... --target-face-num N" und Netz > 1,5 x N: erst schnelle Dezimierung (bitblade_fastdecimate.py),
# dann Original mit denselben Argumenten auf dem kleinen Netz (Bereinigung). Jeder Fehler -> Original unveraendert.
# Abschalten: Datei /var/www/data/bitblade_fastdecimate_aus anlegen.
DIR="$(cd "$(dirname "$0")" && pwd)"; REAL="$DIR/ReconstructMesh.real"
args=("$@"); IN=""; T=""; ii=-1
for ((k=0; k<${#args[@]}; k++)); do
  case "${args[$k]}" in
    -i|--input-file) IN="${args[$((k+1))]}"; ii=$((k+1));;
    --target-face-num) T="${args[$((k+1))]}";;
  esac
done
PY=/code/venv/bin/python3; [ -x "$PY" ] || PY=python3
if [ ! -e /var/www/data/bitblade_fastdecimate_aus ] && [ -n "$IN" ] && [ -n "$T" ] && [ "${IN##*.}" = "ply" ] && [ -f "$IN" ] && [ -f "$DIR/bitblade_fastdecimate.py" ]; then
  TMP="${IN%.ply}.bbdez.ply"
  "$PY" "$DIR/bitblade_fastdecimate.py" "$IN" "$TMP" "$T"; rc=$?
  if [ $rc -eq 0 ] && [ -s "$TMP" ]; then
    args[$ii]="$TMP"
    "$REAL" "${args[@]}"; rc2=$?
    if [ $rc2 -eq 0 ]; then rm -f "$TMP"; exit 0; fi
    echo "[bitblade] Patch 32: ReconstructMesh auf dezimiertem Netz fehlgeschlagen (rc=$rc2) -> Original"
    rm -f "$TMP"; args[$ii]="$IN"
  elif [ $rc -ne 2 ]; then
    echo "[bitblade] Patch 32: schnelle Dezimierung fehlgeschlagen (rc=$rc) -> Original"; rm -f "$TMP"
  fi
fi
exec "$REAL" "${args[@]}"
