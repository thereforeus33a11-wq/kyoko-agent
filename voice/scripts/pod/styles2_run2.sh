#!/usr/bin/env bash
# Rejudging the five-style voice, step 3 (second half): after the style lines' run (WAIT_PIDS) ends, yesterday's sid 0
# gates on the sid 0 gate set, the first full score (styles2_score.py), then the settings grid's hearing (yesterday's
# styles_eval_run.sh, resuming: only the grid's clips are new; numpy/BLAS threads capped so the hearing processes do
# not oversubscribe the pod's 27-CPU quota) and the score again. Nothing of hers in this file. Ends with STYLES2-RUN2-DONE.
set -uo pipefail
source /w/job/scripts/lang_env.sh
S=${S:-/w/range_build/styles2}; WAIT_PIDS=${WAIT_PIDS:-}
step() { echo "=== $(date -u +%H:%M:%S) $*"; }
for p in $WAIT_PIDS; do while kill -0 $p 2>/dev/null; do sleep 20; done; done
step "sid 0 gate set: score (yesterday's styles_eval_score.py)"
OUT=$S/eval_s0 ASR_SHARDS=2 MEASURE_JOBS=8 bash /w/job/scripts/styles_eval_run.sh > $S/eval_s0/logs/run_again.log 2>&1
gsv python /w/job/scripts/styles_eval_score.py --out $S/eval_s0 --seeds0 "2101 2202" --seed-style 2101 > $S/eval_s0/logs/score_s0.log 2>&1
tail -n 2 $S/eval_s0/logs/score_s0.log
step "first score"
gsv python /w/job/scripts/styles2_score.py --out $S/eval > $S/eval/logs/score2_a.log 2>&1; tail -n 2 $S/eval/logs/score2_a.log
step "settings grid: hear (resume)"
export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4
OUT=$S/eval ASR_SHARDS=6 MEASURE_JOBS=12 bash /w/job/scripts/styles_eval_run.sh
step "score with the grid"
gsv python /w/job/scripts/styles2_score.py --out $S/eval > $S/eval/logs/score2_b.log 2>&1; tail -n 2 $S/eval/logs/score2_b.log
step STYLES2-RUN2-DONE
