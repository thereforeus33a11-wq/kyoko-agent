#!/usr/bin/env bash
# Scoring the five-style run, step 2: speak the scoring lines the phone's way (phone_test_lang.py: mixed phonemizer,
# phoneme codepoints, sherpa-onnx, --sid) with every candidate's seeded copies. sid 0 lines (her held-out bilingual
# lines and her_test.txt) with every seed in SEEDS0; each style's lines with its own sid and seed SEED_STYLE.
# The baseline e974 (the phone voice, one speaker) speaks the sid 0 lines with every seed in BASE_SEEDS.
# Usage: bash styles_eval_speak.sh <voice> [<voice> ...]   (folders under $OUT/voices, e.g. e974 e1749)
# Writes $OUT/wav/<voice>/seed<S>/sid<N>/NNNN.wav (+ phone_test.tsv, .log). Ends with EVAL-SPEAK-DONE.
set -uo pipefail
source /w/job/scripts/lang_env.sh
OUT=${OUT:-/w/range_build/styles/eval}
SEEDS0=${SEEDS0:-"1234 5678"}; SEED_STYLE=${SEED_STYLE:-1234}; BASE_SEEDS=${BASE_SEEDS:-"1234 5678 9012 3456"}
JOBS=${JOBS:-32}; THREADS=${THREADS:-2}
export CUDA_VISIBLE_DEVICES=
source /w/piper-env/bin/activate
cd /w/piper1-gpl
speak() {  # speak <voice> <seed> <sid>
  local D=$OUT/wav/$1/seed$2/sid$3
  if [ -s $D/phone_test.tsv ] && grep -q PHONE-TEST-DONE $D.log 2>/dev/null; then return 0; fi
  mkdir -p $D
  python /w/job/scripts/phone_test_lang.py $OUT/voices/$1/seed$2 $OUT/lines/sid$3.tsv $D --sid $3 --threads $THREADS > $D.log 2>&1 \
    || echo "SPEAK-FAILED $1 seed$2 sid$3 (see $D.log)"
}
echo "=== $(date -u +%H:%M:%S) speak: $*"
for V in "$@"; do
  if [ "$V" = e974 ]; then specs=$(for s in $BASE_SEEDS; do echo "$s:0"; done)
  else specs="$(for s in $SEEDS0; do echo "$s:0"; done) $(for sid in 1 2 3 4; do echo "$SEED_STYLE:$sid"; done)"; fi
  for sp in $specs; do
    while [ "$(jobs -rp | wc -l)" -ge "$JOBS" ]; do sleep 1; done
    speak $V ${sp%:*} ${sp#*:} &
  done
done
wait
echo "=== $(date -u +%H:%M:%S) EVAL-SPEAK-DONE"
