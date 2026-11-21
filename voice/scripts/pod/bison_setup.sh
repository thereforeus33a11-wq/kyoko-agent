#!/usr/bin/env bash
# Her voice tools on the one-GPU Blackwell pod (1x RTX PRO 6000 Blackwell 96 GB, sm_120; image runpod/pytorch
# cu13.2, Ubuntu 24.04), so every pod script and the range trial's scripts run unchanged: the old pods' layout, and
# the envs exactly as setup.sh, setup_clean.sh, setup_lang.sh and the range trial's setup_irodori.sh make them (same
# commits, same pins). Two additions in gsv-env: praat-parselmouth==0.4.7 (measure.py) and faster-whisper==1.1.1 +
# requests (what stage1_v2.sh installs there on demand, for speak_checked.py). The image's own torch is not used.
#
# Storage. /workspace is MooseFS: many small files there hung the previous pod (a uv cache on it, five installs
# writing to it at once). So:
#  - container disk (/w and the rest of /, 50 GB, wiped when the pod stops): the envs, the repos, the uv cache
#    /w/uvcache (UV_LINK_MODE=hardlink: every env links its files from it, so torch is stored once), uv's Pythons
#    /w/uvpython, her data /w/yume (xfer_finish2.sh), unpacked archives (kana recogniser, nltk_data), every log;
#  - volume, big single files only:
#      /workspace/yume/cache/uvcache.tar   /w/uvcache + /w/uvpython, written when every env passes; restored at
#                                          the start when /w/uvcache is missing (the envs then link from it again)
#      /workspace/yume/models/             fetched once: gsv_pretrained/ (linked into GPT-SoVITS),
#                                          faster-whisper-large-v3/, hf_range/ (Irodori, HF_HOME), piper-base/,
#                                          and single archives (the kana recogniser's tar.bz2, nltk_data.zip)
#    Every big read or write on the volume holds /w/locks/volume, so only one runs at a time.
#  - the old paths on top: /w/job/{scripts,data,out}, /w/range/scripts, /workspace/{teacher,range_proto,models,...}.
#
# Idempotent and safe to re-run after a pod stop: her data comes back first (xfer_finish2.sh), then the uv cache
# (uvcache.tar), and an env whose stamp (/w/stamps) is there is only checked again, not reinstalled.
#
# Inputs on the volume (uploaded from the workstation):
#   /workspace/yume/setup/pod_scripts.tgz          voice/scripts/pod (generic scripts, no voice data)
#   /workspace/yume/setup/cmudict.dict             the CMU dictionary en_ipa_table.json pins by sha256
#   /workspace/yume/range_build/range_scripts.tgz  the range trial's private scripts (never in git)
#   /workspace/yume/source/yume_voice_clips.zip    her clips (4 wavs) and her lists
#   /workspace/yume/xfer.tar + xfer_finish2.sh     her data pack; XFER_OK holds its sha256
# Run (the script copies itself to /w and runs from there):
#   setsid nohup bash /workspace/yume/setup/bison_setup.sh > /w/logs/bison_setup.log 2>&1 < /dev/null &
# Builds: two lanes (gsv, dfn, asr | irodori, piper), each env's log in /w/logs/bison_setup_<env>.log.
# CACHE_SAVE=0 skips writing uvcache.tar. Ends with BISON-SETUP-DONE, or BISON-SETUP-FAILED.
set -euo pipefail
if [ "${BISON_LOCAL:-0}" != 1 ]; then   # bash reads a script as it runs: run a copy on the container disk
  mkdir -p /w && cp "$0" /w/bison_setup.run.sh && BISON_LOCAL=1 exec bash /w/bison_setup.run.sh "$@"
