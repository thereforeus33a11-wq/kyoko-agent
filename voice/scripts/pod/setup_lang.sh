#!/usr/bin/env bash
# Pod setup for her English, after setup.sh: the English recogniser (faster-whisper large-v3, its own
# env), the timbre model (WavLM speaker verification), and the Piper patch for her mixed lines.
# Models go to the saved volume (/workspace/models), so a stopped pod keeps them.
# Log in /w/logs/setup_lang.log. Ends with SETUP-LANG-DONE.
set -euxo pipefail
J=/w/job; M=/workspace/models
mkdir -p $M /w/logs
export UV_CACHE_DIR=/w/uvcache UV_LINK_MODE=copy

# English recogniser. CTranslate2 needs cuBLAS 12 and cuDNN 9; the pip wheels bring them (asr_env.sh
# puts them on LD_LIBRARY_PATH).
[ -x /w/asr-env/bin/python ] || uv venv -q -p 3.11 /w/asr-env
uv pip install -q --python /w/asr-env/bin/python faster-whisper==1.1.1 'nvidia-cublas-cu12' 'nvidia-cudnn-cu12==9.*' \
    soundfile huggingface_hub
uv pip install -q --python /w/asr-env/bin/python whisper-normalizer || echo "whisper-normalizer missing: check_lang.py falls back to its own normalizer"
[ -s $M/faster-whisper-large-v3/model.bin ] || /w/asr-env/bin/python -c \
  "from huggingface_hub import snapshot_download; snapshot_download('Systran/faster-whisper-large-v3', local_dir='$M/faster-whisper-large-v3')"
# Timbre: WavLM base plus, speaker verification head (transformers is already in gsv-env).
[ -s $M/wavlm-base-plus-sv/config.json ] || /w/gsv-env/bin/python -c \
  "from huggingface_hub import snapshot_download; snapshot_download('microsoft/wavlm-base-plus-sv', local_dir='$M/wavlm-base-plus-sv')"
/w/gsv-env/bin/python -c "import librosa, pyworld, sherpa_onnx, pyopenjtalk; print('gsv-env ok', pyopenjtalk.__version__)"

# Piper: her mixed phonemizer at the phonemize step, a fixed validation list, kept checkpoints,
# and a learning-rate restart for the resumed run (all off unless their variables are set).
/w/piper-env/bin/python $J/scripts/mixed_patch.py

# Parity: on her Japanese the mixed phonemizer must give exactly Piper's own phonemes.
cd /w/piper1-gpl
CMUDICT=$J/data/cmudict.dict /w/piper-env/bin/python - <<'PY'
import sys
sys.path.insert(0, "/w/job/scripts")
from piper.phonemize_japanese import JapanesePhonemizer
from mix_phonemize import MixedPhonemizer
ja = JapanesePhonemizer()
mp = MixedPhonemizer(ja=ja)
lines = [l.split("|", 1)[-1].strip() for l in open("/w/job/data/her_test.txt", encoding="utf-8") if l.strip()]
bad = [t for t in lines if mp.phonemize(t) != ja.phonemize(t)]
print(f"pure Japanese parity: {len(lines) - len(bad)}/{len(lines)}", "MISMATCH " + str(bad) if bad else "OK")
assert not bad
print(mp.phonemize("maji? that's crazy ne"))
PY
cd /w/piper1-gpl && CMUDICT=$J/data/cmudict.dict /w/piper-env/bin/python -I -m unittest discover -s $J/scripts/tests 2>&1 | grep -v "^WARNING" | tail -3
nvidia-smi --query-gpu=name,memory.used --format=csv
echo SETUP-LANG-DONE
