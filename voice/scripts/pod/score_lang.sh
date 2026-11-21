#!/usr/bin/env bash
# Stage 3 for her English: export the kept checkpoints, speak the held-out lines and her_test.txt the
# phone's way, score them against the teacher and e800, pick one, and make the owner's A/B.
#   EPOCHS_TO_SCORE (default "899 999 1099": e800 + 100, 200, 300; 0-based epoch numbers of the
#   keep-epoch=N.ckpt files), E800_SHERPA (today's phone voice; exported from CK when missing).
#   For another run: PIPER_ROOT, KEEP_DIR, STUDENT_DIR, PHONE_LANG, TEACHER_STATS (voice v2:
#   /workspace/piper-lang2, /workspace/piper-lang2-keep, $J/out/v2/student, /workspace/phone_lang2,
#   $J/out/v2/ds_lang/teacher_stats.json).
# Outputs in $OL/student: one folder per candidate, student_scores.json, choice.txt, ab_lang.wav (each
# held-out line, today's voice then the chosen one) and same_her.wav (20 held-out lines in the chosen
# voice back to back: does she stay one her from line to line); the chosen voice in /workspace/phone_lang
# (sherpa/model.onnx, tokens.txt, config, .sha256 files).
# Ends with SCORE-LANG-DONE.
set -euo pipefail
source /w/job/scripts/lang_env.sh
W=${PIPER_ROOT:-/workspace/piper-lang}; K=${KEEP_DIR:-/w/piper-lang-keep}; S=${STUDENT_DIR:-$OL/student}
PL=${PHONE_LANG:-/workspace/phone_lang}; TEACHER_STATS=${TEACHER_STATS:-$OL/ds_lang/teacher_stats.json}
EPOCHS_TO_SCORE=${EPOCHS_TO_SCORE:-"899 999 1099"}
E800_SHERPA=${E800_SHERPA:-/workspace/phone_final/sherpa}
mkdir -p $S
step() { echo "=== $(date -u +%H:%M:%S) $*"; }

