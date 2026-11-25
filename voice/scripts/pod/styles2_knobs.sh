#!/usr/bin/env bash
# Rejudging the five-style voice: the inference-settings grid for the styles (nothing of hers in this file).
# Each setting (noise_scale, noise_scale_w, length_scale: sherpa-onnx's VITS model config) speaks every style's lines
# (LINES: "new" = its new lines, "val" = its held-out lines) with the style's sid and each seed in SEEDS, the phone's
# way (phone_test_lang.py), into $OUT/wav/e1749<tag>/seed<S>/sid<N>/. $OUT/knobs.tsv names each tag's setting.
# Usage: bash styles2_knobs.sh [tag ...]   (default: every tag of the grid). Settings: OUT, SEEDS, LINES, JOBS.
# Ends with STYLES2-KNOBS-DONE.
set -uo pipefail
source /w/job/scripts/lang_env.sh
OUT=${OUT:-/w/range_build/styles2/eval}; SEEDS=${SEEDS:-"2101 2202"}; LINES=${LINES:-new}; JOBS=${JOBS:-12}
declare -A K=( [k01]="0.333 0.8 1.0" [k02]="0.5 0.8 1.0" [k03]="0.8 0.8 1.0" [k04]="0.667 0.4 1.0" [k05]="0.667 0.6 1.0"
               [k06]="0.667 1.0 1.0" [k07]="0.667 0.8 0.9" [k08]="0.667 0.8 1.1" [k09]="0.667 0.8 1.2" [k10]="0.5 0.6 1.0"
               [k11]="0.5 0.8 1.1" [k12]="0.5 0.6 1.1" )
tags=${*:-$(printf '%s\n' "${!K[@]}" | sort)}
export CUDA_VISIBLE_DEVICES=
source /w/piper-env/bin/activate; cd /w/piper1-gpl
[ -s $OUT/knobs.tsv ] || printf 'tag\tnoise_scale\tnoise_scale_w\tlength_scale\n' > $OUT/knobs.tsv
for sid in 1 2 3 4; do   # the style's lines of the chosen kind (group <style>_new or <style>_val)
  awk -F'\t' -v want="_$LINES\$" 'NR == 1 {for (i = 1; i <= NF; i++) if ($i == "group") g = i; print; next} $g ~ want' \
    $OUT/lines/sid$sid.tsv > $OUT/lines/${LINES}_sid$sid.tsv
done
echo "=== $(date -u +%T) settings grid on the $LINES lines, seeds $SEEDS: $(echo $tags)"
for t in $tags; do
  set -- ${K[$t]}
  grep -q "^$t	" $OUT/knobs.tsv || printf '%s\t%s\t%s\t%s\n' $t $1 $2 $3 >> $OUT/knobs.tsv
  for s in $SEEDS; do
    for sid in 1 2 3 4; do
      D=$OUT/wav/e1749$t/seed$s/sid$sid
      [ -s $D/phone_test.tsv ] && grep -q PHONE-TEST-DONE $D.log 2>/dev/null && continue
      while [ "$(jobs -rp | wc -l)" -ge "$JOBS" ]; do sleep 1; done
      mkdir -p $D
      python /w/job/scripts/phone_test_lang.py $OUT/voices/e1749/seed$s $OUT/lines/${LINES}_sid$sid.tsv $D --sid $sid --threads 2 \
        --noise-scale $1 --noise-scale-w $2 --length-scale $3 > $D.log 2>&1 || echo "SPEAK-FAILED $t seed$s sid$sid" &
    done
  done
done
wait
echo "=== $(date -u +%T) STYLES2-KNOBS-DONE: $(find $OUT/wav/e1749k* -name '[0-9]*.wav' | wc -l) clips"
