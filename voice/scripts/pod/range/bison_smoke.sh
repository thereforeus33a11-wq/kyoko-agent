#!/usr/bin/env bash
# Smoke tests for bison_setup.sh, on her data once the transfer is done (/workspace/yume/XFER_OK). No voice data
# in this script: the reference text comes from yume.list at run time, the lines spoken are new.
#  1. her teacher (range_speak.py) speaks one Japanese and one English line from refs/v12_071_clean.wav;
#     WavLM sim to the centroid of her 4 clean clips (measure.py) must be in her teacher's usual 0.85-0.93,
#     and the median f0 at most 345 Hz (her adult cap);
#  2. faster-whisper (asr_check.py) hears both lines right; the kana recogniser (asr_kana.py) the Japanese one;
#  3. Irodori (irodori_speak.py) speaks one line cloned from her 4 clean clips, heard right, f0 capped;
#  4. DeepFilterNet (dfn_clean.py) cleans a file;
#  5. piper1-gpl imports and loads her phone voice's checkpoint on the GPU and runs it;
#  6. nvidia-smi sees the work on the GPU.
# Writes /workspace/yume/SETUP_OK (one line per env) only when every test passes.
# Outputs (her timbre: private) on the container disk in /w/range_build/smoke, then kept on the volume as one file,
# /workspace/yume/range_build/smoke.tar. Ends with SMOKE-PASSED or SMOKE-FAILED.
set -uo pipefail
if [ "${BISON_LOCAL:-0}" != 1 ]; then   # run from the container disk (bash reads a script as it goes)
  cp "$0" /w/bison_smoke.run.sh && BISON_LOCAL=1 exec bash /w/bison_smoke.run.sh "$@"
fi
Y=/workspace/yume; O=/w/range_build/smoke; RF=/workspace/range_proto/refs; S=/w/range/scripts
PIPER_CKPT=${PIPER_CKPT:-$Y/piper-lang2-keep/keep-epoch=974.ckpt}
[ -f $Y/XFER_OK ] || { echo "no $Y/XFER_OK yet"; echo SMOKE-FAILED; exit 1; }
source /w/job/scripts/lang_env.sh
export CUDA_VISIBLE_DEVICES=0
# the image points these into /workspace (many small files): kept on the container disk
export HF_HOME=/w/hf HF_XET_CACHE=/w/hf/xet PIP_CACHE_DIR=/w/pipcache UV_CACHE_DIR=/w/uvcache
rm -rf $O; mkdir -p $O/teacher $O/irodori $O/dfn $O/kana
fail=0
pass() { echo "PASS $*"; }
bad() { echo "FAIL $*"; fail=1; }
step() { echo "=== $(date -u +%H:%M:%S) $*"; }
CENTROID="$RF/v12_040_clean.wav $RF/v12_065_clean.wav $RF/v12_071_clean.wav $RF/yume_07_clean.wav"
for f in $RF/v12_071_clean.wav $CENTROID "$G_HER" "$S2" "$PIPER_CKPT"; do [ -s "$f" ] || bad "missing $f"; done
[ $fail = 0 ] || { echo SMOKE-FAILED; exit 1; }

# The GPU, every 2 s, for the whole run.
nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader > $O/gpu_idle.txt
( while :; do
    echo "$(date -u +%T) $(nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader) | $(nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader | tr '\n' ';')"
    sleep 2
  done ) > $O/gpu.log 2>&1 &
GW=$!
trap 'kill $GW 2>/dev/null' EXIT

