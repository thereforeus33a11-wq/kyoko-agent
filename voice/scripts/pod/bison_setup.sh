#!/usr/bin/env bash
# Her voice tools on the bison pod (1x RTX PRO 6000 Blackwell 96 GB, sm_120; image runpod/pytorch cu13.2,
# Ubuntu 24.04), rebuilt on a fresh container so every pod script runs unchanged: the old pods' layout, and
# the envs exactly as setup.sh, setup_clean.sh, setup_lang.sh and the range trial's setup_irodori.sh make them
# (same commits, same pins). The image's own torch is not used.
#
# Layout. /workspace is MooseFS: big files are fine there, many small files are not (a 33k-file untar plus five
# uv installs writing their cache there hung the mount for every process on the pod). So:
#  - container disk /w (wiped on a stop): the envs, the repos, the uv cache (/w/uvcache, hard-linked into every
#    env, so torch is stored once), uv's interpreters (/w/uvpython), the kana recogniser, logs, scratch;
#  - volume, one file per many-file tree, in /workspace/yume/cache:
#      uvcache.tar    /w/uvcache + /w/uvpython   (restored when /w/uvcache is missing; envs then rebuild offline)
#      repos.tar      /w/GPT-SoVITS /w/piper1-gpl /w/irodori at their commits, built and patched
#      dfn_model.tar  ~/.cache/DeepFilterNet (the DeepFilterNet 3 model)
#  - volume, big model files in /workspace/yume/models (linked to their old paths): GPT-SoVITS pretrained,
#    faster-whisper-large-v3, Irodori (hf_range), Piper base, and single archives (the kana recogniser's
#    tar.bz2, Open JTalk's dictionary tar.gz, nltk_data.zip) unpacked onto /w;
#  - her data: /w/yume (unpacked from xfer.tar by the transfer), with /workspace/yume/{teacher,range_proto,...}
#    linking into it; this script adds the old pods' paths on top (/workspace/teacher, /w/job/out, ...).
# Idempotent: a finished step leaves a stamp in /w/stamps. The script copies itself to /w and runs from there.
#
# Inputs on the volume (uploaded from the workstation):
#   /workspace/yume/setup/pod_scripts.tgz          voice/scripts/pod (generic scripts, no voice data)
#   /workspace/yume/setup/cmudict.dict             the CMU dictionary en_ipa_table.json pins by sha256
#   /workspace/yume/range_build/range_scripts.tgz  the range trial's private scripts (never in git)
#   /workspace/yume/source/yume_voice_clips.zip    her clips, used once /workspace/yume/XFER_OK exists
# Run: setsid nohup bash /workspace/yume/setup/bison_setup.sh > /workspace/yume/logs/bison_setup.log 2>&1 < /dev/null &
#  Envs build two at a time (logs /w/logs/bison_setup_<env>.log, copied to /workspace/yume/logs at the end).
#  CACHE_SAVE=0 skips writing the cache tars.
# Ends with BISON-SETUP-DONE, or BISON-SETUP-DONE DATA-PENDING while her transfer has not finished (run it again
# after /workspace/yume/XFER_OK: the envs are skipped, her clips and links are added).
set -euo pipefail
if [ "${BISON_LOCAL:-0}" != 1 ]; then
  mkdir -p /w && cp "$0" /w/bison_setup.run.sh && BISON_LOCAL=1 exec bash /w/bison_setup.run.sh "$@"
