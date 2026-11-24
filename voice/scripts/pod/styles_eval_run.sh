#!/usr/bin/env bash
# Scoring the five-style run, step 3: list every clip, then hear (faster-whisper, ASR_SHARDS processes on the GPU),
# measure (CPU pool) and embed (WavLM, GPU) them side by side; then the English word error. Every step resumes, so a
# rerun after more voices were spoken only does the new clips. Then styles_eval_score.py (the gates).
# Settings: OUT, ASR_SHARDS (4), MEASURE_JOBS (16). The pod's CPU quota is 27 CPUs (cgroup cpu.max), not the 256
# nproc shows: 4 hearing processes, 16 measure workers and a 2-thread embedder fit; 64 workers starved them all.
# Ends with EVAL-RUN-DONE.
set -uo pipefail
source /w/job/scripts/lang_env.sh
OUT=${OUT:-/w/range_build/styles/eval}; ASR_SHARDS=${ASR_SHARDS:-4}; MEASURE_JOBS=${MEASURE_JOBS:-16}
PY=/w/job/scripts/styles_eval.py
step() { echo "=== $(date -u +%H:%M:%S) $*"; }
cd $OUT && mkdir -p logs
step items; python3 $PY items --out $OUT
step "hear, measure, embed"
pids=""
for i in $(seq 0 $((ASR_SHARDS - 1))); do
  asr $PY asr --out $OUT --shard $i/$ASR_SHARDS > logs/asr_$i.log 2>&1 & pids="$pids $!"
done
(export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 CUDA_VISIBLE_DEVICES=; gsv python $PY measure --out $OUT --jobs $MEASURE_JOBS) > logs/measure.log 2>&1 & pids="$pids $!"
(export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2; gsv python $PY embed --out $OUT) > logs/embed.log 2>&1 & pids="$pids $!"
fail=0
for p in $pids; do wait $p || fail=1; done
[ $fail = 0 ] || echo "a step failed: see logs/asr_*.log, logs/measure.log, logs/embed.log"
grep -h -- "-DONE" logs/asr_*.log logs/measure.log logs/embed.log
step wer; asr $PY wer --out $OUT > logs/wer.log 2>&1; tail -2 logs/wer.log
step score; gsv python /w/job/scripts/styles_eval_score.py --out $OUT > logs/score.log 2>&1; tail -3 logs/score.log
step EVAL-RUN-DONE
