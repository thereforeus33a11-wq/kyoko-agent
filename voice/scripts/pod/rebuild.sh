#!/usr/bin/env bash
# One pass from a fresh pod to her phone voice training: setup, the chosen teacher retrained
# (SoVITS on all 71 clips, GPT on the 7 clean clips, full precision), the owner's test file,
# the practice lines, the checks, the mood auditions, then Piper. Outputs live on /workspace.
set -uo pipefail
J=/w/job; O=$J/out
step() { echo "=== $(date -u +%H:%M:%S) $*"; }
mkdir -p /w/logs
step setup;   bash $J/scripts/setup.sh > /w/logs/setup.log 2>&1 || { step SETUP-FAILED; exit 1; }
source $J/scripts/env.sh
grep '/yume_0' $J/data/yume.list > $O/y52.list
{ head -5 $J/data/test_lines.txt; awk 'NR<=420 && NR%21==1' $J/data/sentences_base.txt; } > $O/eval40.txt
cp $J/data/test_lines.txt $O/eval_lines.txt
step teacher
( HALF=False EXP=y71 GPU=0 LIST=$J/data/yume.list bash $J/scripts/gsv_format.sh > $O/fmt_y71.log 2>&1 && \
  FP16=0 EXP=y71 GPU=0 BATCH=8 S2_EPOCHS=12 S1_EPOCHS=15 bash $J/scripts/gsv_train.sh > $O/train_y71.log 2>&1 ) &
( HALF=False EXP=y52 GPU=1 LIST=$O/y52.list bash $J/scripts/gsv_format.sh > $O/fmt_y52.log 2>&1 && \
  FP16=0 EXP=y52 GPU=1 BATCH=2 S2_EPOCHS=8 S1_EPOCHS=15 bash $J/scripts/gsv_train.sh > $O/train_y52.log 2>&1 ) &
wait
ls /w/GPT-SoVITS/SoVITS_weights_v2ProPlus/y71_e12_*.pth /w/GPT-SoVITS/GPT_weights_v2ProPlus/y52-e10.ckpt || { step TEACHER-FAILED; exit 1; }
mkdir -p /workspace/teacher && cp /w/GPT-SoVITS/SoVITS_weights_v2ProPlus/y71_e12_*.pth /w/GPT-SoVITS/GPT_weights_v2ProPlus/y52-e10.ckpt /workspace/teacher/
step sentences
( cd /w && { [ -s jpn_sentences.tsv ] || { wget -q --tries=10 https://downloads.tatoeba.org/exports/per_language/jpn/jpn_sentences.tsv.bz2 && bunzip2 -f jpn_sentences.tsv.bz2; }; } ) && \
  python $J/scripts/more_sentences.py $J/data/sentences_base.txt /w/jpn_sentences.tsv $O/sentences.txt --n 2600 || { step SENTENCES-FAILED; exit 1; }
step auditions; bash $J/scripts/auditions.sh > /w/logs/auditions.log 2>&1
step stage1;    bash $J/scripts/stage1c.sh > /w/logs/stage1c.log 2>&1 || { step STAGE1-FAILED; exit 1; }
step piper;     EPOCHS=800 VAL_EVERY=25 bash $J/scripts/stage2.sh > /w/logs/stage2.log 2>&1
step REBUILD-DONE
