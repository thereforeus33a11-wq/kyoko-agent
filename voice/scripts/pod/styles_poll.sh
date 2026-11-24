#!/usr/bin/env bash
# One look at the five-style run (fits in one short exec): refreshes the loss numbers (tb_epochs.py) and PROGRESS.md
# (styles_progress.py), then prints one status line: training pid alive, last epoch report, last copy, free disk,
# non-finite counts, the end markers. No data in it but numbers.
# Usage: styles_poll.sh <training pid> [<train log>] ; settings: S, ROOT, EPOCHS, START, KEEP_DIR, KEEP_VOL
set -uo pipefail
PID=${1:?training pid}; LOG=${2:-/w/logs/styles_train.log}
S=${S:-/w/range_build/styles}; ROOT=${ROOT:-/w/piper-styles}; EPOCHS=${EPOCHS:-1750}; START=${START:-975}
KEEP_DIR=${KEEP_DIR:-/w/piper-styles-keep}; KEEP_VOL=${KEEP_VOL:-/workspace/yume/piper-styles-keep}
PY=/w/piper-env/bin/python; J=/w/job/scripts
mkdir -p /w/logs && touch /w/logs/styles_train.alive
alive=dead; kill -0 "$PID" 2> /dev/null && alive=alive
vers=$(ls -d $ROOT/lightning_logs/version_* 2> /dev/null | sort -V)
logs=""; for l in $S/logs/train_logs.txt; do [ -s "$l" ] && logs=$(cat "$l"); done; [ -n "$logs" ] || logs=$LOG
cl=""; for l in $logs; do cl="$cl --log $l"; done
cps=""; for c in $(ls $ROOT/keep_copy*.log $ROOT/keep_rotate*.log 2> /dev/null); do cps="$cps --copylog $c"; done
CL=$ROOT/keep_copy.log; [ -s $ROOT/keep_rotate.log ] && CL=$ROOT/keep_rotate.log
[ -n "$vers" ] && timeout 15 $PY $J/tb_epochs.py $vers --start $START --block 25 --json $S/train_tb.json --tsv $S/train_tb.tsv > /dev/null 2>&1
state="training pid $PID $alive"
grep -q "STAGE2-STYLES-DONE" $LOG 2> /dev/null && state="$state; STAGE2-STYLES-DONE"
grep -q "piper fit FAILED" $LOG 2> /dev/null && state="$state; piper fit FAILED"
timeout 8 $PY $J/styles_progress.py --out $S/PROGRESS.md --notes $S/progress_notes.md $cl $cps --keep-dir $KEEP_DIR \
  --vol-dir $KEEP_VOL --tb-json $S/train_tb.json --epochs $EPOCHS --start $START --state "$state" > /dev/null 2>&1 \
  || echo "progress write failed"
last=$(tr '\r' '\n' < $LOG | grep -o "\[styles_patch\] epoch [0-9]*; [0-9]* batches, epoch wall [0-9.]* s, [0-9.]* it/s" | tail -1)
nf=$($PY -c "import json;d=json.load(open('$S/train_tb.json'));print({k:v for k,v in d['nonfinite'].items() if v} or 'none')" 2> /dev/null)
err=$(tr '\r' '\n' < $LOG | grep -ciE "traceback|error|nan detected|out of memory|killed")
echo "$(date -u +%T) $state | $last | nonfinite $nf | errlines $err | copy: $(grep -vE "^cp:|watching" $CL 2> /dev/null | tail -1 | cut -c1-110) | / free $(df -BG --output=avail / | tail -1 | tr -d ' ') | gpu $(nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader 2> /dev/null)"
