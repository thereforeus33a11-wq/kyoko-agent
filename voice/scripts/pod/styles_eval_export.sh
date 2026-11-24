#!/usr/bin/env bash
# Scoring the five-style run, step 1: every kept checkpoint to a sherpa-onnx voice (Piper's export_onnx, then
# sherpa_meta.py with the five-speaker config: num_speakers 5, speaker_id_map normal 0 .. yell 4), and seeded copies
# of each (seed_onnx.py) so every candidate is spoken with the same noise seeds. The baseline is the phone's own
# voice (phone_lang2 = e974, proved sample-identical to e974's export by parity_styles.sh), seeded with every seed.
# A candidate with only a slim copy (slim_ckpt.py) is merged into a full checkpoint of the same run first.
# Settings: OUT, KEEP (full checkpoints), SLIMS (folders holding keep-epoch=E.gen.pt), MERGE_BASE (a full checkpoint
# of the run), CFG, PHONE (the phone's sherpa dir), SEEDS (candidates), BASE_SEEDS (the baseline), JOBS.
# Usage: bash styles_eval_export.sh E [E ...]      (0-based epochs of keep-epoch=E; "base" = the phone voice)
# Ends with EVAL-EXPORT-DONE; a failed export writes EXPORT-FAILED <E> and the run goes on with the others.
set -uo pipefail
source /w/job/scripts/lang_env.sh
OUT=${OUT:-/w/range_build/styles/eval}; KEEP=${KEEP:-/w/piper-styles-keep}
SLIMS=${SLIMS:-"/w/piper-styles-keep/slim $OUT/slim_first"}
MERGE_BASE=${MERGE_BASE:-$KEEP/keep-epoch=1124.ckpt}
CFG=${CFG:-/w/range_build/styles/ja_JP-yume-medium.onnx.json}
PHONE=${PHONE:-/w/yume/phone_lang2/sherpa}
SEEDS=${SEEDS:-"1234 5678"}; BASE_SEEDS=${BASE_SEEDS:-"1234 5678 9012 3456"}; JOBS=${JOBS:-6}
SC=/w/job/scripts
export OMP_NUM_THREADS=${OMP_NUM_THREADS:-8} CUDA_VISIBLE_DEVICES=
mkdir -p $OUT/voices $OUT/tmp
step() { echo "=== $(date -u +%H:%M:%S) $*"; }

seeded() {  # seeded <voice dir> <seeds>
  for s in $2; do
    mkdir -p $1/seed$s
    python $SC/seed_onnx.py $1/sherpa/model.onnx $1/seed$s/model.onnx $s > /dev/null && cp $1/sherpa/tokens.txt $1/seed$s/
  done
}

one() {  # one <epoch>
  local E=$1 D=$OUT/voices/e$1 CK
  if [ -s $D/sherpa/model.onnx ] && [ -s $D/seed${SEEDS##* }/model.onnx ]; then echo "e$E exported already"; return 0; fi
  mkdir -p $D
  CK=$KEEP/keep-epoch=$E.ckpt
  if [ ! -s $CK ]; then
    local SL=""
    for d in $SLIMS; do [ -s $d/keep-epoch=$E.gen.pt ] && SL=$d/keep-epoch=$E.gen.pt && break; done
    [ -n "$SL" ] || { echo "EXPORT-FAILED $E: no checkpoint and no slim"; return 1; }
    CK=$OUT/tmp/merged_e$E.ckpt
    python $SC/slim_ckpt.py --merge $SL $MERGE_BASE $CK > $D/merge.log 2>&1 || { echo "EXPORT-FAILED $E: merge"; return 1; }
    echo "slim $SL" >> $D/merge.log
  fi
  echo "checkpoint $CK" > $D/export.log
  (cd /w/piper1-gpl && python -m piper.train.export_onnx --checkpoint "$CK" --output-file $D/export.onnx >> $D/export.log 2>&1) \
    && python $SC/sherpa_meta.py $D/export.onnx $CFG $D/sherpa >> $D/export.log 2>&1 \
    || { echo "EXPORT-FAILED $E: export (see $D/export.log)"; rm -f $D/export.onnx; return 1; }
  rm -f $D/export.onnx
  [ "$CK" = "$OUT/tmp/merged_e$E.ckpt" ] && rm -f "$CK"
  cp $CFG $D/ja_JP-yume-medium.onnx.json
  seeded $D "$SEEDS"
  sha256sum $D/sherpa/model.onnx | cut -d' ' -f1 > $D/sherpa/model.onnx.sha256
  echo "e$E exported: $(stat -c %s $D/sherpa/model.onnx) bytes"
}

source /w/piper-env/bin/activate
step "export: $*"
for E in "$@"; do
  if [ "$E" = base ]; then
    D=$OUT/voices/e974; mkdir -p $D/sherpa
    cp $PHONE/model.onnx $PHONE/tokens.txt $D/sherpa/
    cp $(dirname $PHONE)/ja_JP-yume-medium.onnx.json $D/
    seeded $D "$BASE_SEEDS"; echo "e974 (the phone voice) seeded: $BASE_SEEDS"
    continue
  fi
  while [ "$(jobs -rp | wc -l)" -ge "$JOBS" ]; do sleep 2; done
  one $E &
done
wait
step EVAL-EXPORT-DONE
