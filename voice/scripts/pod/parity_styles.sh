#!/usr/bin/env bash
# Proof that the five-style warm start speaks exactly as her phone voice at step 0: export the warm-start
# checkpoint and the base, give every random node of each graph the same seed (seed_onnx.py), speak the same
# lines the phone's way (phone_test_lang.py, sherpa-onnx, 32-bit float output) with sid 0..4, and compare the
# waveforms (wav_parity.py). Controls: the phone's own model twice with one seed (the path is deterministic)
# and with another seed (the comparison sees a change of noise).
# Settings: BASE_CK, WS_CK, PHONE (the phone's sherpa dir), OUT, LINES (TSV with n and text), SEED, SEED2, THREADS.
set -euo pipefail
source /w/job/scripts/lang_env.sh
BASE_CK=${BASE_CK:-/w/yume/piper-lang2-keep/keep-epoch=974.ckpt}
WS_CK=${WS_CK:-/w/piper-styles-ws/ws_e974_styles.ckpt}
PHONE=${PHONE:-/w/yume/phone_lang2/sherpa}
PHONE_CFG=${PHONE_CFG:-/w/yume/phone_lang2/ja_JP-yume-medium.onnx.json}
OUT=${OUT:-/w/range_build/styles/parity}; LINES=${LINES:-$OUT/lines.tsv}
SEED=${SEED:-1234}; SEED2=${SEED2:-5678}; THREADS=${THREADS:-2}
SC=$J/scripts
step() { echo "=== $(date -u +%H:%M:%S) $*"; }
source /w/piper-env/bin/activate
cd /w/piper1-gpl
export CUDA_VISIBLE_DEVICES=
mkdir -p $OUT
# The five-style config: the phone's, with five speakers named in sid order.
python - "$PHONE_CFG" "$OUT/styles.onnx.json" <<'PY'
import json, sys
c = json.load(open(sys.argv[1], encoding="utf-8"))
c["num_speakers"] = 5
c["speaker_id_map"] = {"normal": 0, "soft": 1, "whisper": 2, "loud": 3, "yell": 4}
json.dump(c, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False, indent=2)
PY
export_voice() {  # export_voice <ckpt> <config> <dir>
  mkdir -p $3
  python -m piper.train.export_onnx --checkpoint "$1" --output-file $3/export.onnx > $3/export.log 2>&1
  python $SC/sherpa_meta.py $3/export.onnx $2 $3/voice >> $3/export.log 2>&1
  rm -f $3/export.onnx
}
seeded() {  # seeded <voice dir> <seed> <out dir>
  mkdir -p $3
  python $SC/seed_onnx.py $1/model.onnx $3/model.onnx $2
  cp $1/tokens.txt $3/
}
speak() {  # speak <voice dir> <sid> <wav dir>
  mkdir -p $3
  python $SC/phone_test_lang.py $1 $LINES $3 --sid $2 --threads $THREADS --float > $3.log 2>&1
}
step "export the base and the warm start"
export_voice $BASE_CK $PHONE_CFG $OUT/base_export
export_voice $WS_CK $OUT/styles.onnx.json $OUT/ws_export
ls -la $PHONE/model.onnx $OUT/base_export/voice/model.onnx $OUT/ws_export/voice/model.onnx
step "seed $SEED on every random node"
seeded $PHONE $SEED $OUT/v_phone
seeded $PHONE $SEED2 $OUT/v_phone_seed2
seeded $OUT/base_export/voice $SEED $OUT/v_base
seeded $OUT/ws_export/voice $SEED $OUT/v_ws
step "speak"
speak $OUT/v_phone 0 $OUT/w/phone_s0
speak $OUT/v_phone 0 $OUT/w/phone_s0_again
speak $OUT/v_phone_seed2 0 $OUT/w/phone_s0_seed2
speak $OUT/v_base 0 $OUT/w/base_s0
for sid in 0 1 2 3 4; do speak $OUT/v_ws $sid $OUT/w/ws_s$sid; done
step "compare"
cmp_() { echo "--- $1"; python $SC/wav_parity.py $OUT/w/$2 $OUT/w/$3 --json $OUT/cmp_$1.json > $OUT/cmp_$1.txt; head -1 $OUT/cmp_$1.txt; }
cmp_ phone_vs_phone_again phone_s0 phone_s0_again
cmp_ phone_vs_phone_seed2 phone_s0 phone_s0_seed2
cmp_ phone_vs_base_export phone_s0 base_s0
for sid in 0 1 2 3 4; do cmp_ phone_vs_ws_sid$sid phone_s0 ws_s$sid; done
step PARITY-DONE
