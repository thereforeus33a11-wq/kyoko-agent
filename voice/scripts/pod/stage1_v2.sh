#!/usr/bin/env bash
# Stage 1, voice v2 (2026-11-20): one consistent her, clean, for both languages.
# Why: the first bilingual set rotated four reference clips line by line (each line a slightly different
# her), was made in half precision, and every clip went through the WORLD vocoder to brighten it (a
# grainy buzz); the owner chose the version with full precision and no brightening, and heard breaths
# and room noise that the teacher copies from its reference. So here:
#   - one reference clip (REF2, chosen by timbre match: v12_071), as recorded (the owner preferred it to a
#     DeepFilterNet-cleaned copy; CLEAN_REF=1 cleans it);
#   - full precision, no brightening, for her English and mixed lines (two takes) AND her Japanese replay
#     lines (one take of the original practice sentences), so both languages are the same voice;
#   - every take trimmed (trim_words.py: from just before the first word to where her voice has really
#     faded, so word endings stay) and, if DFN_ATTEN is set, lightly cleaned (dfn_clean.py --atten);
#   - the same checks as before (Japanese: check_distill.py; English/mixed: check_lang.py), no brightening.
# Then make_ds_mix.py builds $V/ds_mix for stage2_lang.sh (DS_MIX=$V/ds_mix).
# Log: /w/logs/stage1_v2.log; ends with STAGE1-V2-DONE. Needs setup.sh, setup_lang.sh, setup_clean.sh.
set -euo pipefail
source /w/job/scripts/lang_env.sh
V=${V:-$J/out/v2}; NG=${NG:-$(nvidia-smi -L | wc -l)}
REF2=${REF2:-$J/data/wavs/v12_071.wav}; CLEAN_REF=${CLEAN_REF:-0}; DFN_ATTEN=${DFN_ATTEN:-}
OPTS="--speed 1.0 --temperature 1.0 --top-k 20"     # full precision: no --half
step() { echo "=== $(date -u +%H:%M:%S) $*"; }
mkdir -p $V
ref_text=$(grep -F "/$(basename $REF2)|" $J/data/yume.list | head -1 | cut -d'|' -f4)
[ -n "$ref_text" ] || { echo "no text for $REF2 in yume.list" >&2; exit 1; }
REF_USE=$REF2
if [ "$CLEAN_REF" = 1 ]; then
  REF_USE=$V/ref_clean.wav
  [ -s $REF_USE ] || /w/dfn-env/bin/python $J/scripts/dfn_clean.py $REF2 $REF_USE
fi
printf '%s\t%s\n' "$REF_USE" "$ref_text" > $V/ref.tsv
echo "reference: $REF_USE ($ref_text)"

speak() {  # speak <lines file> <out dir> <seed>
  local lines=$1 out=$2 seed=$3 i
  mkdir -p $out
  for i in $(seq 0 7); do
    CUDA_VISIBLE_DEVICES=$(( i % NG )) gsv python $J/scripts/speak.py --gpt $G_HER --sovits $S2 --out $out \
      --refs $V/ref.tsv --seed $seed --lines $lines --shard $i/8 $OPTS > $out.speak_$i.log 2>&1 &
  done
  wait
  echo "$(ls $out/*.wav 2>/dev/null | wc -l) takes in $out"
}
clean_dir() {  # clean_dir <raw dir> <clean dir>: trim, then (if DFN_ATTEN) a light DeepFilterNet pass
  local src=$1 dst=$2 i
  for i in $(seq 0 $((NG - 1))); do
    CUDA_VISIBLE_DEVICES=$i asr $J/scripts/trim_words.py $WHISPER $src $src.trim --shard $i/$NG > $src.trim_$i.log 2>&1 &
  done
  wait
  if [ -z "$DFN_ATTEN" ]; then
    rm -rf $dst; cp -r $src.trim $dst
  else
    for i in $(seq 0 $((NG - 1))); do
      CUDA_VISIBLE_DEVICES=$i /w/dfn-env/bin/python $J/scripts/dfn_clean.py --atten $DFN_ATTEN --dir $src.trim $dst \
        --shard $i/$NG > $dst.dfn_$i.log 2>&1 &
    done
    wait
  fi
  echo "$(ls $dst/*.wav 2>/dev/null | wc -l) clean takes in $dst"
}

if [ "${SKIP_SPEAK:-0}" != 1 ]; then
  step "English and mixed, take A"; speak $LANG_IN/speak_lang.txt $V/en_raw/A 1234
  step "English and mixed, take B"; speak $LANG_IN/speak_lang.txt $V/en_raw/B 9876
  step "Japanese replay lines";     speak $J/out/sentences.txt $V/ja_raw 1234
fi
step "trim and clean"
clean_dir $V/en_raw/A $V/en_clean/A
clean_dir $V/en_raw/B $V/en_clean/B
clean_dir $V/ja_raw $V/ja_clean
step "Japanese checks"
rm -rf $V/ds_ja
gsv python $J/scripts/check_distill.py $V/ja_clean $J/out/sentences.txt $V/ds_ja --no-brighten --jobs $(( $(nproc) - 4 )) | tail -3
step "English and mixed checks"
W=$V/work; rm -rf $W $V/ds_lang; mkdir -p $W
for i in $(seq 0 $((NG - 1))); do
  CUDA_VISIBLE_DEVICES=$i asr $J/scripts/check_lang.py asr --lines $LANG_IN/lines_lang.tsv --raw $V/en_clean --work $W \
    --shard $i/$NG --model $WHISPER > $W/asr_$i.log 2>&1 &
done
wait
gsv python $J/scripts/check_lang.py prep --lines $LANG_IN/lines_lang.tsv --raw $V/en_clean --work $W --no-brighten \
  --jobs $(( $(nproc) - 4 )) > $W/prep.log 2>&1
CUDA_VISIBLE_DEVICES=0 gsv python $J/scripts/check_lang.py sim --work $W --refs $V/ref.tsv --ja-wavs $V/ds_ja/wavs \
  --model $WAVLM --no-brighten > $W/sim.log 2>&1 || echo "timbre check failed (see $W/sim.log)"
gsv python $J/scripts/check_lang.py pick --lines $LANG_IN/lines_lang.tsv --work $W --out $V/ds_lang --ja-wavs $V/ds_ja/wavs | tail -45
step "mix"
cd /w/piper1-gpl
/w/piper-env/bin/python $J/scripts/make_ds_mix.py --ja-ds $V/ds_ja --lang-ds $V/ds_lang \
  --lines $LANG_IN/lines_lang.tsv --out $V/ds_mix
cat $V/ds_mix/summary.txt
step STAGE1-V2-DONE
