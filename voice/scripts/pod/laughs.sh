#!/usr/bin/env bash
# Generated laughs and small sounds for the owner to judge: four of her references, three takes per line, on GPU 3 (Piper trains meanwhile).
set -uo pipefail
source /w/job/scripts/env.sh
cd $R
O=$J/out/laughs; mkdir -p $O
S2=$(ls SoVITS_weights_v2ProPlus/y71_e12_*.pth); G1=GPT_weights_v2ProPlus/y52-e10.ckpt
one() {
  tag=$1; clip=$2; text=$3; temp=$4
  d=$O/$tag; mkdir -p $d
  CUDA_VISIBLE_DEVICES=3 python $J/scripts/speak.py --half --gpt $G1 --sovits $S2 --out $d \
     --ref $J/data/wavs/$clip.wav --ref-text "$text" --lines $J/data/laugh_lines3.txt --speed 1.0 --temperature $temp --top-k 25 > $d.log 2>&1
  for w in $d/0???.wav; do [ -f "$w" ] || continue; python $J/scripts/younger.py $w ${w%.wav}_b.wav --semitones 1.0 --formant 1.04; done
  echo "done $tag"
}
while IFS=$'\t' read -r style cand clip text; do
  case "$style$cand" in defaultA|defaultC|drunkC|snapB) one "${style}_$cand" "$clip" "$text" 1.15 ;; esac
done < $J/data/aud_refs.tsv
echo LAUGHS-DONE