fi
Y=/workspace/yume; M=$Y/models; ST=$Y/setup; CACHE=$Y/cache
J=/w/job; STAMP=/w/stamps; ELOG=/w/logs; VLOCK=/w/locks/volume
UVTAR=$CACHE/uvcache.tar
GSV_COMMIT=6d51ffc; PIPER_COMMIT=46c3c71; IRODORI_COMMIT=f01c08cd40c0afa62a862439a5de12f6dcf62054
TORCH="torch==2.7.1 torchaudio==2.7.1"; CU128=https://download.pytorch.org/whl/cu128
CMUDICT_SHA=81917843c7f44ce2b094ac63873c2c7a4cf802040792c455ba3ca406891c3d22
PIPER_BASE_SHA=1cf854279c5cd05edab8f749e9f17247adab05c73348edd74f75ab85f2b72c28
SHERPA=sherpa-onnx-zipformer-ja-reazonspeech-2024-08-01
# The image points UV_CACHE_DIR, PIP_CACHE_DIR, VIRTUALENV_OVERRIDE_APP_DATA and HF_HOME into /workspace: all on the
# container disk here. HF_XET_CACHE too (the xet chunk cache is many small files), also when HF_HOME is on the volume.
export DEBIAN_FRONTEND=noninteractive UV_CACHE_DIR=/w/uvcache UV_LINK_MODE=hardlink UV_PYTHON_INSTALL_DIR=/w/uvpython \
  UV_LOCK_TIMEOUT=3600 PIP_CACHE_DIR=/w/pipcache VIRTUALENV_OVERRIDE_APP_DATA=/w/virtualenv-appdata \
  HF_HOME=/w/hf HF_XET_CACHE=/w/hf/xet HF_HUB_ENABLE_HF_TRANSFER=0 HF_XET_HIGH_PERFORMANCE=0 HF_HUB_DISABLE_TELEMETRY=1

step() { echo "=== $(date -u +%H:%M:%S) $*"; }
done_() { [ -f $STAMP/$1 ]; }
mark() { mkdir -p $STAMP; date -u +%FT%TZ > $STAMP/$1; }
vol() { ( flock 9; "$@" ) 9> $VLOCK; }   # one big volume read or write at a time, across both build lanes
fetch() {  # fetch <url> <dst>: one big file onto the volume, once (whole file or nothing); call through vol
  [ -s "$2" ] && return 0
  mkdir -p "$(dirname "$2")"
  curl -fsSL --retry 8 --retry-delay 5 -o "$2.part" "$1" && mv -f "$2.part" "$2"
}
link() {  # link <target> <path>: path -> target; never over a real folder or file
  if [ -L "$2" ] || [ ! -e "$2" ]; then ln -sfn "$1" "$2"; else echo "kept the real $2 (not linked to $1)"; fi
}
gpu_wait() {  # gpu_wait <MiB>: until the GPU has that much free plus 8 GB for the other agents (up to 30 min)
  local f i
  for i in $(seq 1 60); do
    f=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1)
    [ "$f" -ge $(( $1 + 8192 )) ] && return 0
    echo "GPU free $f MiB: waiting"; sleep 30
  done
  echo "GPU never had $1 + 8192 MiB free"; return 1
}
gpu_check() {  # gpu_check <python>: torch sees the Blackwell card and runs a kernel on it
  gpu_wait 2048
  $1 -c "import torch; x = torch.randn(2048, 2048, device='cuda'); y = (x @ x).float().sum().item(); \
print('torch', torch.__version__, 'cuda', torch.version.cuda, torch.cuda.get_device_name(0), 'sm_%d%d' % torch.cuda.get_device_capability(0), \
'archs', ','.join(torch.cuda.get_arch_list()), 'matmul ok' if y == y else 'matmul NaN'); assert y == y"
}
hf_get() {  # hf_get <python> <repo> [local dir]: one repo, one file at a time (call through vol)
  $1 -c "import sys; from huggingface_hub import snapshot_download as s; \
print(s(sys.argv[1], local_dir=(sys.argv[2] or None), max_workers=1))" "$2" "${3:-}"
}

mkdir -p $ELOG /w/locks /w/range/logs /w/range/scripts /w/range_build $J/scripts $J/data /w/hf
step "bison setup on $(hostname): $(nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader)"
df -h / | tail -1

# --- her data: back on the container disk after a stop (xfer_finish2.sh checks the pack and every file) ---
step "her data"
if [ ! -s /w/yume/teacher/y52-e10.ckpt ] || [ ! -d /w/yume/range_proto/refs ]; then
  sha=${XFER_SHA:-$(grep -o 'sha256 [0-9a-f]\{64\}' $Y/XFER_OK 2>/dev/null | head -1 | cut -d' ' -f2)}
  [ -n "$sha" ] || { echo "no /w/yume and no sha256 for xfer.tar (XFER_OK missing; set XFER_SHA)"; step BISON-SETUP-FAILED; exit 1; }
  vol bash $Y/xfer_finish2.sh "$sha" > $ELOG/xfer_finish2.log 2>&1 || true
  tail -3 $ELOG/xfer_finish2.log
  grep -q '^XFER-DONE' $ELOG/xfer_finish2.log || { step BISON-SETUP-FAILED; exit 1; }