# The test set: the 60 held-out lines (renumbered from 0) and her 25 Japanese test lines after them.
python3 - "$LANG_IN/lines_lang.tsv" "$J/data/her_test.txt" "$S/lines.tsv" <<'PY'
import csv, sys
src, her, out = sys.argv[1:4]
rows = [r for r in csv.DictReader(open(src, encoding="utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE) if r["split"] == "holdout"]
keys = list(rows[0].keys())
ja = [l.split("|", 1)[-1].strip() for l in open(her, encoding="utf-8") if l.strip()]
with open(out, "w", encoding="utf-8") as f:
    f.write("\t".join(keys) + "\n")
    for k, r in enumerate(rows):
        r["n"] = str(k); f.write("\t".join(r[c] for c in keys) + "\n")
    for k, t in enumerate(ja):
        r = dict(n=str(len(rows) + k), kind="ja", category="her_test", split="her_test", rank="-1", text=t,
                 teacher_lang="ja", teacher_text=t)
        f.write("\t".join(r[c] for c in keys) + "\n")
print(len(rows), "held-out lines and", len(ja), "of her Japanese test lines")
PY

export_sherpa() {  # export_sherpa <ckpt> <dir>
  mkdir -p $2
  (source /w/piper-env/bin/activate; cd /w/piper1-gpl
   python -m piper.train.export_onnx --checkpoint "$1" --output-file $2/export.onnx > $2/export.log 2>&1
   python $J/scripts/sherpa_meta.py $2/export.onnx $W/ja_JP-yume-medium.onnx.json $2/sherpa >> $2/export.log 2>&1
   rm -f $2/export.onnx)
}
speak_and_check() {  # speak_and_check <sherpa dir> <work dir> <route>
  mkdir -p $2
  (source /w/piper-env/bin/activate; cd /w/piper1-gpl
   python $J/scripts/phone_test_lang.py $1 $S/lines.tsv $2/raw/S --route $3 --threads 4 > $2/phone_test.log 2>&1)
  CUDA_VISIBLE_DEVICES=0 asr $J/scripts/check_lang.py asr --lines $S/lines.tsv --raw $2/raw --work $2 --shard 0/1 \
    --model $WHISPER > $2/asr.log 2>&1
  gsv python $J/scripts/check_lang.py prep --lines $S/lines.tsv --raw $2/raw --work $2 --no-brighten \
    --jobs 16 > $2/prep.log 2>&1
}

# SCORE_SERIAL=1: one set at a time (and a failing step stops the run). A one-GPU pod (24 GB card, 41 GB
# container) cannot hold a large-v3 recogniser and 16 prep workers per set for six sets at once.
bg() { if [ "${SCORE_SERIAL:-0}" = 1 ]; then "$@"; else "$@" & fi; }

step "e800, today's route"
if [ ! -s $E800_SHERPA/model.onnx ]; then
  CK=${CK:-$(ls -t /workspace/piper-out/lightning_logs/version_*/checkpoints/last.ckpt | head -1)}
  export_sherpa $CK $S/e800; E800_SHERPA=$S/e800/sherpa
fi
bg speak_and_check $E800_SHERPA $S/e800 kana
SETS="e800=$S/e800"
for E in $EPOCHS_TO_SCORE; do
  CK_E=$K/keep-epoch=$E.ckpt
  [ -s $CK_E ] || CK_E=$(ls -t $W/lightning_logs/version_*/checkpoints/last.ckpt | head -1)
  step "epoch $E: $CK_E"
  export_sherpa $CK_E $S/e$E
  bg speak_and_check $S/e$E/sherpa $S/e$E mixed
  SETS="$SETS e$E=$S/e$E"
done
wait
python3 $J/scripts/score_student.py --lines $S/lines.tsv --teacher $TEACHER_STATS --out $S $SETS
C=$(cat $S/choice.txt)
step "chosen: $C"

# The owner's A/B: each held-out English or mixed line, today (A) then the chosen voice (B).
gsv python - "$S" "$C" <<'PY'
import csv, sys, numpy as np, soundfile as sf
s, c = sys.argv[1:3]
rows = [r for r in csv.DictReader(open(f"{s}/lines.tsv", encoding="utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE) if r["split"] == "holdout"]
parts, sr = [], 22050
for r in rows:
    for tag in ("e800", c):
        x, sr = sf.read(f"{s}/{tag}/bright/S/{int(r['n']):04d}.wav", dtype="float32")
        parts += [x, np.zeros(int(sr * (0.5 if tag == "e800" else 1.1)), np.float32)]
sf.write(f"{s}/ab_lang.wav", np.concatenate(parts), sr, subtype="PCM_16")
open(f"{s}/ab_lang.txt", "w", encoding="utf-8").write("\n".join(r["text"] for r in rows) + "\n")
print("A/B:", len(rows), "lines")
# Same her: 20 held-out lines in the chosen voice, back to back, as the pilot that sounded like
# different people every other line was.
same, said = [], []
for r in rows[:20]:
    x, sr = sf.read(f"{s}/{c}/bright/S/{int(r['n']):04d}.wav", dtype="float32")
    same += [x, np.zeros(int(sr * 0.7), np.float32)]; said.append(r["text"])
sf.write(f"{s}/same_her.wav", np.concatenate(same), sr, subtype="PCM_16")
open(f"{s}/same_her.txt", "w", encoding="utf-8").write("\n".join(said) + "\n")
print("same her:", len(said), "lines")
PY

mkdir -p $PL/sherpa
cp $S/$C/sherpa/model.onnx $S/$C/sherpa/tokens.txt $PL/sherpa/
cp $W/ja_JP-yume-medium.onnx.json $PL/
E=${C#e}; CK_C=$K/keep-epoch=$E.ckpt; [ -s $CK_C ] || CK_C=$(ls -t $W/lightning_logs/version_*/checkpoints/last.ckpt | head -1)
cp $CK_C $PL/yume_piper_lang_$C.ckpt
cp $S/ab_lang.wav $S/ab_lang.txt $S/same_her.wav $S/same_her.txt $S/student_scores.json $PL/
# podio.py down reads these for files too big to hash within one exec call.
for f in $PL/sherpa/model.onnx $PL/yume_piper_lang_$C.ckpt $PL/ab_lang.wav $PL/same_her.wav; do sha256sum $f | cut -d' ' -f1 > $f.sha256; done
ls -la $PL $PL/sherpa
step SCORE-LANG-DONE