fi
Y=/workspace/yume; M=$Y/models; ST=$Y/setup; CACHE=$Y/cache; LOGS=$Y/logs
J=/w/job; STAMP=/w/stamps; ELOG=/w/logs
UVTAR=$CACHE/uvcache.tar; REPOTAR=$CACHE/repos.tar; DFNTAR=$CACHE/dfn_model.tar
GSV_COMMIT=6d51ffc; PIPER_COMMIT=46c3c71; IRODORI_COMMIT=f01c08cd40c0afa62a862439a5de12f6dcf62054
TORCH="torch==2.7.1 torchaudio==2.7.1"; CU128=https://download.pytorch.org/whl/cu128
CMUDICT_SHA=81917843c7f44ce2b094ac63873c2c7a4cf802040792c455ba3ca406891c3d22
PIPER_BASE_SHA=1cf854279c5cd05edab8f749e9f17247adab05c73348edd74f75ab85f2b72c28
SHERPA=sherpa-onnx-zipformer-ja-reazonspeech-2024-08-01
JTALK=open_jtalk_dic_utf_8-1.11
# uv on the container disk: cache, interpreters, hard links into the envs. The image points UV_CACHE_DIR,
# PIP_CACHE_DIR, VIRTUALENV_OVERRIDE_APP_DATA and HF_HOME into /workspace: overridden here.
export DEBIAN_FRONTEND=noninteractive UV_CACHE_DIR=/w/uvcache UV_LINK_MODE=hardlink UV_PYTHON_CACHE_DIR=/w/uvcache/python-dl \
  UV_PYTHON_INSTALL_DIR=/w/uvpython UV_LOCK_TIMEOUT=3600 \
  PIP_CACHE_DIR=/w/pipcache VIRTUALENV_OVERRIDE_APP_DATA=/w/virtualenv-appdata \
  HF_HOME=/w/hf HF_XET_CACHE=/w/hf/xet HF_HUB_ENABLE_HF_TRANSFER=0 HF_HUB_DISABLE_TELEMETRY=1
# Source builds (pyopenjtalk 0.4.1, ...) with setuptools-scm below 10: 10.x lists every folder from the build dir
# up to / and stats each entry, so it stats /workspace, and a build hung with the mount. Only the build tool is
# pinned (UV_BUILD_CONSTRAINT applies to build environments), not any package in the envs.
mkdir -p /w && echo "setuptools-scm<10" > /w/build-constraints.txt
export UV_BUILD_CONSTRAINT=/w/build-constraints.txt
XFER=0; [ -f $Y/XFER_OK ] && XFER=1
RESTORED=0

step() { echo "=== $(date -u +%H:%M:%S) $*"; }
done_() { [ -f $STAMP/$1 ]; }
mark() { mkdir -p $STAMP; date -u +%FT%TZ > $STAMP/$1; }
fetch() {  # fetch <url> <dst>: download one big file once onto the volume (whole file or nothing)
  [ -s "$2" ] && return 0
  mkdir -p "$(dirname "$2")"
  local part="$2.part.$BASHPID"   # two build lanes may fetch the same file at once
  curl -fsSL --retry 8 --retry-delay 5 -o "$part" "$1" && mv -f "$part" "$2"
}
link() {  # link <target> <path>: path -> target; never over a real folder or file
  if [ -L "$2" ] || [ ! -e "$2" ]; then ln -sfn "$1" "$2"; else echo "kept the real $2 (not linked to $1)"; fi
}
U() {  # uv, offline first when the cache came from the volume's tar (falls back to the network, and says so)
  if [ $RESTORED = 1 ]; then
    UV_OFFLINE=1 uv "$@" && return 0
    echo "uv offline failed (uv $*): trying online"
  fi
  uv "$@"
}
jtalk_dict() {  # Open JTalk's dictionary for python $1, unpacked from the volume's tar.gz (fetched once)
  local py=$1 d
  d=$($py -c "import importlib.util, os; print(os.path.dirname(importlib.util.find_spec('pyopenjtalk').origin))")
  fetch https://github.com/r9y9/open_jtalk/releases/download/v1.11.1/$JTALK.tar.gz $M/$JTALK.tar.gz
  [ -s "$d/$JTALK/sys.dic" ] || tar xzf $M/$JTALK.tar.gz -C "$d"
  $py -c "import pyopenjtalk; pyopenjtalk.g2p('テスト'); print('pyopenjtalk ok', pyopenjtalk.__version__)"
}
gpu_check() {  # gpu_check <python>: torch sees the Blackwell card and runs a kernel on it
  $1 -c "import torch; x = torch.randn(2048, 2048, device='cuda'); y = (x @ x).float().sum().item(); \
print('torch', torch.__version__, 'cuda', torch.version.cuda, torch.cuda.get_device_name(0), 'sm_%d%d' % torch.cuda.get_device_capability(0), \
'archs', ','.join(torch.cuda.get_arch_list()), 'matmul ok' if y == y else 'matmul NaN')"
}