fi
echo "her data: $(find /w/yume -type f | wc -l) files in /w/yume ($(du -sh /w/yume | cut -f1))"

# --- system packages (setup.sh's list), only what the image lacks ---
step apt
need=""
for p in build-essential cmake ninja-build ffmpeg git unzip wget bzip2 libsndfile1 pkg-config; do
  dpkg -s $p >/dev/null 2>&1 || need="$need $p"
done
if [ -n "$need" ]; then apt-get update -q > $ELOG/apt.log 2>&1 && apt-get install -y -q $need >> $ELOG/apt.log 2>&1; fi
command -v uv >/dev/null || python3 -m pip install -q uv
uv --version

# --- the uv cache back from the volume (a fresh container) ---
step "uv cache"
for old in /workspace/uvcache_range /w/uvcache; do   # an earlier draft linked these to /workspace/yume/uvcache
  if [ -L $old ] && [ "$(readlink $old)" != /w/uvcache ]; then rm $old; fi
done
if [ ! -d /w/uvcache ] && [ -s $UVTAR ]; then
  t0=$(date +%s)
  vol tar xf $UVTAR -C /w
  echo "restored $UVTAR in $(( $(date +%s) - t0 )) s: $(du -sh /w/uvcache | cut -f1) cache, $(du -sh /w/uvpython 2>/dev/null | cut -f1) Pythons"
fi
mkdir -p /w/uvcache
uv python install -q 3.11
echo "uv cache $(du -sh /w/uvcache | cut -f1); Pythons: $(ls /w/uvpython 2>/dev/null | grep -v '^\.' | tr '\n' ' ')"

# --- the old pods' layout ---
step layout
vol tar xzf $ST/pod_scripts.tgz -C $J/scripts
vol tar xzf $Y/range_build/range_scripts.tgz -C /w/range/scripts
link /w/uvcache /workspace/uvcache_range      # setup_irodori.sh's UV_CACHE_DIR: the local cache, not the volume
link $Y/models /workspace/models              # lang_env.sh (WHISPER, WAVLM), measure.py, Irodori's HF_HOME
for d in teacher range_proto job_out phone_lang2 piper-lang2-keep; do   # her data at the old volume paths
  [ -e $Y/$d ] && link $Y/$d /workspace/$d
done
link /w/yume/job_out $J/out                   # outputs: on the container disk with the rest of her data
mkdir -p /tmp/claude-0/voice                  # asr_kana.py reads the kana recogniser at its workstation path
link /w/$SHERPA /tmp/claude-0/voice/$SHERPA

