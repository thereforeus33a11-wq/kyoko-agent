#!/usr/bin/env bash
# While the style lines are being heard: speak the settings grid (styles2_knobs.sh) and measure and embed its clips
# (styles_eval.py items / measure / embed resume: only new clips), so only its hearing is left. Nothing of hers here.
set -uo pipefail
source /w/job/scripts/lang_env.sh
OUT=${OUT:-/w/range_build/styles2/eval}; PY=/w/job/scripts/styles_eval.py
OUT=$OUT JOBS=10 bash /w/job/scripts/styles2_knobs.sh
python3 $PY items --out $OUT
(export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 CUDA_VISIBLE_DEVICES=; gsv python $PY measure --out $OUT --jobs 12) > $OUT/logs/measure_k.log 2>&1
(export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2; gsv python $PY embed --out $OUT) > $OUT/logs/embed_k.log 2>&1
tail -n 1 $OUT/logs/measure_k.log $OUT/logs/embed_k.log
echo "=== $(date -u +%T) PREK-DONE"
