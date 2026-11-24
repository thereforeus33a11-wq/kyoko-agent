#!/usr/bin/env bash
# Stage 2 for her five styles: ONE multi-speaker Piper voice whose sids are 0 normal, 1 soft, 2 whisper, 3 loud,
# 4 yell, warm-started exactly from her phone voice (styles_warmstart.py: every weight of keep-epoch=974 copied,
# the new speaker conditioning at zero, sid 0 anchored at none), on ds_mix as "normal" and the four checked style
# sets (styles_ds.py), read by the mixed phonemizer (mixed_patch.py), resuming e974's run and optimizer
# (--ckpt_path), as stage2_lang.sh resumed e800. One GPU.
#   DRY=1      a few hundred steps in a throwaway folder: the CSV, the phonemes, the resume load, all five sids in
#              the batches, memory and speed; it fills the cache the real run reuses, and checks the cached ids.
#   PREPARE_ONLY=1  only the cache (and the style clips' trim widened), then stop.
#   otherwise  the run to EPOCHS, a kept checkpoint every KEEP_EVERY epochs in KEEP_DIR, each copied to KEEP_VOL
#              on the volume as soon as it is written (keep_copy.sh; COPIER=keep_rotate.sh instead keeps only the
#              newest on the volume and a slim of every one beside it on /w, for a volume too small for all).
# Settings from the environment: CK (the warm-start checkpoint), EPOCHS, BATCH (48: e974's run was 16 per GPU
# on 3 GPUs), PRECISION (bf16-mixed, as e974), RESUME_LR (1.5e-5; "none" keeps the checkpoint's rate),
# RESUME_LR_FINAL (0.33), COND_LR_MULT (10),
# ANCHOR0 (1), KEEP_EVERY (25), VAL_EVERY (25), DRY_BATCHES (150 per dry epoch, 2 epochs).
set -euo pipefail
source /w/job/scripts/lang_env.sh
S=/w/range_build/styles
D=${DS:-$S/ds}; W=${PIPER_ROOT:-/w/piper-styles}; CACHE=${PIPER_CACHE:-/w/piper-cache-styles}
CK=${CK:-/w/piper-styles-ws/ws_e974_styles.ckpt}
source /w/piper-env/bin/activate
cd /w/piper1-gpl
python - "$CK" <<'PY'
import sys, torch
ck = torch.load(sys.argv[1], map_location="cpu", weights_only=False, mmap=True)
hp = ck["hyper_parameters"]
print("resuming from", sys.argv[1], "epoch", ck["epoch"], "num_speakers", hp["num_speakers"], "gin", hp["gin_channels"],
      "lr", [[g["lr"] for g in o["param_groups"]] for o in ck["optimizer_states"]])
assert ck["epoch"] >= 974 and hp["num_speakers"] == 5, "not the e974 five-style warm start or one of its kept checkpoints"
PY
EPOCHS=${EPOCHS:?set EPOCHS (see PLAN.md)}; PRECISION=${PRECISION:-bf16-mixed}; BATCH=${BATCH:-48}
export PIPER_MIXED_DIR=$J/scripts PIPER_CMUDICT=$CMUDICT PIPER_VAL_IDS=$D/val_ids.txt
export PIPER_KEEP_EVERY=${KEEP_EVERY:-25} PIPER_KEEP_DIR=${KEEP_DIR:-/w/piper-styles-keep}
KEEP_VOL=${KEEP_VOL:-/workspace/yume/piper-styles-keep}
RESUME_LR=${RESUME_LR:-1.5e-5}
if [ "$RESUME_LR" != none ]; then export PIPER_RESUME_LR=$RESUME_LR PIPER_RESUME_LR_FINAL=${RESUME_LR_FINAL:-0.33}; fi
export PIPER_STYLE_COND_LR_MULT=${COND_LR_MULT:-10} PIPER_STYLE_REPORT=1
[ "${ANCHOR0:-1}" = 1 ] && export PIPER_STYLE_ANCHOR0=1
ROOT=$W; EXTRA=""
if [ "${DRY:-0}" = 1 ]; then
  ROOT=/w/piper-styles-dry; VAL_EVERY=1
  EXTRA="--trainer.limit_train_batches ${DRY_BATCHES:-150} --trainer.limit_val_batches 2"
  export PIPER_KEEP_EVERY=1 PIPER_KEEP_DIR=$ROOT/keep; KEEP_VOL=${KEEP_VOL_DRY:-/workspace/yume/piper-styles-dry}
  rm -rf $ROOT
