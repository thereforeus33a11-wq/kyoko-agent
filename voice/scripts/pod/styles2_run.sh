#!/usr/bin/env bash
# Rejudging the five-style voice, step 3: hear, measure and embed everything spoken (yesterday's styles_eval_run.sh,
# unchanged), the style lines first, then yesterday's sid 0 gate set (scored by yesterday's styles_eval_score.py with
# the candidate's seeds 2101 2202 and e974's four), then the settings grid (styles2_knobs.sh) and its clips.
# Nothing of hers in this file. Settings: S, KNOBS (1: also the grid). Ends with STYLES2-RUN-DONE.
set -uo pipefail
source /w/job/scripts/lang_env.sh
S=${S:-/w/range_build/styles2}; KNOBS=${KNOBS:-1}
step() { echo "=== $(date -u +%H:%M:%S) $*"; }
step "style lines"
OUT=$S/eval ASR_SHARDS=4 MEASURE_JOBS=14 bash /w/job/scripts/styles_eval_run.sh
step "sid 0 gate set"
OUT=$S/eval_s0 ASR_SHARDS=3 MEASURE_JOBS=14 bash /w/job/scripts/styles_eval_run.sh
gsv python /w/job/scripts/styles_eval_score.py --out $S/eval_s0 --seeds0 "2101 2202" --seed-style 2101 > $S/eval_s0/logs/score_s0.log 2>&1
tail -3 $S/eval_s0/logs/score_s0.log
if [ "$KNOBS" = 1 ]; then
  step "settings grid: speak"
  OUT=$S/eval bash /w/job/scripts/styles2_knobs.sh
  step "settings grid: hear, measure, embed"
  OUT=$S/eval ASR_SHARDS=5 MEASURE_JOBS=14 bash /w/job/scripts/styles_eval_run.sh
fi
step STYLES2-RUN-DONE