step "bison setup: transfer done=$XFER"
mkdir -p $ELOG /w/range/logs $J/scripts $J/data /w/range/scripts $LOGS $M $CACHE /w/hf

# --- system packages (setup.sh's list, plus curl and zstd), only what the image lacks ---
step apt
need=""
for p in build-essential cmake ninja-build ffmpeg git unzip wget bzip2 libsndfile1 pkg-config curl zstd; do
  dpkg -s $p >/dev/null 2>&1 || need="$need $p"
done
if [ -n "$need" ]; then apt-get update -q && apt-get install -y -q $need; fi
command -v uv >/dev/null || python3 -m pip install -q --break-system-packages uv
uv --version

# --- the many-file trees back from their tars (a fresh container) ---
step restore
if [ -L /w/uvcache ]; then rm /w/uvcache; fi   # a first version linked it to the volume
if [ ! -d /w/uvcache ] && [ -s $UVTAR ]; then
  tar xf $UVTAR -C /w && RESTORED=1 && mark uvcache-restored
  echo "uv cache restored from $UVTAR: $(du -sh /w/uvcache | cut -f1)"
elif done_ uvcache-restored; then
  RESTORED=1
fi
mkdir -p /w/uvcache
if [ ! -d /w/GPT-SoVITS/.git ] && [ ! -d /w/piper1-gpl/.git ] && [ ! -d /w/irodori/.git ] && [ -s $REPOTAR ]; then
  tar xf $REPOTAR -C /w && echo "repos restored from $REPOTAR"
fi
if [ ! -d /root/.cache/DeepFilterNet ] && [ -s $DFNTAR ]; then
  mkdir -p /root/.cache && tar xf $DFNTAR -C /root/.cache && echo "DeepFilterNet model restored from $DFNTAR"
fi
echo "uv cache: $(du -sh /w/uvcache | cut -f1), restored=$RESTORED"
U python install -q 3.11

# --- the old pods' layout ---
step layout
tar xzf $ST/pod_scripts.tgz -C $J/scripts
if [ -s $Y/range_build/range_scripts.tgz ]; then tar xzf $Y/range_build/range_scripts.tgz -C /w/range/scripts; else echo "no range scripts on the volume yet"; fi
link /w/uvcache /workspace/uvcache_range    # setup_irodori.sh's cache: the same local cache as /w/uvcache
link $M /workspace/models                   # lang_env.sh (WHISPER, WAVLM), measure.py, the Irodori HF_HOME
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

build_gsv() {  # setup.sh: GPT-SoVITS 6d51ffc and gsv-env; setup_lang.sh's gsv-env check; the kana recogniser
  cd /w
  [ -d GPT-SoVITS/.git ] || git clone -q https://github.com/RVC-Boss/GPT-SoVITS.git
  cd GPT-SoVITS && git checkout -q $GSV_COMMIT
  local GP=/w/gsv-env/bin/python
  if ! done_ gsv-env.v1; then
    [ -x $GP ] || U venv -q -p 3.11 /w/gsv-env
    U pip install -q --python $GP $TORCH --index-url $CU128
    U pip install -q --python $GP -r requirements.txt numpy==1.26.4 transformers==4.57.6 gradio==4.44.1 \
        $TORCH resampy pyworld soundfile sherpa-onnx
    # Beyond setup.sh, what later scripts use in gsv-env (the old pods got these by hand or on demand):
    # faster-whisper for speak_checked.py (stage1_v2.sh installs it on demand), parselmouth for measure.py.
    U pip install -q --python $GP faster-whisper==1.1.1 requests praat-parselmouth
    mark gsv-env.v1
  fi
  # Pretrained models: big files on the volume, linked into the tree.
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
  jtalk_dict $GP
  $GP -c "import librosa, pyworld, sherpa_onnx, pyopenjtalk, faster_whisper, transformers, parselmouth; print('gsv-env ok', transformers.__version__)"
  gpu_check $GP
  # The Japanese recogniser (setup.sh): its archive on the volume, unpacked on /w; asr_kana.py looks for it at
  # its workstation path, so that path links here too.
  fetch https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/$SHERPA.tar.bz2 $M/$SHERPA.tar.bz2
  [ -s /w/$SHERPA/tokens.txt ] || tar xjf $M/$SHERPA.tar.bz2 -C /w
  mkdir -p /tmp/claude-0/voice; link /w/$SHERPA /tmp/claude-0/voice/$SHERPA
  echo BUILD-GSV-OK
}