# --- /w/job/data: what setup.sh, setup_lang.sh and lang_env.sh expect ---
step data
mkdir -p $J/data/lang $J/data/wavs $J/data/flac
vol cp $ST/cmudict.dict $J/data/cmudict.dict
echo "$CMUDICT_SHA  $J/data/cmudict.dict" | sha256sum -c
cp $J/scripts/lang_lines/out/lines_lang.tsv $J/scripts/lang_lines/out/speak_lang.txt $J/data/lang/
cp $J/scripts/her_test.txt $J/scripts/laugh_lines.txt $J/data/
if [ ! -s $J/data/yume.list ] || [ "$(ls $J/data/wavs/*.wav 2>/dev/null | wc -l)" -lt 4 ]; then
  tmp=$(mktemp -d /w/unz.XXXXXX)
  vol unzip -q -o $Y/source/yume_voice_clips.zip -d $tmp
  cp $tmp/yume_voice_clips/wavs/*.wav $J/data/wavs/
  cp $tmp/yume_voice_clips/yume_pod.list $J/data/yume.list   # the 71-line list her teacher trained on, /w/job/data/wavs/ paths
  rm -rf "$tmp"
fi
for f in $J/data/wavs/*.wav; do   # flac/ as on the old pods (lossless, the same samples)
  g=$J/data/flac/$(basename "${f%.wav}").flac
  [ -s "$g" ] || ffmpeg -y -loglevel error -i "$f" "$g"
done
echo "data: $(ls $J/data | tr '\n' ' ')| clips: $(ls $J/data/wavs | wc -l) wav, $(ls $J/data/flac | wc -l) flac, yume.list $(wc -l < $J/data/yume.list) lines"

build_gsv() {  # setup.sh: GPT-SoVITS 6d51ffc and gsv-env; setup_lang.sh's gsv-env check; the kana recogniser
  cd /w
  [ -d GPT-SoVITS/.git ] || git clone -q https://github.com/RVC-Boss/GPT-SoVITS.git
  cd GPT-SoVITS && git checkout -q $GSV_COMMIT
  local GP=/w/gsv-env/bin/python
  if ! done_ gsv-env; then
    [ -x $GP ] || uv venv -q -p 3.11 /w/gsv-env
    uv pip install -q --python $GP $TORCH --index-url $CU128
    uv pip install -q --python $GP -r requirements.txt numpy==1.26.4 transformers==4.57.6 gradio==4.44.1 \
        $TORCH resampy pyworld soundfile sherpa-onnx
    uv pip install -q --python $GP faster-whisper==1.1.1 requests   # as stage1_v2.sh (speak_checked.py)
    uv pip install -q --python $GP praat-parselmouth==0.4.7         # measure.py
    mark gsv-env
  fi
  # Pretrained models: big files fetched once onto the volume, linked into the tree (fast_langdetect stays local:
  # GPT-SoVITS writes its language model there on first use).
  local P=GPT_SoVITS/pretrained_models C=$M/gsv_pretrained HF=https://huggingface.co/lj1995/GPT-SoVITS/resolve/main f e
  for f in s1v3.ckpt v2Pro/s2Gv2ProPlus.pth v2Pro/s2Dv2ProPlus.pth sv/pretrained_eres2netv2w24s4ep4.ckpt \
           chinese-hubert-base/config.json chinese-hubert-base/preprocessor_config.json chinese-hubert-base/pytorch_model.bin \
           chinese-roberta-wwm-ext-large/config.json chinese-roberta-wwm-ext-large/pytorch_model.bin chinese-roberta-wwm-ext-large/tokenizer.json; do
    vol fetch "$HF/$f" "$C/$f"
  done
  for e in s1v3.ckpt v2Pro sv chinese-hubert-base chinese-roberta-wwm-ext-large; do
    if [ -e "$P/$e" ] && [ ! -L "$P/$e" ]; then
      if [ -n "$(git ls-files "$P/$e")" ]; then echo "$P/$e is tracked by git: not replaced"; return 1; fi
      rm -rf "$P/$e"
    fi
    ln -sfn "$C/$e" "$P/$e"
  done
  mkdir -p $P/fast_langdetect
  vol fetch https://huggingface.co/XXXXRT/GPT-SoVITS-Pretrained/resolve/main/nltk_data.zip $M/nltk_data.zip
  [ -d /w/gsv-env/nltk_data ] || vol unzip -q -o $M/nltk_data.zip -d /w/gsv-env/
  # setup_lang.sh: pyopenjtalk fetches its dictionary on first use: once here, not in parallel workers later.
  $GP -c "import librosa, pyworld, sherpa_onnx, pyopenjtalk, faster_whisper, transformers, parselmouth; pyopenjtalk.g2p('テスト'); \
print('gsv-env ok: transformers', transformers.__version__, 'parselmouth', parselmouth.VERSION, 'faster-whisper', faster_whisper.__version__)"
  gpu_check $GP
  # The kana recogniser (setup.sh): its archive on the volume, unpacked on the container disk.
  vol fetch https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/$SHERPA.tar.bz2 $M/$SHERPA.tar.bz2
  [ -s /w/$SHERPA/tokens.txt ] || vol tar xjf $M/$SHERPA.tar.bz2 -C /w
  ls /w/$SHERPA
  echo BUILD-GSV-OK
}

build_piper() {  # setup.sh: piper1-gpl 46c3c71, piper-env, pyopenjtalk 0.4.1, its patches, the base voice
  cd /w
  [ -d piper1-gpl/.git ] || git clone -q https://github.com/OHF-voice/piper1-gpl.git
  cd piper1-gpl && git checkout -q $PIPER_COMMIT
  local PP=/w/piper-env/bin/python
  if ! done_ piper-env; then
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
    mark piper-env
  fi
  $PP -c "import importlib.metadata as m; print('pyopenjtalk', m.version('pyopenjtalk'))"
  $PP -c "import piper.train.vits.monotonic_align, piper.phonemize_japanese as j; print(j.JapanesePhonemizer().phonemize('今日はいい天気だね'))"
  # The base voice (hifi_tts_92, CC BY 4.0) on the volume. A literal '=' in the name: the CDN refuses '%3D'.
  local PB="https://huggingface.co/datasets/rhasspy/piper-checkpoints/resolve/main/en/en_US/hifi_tts_92/medium"
  if [ ! -s $M/piper-base/base.ckpt.sha256 ]; then
    vol fetch "$PB/epoch=3642-val_mel=0.3319.ckpt" $M/piper-base/base.ckpt
    echo "$PIPER_BASE_SHA  $M/piper-base/base.ckpt" | vol sha256sum -c || { rm -f $M/piper-base/base.ckpt; return 1; }
    echo "$PIPER_BASE_SHA  base.ckpt" > $M/piper-base/base.ckpt.sha256
  fi
  vol fetch "$PB/config.json" $M/piper-base/config.json
  link $M/piper-base /w/piper-base
  # Piper 1.8 on several GPUs and without the MOS predictor (setup.sh), her mixed phonemizer (setup_lang.sh).
  $PP $J/scripts/ddp_patch.py
  $PP $J/scripts/mos_patch.py
  $PP $J/scripts/mixed_patch.py
  gpu_check $PP
  echo BUILD-PIPER-OK
}

build_dfn() {  # setup_clean.sh: DeepFilterNet in its own env (its model in ~/.cache/DeepFilterNet)
  local DP=/w/dfn-env/bin/python
  if ! done_ dfn-env; then
    [ -x $DP ] || uv venv -q -p 3.11 /w/dfn-env
    uv pip install -q --python $DP $TORCH --index-url $CU128
    uv pip install -q --python $DP deepfilternet soundfile numpy
    mark dfn-env
  fi
  $DP -c "from df.enhance import init_df; init_df(); print('dfn ok')"
  gpu_check $DP
  echo BUILD-DFN-OK
}

build_asr() {  # setup_lang.sh: faster-whisper large-v3 in its own env, the model on the volume
  local AP=/w/asr-env/bin/python
  if ! done_ asr-env; then
    [ -x $AP ] || uv venv -q -p 3.11 /w/asr-env
    uv pip install -q --python $AP faster-whisper==1.1.1 requests 'nvidia-cublas-cu12' 'nvidia-cudnn-cu12==9.*' \
        soundfile huggingface_hub
    uv pip install -q --python $AP whisper-normalizer || echo "whisper-normalizer missing: check_lang.py falls back to its own normalizer"
    mark asr-env
  fi
  [ -s $M/faster-whisper-large-v3/model.bin ] || vol hf_get $AP Systran/faster-whisper-large-v3 $M/faster-whisper-large-v3
  ls -la $M/faster-whisper-large-v3
  ( export LD_LIBRARY_PATH="$($AP -c 'import os, nvidia.cublas.lib, nvidia.cudnn.lib; print(list(nvidia.cublas.lib.__path__)[0] + ":" + list(nvidia.cudnn.lib.__path__)[0])'):${LD_LIBRARY_PATH:-}"
    $AP -c "import ctranslate2, faster_whisper; print('ctranslate2', ctranslate2.__version__, 'faster-whisper', faster_whisper.__version__, \
'cuda devices', ctranslate2.get_cuda_device_count(), 'compute types', sorted(ctranslate2.get_supported_compute_types('cuda')))" )
  echo BUILD-ASR-OK
}

build_irodori() {  # the range trial's setup_irodori.sh: Irodori-TTS f01c08cd, its own lock (torch too), its two models
  cd /w
  [ -d irodori/.git ] || git clone -q https://github.com/Aratako/Irodori-TTS.git irodori
  cd irodori && git checkout -q $IRODORI_COMMIT
  if ! done_ irodori-env; then
    UV_PROJECT_ENVIRONMENT=/w/irodori-env uv sync --extra cu128 --frozen
    mark irodori-env
  fi
  # The range scripts read the models from HF_HOME=/workspace/models/hf_range (the hub cache: a few big blobs).
  ( export HF_HOME=$M/hf_range
    vol hf_get /w/irodori-env/bin/python Aratako/Irodori-TTS-v4.1-Small
    vol hf_get /w/irodori-env/bin/python Aratako/Semantic-DACVAE-Japanese-32dim )
  gpu_check /w/irodori-env/bin/python
  echo BUILD-IRODORI-OK
}

run_build() {  # run_build <env>: one build, its own log, a status file
  # Not as an if/||/&& operand: bash ignores set -e inside a subshell used as a condition, so a failing step
  # would not stop the build.
  local b=$1 rc
  step "build $b ($(df -h / | awk 'NR == 2 {print $4}') free on /)"
  set +e
  ( set -euxo pipefail; build_$b ) > $ELOG/bison_setup_$b.log 2>&1
  rc=$?
  set -e
  if [ $rc = 0 ]; then
    echo ok > $ELOG/build_$b.status; step "build $b ok"
  else
    echo failed > $ELOG/build_$b.status; step "BUILD $b FAILED (exit $rc):"; tail -25 $ELOG/bison_setup_$b.log
  fi
}
step "builds, two at a time (logs $ELOG/bison_setup_<env>.log)"
rm -f $ELOG/build_*.status
( run_build gsv; run_build dfn; run_build asr ) &
LANE1=$!
( run_build irodori; run_build piper ) &
LANE2=$!
wait $LANE1 || true; wait $LANE2 || true
fail=0
for b in gsv piper dfn asr irodori; do
  [ "$(cat $ELOG/build_$b.status 2>/dev/null)" = ok ] || { echo "env $b: not ok"; fail=1; }
done
[ $fail = 0 ] || { df -h / | tail -1; step BISON-SETUP-FAILED; exit 1; }

# --- setup_lang.sh: the timbre model (from her data pack) ---
[ -s $M/wavlm-base-plus-sv/config.json ] || { echo "no $M/wavlm-base-plus-sv"; step BISON-SETUP-FAILED; exit 1; }
echo "WavLM: $(readlink -f $M/wavlm-base-plus-sv)"

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
CMUDICT=$J/data/cmudict.dict PIPER_SRC=/w/piper1-gpl/src /w/piper-env/bin/python -I -m unittest discover -s $J/scripts/tests \
  > $ELOG/bison_unittest.log 2>&1 || { grep -v "^WARNING" $ELOG/bison_unittest.log | tail -20; step BISON-SETUP-FAILED; exit 1; }
grep -v "^WARNING" $ELOG/bison_unittest.log | tail -3

# --- every env passed: the uv cache onto the volume as one tar (when it is new or this run added to it) ---
if [ "${CACHE_SAVE:-1}" = 1 ]; then
  if [ ! -s $UVTAR ] || [ -n "$(find /w/uvcache/archive-v0 /w/uvcache/sdists-v* /w/uvpython -mindepth 1 -maxdepth 1 \
         -newer $UVTAR -print -quit 2>/dev/null)" ]; then
    step "uv cache -> $UVTAR"
    mkdir -p $CACHE; t0=$(date +%s)
    vol tar cf $UVTAR.part -C /w --exclude='uvcache/.tmp*' --exclude='uvcache/builds-v0' uvcache uvpython
    mv -f $UVTAR.part $UVTAR
    echo "wrote $UVTAR: $(du -h $UVTAR | cut -f1) in $(( $(date +%s) - t0 )) s"
  else
    echo "uv cache unchanged since $UVTAR"
  fi
fi

step "where things are"
cat <<EOF
  envs (container disk)   /w/gsv-env /w/piper-env /w/dfn-env /w/asr-env /w/irodori-env (uv's Pythons in /w/uvpython)
  repos (container disk)  /w/GPT-SoVITS @$GSV_COMMIT  /w/piper1-gpl @$PIPER_COMMIT  /w/irodori @${IRODORI_COMMIT:0:8}
  uv cache                /w/uvcache (hard-linked into every env); saved as $UVTAR
  scripts                 /w/job/scripts (repo pod scripts), /w/range/scripts (range trial's scripts)
  her clips               /w/job/data/{wavs,flac,yume.list}; cmudict.dict, lang/, her_test.txt, laugh_lines.txt
  her data                /w/yume (from xfer.tar); /workspace/yume/{teacher,range_proto,job_out,...} link into it
  old paths               /w/job/out -> /w/yume/job_out; /workspace/{teacher,range_proto,job_out,phone_lang2,
                          piper-lang2-keep} -> /workspace/yume/...; /workspace/models -> $M;
                          /workspace/uvcache_range -> /w/uvcache
  models (volume)         $M: gsv_pretrained (linked into GPT-SoVITS), faster-whisper-large-v3, hf_range (Irodori),
                          piper-base (/w/piper-base), wavlm-base-plus-sv (-> /w/yume), $SHERPA.tar.bz2, nltk_data.zip
  kana recogniser         /w/$SHERPA, also at /tmp/claude-0/voice/$SHERPA for asr_kana.py
  logs                    /w/logs/bison_setup.log, /w/logs/bison_setup_<env>.log
EOF
du -sh /w/uvcache /w/uvpython 2>/dev/null
df -h / | tail -1
nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader
step BISON-SETUP-DONE