col() {  # col <measure.tsv> <file basename> <column name>
  awk -F'\t' -v f="$2" -v c="$3" 'NR==1 {for (i = 1; i <= NF; i++) if ($i == c) k = i; next}
    $2 == "all" && index($1, f) {print $k; exit}' "$1"
}
check_take() {  # check_take <label> <measure.tsv> <file> <sim lo> <sim hi> <max err>
  local s f e h
  s=$(col $2 $3 sim_her); f=$(col $2 $3 f0_med); e=$(col $2 $3 err); h=$(col $2 $3 heard)
  echo "  $1: sim_her=$s f0_med=$f err=$e heard: $h"
  [ -n "$s" ] || { bad "$1: not measured"; return; }
  awk -v s="$s" -v lo="$4" -v hi="$5" 'BEGIN {exit !(s >= lo && s <= hi)}' && pass "$1 sim $s in [$4, $5]" || bad "$1 sim $s not in [$4, $5]"
  awk -v f="$f" 'BEGIN {exit !(f > 0 && f <= 345)}' && pass "$1 median f0 $f Hz <= 345" || bad "$1 median f0 $f Hz"
  awk -v e="$e" -v m="$6" 'BEGIN {exit !(e == e + 0 && e <= m)}' && pass "$1 heard right (error $e <= $6)" || bad "$1 heard wrong (error $e > $6)"
}

step "1. her teacher, Japanese and English, reference refs/v12_071_clean.wav"
ref_text=$(grep -F "/v12_071.wav|" $J/data/yume.list | head -1 | cut -d'|' -f4)
[ -n "$ref_text" ] || bad "no text for v12_071 in yume.list"
JA="今日は天気がいいから、駅前のカフェまで歩いて行こうよ。"
EN="I think we should walk to the station before it gets dark."
{ printf 'smoke_ja\tja\t%s\t%s\t1\t1.0\t%s\n' $RF/v12_071_clean.wav "$ref_text" "$JA"
  printf 'smoke_en\ten\t%s\t%s\t1\t1.0\t%s\n' $RF/v12_071_clean.wav "$ref_text" "$EN"; } > $O/jobs_teacher.tsv
t0=$(date +%s)
gsv python $S/range_speak.py --gpt "$G_HER" --sovits "$S2" --jobs $O/jobs_teacher.tsv --out $O/teacher > $O/teacher.log 2>&1 \
  || { tail -20 $O/teacher.log; bad "teacher run"; }
grep -E "^[0-9]{4}_" $O/teacher.log; echo "  teacher: $(( $(date +%s) - t0 )) s with model load"
TJ=$O/teacher/0000_smoke_ja_t0.wav; TE=$O/teacher/0001_smoke_en_t0.wav
[ -s $TJ ] && [ -s $TE ] && pass "teacher spoke both lines" || bad "teacher takes missing"

step "2a. faster-whisper hears the teacher lines"
asr $S/asr_check.py $WHISPER $O/teacher/jobs_done.tsv $O/teacher/heard.tsv $O/teacher > $O/asr_teacher.log 2>&1 \
  || { tail -20 $O/asr_teacher.log; bad "faster-whisper run"; }
cat $O/teacher/heard.tsv
step "1b. timbre and pitch of the teacher lines (measure.py, WavLM on the GPU)"
(cd $R; gsv python $S/measure.py --ref $RF/v12_071_clean.wav --centroid $CENTROID --device cuda \
  --jobs $O/teacher/jobs_done.tsv --heard $O/teacher/heard.tsv --out $O/teacher/measure.tsv $O/teacher) > $O/measure_teacher.log 2>&1 \
  || { tail -20 $O/measure_teacher.log; bad "measure teacher"; }
check_take "teacher ja" $O/teacher/measure.tsv 0000_smoke_ja_t0.wav 0.85 0.93 0.15
check_take "teacher en" $O/teacher/measure.tsv 0001_smoke_en_t0.wav 0.85 0.93 0.20

step "2b. the kana recogniser (sherpa-onnx ReazonSpeech) hears the Japanese teacher line"
ln -sf $TJ $O/kana/0000_smoke_ja.wav
printf 'smoke|%s\n' "$JA" > $O/kana/lines.txt
gsv python /w/job/scripts/asr_kana.py $O/kana $O/kana/lines.txt > $O/kana.log 2>&1 || { tail -20 $O/kana.log; bad "kana recogniser run"; }
grep -v "^\s*$" $O/kana.log | tail -2
kc=$(sed -n 's/^mean kana CER \([0-9.]*\),.*/\1/p' $O/kana.log)
awk -v c="$kc" 'BEGIN {exit !(c == c + 0 && c <= 0.15)}' && pass "kana recogniser CER $kc <= 0.15" || bad "kana recogniser CER '$kc'"

