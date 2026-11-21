#!/usr/bin/env bash
# Her voice tools on the bison pod (1x RTX PRO 6000 Blackwell 96 GB, sm_120; image runpod/pytorch cu13.2,
# Ubuntu 24.04), rebuilt on a fresh container so every pod script runs unchanged: the old pods' layout, and
# the envs exactly as setup.sh, setup_clean.sh, setup_lang.sh and the range trial's setup_irodori.sh make them
# (same commits, same pins). The image's own torch is not used.
#
# Idempotent. A finished step leaves a stamp in /w/stamps (the container disk), and every download (the uv
# cache, the models) lives on the saved volume under /workspace/yume, so after a stop the next container
# reinstalls from the cache and re-links; nothing is fetched twice.
#
# Inputs on the volume (uploaded from the workstation):
#   /workspace/yume/setup/pod_scripts.tgz          voice/scripts/pod (generic scripts, no voice data)
#   /workspace/yume/setup/cmudict.dict             the CMU dictionary en_ipa_table.json pins by sha256
#   /workspace/yume/range_build/range_scripts.tgz  the range trial's private scripts (never in git)
#   /workspace/yume/source/yume_voice_clips.zip    her clips, used only once /workspace/yume/XFER_OK exists
# Run: setsid nohup bash /workspace/yume/setup/bison_setup.sh > /workspace/yume/logs/bison_setup.log 2>&1 < /dev/null &
# Each env builds in parallel with its own log (/workspace/yume/logs/bison_setup_<env>.log).
# Ends with BISON-SETUP-DONE, or BISON-SETUP-DONE DATA-PENDING while her transfer has not finished (run it
# again after /workspace/yume/XFER_OK appears: the envs are skipped, her clips and links are added).
set -euo pipefail
Y=/workspace/yume; M=$Y/models; ST=$Y/setup; J=/w/job; STAMP=/w/stamps; LOGS=$Y/logs
GSV_COMMIT=6d51ffc; PIPER_COMMIT=46c3c71; IRODORI_COMMIT=f01c08cd40c0afa62a862439a5de12f6dcf62054
TORCH="torch==2.7.1 torchaudio==2.7.1"; CU128=https://download.pytorch.org/whl/cu128
CMUDICT_SHA=81917843c7f44ce2b094ac63873c2c7a4cf802040792c455ba3ca406891c3d22
PIPER_BASE_SHA=1cf854279c5cd05edab8f749e9f17247adab05c73348edd74f75ab85f2b72c28
SHERPA=sherpa-onnx-zipformer-ja-reazonspeech-2024-08-01
export DEBIAN_FRONTEND=noninteractive UV_CACHE_DIR=$Y/uvcache UV_LINK_MODE=copy UV_PYTHON_CACHE_DIR=$Y/uvcache/python-dl
export HF_HUB_ENABLE_HF_TRANSFER=0 HF_HUB_DISABLE_TELEMETRY=1
XFER=0; [ -f $Y/XFER_OK ] && XFER=1

