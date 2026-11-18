#!/usr/bin/env bash
# Pod setup: GPT-SoVITS (her big voice) + Piper (her phone voice) + the checking tools.
# Runs once, in the background; log in /w/logs/setup.log. Ends with SETUP-DONE.
set -euxo pipefail
mkdir -p /w /workspace/piper-out /workspace/job_out
# Outputs live on the pod's saved volume, so a stopped pod keeps them.
mkdir -p /w/job && ln -sfn /workspace/job_out /w/job/out
export DEBIAN_FRONTEND=noninteractive
J=/w/job
mkdir -p /w/logs

apt-get update -q
apt-get install -y -q build-essential cmake ninja-build ffmpeg git unzip wget bzip2 libsndfile1 pkg-config
python3 -m pip install -q uv || pip install -q uv
export UV_CACHE_DIR=/w/uvcache UV_LINK_MODE=copy

# FLAC -> WAV for her clips (lossless both ways).
mkdir -p $J/data/wavs
for f in $J/data/flac/*.flac; do ffmpeg -y -loglevel error -i "$f" "$J/data/wavs/$(basename "${f%.flac}").wav"; done

# --- GPT-SoVITS v2ProPlus (same commit as the CPU run) ---
cd /w
[ -d GPT-SoVITS ] || git clone -q https://github.com/RVC-Boss/GPT-SoVITS.git
cd GPT-SoVITS && git checkout -q 6d51ffc
uv venv -q -p 3.11 /w/gsv-env
GP=/w/gsv-env/bin/python
uv pip install -q --python $GP torch==2.7.1 torchaudio==2.7.1 --index-url https://download.pytorch.org/whl/cu128
uv pip install -q --python $GP -r requirements.txt numpy==1.26.4 transformers==4.57.6 gradio==4.44.1 \
    torch==2.7.1 torchaudio==2.7.1 resampy pyworld soundfile sherpa-onnx
P=GPT_SoVITS/pretrained_models
HF=https://huggingface.co/lj1995/GPT-SoVITS/resolve/main
for f in s1v3.ckpt v2Pro/s2Gv2ProPlus.pth v2Pro/s2Dv2ProPlus.pth sv/pretrained_eres2netv2w24s4ep4.ckpt \
         chinese-hubert-base/config.json chinese-hubert-base/preprocessor_config.json chinese-hubert-base/pytorch_model.bin \
         chinese-roberta-wwm-ext-large/config.json chinese-roberta-wwm-ext-large/pytorch_model.bin chinese-roberta-wwm-ext-large/tokenizer.json; do
  mkdir -p "$P/$(dirname $f)"; [ -s "$P/$f" ] || wget -q --tries=10 -O "$P/$f" "$HF/$f"
done
mkdir -p $P/fast_langdetect
wget -q --tries=10 -O nltk_data.zip https://huggingface.co/XXXXRT/GPT-SoVITS-Pretrained/resolve/main/nltk_data.zip
unzip -q -o nltk_data.zip -d /w/gsv-env/ && rm nltk_data.zip

# --- Japanese speech recognition, for checking every generated clip ---
cd /w
wget -q --tries=10 https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-zipformer-ja-reazonspeech-2024-08-01.tar.bz2
tar xjf sherpa-onnx-zipformer-ja-reazonspeech-2024-08-01.tar.bz2 && rm sherpa-onnx-zipformer-ja-reazonspeech-2024-08-01.tar.bz2

# --- Piper 1.8 (piper1-gpl, same commit as the local check) ---
[ -d piper1-gpl ] || git clone -q https://github.com/OHF-voice/piper1-gpl.git
cd piper1-gpl && git checkout -q 46c3c71
uv venv -q -p 3.11 /w/piper-env
PP=/w/piper-env/bin/python
uv pip install -q --python $PP torch==2.7.1 torchaudio==2.7.1 --index-url https://download.pytorch.org/whl/cu128
uv pip install -q --python $PP 'scikit-build<1' 'cmake>=3.18,<4' cython
uv pip install -q --python $PP -e '.[train]' torch==2.7.1 pyopenjtalk==0.4.1 sherpa-onnx onnx onnxruntime soundfile 'scikit-build<1' 'cmake>=3.18,<4'
( source /w/piper-env/bin/activate && ./build_monotonic_align.sh && python setup.py build_ext --inplace )
$PP -c "import piper.train.vits.monotonic_align, piper.phonemize_japanese as j; print(j.JapanesePhonemizer().phonemize('今日はいい天気だね'))" || echo PIPER-CHECK-FAILED
mkdir -p /w/piper-base && cd /w/piper-base
PB="https://huggingface.co/datasets/rhasspy/piper-checkpoints/resolve/main/en/en_US/hifi_tts_92/medium"
# A literal '=' in the file name: the CDN refuses the percent-encoded form.
[ -s base.ckpt ] || curl -sS -L --retry 5 -o base.ckpt "$PB/epoch=3642-val_mel=0.3319.ckpt"
echo "1cf854279c5cd05edab8f749e9f17247adab05c73348edd74f75ab85f2b72c28  base.ckpt" | sha256sum -c
curl -sS -L --retry 5 -o config.json "$PB/config.json"
# Piper 1.8 on several GPUs, and without the MOS predictor.
$PP /w/job/scripts/ddp_patch.py
$PP /w/job/scripts/mos_patch.py

nvidia-smi --query-gpu=name,memory.total --format=csv
echo SETUP-DONE
