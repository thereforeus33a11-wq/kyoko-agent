#!/usr/bin/env bash
# The chosen five-style voice to the volume, for the phone: DEST/sherpa/model.onnx, DEST/sherpa/tokens.txt,
# DEST/ja_JP-yume-medium.onnx.json (num_speakers 5, speaker_id_map normal 0 .. yell 4), each with a .sha256 beside it
# (podio.py down reads those), and its full training checkpoint to KEEP_VOL if it is not there yet. Every write is
# under the volume lock, one file at a time, written as .part, read back and checked, then renamed.
# Usage: bash styles_eval_ship.sh <voice, e.g. e1449>      Settings: OUT, DEST, KEEP, KEEP_VOL. Ends with SHIP-DONE.
set -euo pipefail
OUT=${OUT:-/w/range_build/styles/eval}; DEST=${DEST:-/workspace/yume/phone_styles}
KEEP=${KEEP:-/w/piper-styles-keep}; KEEP_VOL=${KEEP_VOL:-/workspace/yume/piper-styles-keep}
V=$1; E=${V#e}; SRC=$OUT/voices/$V
put() {  # put <src> <dst>: copy under the lock, check the copy read back from the volume, write <dst>.sha256
  local want got
  want=$(sha256sum "$1" | cut -d' ' -f1)
  flock /w/locks/volume bash -c "cp '$1' '$2.part' && sync '$2.part' && mv -f '$2.part' '$2'"
  got=$(flock /w/locks/volume sha256sum "$2" | cut -d' ' -f1)
  [ "$want" = "$got" ] || { echo "SHIP-FAILED: $2 reads back $got, not $want"; exit 1; }
  echo "$want" > "$2.sha256"
  [ "$(cat "$2.sha256")" = "$want" ] || { echo "SHIP-FAILED: $2.sha256 not written"; exit 1; }
  echo "$2 $(stat -c %s "$2") bytes sha256 $want"
}
python3 - "$SRC/ja_JP-yume-medium.onnx.json" <<'PY'
import json, sys
c = json.load(open(sys.argv[1], encoding="utf-8"))
assert c["num_speakers"] == 5 and c["speaker_id_map"] == {"normal": 0, "soft": 1, "whisper": 2, "loud": 3, "yell": 4}, c["speaker_id_map"]
print("config: num_speakers", c["num_speakers"], "speaker_id_map", c["speaker_id_map"])
PY
mkdir -p $DEST/sherpa
put $SRC/sherpa/model.onnx $DEST/sherpa/model.onnx
put $SRC/sherpa/tokens.txt $DEST/sherpa/tokens.txt
put $SRC/ja_JP-yume-medium.onnx.json $DEST/ja_JP-yume-medium.onnx.json
echo "$V" > $DEST/VOICE_EPOCH.txt
if [ -s $KEEP/keep-epoch=$E.ckpt ]; then
  if [ -s $KEEP_VOL/keep-epoch=$E.ckpt ] && [ "$(cat $KEEP_VOL/keep-epoch=$E.ckpt.sha256 2>/dev/null)" = "$(cat $KEEP/keep-epoch=$E.ckpt.sha256 2>/dev/null)" ]; then
    echo "checkpoint keep-epoch=$E.ckpt is on the volume already"
  else
    put $KEEP/keep-epoch=$E.ckpt $KEEP_VOL/keep-epoch=$E.ckpt
  fi
else
  echo "no full checkpoint keep-epoch=$E.ckpt on /w (slim only): its slim is kept in the agent's container"
fi
ls -la $DEST $DEST/sherpa
echo SHIP-DONE
