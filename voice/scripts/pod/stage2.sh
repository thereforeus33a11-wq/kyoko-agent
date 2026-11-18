#!/usr/bin/env bash
# Stage 2: train her phone voice (Piper, Japanese with pitch accent), warm-started from hifi_tts_92 (CC BY 4.0).
# EPOCHS and GPUS from the environment. BENCH=1 runs a short timing run first.
set -euo pipefail
J=/w/job; D=$J/out/ds; W=/workspace/piper-out
source /w/piper-env/bin/activate
cd /w/piper1-gpl
EPOCHS=${EPOCHS:-2000}; GPUS=${GPUS:-4}; ROOT=${ROOT:-$W}
mkdir -p $ROOT /w/piper-cache
echo "=== $(date -u +%H:%M:%S) piper fit epochs=$EPOCHS gpus=$GPUS root=$ROOT"
python -m piper.train fit \
  --data.voice_name yume --data.csv_path $D/metadata.csv --data.audio_dir $D/wavs \
  --model.sample_rate 22050 --data.espeak_voice ja --data.phoneme_type japanese \
  --data.cache_dir /w/piper-cache --data.config_path $W/ja_JP-yume-medium.onnx.json \
  --data.batch_size 16 --data.num_workers 6 --data.validation_split 0.05 \
  --model.warmstart_ckpt /w/piper-base/base.ckpt --model.mos_metric none \
  --trainer.max_epochs $EPOCHS --trainer.devices $GPUS --trainer.strategy ddp_find_unused_parameters_true \
  --trainer.precision bf16-mixed --trainer.check_val_every_n_epoch ${VAL_EVERY:-20} \
  --trainer.default_root_dir $ROOT
echo "=== $(date -u +%H:%M:%S) STAGE2-DONE"
