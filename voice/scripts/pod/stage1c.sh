#!/usr/bin/env bash
# Stage 1, final: her voice from the chosen pair (SoVITS on all 8.1 min, GPT on the 7 clean clips,
# both trained in full precision), the owner's test file, then the practice lines on 4 GPUs, checked.
set -euo pipefail
source /w/job/scripts/env.sh
O=$J/out; cd $R
S2=$(ls SoVITS_weights_v2ProPlus/y71_e12_*.pth); G1=GPT_weights_v2ProPlus/y52-e10.ckpt
echo "$S2 $G1" > $O/chosen.txt
step() { echo "=== $(date -u +%H:%M:%S) $*"; }
step owner-test
rm -rf $O/test && mkdir -p $O/test
CUDA_VISIBLE_DEVICES=0 python $J/scripts/speak.py --gpt $G1 --sovits $S2 --out $O/test/raw --ref $REF --ref-text "$REF_TEXT" \
    --lines $J/data/test_lines.txt $SPEAK_OPTS > $O/test/speak.log 2>&1
for n in 0 1 2 3 4; do python $J/scripts/younger.py $O/test/raw/000$n.wav $O/test/b_$n.wav --semitones 1.0 --formant 1.04; done
python - <<PY
import numpy as np, soundfile as sf
parts=[]; sr=None
for n in range(5):
    x, sr = sf.read(f"$O/test/b_{n}.wav", dtype="float32"); parts += [x, np.zeros(int(sr*0.6), dtype=np.float32)]
sf.write("$O/her_voice_8min_model.wav", np.concatenate(parts), sr, subtype="PCM_16")
PY
step distill
rm -rf $O/distill_raw; mkdir -p $O/distill_raw
for i in 0 1 2 3 4 5 6 7; do
  CUDA_VISIBLE_DEVICES=$(( i % 4 )) python $J/scripts/speak.py --gpt $G1 --sovits $S2 --out $O/distill_raw \
      --ref $REF --ref-text "$REF_TEXT" --lines $O/sentences.txt --shard $i/8 $SPEAK_OPTS > $O/distill_$i.log 2>&1 &
done
wait
ls $O/distill_raw/*.wav | wc -l
step check
rm -rf $O/ds
python $J/scripts/check_distill.py $O/distill_raw $O/sentences.txt $O/ds --jobs $(( $(nproc) - 4 ))
step STAGE1-DONE