step() { echo "=== $(date -u +%H:%M:%S) $*"; }
done_() { [ -f $STAMP/$1 ]; }
mark() { mkdir -p $STAMP; date -u +%FT%TZ > $STAMP/$1; }
fetch() {  # fetch <url> <dst>: download once onto the volume (whole file or nothing)
  [ -s "$2" ] && return 0
  mkdir -p "$(dirname "$2")"
  curl -fsSL --retry 8 --retry-delay 5 -o "$2.part" "$1" && mv "$2.part" "$2"
}
link() {  # link <target> <path>: path -> target; never over a real folder or file
  if [ -L "$2" ] || [ ! -e "$2" ]; then ln -sfn "$1" "$2"; else echo "kept the real $2 (not linked to $1)"; fi
}
jtalk_dict() {  # Open JTalk's dictionary for the env of python $1: copied from the volume, else fetched once and kept
  local py=$1 d
  d=$($py -c "import importlib.util, os; print(os.path.join(os.path.dirname(importlib.util.find_spec('pyopenjtalk').origin), 'open_jtalk_dic_utf_8-1.11'))")
  if [ ! -d "$d" ] && [ -s $M/open_jtalk_dic_utf_8-1.11/sys.dic ]; then cp -r $M/open_jtalk_dic_utf_8-1.11 "$d"; fi
  $py -c "import pyopenjtalk; pyopenjtalk.g2p('テスト'); print('pyopenjtalk ok', pyopenjtalk.__version__)"
  if [ -s "$d/sys.dic" ] && [ ! -s $M/open_jtalk_dic_utf_8-1.11/sys.dic ]; then
    local t=$M/open_jtalk_dic_utf_8-1.11.tmp.$BASHPID
    rm -rf $t; cp -r "$d" $t
    mv -T $t $M/open_jtalk_dic_utf_8-1.11 2>/dev/null || rm -rf $t
  fi
}
gpu_check() {  # gpu_check <python>: torch sees the Blackwell card and runs a kernel on it
  $1 -c "import torch; x = torch.randn(2048, 2048, device='cuda'); y = (x @ x).float().sum().item(); \
print('torch', torch.__version__, 'cuda', torch.version.cuda, torch.cuda.get_device_name(0), 'sm_%d%d' % torch.cuda.get_device_capability(0), \
'archs', ','.join(torch.cuda.get_arch_list()), 'matmul ok' if y == y else 'matmul NaN')"
}

step "bison setup: transfer done=$XFER"
mkdir -p /w/logs /w/range/logs $J/scripts $J/data /w/range/scripts $LOGS $M $UV_CACHE_DIR

# --- system packages (setup.sh's list, plus curl), only what the image lacks ---
step apt
need=""
for p in build-essential cmake ninja-build ffmpeg git unzip wget bzip2 libsndfile1 pkg-config curl; do
  dpkg -s $p >/dev/null 2>&1 || need="$need $p"
done
if [ -n "$need" ]; then apt-get update -q && apt-get install -y -q $need; fi
command -v uv >/dev/null || python3 -m pip install -q --break-system-packages uv
uv --version

# --- the old pods' layout ---
step layout
tar xzf $ST/pod_scripts.tgz -C $J/scripts
if [ -s $Y/range_build/range_scripts.tgz ]; then tar xzf $Y/range_build/range_scripts.tgz -C /w/range/scripts; else echo "no range scripts on the volume yet"; fi
link $Y/uvcache /w/uvcache                  # setup.sh, setup_clean.sh, setup_lang.sh, stage1_v2.sh use /w/uvcache
link $Y/uvcache /workspace/uvcache_range    # setup_irodori.sh's cache
link $M /workspace/models                   # lang_env.sh (WHISPER, WAVLM), measure.py, the Irodori HF_HOME
if [ $XFER = 1 ]; then mkdir -p $Y/job_out $Y/piper-out; fi
# Her data at the old paths (only links whose target has arrived: a dangling link would break mkdir -p).
for d in teacher range_proto job_out piper-out piper-lang piper-lang2 piper-lang2-keep phone_lang phone_lang2 phone_final; do
  if [ -e $Y/$d ]; then link $Y/$d /workspace/$d; fi
done
if [ -e $Y/job_out ]; then link $Y/job_out $J/out; fi

