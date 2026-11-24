#!/usr/bin/env bash
# The words control (styles_eval_ctrl.py): every style's held-out lines spoken with sid 0 by the given voices (e974
# and candidates), heard and measured as the scoring set, judged by each line's own style rule.
# Usage: bash styles_eval_ctrlrun.sh <voice> [<voice> ...]     Settings: E (scoring folder), C. Ends with CTRLRUN-DONE.
set -euo pipefail
source /w/job/scripts/lang_env.sh
E=${E:-/w/range_build/styles/eval}; C=${C:-/w/range_build/styles/eval_ctrl}
PY=/w/job/scripts/styles_eval.py
step() { echo "=== $(date -u +%H:%M:%S) $*"; }
rm -rf $C; mkdir -p $C/lines $C/voices $C/logs
cp $E/lines/meta.tsv $C/lines/meta.tsv
awk -F'\t' 'NR == 1 || $2 != "0"' $E/lines/meta.tsv > $C/lines/sid0.tsv      # the style lines, to be spoken with sid 0
for k in 1 2 3 4; do head -1 $E/lines/meta.tsv > $C/lines/sid$k.tsv; done
for v in "$@"; do ln -s $E/voices/$v $C/voices/$v; done
step "speak: $*"
OUT=$C SEEDS0=1234 SEED_STYLE=1234 BASE_SEEDS=1234 bash /w/job/scripts/styles_eval_speak.sh "$@"
python3 $PY items --out $C
step hear
asr $PY asr --out $C --shard 0/2 > $C/logs/asr0.log 2>&1 & p0=$!
asr $PY asr --out $C --shard 1/2 > $C/logs/asr1.log 2>&1 & p1=$!
(export OMP_NUM_THREADS=1 CUDA_VISIBLE_DEVICES=; gsv python $PY measure --out $C --jobs 12) > $C/logs/measure.log 2>&1
wait $p0 $p1
asr $PY wer --out $C > $C/logs/wer.log 2>&1
grep -h -- "-DONE" $C/logs/*.log
step judge
gsv python /w/job/scripts/styles_eval_ctrl.py --out $C --main $E
step CTRLRUN-DONE