fi
mkdir -p $ROOT $CACHE $PIPER_KEEP_DIR
# The cache first, as Piper's fit would make it (phonemes, VAD-trimmed audio, spectrograms; a full cache is only
# checked), then the style clips' trim widened so it never cuts into sound (style_trim_fix.py: Silero misses
# whispered words; her normal clips stay exactly as e974 trained on them). Idempotent.
echo "=== $(date -u +%H:%M:%S) cache: $CACHE"
python - "$D" "$CACHE" "$S/ja_JP-yume-medium.onnx.json" <<'PY'
import sys
from piper.train.vits.dataset import VitsDataModule
d, cache, cfg = sys.argv[1:4]
VitsDataModule(csv_path=f"{d}/metadata.csv", audio_dir=f"{d}/wavs", cache_dir=cache, config_path=cfg, voice_name="yume",
               espeak_voice="ja", phoneme_type="japanese", sample_rate=22050, num_speakers=5).prepare_data()
PY
python $J/scripts/style_trim_fix.py $D/metadata.csv $D/wavs $CACHE $S/ja_JP-yume-medium.onnx.json \
  --speakers soft whisper loud yell --out $ROOT/trim_widened.tsv
[ "${PREPARE_ONLY:-0}" = 1 ] && { echo "=== $(date -u +%H:%M:%S) PREPARE-DONE"; exit 0; }
echo "=== $(date -u +%H:%M:%S) piper fit to epoch $EPOCHS on 1 GPU ($PRECISION), batch $BATCH, lr restart ${PIPER_RESUME_LR:-none}" \
     "(conditioning x$PIPER_STYLE_COND_LR_MULT, sid 0 anchored ${PIPER_STYLE_ANCHOR0:-0}), root $ROOT, keep $PIPER_KEEP_DIR -> $KEEP_VOL"
python -m piper.train fit \
  --data.voice_name yume --data.csv_path $D/metadata.csv --data.audio_dir $D/wavs \
  --model.sample_rate 22050 --data.espeak_voice ja --data.phoneme_type japanese \
  --model.num_speakers 5 --model.gin_channels 32 \
  --data.cache_dir $CACHE --data.config_path $S/ja_JP-yume-medium.onnx.json \
  --data.batch_size $BATCH --data.num_workers 8 --model.mos_metric none \
  --trainer.max_epochs $EPOCHS --trainer.devices 1 --trainer.accelerator gpu \
  --trainer.precision $PRECISION --trainer.check_val_every_n_epoch ${VAL_EVERY:-25} \
  --trainer.default_root_dir $ROOT --ckpt_path $CK $EXTRA &
TRAIN=$!
COPIER=${COPIER:-keep_copy.sh}
bash $J/scripts/$COPIER $PIPER_KEEP_DIR $KEEP_VOL $TRAIN > $ROOT/${COPIER%.sh}.log 2>&1 &
COPY=$!
rc=0; wait $TRAIN || rc=$?
wait $COPY || true
cat $ROOT/${COPIER%.sh}.log
[ $rc = 0 ] || { echo "=== $(date -u +%H:%M:%S) piper fit FAILED (exit $rc)"; exit $rc; }
# The ids Piper cached are the ones the mixed phonemizer gives (and so the phone will), for every sid.
python $J/scripts/check_ids.py $D/metadata.csv $CACHE $S/ja_JP-yume-medium.onnx.json
if [ "${DRY:-0}" = 1 ]; then
  echo "=== $(date -u +%H:%M:%S) DRY-DONE"
else
  echo "=== $(date -u +%H:%M:%S) STAGE2-STYLES-DONE"
fi