step "3. Irodori clones her from her 4 clean clips"
printf 'smoke_ja\ther4\t-\t-\t1\t%s\n' "$JA" > $O/jobs_irodori.tsv
t0=$(date +%s)
(export HF_HOME=/workspace/models/hf_range HF_HUB_OFFLINE=1 PYTHONPATH=/w/irodori; cd /w/irodori
 /w/irodori-env/bin/python $S/irodori_speak.py --jobs $O/jobs_irodori.tsv --out $O/irodori --precision fp32) > $O/irodori.log 2>&1 \
  || { tail -20 $O/irodori.log; bad "irodori run"; }
grep "^\[" $O/irodori.log; echo "  irodori: $(( $(date +%s) - t0 )) s with model load"
[ -s $O/irodori/0000_smoke_ja_t0.wav ] && pass "irodori spoke" || bad "irodori take missing"
asr $S/asr_check.py $WHISPER $O/irodori/jobs_done.tsv $O/irodori/heard.tsv $O/irodori > $O/asr_irodori.log 2>&1 || bad "irodori asr"
(cd $R; gsv python $S/measure.py --ref $RF/v12_071_clean.wav --centroid $CENTROID --device cuda \
  --jobs $O/irodori/jobs_done.tsv --heard $O/irodori/heard.tsv --out $O/irodori/measure.tsv $O/irodori) > $O/measure_irodori.log 2>&1 \
  || { tail -20 $O/measure_irodori.log; bad "measure irodori"; }
# Irodori's timbre is judged by the range trial's own numbers (README_v2), not the teacher's band: a loose floor here.
check_take "irodori ja" $O/irodori/measure.tsv 0000_smoke_ja_t0.wav ${IRODORI_SIM_LO:-0.75} 1.0 0.20

step "4. DeepFilterNet cleans a file (CPU, as post2.sh runs it)"
CUDA_VISIBLE_DEVICES="" /w/dfn-env/bin/python /w/job/scripts/dfn_clean.py --atten 10 $TJ $O/dfn/0000_smoke_ja_t0.wav > $O/dfn.log 2>&1 \
  || { tail -20 $O/dfn.log; bad "dfn run"; }
/w/gsv-env/bin/python - $TJ $O/dfn/0000_smoke_ja_t0.wav <<'PY' && pass "deepfilternet cleaned a file" || bad "deepfilternet output"
import sys, numpy as np, soundfile as sf
a, sa = sf.read(sys.argv[1]); b, sb = sf.read(sys.argv[2])
d = float(np.sqrt(np.mean((a[:len(b)] - b[:len(a)]) ** 2)))
print(f"  in {len(a) / sa:.2f}s @ {sa}, out {len(b) / sb:.2f}s @ {sb}, out rms {np.sqrt(np.mean(b ** 2)):.4f}, changed by rms {d:.4f}")
assert sa == sb and abs(len(a) - len(b)) <= 0.01 * len(a) and np.sqrt(np.mean(b ** 2)) > 1e-3 and d > 0
PY

step "5. piper1-gpl loads her phone voice ($(basename "$PIPER_CKPT")) on the GPU"
(cd /w/piper1-gpl; /w/piper-env/bin/python - "$PIPER_CKPT" <<'PY') > $O/piper.log 2>&1 && pass "piper loads and runs her checkpoint" || { tail -20 $O/piper.log; bad "piper load"; }
import sys, time, torch
from piper.train.vits.lightning import VitsModel
t0 = time.time()
m = VitsModel.load_from_checkpoint(sys.argv[1], map_location="cuda").eval()
g = m.model_g
n = sum(p.numel() for p in g.parameters())
hp = dict(m.hparams)
print(f"loaded in {time.time() - t0:.1f}s: {n / 1e6:.1f}M generator params on {next(g.parameters()).device},",
      {k: hp[k] for k in ("num_symbols", "num_speakers", "sample_rate") if k in hp})
