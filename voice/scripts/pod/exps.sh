#!/usr/bin/env bash
# Three experiments in parallel: is it the half-precision training or the reel's transcripts?
source /w/job/scripts/env.sh
O=$J/out; mkdir -p $O/exp
{ cat $O/eval_lines.txt; awk 'NR<=420 && NR%21==1' $J/data/sentences_base.txt; } > $O/eval40.txt
grep '/yume_0' $J/data/yume.list > $O/y52.list
cd $J/scripts && python clean_list.py $J/data/yume.list $O/yclean.list 0.25
EXP=y52 GPU=0 LIST=$O/y52.list S2_EPOCHS=8 S1_EPOCHS=15 BATCH=2 EVAL_S2=8 EVAL_GPT="10 15" bash $J/scripts/exp.sh > $O/exp_y52.log 2>&1 &
EXP=y71 GPU=1 LIST=$J/data/yume.list S2_EPOCHS=12 S1_EPOCHS=15 BATCH=8 EVAL_S2=12 EVAL_GPT="10 15" bash $J/scripts/exp.sh > $O/exp_y71.log 2>&1 &
EXP=yclean GPU=2 LIST=$O/yclean.list S2_EPOCHS=12 S1_EPOCHS=15 BATCH=8 EVAL_S2=12 EVAL_GPT="10 15" bash $J/scripts/exp.sh > $O/exp_yclean.log 2>&1 &
wait
echo EXPS-DONE