# --- /w/job/data: what setup.sh and setup_lang.sh expect ---
step data
mkdir -p $J/data/lang
cp $ST/cmudict.dict $J/data/cmudict.dict
echo "$CMUDICT_SHA  $J/data/cmudict.dict" | sha256sum -c
cp $J/scripts/lang_lines/out/lines_lang.tsv $J/scripts/lang_lines/out/speak_lang.txt $J/data/lang/
cp $J/scripts/her_test.txt $J/scripts/laugh_lines.txt $J/data/
if [ $XFER = 1 ] && ! done_ clips.v1; then
  tmp=$(mktemp -d /w/unz.XXXXXX)
  unzip -q -o $Y/source/yume_voice_clips.zip -d $tmp
  mkdir -p $J/data/wavs $J/data/flac
  cp $tmp/yume_voice_clips/wavs/*.wav $J/data/wavs/
  cp $tmp/yume_voice_clips/yume_pod.list $J/data/yume.list      # the 71-line list, paths /w/job/data/wavs/
  for f in $J/data/wavs/*.wav; do   # flac/ as on the old pods (lossless, the same samples)
    ffmpeg -y -loglevel error -i "$f" "$J/data/flac/$(basename "${f%.wav}").flac"
  done
  rm -rf "$tmp"; mark clips.v1
fi
echo "data: $(ls $J/data | tr '\n' ' ')clips: $(ls $J/data/wavs 2>/dev/null | wc -l)"

# --- uv's CPython 3.11 once, before the parallel builds ---
uv python install -q 3.11

build_gsv() {  # setup.sh: GPT-SoVITS 6d51ffc and gsv-env; setup_lang.sh's gsv-env check; stage1_v2.sh's faster-whisper
  cd /w
  [ -d GPT-SoVITS/.git ] || git clone -q https://github.com/RVC-Boss/GPT-SoVITS.git
  cd GPT-SoVITS && git checkout -q $GSV_COMMIT
  if ! done_ gsv-env.v1; then
    [ -x /w/gsv-env/bin/python ] || uv venv -q -p 3.11 /w/gsv-env
    local GP=/w/gsv-env/bin/python
    uv pip install -q --python $GP $TORCH --index-url $CU128
    uv pip install -q --python $GP -r requirements.txt numpy==1.26.4 transformers==4.57.6 gradio==4.44.1 \
        $TORCH resampy pyworld soundfile sherpa-onnx
    # speak_checked.py hears in gsv-env (stage1_v2.sh installs this on demand; here up front)
    uv pip install -q --python $GP faster-whisper==1.1.1 requests
    mark gsv-env.v1
  fi
  # Pretrained models: on the volume, linked into the tree.
  local P=GPT_SoVITS/pretrained_models C=$M/gsv_pretrained HF=https://huggingface.co/lj1995/GPT-SoVITS/resolve/main f e
  for f in s1v3.ckpt v2Pro/s2Gv2ProPlus.pth v2Pro/s2Dv2ProPlus.pth sv/pretrained_eres2netv2w24s4ep4.ckpt \
           chinese-hubert-base/config.json chinese-hubert-base/preprocessor_config.json chinese-hubert-base/pytorch_model.bin \
           chinese-roberta-wwm-ext-large/config.json chinese-roberta-wwm-ext-large/pytorch_model.bin chinese-roberta-wwm-ext-large/tokenizer.json; do
    fetch "$HF/$f" "$C/$f"
  done
  mkdir -p $C/fast_langdetect
  for e in s1v3.ckpt v2Pro sv chinese-hubert-base chinese-roberta-wwm-ext-large fast_langdetect; do
    if [ -d "$P/$e" ] && [ ! -L "$P/$e" ]; then cp -rn "$P/$e/." "$C/$e/"; rm -rf "$P/$e"; fi
    ln -sfn "$C/$e" "$P/$e"
  done
  fetch https://huggingface.co/XXXXRT/GPT-SoVITS-Pretrained/resolve/main/nltk_data.zip $M/nltk_data.zip
  [ -d /w/gsv-env/nltk_data ] || unzip -q -o $M/nltk_data.zip -d /w/gsv-env/
  jtalk_dict /w/gsv-env/bin/python
  /w/gsv-env/bin/python -c "import librosa, pyworld, sherpa_onnx, pyopenjtalk, faster_whisper, transformers, parselmouth; print('gsv-env ok', transformers.__version__)"
  gpu_check /w/gsv-env/bin/python
  # The Japanese recogniser (setup.sh), kept on the volume; asr_kana.py looks for it at its workstation path.
  if [ ! -s $M/$SHERPA/tokens.txt ]; then
    fetch https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/$SHERPA.tar.bz2 $M/$SHERPA.tar.bz2
    rm -rf $M/$SHERPA.tmp; mkdir -p $M/$SHERPA.tmp
    tar xjf $M/$SHERPA.tar.bz2 -C $M/$SHERPA.tmp && rm -rf $M/$SHERPA && mv $M/$SHERPA.tmp/$SHERPA $M/$SHERPA
    rm -rf $M/$SHERPA.tmp $M/$SHERPA.tar.bz2
  fi
  link $M/$SHERPA /w/$SHERPA
  mkdir -p /tmp/claude-0/voice; link $M/$SHERPA /tmp/claude-0/voice/$SHERPA
  echo BUILD-GSV-OK
}

build_piper() {  # setup.sh: piper1-gpl 46c3c71, piper-env, its patches, the base voice
  cd /w
  [ -d piper1-gpl/.git ] || git clone -q https://github.com/OHF-voice/piper1-gpl.git
  cd piper1-gpl && git checkout -q $PIPER_COMMIT
  local PP=/w/piper-env/bin/python
  if ! done_ piper-env.v1; then
    [ -x $PP ] || uv venv -q -p 3.11 /w/piper-env
    uv pip install -q --python $PP $TORCH --index-url $CU128
    uv pip install -q --python $PP 'scikit-build<1' 'cmake>=3.18,<4' cython
    uv pip install -q --python $PP -e '.[train]' torch==2.7.1 pyopenjtalk==0.4.1 sherpa-onnx onnx onnxruntime soundfile \
        'scikit-build<1' 'cmake>=3.18,<4'
    # README: the phone runs plain pyopenjtalk 0.4.1, so the voice trains on its labels, not pyopenjtalk-plus's.
    if $PP -c "import importlib.metadata as m; m.version('pyopenjtalk-plus')" 2>/dev/null; then
      uv pip uninstall -q --python $PP pyopenjtalk-plus
      uv pip install -q --python $PP --reinstall pyopenjtalk==0.4.1
    fi
    ( source /w/piper-env/bin/activate && ./build_monotonic_align.sh && python setup.py build_ext --inplace )
    mark piper-env.v1
  fi
  $PP -c "import importlib.metadata as m; print('pyopenjtalk', m.version('pyopenjtalk'))"
  jtalk_dict $PP
  $PP -c "import piper.train.vits.monotonic_align, piper.phonemize_japanese as j; print(j.JapanesePhonemizer().phonemize('今日はいい天気だね'))"
  # The base voice (hifi_tts_92, CC BY 4.0), on the volume. A literal '=' in the name: the CDN refuses '%3D'.
  local PB="https://huggingface.co/datasets/rhasspy/piper-checkpoints/resolve/main/en/en_US/hifi_tts_92/medium"
  mkdir -p $M/piper-base
  if [ ! -s $M/piper-base/base.ckpt.sha256 ]; then
    curl -sS -L --retry 5 -o $M/piper-base/base.ckpt.part "$PB/epoch=3642-val_mel=0.3319.ckpt"
    echo "$PIPER_BASE_SHA  $M/piper-base/base.ckpt.part" | sha256sum -c
    mv $M/piper-base/base.ckpt.part $M/piper-base/base.ckpt && echo "$PIPER_BASE_SHA" > $M/piper-base/base.ckpt.sha256
  fi
  fetch "$PB/config.json" $M/piper-base/config.json
  link $M/piper-base /w/piper-base
  # Piper 1.8 on several GPUs, without the MOS predictor, and her mixed phonemizer (setup_lang.sh). All idempotent.
  $PP $J/scripts/ddp_patch.py
  $PP $J/scripts/mos_patch.py
  $PP $J/scripts/mixed_patch.py
  gpu_check $PP
  echo BUILD-PIPER-OK
}

build_dfn() {  # setup_clean.sh: DeepFilterNet in its own env; its model on the volume
  if ! done_ dfn-env.v1; then
    [ -x /w/dfn-env/bin/python ] || uv venv -q -p 3.11 /w/dfn-env
    uv pip install -q --python /w/dfn-env/bin/python $TORCH --index-url $CU128
    uv pip install -q --python /w/dfn-env/bin/python deepfilternet soundfile numpy
    mark dfn-env.v1
  fi
  mkdir -p $M/DeepFilterNet /root/.cache; link $M/DeepFilterNet /root/.cache/DeepFilterNet
  /w/dfn-env/bin/python -c "from df.enhance import init_df; init_df(); print('dfn ok')"
  gpu_check /w/dfn-env/bin/python
  echo BUILD-DFN-OK
}

build_asr() {  # setup_lang.sh: faster-whisper large-v3 in its own env, the model on the volume
  local AP=/w/asr-env/bin/python
  if ! done_ asr-env.v1; then
    [ -x $AP ] || uv venv -q -p 3.11 /w/asr-env
    uv pip install -q --python $AP faster-whisper==1.1.1 requests 'nvidia-cublas-cu12' 'nvidia-cudnn-cu12==9.*' \
        soundfile huggingface_hub
    uv pip install -q --python $AP whisper-normalizer || echo "whisper-normalizer missing: check_lang.py falls back to its own normalizer"
    mark asr-env.v1
  fi
  [ -s $M/faster-whisper-large-v3/model.bin ] || $AP -c \
    "from huggingface_hub import snapshot_download; snapshot_download('Systran/faster-whisper-large-v3', local_dir='$M/faster-whisper-large-v3')"
  ( export LD_LIBRARY_PATH="$($AP -c 'import os, nvidia.cublas.lib, nvidia.cudnn.lib; print(list(nvidia.cublas.lib.__path__)[0] + ":" + list(nvidia.cudnn.lib.__path__)[0])'):${LD_LIBRARY_PATH:-}"
    $AP -c "import ctranslate2, faster_whisper; print('ctranslate2', ctranslate2.__version__, 'faster-whisper', faster_whisper.__version__, \
'cuda devices', ctranslate2.get_cuda_device_count(), 'compute types', sorted(ctranslate2.get_supported_compute_types('cuda')))" )
  echo BUILD-ASR-OK
}

build_irodori() {  # the range trial's setup_irodori.sh: Irodori-TTS f01c08cd, irodori-env, its two models
  cd /w
  [ -d irodori/.git ] || git clone -q https://github.com/Aratako/Irodori-TTS.git irodori
  cd irodori && git checkout -q $IRODORI_COMMIT
  if ! done_ irodori-env.v1; then
    UV_PROJECT_ENVIRONMENT=/w/irodori-env uv sync --extra cu128 --frozen
    mark irodori-env.v1
  fi
  HF_HOME=$M/hf_range /w/irodori-env/bin/python -c "from huggingface_hub import snapshot_download as s; print(s('Aratako/Irodori-TTS-v4.1-Small')); print(s('Aratako/Semantic-DACVAE-Japanese-32dim'))"
  gpu_check /w/irodori-env/bin/python
  echo BUILD-IRODORI-OK
}

step "builds (parallel; logs $LOGS/bison_setup_<env>.log)"
declare -A PIDS
for b in gsv piper dfn asr irodori; do
  ( set -euxo pipefail; build_$b ) > $LOGS/bison_setup_$b.log 2>&1 &
  PIDS[$b]=$!
done
fail=0
for b in gsv piper dfn asr irodori; do
  if wait ${PIDS[$b]}; then step "build $b ok"; else step "BUILD $b FAILED:"; tail -25 $LOGS/bison_setup_$b.log; fail=1; fi
done
[ $fail = 0 ] || { step BISON-SETUP-FAILED; exit 1; }

# --- setup_lang.sh: the timbre model (from the transfer; fetched only if the transfer lacks it) ---
if [ $XFER = 1 ] && [ ! -s $M/wavlm-base-plus-sv/config.json ]; then
  /w/gsv-env/bin/python -c "from huggingface_hub import snapshot_download; snapshot_download('microsoft/wavlm-base-plus-sv', local_dir='$M/wavlm-base-plus-sv')"
fi

# --- setup_lang.sh: on her Japanese the mixed phonemizer must give exactly Piper's own phonemes; unit tests ---
step "piper parity and unit tests"
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
CMUDICT=$J/data/cmudict.dict /w/piper-env/bin/python -I -m unittest discover -s $J/scripts/tests > /w/logs/bison_unittest.log 2>&1 \
  || { grep -v "^WARNING" /w/logs/bison_unittest.log | tail -20; step "UNIT TESTS FAILED"; exit 1; }
grep -v "^WARNING" /w/logs/bison_unittest.log | tail -3

step summary
du -sh $M/* 2>/dev/null | sort -k2
df -h / /workspace | tail -2
nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv
if [ $XFER = 1 ]; then step BISON-SETUP-DONE; else step "BISON-SETUP-DONE DATA-PENDING (run again after $Y/XFER_OK)"; fi
