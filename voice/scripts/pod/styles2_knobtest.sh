#!/usr/bin/env bash
# Check of the inference-setting options of phone_test_lang.py (nothing of hers here): the same seeded voice and
# lines spoken with no setting, with sherpa's defaults given explicitly (must be sample-identical), and with each
# setting changed (must differ). Usage: bash styles2_knobtest.sh <voice seed dir> <lines.tsv> <out> <sid>
set -uo pipefail
source /w/job/scripts/lang_env.sh; source /w/piper-env/bin/activate; cd /w/piper1-gpl
V=$1; L=$2; O=$3; SID=$4; P=/w/job/scripts/phone_test_lang.py; export CUDA_VISIBLE_DEVICES=
python - "$L" "$O/lines3.tsv" <<'PY'
import sys
rows = open(sys.argv[1], encoding="utf-8").read().splitlines()
open(sys.argv[2], "w", encoding="utf-8").write("\n".join(rows[:4]) + "\n")
PY
python $P $V $O/lines3.tsv $O/none --sid $SID --float > /dev/null 2>&1
python $P $V $O/lines3.tsv $O/defaults --sid $SID --float --noise-scale 0.667 --noise-scale-w 0.8 --length-scale 1.0 > /dev/null 2>&1
python $P $V $O/lines3.tsv $O/ns --sid $SID --float --noise-scale 0.333 > /dev/null 2>&1
python $P $V $O/lines3.tsv $O/nsw --sid $SID --float --noise-scale-w 0.4 > /dev/null 2>&1
python $P $V $O/lines3.tsv $O/ls --sid $SID --float --length-scale 1.2 > /dev/null 2>&1
python - $O <<'PY'
import glob, os, sys
import numpy as np, soundfile as sf
o = sys.argv[1]
base = sorted(glob.glob(f"{o}/none/*.wav"))
for tag in ("defaults", "ns", "nsw", "ls"):
    same = 0; durs = []
    for b in base:
        x, _ = sf.read(b); y, _ = sf.read(f"{o}/{tag}/{os.path.basename(b)}")
        same += int(len(x) == len(y) and np.array_equal(x, y)); durs.append(len(y) / len(x))
    print(f"{tag:9s} identical to no setting: {same}/{len(base)}; length ratio {np.round(durs, 3).tolist()}")
print("KNOBTEST-DONE")
PY
