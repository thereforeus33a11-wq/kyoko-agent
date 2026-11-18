#!/usr/bin/env bash
# One training experiment on one GPU: format, train in full precision, speak the eval set, score it.
# EXP, GPU, LIST, S2_EPOCHS, S1_EPOCHS, BATCH, EVAL_S2 (epoch), EVAL_GPT (space-separated epochs)
set -uo pipefail
source /w/job/scripts/env.sh
cd $R
O=$J/out/exp/$EXP; mkdir -p $O
echo "=== $(date -u +%H:%M:%S) $EXP format"
HALF=False EXP=$EXP GPU=$GPU LIST=$LIST bash $J/scripts/gsv_format.sh > $O/format.log 2>&1 || { echo "$EXP FORMAT-FAILED"; exit 1; }
echo "=== $(date -u +%H:%M:%S) $EXP train"
FP16=0 EXP=$EXP GPU=$GPU bash $J/scripts/gsv_train.sh > $O/train.log 2>&1 || { echo "$EXP TRAIN-FAILED"; exit 1; }
S2=$(ls SoVITS_weights_v2ProPlus/${EXP}_e${EVAL_S2}_*.pth | head -1)
for g in $EVAL_GPT; do
  CUDA_VISIBLE_DEVICES=$GPU python $J/scripts/speak.py --gpt GPT_weights_v2ProPlus/${EXP}-e$g.ckpt --sovits $S2 \
      --out $O/eval/e${EVAL_S2}_g$g --ref $REF --ref-text "$REF_TEXT" --lines $J/out/eval40.txt $SPEAK_OPTS > $O/speak_g$g.log 2>&1
done
python $J/scripts/pick.py $J/out/eval40.txt $O/eval > $O/score.txt 2>&1
echo "=== $(date -u +%H:%M:%S) $EXP done"; grep -E "CER" $O/score.txt
