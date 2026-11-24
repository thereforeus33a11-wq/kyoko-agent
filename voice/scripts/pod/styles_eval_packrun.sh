#!/usr/bin/env bash
# The owner's pack for the chosen voice: the same lines (LINES: n of the scoring set's lines/meta.tsv) in each of the
# five styles and in e974, spoken the phone's way (seed SEED), heard and measured exactly as the scoring set
# (styles_eval.py, styles_eval_score.py), then styles_eval_pack.py writes the wavs and README into $P/out.
# Usage: bash styles_eval_packrun.sh <voice, e.g. e1449>    Settings: E (the scoring folder), P, LINES, SEED, TITLE.
# Ends with PACKRUN-DONE.
set -euo pipefail
source /w/job/scripts/lang_env.sh
V=$1; E=${E:-/w/range_build/styles/eval}; P=${P:-/w/range_build/styles/eval_pack}
LINES=${LINES:-"61 66 72 79 39 45"}; SEED=${SEED:-1234}
PY=/w/job/scripts/styles_eval.py
step() { echo "=== $(date -u +%H:%M:%S) $*"; }
rm -rf $P; mkdir -p $P/lines $P/voices $P/logs
python3 - "$E/lines/meta.tsv" "$P/lines" $LINES <<'PY'
import csv, sys
src, dst, keep = sys.argv[1], sys.argv[2], [int(n) for n in sys.argv[3:]]
rows = {int(r["n"]): r for r in csv.DictReader(open(src, encoding="utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE)}
cols = list(next(iter(rows.values())).keys())
sel = [rows[n] for n in keep]
for name in ["meta"] + [f"sid{k}" for k in range(5)]:
    with open(f"{dst}/{name}.tsv", "w", encoding="utf-8") as o:
        o.write("\t".join(cols) + "\n")
        for r in sel:
            o.write("\t".join(r[c] for c in cols) + "\n")
print(len(sel), "lines:", [r["kind"] for r in sel])
PY
ln -s $E/voices/$V $P/voices/$V; ln -s $E/voices/e974 $P/voices/e974
step speak
OUT=$P SEEDS0=$SEED SEED_STYLE=$SEED BASE_SEEDS=$SEED bash /w/job/scripts/styles_eval_speak.sh e974 $V
# sid 0 .. 4 of the chosen voice: the speak script speaks sid 0 with SEEDS0 and sids 1-4 with SEED_STYLE on the
# sid files, which hold the same lines here
awk -F'\t' 'NR == 1 || $3 == "set"' $E/sets.tsv > $P/sets.tsv   # the classifier's training clips (not the real held-out clips)
python3 $PY items --out $P
step "hear, measure, embed"
asr $PY asr --out $P --shard 0/1 > $P/logs/asr.log 2>&1
asr $PY wer --out $P > $P/logs/wer.log 2>&1
(export OMP_NUM_THREADS=1 CUDA_VISIBLE_DEVICES=; gsv python $PY measure --out $P --jobs 12) > $P/logs/measure.log 2>&1
(export OMP_NUM_THREADS=2; gsv python $PY embed --out $P) > $P/logs/embed.log 2>&1
grep -h -- "-DONE" $P/logs/*.log
step score
gsv python /w/job/scripts/styles_eval_score.py --out $P --seeds0 "$SEED $SEED" > $P/logs/score.log 2>&1 || { tail -20 $P/logs/score.log; exit 1; }
gsv python /w/job/scripts/styles_eval_pack.py --pack $P --voice $V --base e974 --seed $SEED --dest $P/out \
  --title "${TITLE:-Her five styles as one phone voice ($V, sids 0 normal, 1 soft, 2 whisper, 3 loud, 4 yell): owner pack, $(date -u +%F)}"
for f in $P/out/*; do sha256sum $f | cut -d' ' -f1 > $f.sha256; done
ls -la $P/out
step PACKRUN-DONE