build_piper() {  # setup.sh: piper1-gpl 46c3c71, piper-env, its patches, the base voice
  cd /w
  [ -d piper1-gpl/.git ] || git clone -q https://github.com/OHF-voice/piper1-gpl.git
  cd piper1-gpl && git checkout -q $PIPER_COMMIT
  local PP=/w/piper-env/bin/python
  if ! done_ piper-env.v1; then
    [ -x $PP ] || U venv -q -p 3.11 /w/piper-env
    U pip install -q --python $PP $TORCH --index-url $CU128
    U pip install -q --python $PP 'scikit-build<1' 'cmake>=3.18,<4' cython
    U pip install -q --python $PP -e '.[train]' torch==2.7.1 pyopenjtalk==0.4.1 sherpa-onnx onnx onnxruntime soundfile \
        'scikit-build<1' 'cmake>=3.18,<4'
    # README: the phone runs plain pyopenjtalk 0.4.1, so the voice trains on its labels, not pyopenjtalk-plus's.
    if $PP -c "import importlib.metadata as m; m.version('pyopenjtalk-plus')" 2>/dev/null; then
      U pip uninstall -q --python $PP pyopenjtalk-plus
      U pip install -q --python $PP --reinstall pyopenjtalk==0.4.1
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

build_dfn() {  # setup_clean.sh: DeepFilterNet in its own env; its model in ~/.cache (kept as dfn_model.tar)
  if ! done_ dfn-env.v1; then
    [ -x /w/dfn-env/bin/python ] || U venv -q -p 3.11 /w/dfn-env
    U pip install -q --python /w/dfn-env/bin/python $TORCH --index-url $CU128
    U pip install -q --python /w/dfn-env/bin/python deepfilternet soundfile numpy
    mark dfn-env.v1
  fi
  if [ -L /root/.cache/DeepFilterNet ]; then rm /root/.cache/DeepFilterNet; fi   # a first version linked it to the volume
  /w/dfn-env/bin/python -c "from df.enhance import init_df; init_df(); print('dfn ok')"
  gpu_check /w/dfn-env/bin/python
  echo BUILD-DFN-OK
}

build_asr() {  # setup_lang.sh: faster-whisper large-v3 in its own env, the model on the volume
  local AP=/w/asr-env/bin/python
  if ! done_ asr-env.v1; then
    [ -x $AP ] || U venv -q -p 3.11 /w/asr-env
    U pip install -q --python $AP faster-whisper==1.1.1 requests 'nvidia-cublas-cu12' 'nvidia-cudnn-cu12==9.*' \
        soundfile huggingface_hub
    U pip install -q --python $AP whisper-normalizer || echo "whisper-normalizer missing: check_lang.py falls back to its own normalizer"
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
    UV_PROJECT_ENVIRONMENT=/w/irodori-env U sync --extra cu128 --frozen
    mark irodori-env.v1
  fi
  # The range scripts read the models from HF_HOME=/workspace/models/hf_range (big files: blobs and their links).
  HF_HOME=$M/hf_range /w/irodori-env/bin/python -c "from huggingface_hub import snapshot_download as s; print(s('Aratako/Irodori-TTS-v4.1-Small')); print(s('Aratako/Semantic-DACVAE-Japanese-32dim'))"
  gpu_check /w/irodori-env/bin/python
  echo BUILD-IRODORI-OK
}

run_build() {  # run_build <env>: one build, its own log, a status file
  local b=$1
  if ( set -euxo pipefail; build_$b ) > $ELOG/bison_setup_$b.log 2>&1; then
    echo ok > $ELOG/build_$b.status; step "build $b ok"
  else
    echo failed > $ELOG/build_$b.status; step "BUILD $b FAILED:"; tail -25 $ELOG/bison_setup_$b.log
  fi
}
step "builds, two at a time (logs $ELOG/bison_setup_<env>.log)"
rm -f $ELOG/build_*.status
( run_build gsv; run_build dfn; run_build asr ) &
LANE1=$!
( run_build piper; run_build irodori ) &
LANE2=$!
wait $LANE1; wait $LANE2
fail=0
for b in gsv piper dfn asr irodori; do
  [ "$(cat $ELOG/build_$b.status 2>/dev/null)" = ok ] || fail=1
done
cp $ELOG/bison_setup_*.log $LOGS/ 2>/dev/null || true
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
CMUDICT=$J/data/cmudict.dict /w/piper-env/bin/python -I -m unittest discover -s $J/scripts/tests > $ELOG/bison_unittest.log 2>&1 \
  || { grep -v "^WARNING" $ELOG/bison_unittest.log | tail -20; step "UNIT TESTS FAILED"; exit 1; }
grep -v "^WARNING" $ELOG/bison_unittest.log | tail -3

# --- the many-file trees onto the volume, one tar each (all envs passed) ---
if [ "${CACHE_SAVE:-1}" = 1 ]; then
  # the uv cache when it is new or this run added unpacked wheels or interpreters to it
  if [ ! -s $UVTAR ] || [ -n "$(find /w/uvcache/archive-v0 /w/uvcache/python-dl -mindepth 1 -maxdepth 1 \
         -newer $UVTAR -print -quit 2>/dev/null)" ]; then
    step "uv cache -> $UVTAR"
    tar cf $UVTAR.part -C /w --exclude='uvcache/.tmp*' --exclude='uvcache/builds-v0' uvcache uvpython
    mv -f $UVTAR.part $UVTAR && mark uvcache-restored
  fi
  if [ ! -s $REPOTAR ]; then
    step "repos -> $REPOTAR"
    tar cf $REPOTAR.part -C /w GPT-SoVITS piper1-gpl irodori && mv -f $REPOTAR.part $REPOTAR
  fi
  if [ ! -s $DFNTAR ] && [ -d /root/.cache/DeepFilterNet ]; then
    step "DeepFilterNet model -> $DFNTAR"
    tar cf $DFNTAR.part -C /root/.cache DeepFilterNet && mv -f $DFNTAR.part $DFNTAR
  fi
  ls -la $CACHE
fi

step "where things are"
cat <<EOF
  envs (container disk)   /w/gsv-env /w/piper-env /w/dfn-env /w/asr-env /w/irodori-env  (python 3.11 in /w/uvpython)
  repos (container disk)  /w/GPT-SoVITS @$GSV_COMMIT  /w/piper1-gpl @$PIPER_COMMIT  /w/irodori @${IRODORI_COMMIT:0:8}
  uv cache                /w/uvcache (hard-linked into the envs); saved as $UVTAR
  repos, DeepFilterNet    saved as $REPOTAR, $DFNTAR (model in /root/.cache/DeepFilterNet)
  scripts                 /w/job/scripts (repo pod scripts), /w/range/scripts (range scripts)
  her clips               /w/job/data/{wavs,flac,yume.list}; cmudict.dict, lang/, her_test.txt beside them
  outputs                 /w/job/out -> $Y/job_out$( [ -e $Y/job_out ] && echo " -> $(readlink -f $Y/job_out)")
  teacher, range trial    /workspace/teacher -> $Y/teacher, /workspace/range_proto -> $Y/range_proto (into /w/yume)
  models (volume)         /workspace/models -> $M: gsv_pretrained (linked into GPT-SoVITS), faster-whisper-large-v3,
                          hf_range (Irodori), piper-base (/w/piper-base), wavlm-base-plus-sv, archives:
                          $SHERPA.tar.bz2 (-> /w/$SHERPA), $JTALK.tar.gz, nltk_data.zip
  kana recogniser         /w/$SHERPA, also at /tmp/claude-0/voice/$SHERPA for asr_kana.py
  logs                    $LOGS/bison_setup.log, /w/logs/bison_setup_<env>.log (copied to $LOGS)
EOF
du -sh /w/uvcache /w/uvpython 2>/dev/null
df -h / /workspace | tail -2
nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv
if [ $XFER = 1 ]; then step BISON-SETUP-DONE; else step "BISON-SETUP-DONE DATA-PENDING (run again after $Y/XFER_OK)"; fi
