#!/usr/bin/env bash
# Check of sid_scales_onnx.py (nothing of hers here): a seeded five-speaker voice and its copy with per-speaker rows
# (sid 4 = noise_scale 0.5, length_scale x1.1, noise_scale_w 0.6 at sherpa's defaults; every other sid 1, 1, 1).
#   sid 0 and sid 1, copy vs original, both at sherpa's defaults: must be sample-identical;
#   sid 4, copy at sherpa's defaults vs original given those settings in sherpa's config: equal up to float rounding.
# Usage: bash sid_scales_test.sh <seeded voice dir> <lines.tsv> <out>
set -uo pipefail
source /w/job/scripts/lang_env.sh; source /w/piper-env/bin/activate; cd /w/piper1-gpl
V=$1; L=$2; O=$3; P=/w/job/scripts/phone_test_lang.py; export CUDA_VISIBLE_DEVICES=
mkdir -p $O/v
head -n 7 $L > $O/lines.tsv
python /w/job/scripts/sid_scales_onnx.py $V/model.onnx $O/v/model.onnx '{"4": [0.749625187, 1.1, 0.75]}' && cp $V/tokens.txt $O/v/
for sid in 0 1 4; do
  python $P $V $O/lines.tsv $O/orig_s$sid --sid $sid --float > /dev/null 2>&1
  python $P $O/v $O/lines.tsv $O/copy_s$sid --sid $sid --float > /dev/null 2>&1
done
python $P $V $O/lines.tsv $O/orig_s4_knobs --sid 4 --float --noise-scale 0.5 --length-scale 1.1 --noise-scale-w 0.6 > /dev/null 2>&1
python - $O <<'PY'
import glob, os, sys
import numpy as np, soundfile as sf
o = sys.argv[1]
def cmp(a, b):
    same = 0; mx = 0.0; n = 0; lens = 0
    for f in sorted(glob.glob(f"{o}/{a}/*.wav")):
        x, _ = sf.read(f); y, _ = sf.read(f"{o}/{b}/{os.path.basename(f)}"); n += 1
        if len(x) == len(y):
            lens += 1; mx = max(mx, float(np.max(np.abs(x - y)))); same += int(np.array_equal(x, y))
    print(f"{a} vs {b}: {same}/{n} identical, {lens}/{n} same length, max abs diff {mx:.2e}")
cmp("orig_s0", "copy_s0"); cmp("orig_s1", "copy_s1"); cmp("orig_s4_knobs", "copy_s4"); cmp("orig_s4", "copy_s4")
print("SIDSCALE-TEST-DONE")
PY
