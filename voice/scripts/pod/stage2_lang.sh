#!/usr/bin/env bash
# Stage 2 for her English: fine-tune her phone voice (Piper) from e800 on Japanese replay plus her
# checked English and mixed lines, read by the mixed phonemizer (mixed_patch.py), resuming e800's run.
#   DRY=1      one short epoch (20 batches) in a throwaway folder: the new CSV, the phonemes and the
#              resume load; it also fills the cache the real run reuses, and checks the cached ids.
#   otherwise  the run, to EPOCHS (default 1100: e800 + 300), a kept checkpoint every KEEP_EVERY epochs.
# Settings from the environment: CK (e800 last.ckpt), EPOCHS, GPUS, PRECISION (bf16-mixed, as e800),
# RESUME_LR (3e-5; "none" keeps e800's end-of-anneal 1e-5), RESUME_LR_FINAL, KEEP_EVERY, VAL_EVERY.
set -euo pipefail
source /w/job/scripts/lang_env.sh
D=$J/out/ds_mix; W=/workspace/piper-lang; CACHE=/w/piper-cache-lang
source /w/piper-env/bin/activate
cd /w/piper1-gpl
CK=${CK:-$(ls -t /workspace/piper-out/lightning_logs/version_*/checkpoints/last.ckpt | head -1)}
python - "$CK" <<'PY'
import sys, torch
ck = torch.load(sys.argv[1], map_location="cpu", weights_only=False, mmap=True)
print("resuming from", sys.argv[1], "epoch", ck["epoch"], "lr", [o["param_groups"][0]["lr"] for o in ck["optimizer_states"]])
assert ck["epoch"] >= 799, "not the e800 checkpoint"
PY
EPOCHS=${EPOCHS:-1100}; GPUS=${GPUS:-4}; PRECISION=${PRECISION:-bf16-mixed}
export PIPER_MIXED_DIR=$J/scripts PIPER_CMUDICT=$CMUDICT PIPER_VAL_IDS=$D/val_ids.txt
export PIPER_KEEP_EVERY=${KEEP_EVERY:-25} PIPER_KEEP_DIR=${KEEP_DIR:-/w/piper-lang-keep}
RESUME_LR=${RESUME_LR:-3e-5}
if [ "$RESUME_LR" != none ]; then export PIPER_RESUME_LR=$RESUME_LR PIPER_RESUME_LR_FINAL=${RESUME_LR_FINAL:-0.33}; fi
ROOT=$W; EXTRA=""
if [ "${DRY:-0}" = 1 ]; then
  ROOT=/w/piper-lang-dry; EPOCHS=801; VAL_EVERY=1; EXTRA="--trainer.limit_train_batches 20 --trainer.limit_val_batches 2"
  export PIPER_KEEP_EVERY=0
  rm -rf $ROOT
fi
mkdir -p $ROOT $W $CACHE $PIPER_KEEP_DIR
echo "=== $(date -u +%H:%M:%S) piper fit to epoch $EPOCHS on $GPUS GPUs ($PRECISION), lr restart ${PIPER_RESUME_LR:-none}, root $ROOT"
python -m piper.train fit \
  --data.voice_name yume --data.csv_path $D/metadata.csv --data.audio_dir $D/wavs \
  --model.sample_rate 22050 --data.espeak_voice ja --data.phoneme_type japanese \
  --data.cache_dir $CACHE --data.config_path $W/ja_JP-yume-medium.onnx.json \
  --data.batch_size 16 --data.num_workers 6 --model.mos_metric none \
  --trainer.max_epochs $EPOCHS --trainer.devices $GPUS --trainer.strategy ddp_find_unused_parameters_true \
  --trainer.precision $PRECISION --trainer.check_val_every_n_epoch ${VAL_EVERY:-25} \
  --trainer.default_root_dir $ROOT --ckpt_path $CK $EXTRA
if [ "${DRY:-0}" = 1 ]; then
  # The ids Piper cached are the ones the mixed phonemizer gives (and so the phone will).
  python $J/scripts/check_ids.py $D/metadata.csv $CACHE $W/ja_JP-yume-medium.onnx.json
  echo "=== $(date -u +%H:%M:%S) DRY-DONE"
else
  echo "=== $(date -u +%H:%M:%S) STAGE2-LANG-DONE"
fi
