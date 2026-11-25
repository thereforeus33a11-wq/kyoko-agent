#!/usr/bin/env bash
# Rejudging the five-style voice, step 2: the scoring folders and their speaking (nothing of hers in this file).
#   $S/eval     the style lines (each style's new and held-out lines; yell also its 24 left-out lines):
#               e974 sid 0, e1749 sid 0 and e1749 with the style's sid, every seed in SEEDS
#   $S/eval_s0  yesterday's sid 0 gate set (her 60 held-out bilingual lines and her_test.txt): e974 with every seed in
#               SEEDS, e1749 sid 0 with SEEDS0 (yesterday's gate: the candidate's two seeds, e974's four for the noise)
# Lines come from $S/lines.tsv (styles2_lines.py); each folder gets lines/meta.tsv and lines/sid<N>.tsv from
# styles_eval.py lines, and yesterday's sets.tsv (the classifier's 1,000 training clips; the real held-out clips).
# Speaking is yesterday's styles_eval_speak.sh (phone_test_lang.py, the phone's way), once per style seed.
# Settings: S, SEEDS, SEEDS0, JOBS, THREADS. Ends with STYLES2-SPEAK-DONE.
set -uo pipefail
source /w/job/scripts/lang_env.sh
S=${S:-/w/range_build/styles2}; SEEDS=${SEEDS:-"2101 2202 2303 2404"}; SEEDS0=${SEEDS0:-"2101 2202"}
JOBS=${JOBS:-12}; THREADS=${THREADS:-2}
PY=/w/job/scripts/styles_eval.py
PREV=$S/prev/range_build/styles/eval
step() { echo "=== $(date -u +%H:%M:%S) $*"; }
mkdir -p $S/eval/lines $S/eval_s0/lines $S/eval_s0/voices
# the style lines and the sid 0 gate lines, as two scoring-line files
awk -F'\t' 'NR == 1 || $2 != "0"' $S/lines.tsv > $S/lines_styles.tsv
awk -F'\t' 'NR == 1 || $2 == "0"' $S/lines.tsv > $S/lines_s0.tsv
step "lines"
gsv python $PY lines --out $S/eval --lines $S/lines_styles.tsv | grep -v '^WARNING'
gsv python $PY lines --out $S/eval_s0 --lines $S/lines_s0.tsv | grep -v '^WARNING'
# sid 0 of the style folder speaks every style line except the left-out yell lines (pitch-only lines of sid 4)
awk -F'\t' 'NR == 1 {for (i = 1; i <= NF; i++) if ($i == "group") g = i; print; next} $g !~ /_excluded$/' \
  $S/eval/lines/meta.tsv > $S/eval/lines/sid0.tsv
cp $PREV/sets.tsv $S/eval/sets.tsv
awk -F'\t' 'NR == 1 || $3 == "set"' $PREV/sets.tsv > $S/eval_s0/sets.tsv
for v in e974 e1749; do [ -e $S/eval_s0/voices/$v ] || ln -s $S/eval/voices/$v $S/eval_s0/voices/$v; done
for k in 0 1 2 3 4; do echo "sid$k $(($(wc -l < $S/eval/lines/sid$k.tsv) - 1)) style lines, $(($(wc -l < $S/eval_s0/lines/sid$k.tsv) - 1)) gate lines"; done
step "speak the style lines"
for st in $SEEDS; do
  OUT=$S/eval SEEDS0="$SEEDS" BASE_SEEDS="$SEEDS" SEED_STYLE=$st JOBS=$JOBS THREADS=$THREADS \
    bash /w/job/scripts/styles_eval_speak.sh e974 e1749
done
step "speak the sid 0 gate lines"
OUT=$S/eval_s0 SEEDS0="$SEEDS0" BASE_SEEDS="$SEEDS" SEED_STYLE=${SEEDS0%% *} JOBS=$JOBS THREADS=$THREADS \
  bash /w/job/scripts/styles_eval_speak.sh e974 e1749
n=$(find $S/eval/wav $S/eval_s0/wav -name '[0-9]*.wav' | wc -l)
grep -l "SPEAK-FAILED\|Traceback" $S/eval/wav/*/*.log $S/eval/wav/*/*/*.log $S/eval_s0/wav/*/*/*.log 2>/dev/null | head
step "STYLES2-SPEAK-DONE: $n clips"