ids = torch.randint(1, int(hp.get("num_symbols", 100)) - 1, (1, 40), device="cuda")
with torch.no_grad():
    sid = torch.LongTensor([0]).cuda() if int(hp.get("num_speakers", 1)) > 1 else None
    out = g.infer(ids, torch.LongTensor([40]).cuda(), sid=sid, noise_scale=0.667, length_scale=1.0, noise_scale_w=0.8)
y = out[0] if isinstance(out, (tuple, list)) else out
print("infer ok:", tuple(y.shape), "samples, finite", bool(torch.isfinite(y).all()))
assert torch.isfinite(y).all() and y.numel() > 1000
PY
cat $O/piper.log | grep -v -i warn | tail -3

step "6. the GPU saw the work"
kill $GW 2>/dev/null; trap - EXIT
idle=$(cut -d' ' -f1 $O/gpu_idle.txt)
peak=$(awk '{print $2}' $O/gpu.log | sort -n | tail -1)
apps=$(grep -c "python" $O/gpu.log)
echo "  memory used idle ${idle} MiB, peak ${peak} MiB; samples naming a python process: $apps of $(wc -l < $O/gpu.log)"
grep -m3 "python" $O/gpu.log
awk -v p="$peak" -v i="$idle" 'BEGIN {exit !(p > i + 1000)}' && pass "nvidia-smi saw the jobs on the GPU (peak $peak MiB)" || bad "no GPU use seen"

tar cf $Y/range_build/smoke.tar.part -C /w/range_build smoke && mv -f $Y/range_build/smoke.tar.part $Y/range_build/smoke.tar \
  && echo "  outputs kept as $Y/range_build/smoke.tar"
if [ $fail = 0 ]; then
  st=$(date -u +%FT%TZ)
  v() { $1 -c "import importlib.metadata as m; print(' '.join(f'{p} {m.version(p)}' for p in '$2'.split()))" 2>/dev/null; }
  {
    echo -e "gsv-env\t/w/gsv-env\tGPT-SoVITS $(git -C /w/GPT-SoVITS rev-parse --short=7 HEAD)\t$(v /w/gsv-env/bin/python 'torch torchaudio transformers faster-whisper')\tteacher ja+en, sim $(col $O/teacher/measure.tsv 0000_smoke_ja_t0.wav sim_her)/$(col $O/teacher/measure.tsv 0001_smoke_en_t0.wav sim_her)\t$st"
    echo -e "asr-env\t/w/asr-env\t$(v /w/asr-env/bin/python 'faster-whisper ctranslate2 nvidia-cudnn-cu12')\tlarge-v3 heard teacher and irodori\t$st"
    echo -e "kana\t/w/sherpa-onnx-zipformer-ja-reazonspeech-2024-08-01\tsherpa-onnx $(v /w/gsv-env/bin/python 'sherpa-onnx' | cut -d' ' -f2) (gsv-env)\tkana CER $kc\t$st"
    echo -e "dfn-env\t/w/dfn-env\t$(v /w/dfn-env/bin/python 'deepfilternet torch')\tcleaned a take\t$st"
    echo -e "piper-env\t/w/piper-env\tpiper1-gpl $(git -C /w/piper1-gpl rev-parse --short=7 HEAD)\t$(v /w/piper-env/bin/python 'torch pyopenjtalk')\tloaded $(basename "$PIPER_CKPT") on GPU\t$st"
    echo -e "irodori-env\t/w/irodori-env\tIrodori-TTS $(git -C /w/irodori rev-parse --short=8 HEAD)\t$(v /w/irodori-env/bin/python 'torch')\tcloned her, sim $(col $O/irodori/measure.tsv 0000_smoke_ja_t0.wav sim_her)\t$st"
  } > $Y/SETUP_OK
  cat $Y/SETUP_OK
  step SMOKE-PASSED
else
  rm -f $Y/SETUP_OK
  step SMOKE-FAILED
fi
