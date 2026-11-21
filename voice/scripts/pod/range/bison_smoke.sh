#!/usr/bin/env bash
# Smoke tests for bison_setup.sh on the one-GPU pod: the range trial's tools at their old paths, proved on her voice.
# No voice data in this script: the teacher's prompt text comes from yume.list at run time, the lines spoken are new.
# Every output is her timbre (private): all on the container disk in /w/range_build/smoke, archived at the end as one
# tar on the volume (/workspace/yume/range_build/range_build.tar).
#  1. her GPT-SoVITS teacher (range_speak.py) speaks one Japanese and one English line from refs/v12_071_clean.wav;
#  2. Irodori (irodori_speak.py, fp32) clones her from her 4 clean clips and speaks one Japanese line;
#  3. post2.sh trims them (edges.py) and cleans them (DeepFilterNet --atten 10, CPU), as the trial's v2 way;
#  4. post2_tail.sh: faster-whisper large-v3 (asr_check.py, GPU) hears the final takes, measure.py measures them;
#     the kana recogniser (asr_kana.py, sherpa-onnx ReazonSpeech) hears the Japanese ones;
#  5. piper1-gpl imports and loads her phone voice's checkpoint on the GPU and runs it;
#  6. nvidia-smi saw the jobs on the GPU.
# Gates: teacher sim to her 4-clip centroid in [TEACHER_SIM_LO, TEACHER_SIM_HI] = [0.85, 0.96] (her teacher's normal
# takes: 0.90 median, up to 0.95); Irodori sim >= IRODORI_SIM_LO = 0.80 (the trial's normal line: 0.97); every median
# f0 <= 345 Hz (her adult cap); heard right (kana error <= 0.15 Japanese, word error <= 0.20 English; kana recogniser
# CER <= 0.15). Before each GPU job: the GPU must have the job's memory plus 8 GB free (other agents share it).
# Writes /w/range_build/SETUP_OK (one line per env) only when every test passes. Ends with SMOKE-PASSED or SMOKE-FAILED.
# Run (after bison_setup.sh): setsid nohup bash /w/job/scripts/range/bison_smoke.sh > /w/logs/bison_smoke.log 2>&1 < /dev/null &
set -uo pipefail
if [ "${SMOKE_LOCAL:-0}" != 1 ]; then   # bash reads a script as it runs: run a copy on the container disk
  mkdir -p /w/range && cp "$0" /w/range/bison_smoke.run.sh && SMOKE_LOCAL=1 exec bash /w/range/bison_smoke.run.sh "$@"
fi
Y=/workspace/yume; B=/w/range_build; O=$B/smoke; RF=/workspace/range_proto/refs; S=/w/range/scripts
PIPER_CKPT=${PIPER_CKPT:-/w/yume/piper-lang2-keep/keep-epoch=974.ckpt}
KANA=/tmp/claude-0/voice/sherpa-onnx-zipformer-ja-reazonspeech-2024-08-01
source /w/job/scripts/lang_env.sh
# the image points these into /workspace (many small files): the container disk
export HF_HOME=/w/hf HF_XET_CACHE=/w/hf/xet PIP_CACHE_DIR=/w/pipcache UV_CACHE_DIR=/w/uvcache HF_HUB_ENABLE_HF_TRANSFER=0
export CUDA_VISIBLE_DEVICES=0 RANGE_O=$O RANGE_GPU=0
TLO=${TEACHER_SIM_LO:-0.85}; THI=${TEACHER_SIM_HI:-0.96}; ILO=${IRODORI_SIM_LO:-0.80}
rm -f $B/SETUP_OK
rm -rf $O; mkdir -p $O/T_raw $O/I_raw $O/kana
fail=0
pass() { echo "PASS $*"; }
bad() { echo "FAIL $*"; fail=1; }
step() { echo "=== $(date -u +%H:%M:%S) $*"; }
gpu_ok() {  # gpu_ok <MiB the job needs>: wait (up to 30 min) until free >= need + 8192
  local f i
  for i in $(seq 1 60); do
    f=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits -i 0 | head -1)
    [ "$f" -ge $(( $1 + 8192 )) ] && { echo "  GPU free $f MiB (job needs about $1, 8192 kept free)"; return 0; }
    echo "  GPU free $f MiB: waiting"; sleep 30
  done
  bad "GPU never had $1 + 8192 MiB free"; return 1
}
col() {  # col <measure.tsv> <file basename> <column name>
  awk -F'\t' -v f="$2" -v c="$3" 'NR==1 {for (i = 1; i <= NF; i++) if ($i == c) k = i; next}
    $2 == "all" && index($1, f) {print $k; exit}' "$1" 2>/dev/null
}
check_take() {  # check_take <label> <measure.tsv> <file> <sim lo> <sim hi> <max err>
  local s f e h
  s=$(col $2 $3 sim_her); f=$(col $2 $3 f0_med); e=$(col $2 $3 err); h=$(col $2 $3 heard)
  echo "  $1: sim_her=$s sim_ref=$(col $2 $3 sim_ref) f0_med=$f HNR=$(col $2 $3 hnr) LUFS=$(col $2 $3 lufs) dur=$(col $2 $3 dur) err=$e"
  [ -n "$s" ] || { bad "$1: not measured"; return; }
  awk -v s="$s" -v lo="$4" -v hi="$5" 'BEGIN {exit !(s >= lo && s <= hi)}' && pass "$1 sim $s in [$4, $5]" || bad "$1 sim $s not in [$4, $5]"
  awk -v f="$f" 'BEGIN {exit !(f > 0 && f <= 345)}' && pass "$1 median f0 $f Hz <= 345" || bad "$1 median f0 $f Hz"
  awk -v e="$e" -v m="$6" 'BEGIN {exit !(e == e + 0 && e <= m)}' && pass "$1 heard right (error $e <= $6)" || bad "$1 heard wrong (error $e > $6)"
}
CENTROID="$RF/v12_040_clean.wav $RF/v12_065_clean.wav $RF/v12_071_clean.wav $RF/yume_07_clean.wav"
for f in $CENTROID "$G_HER" "$S2" "$PIPER_CKPT" $WHISPER/model.bin $WAVLM/config.json $KANA/tokens.txt /w/irodori-env/bin/python \
         $S/range_speak.py $S/irodori_speak.py $S/post2.sh $S/post2_tail.sh $S/asr_check.py $S/measure.py $S/sound_trim.py \
         $S/lead_trim.py /w/job/scripts/edges.py /w/job/scripts/dfn_clean.py /w/job/scripts/asr_kana.py; do
  [ -s "$f" ] || bad "missing $f"
done
[ $fail = 0 ] || { step SMOKE-FAILED; exit 1; }
echo "  teacher $(basename "$G_HER") + $(basename "$S2"); Irodori $(git -C /w/irodori rev-parse --short=8 HEAD); piper $(basename "$PIPER_CKPT")"

# The GPU every 2 s for the whole run: memory used, utilisation, and the compute processes nvidia-smi lists.
nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -i 0 > $O/gpu_idle.txt
( while :; do
    echo "$(date -u +%T) $(nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader,nounits -i 0 | tr -d ' ') | $(nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader 2>/dev/null | tr '\n' ';')"
    sleep 2
  done ) > $O/gpu.log 2>&1 &
GW=$!
trap 'kill $GW 2>/dev/null' EXIT
mark() { echo "$(date -u +%T) $1" >> $O/phases.txt; }   # which job ran when, to read gpu.log against

step "1. her teacher speaks a Japanese and an English line, reference refs/v12_071_clean.wav (range_speak.py)"
ref_text=$(grep -F "/v12_071.wav|" $J/data/yume.list | head -1 | cut -d'|' -f4)
[ -n "$ref_text" ] || bad "no text for v12_071 in yume.list"
JA="今日は天気がいいから、駅前のカフェまで歩いて行こうよ。"
EN="I think we should walk to the station before it gets dark."
{ printf 'smoke_ja\tja\t%s\t%s\t1\t1.0\t%s\n' $RF/v12_071_clean.wav "$ref_text" "$JA"
  printf 'smoke_en\ten\t%s\t%s\t1\t1.0\t%s\n' $RF/v12_071_clean.wav "$ref_text" "$EN"; } > $O/jobs_teacher.tsv
t0=$(date +%s)
if gpu_ok 6000; then
  mark "teacher start"
  gsv python $S/range_speak.py --gpt "$G_HER" --sovits "$S2" --jobs $O/jobs_teacher.tsv --out $O/T_raw > $O/teacher.log 2>&1 \
    || { tail -20 $O/teacher.log; bad "teacher run"; }
  mark "teacher end"
fi
grep -E "^[0-9]{4}_" $O/teacher.log | sed 's/^/  /'; echo "  teacher: $(( $(date +%s) - t0 )) s with model load"
[ -s $O/T_raw/0000_smoke_ja_t0.wav ] && [ -s $O/T_raw/0001_smoke_en_t0.wav ] && pass "teacher spoke both lines" || bad "teacher takes missing"

step "2. Irodori clones her from her 4 clean clips and speaks one line (irodori_speak.py, fp32)"
printf 'smoke_iro_ja\ther4\t-\t-\t1\t%s\n' "$JA" > $O/jobs_irodori.tsv
t0=$(date +%s)
if gpu_ok 8000; then
  mark "irodori start"
  (export HF_HOME=/workspace/models/hf_range HF_HUB_OFFLINE=1 PYTHONPATH=/w/irodori; cd /w/irodori
   /w/irodori-env/bin/python $S/irodori_speak.py --jobs $O/jobs_irodori.tsv --out $O/I_raw --precision fp32) > $O/irodori.log 2>&1 \
    || { tail -20 $O/irodori.log; bad "irodori run"; }
  mark "irodori end"
fi
grep "^\[" $O/irodori.log | sed 's/^/  /'; echo "  irodori: $(( $(date +%s) - t0 )) s with model load"
[ -s $O/I_raw/0000_smoke_iro_ja_t0.wav ] && pass "irodori spoke" || bad "irodori take missing"

step "3. post2.sh: edges.py trim, then DeepFilterNet --atten 10 on the CPU, as the trial's v2 way"
for w in T I; do
  bash $S/post2.sh $w $O/${w}_raw > $O/post2_$w.log 2>&1 || bad "post2.sh $w exit $?"
  grep -v "^\s*$" $O/post2_$w.log | tail -4 | sed 's/^/  /'
  n=$(ls $O/$w/final2/[0-9]*.wav 2>/dev/null | wc -l); r=$(ls $O/${w}_raw/[0-9]*.wav 2>/dev/null | wc -l)
  [ "$n" = "$r" ] && [ "$n" -gt 0 ] && pass "post2 $w: $n of $r takes trimmed and cleaned" || bad "post2 $w: $n of $r takes in final2"
done
/w/gsv-env/bin/python - $O <<'PY' && pass "trim kept her speech, DeepFilterNet changed every take, rates kept" || bad "trim/DFN output check"
import glob, os, sys
import numpy as np, soundfile as sf
O = sys.argv[1]; ok = True; n = 0
for w in ("T", "I"):
    for f in sorted(glob.glob(f"{O}/{w}_raw/[0-9]*.wav")):
        b = os.path.basename(f); n += 1
        try:
            r, sr = sf.read(f); t, st = sf.read(f"{O}/{w}/v2_trim/{b}"); c, sc = sf.read(f"{O}/{w}/final2/{b}")
        except Exception as e:
            print(f"  {w}/{b}: {e}"); ok = False; continue
        d = float(np.sqrt(np.mean((t[:len(c)] - c[:len(t)]) ** 2)))
        good = (sr == st == sc and 0.5 * sr <= len(t) <= len(r) and abs(len(c) - len(t)) <= 0.01 * len(t) + 480
                and np.sqrt(np.mean(c ** 2)) > 1e-3 and d > 0)
        print(f"  {w}/{b}: raw {len(r) / sr:.2f}s -> trimmed {len(t) / st:.2f}s -> cleaned {len(c) / sc:.2f}s @ {sc} Hz,"
              f" DFN changed it by rms {d:.4f}: {'ok' if good else 'BAD'}")
        ok &= bool(good)
sys.exit(0 if ok and n else 1)
PY

step "4a. post2_tail.sh: faster-whisper hears the final takes (asr_check.py, GPU 0), measure.py measures them (CPU)"
t0=$(date +%s)
if gpu_ok 5000; then
  mark "post2_tail start"
  bash $S/post2_tail.sh T I > $O/post2_tail.log 2>&1 || bad "post2_tail.sh exit $?"
  mark "post2_tail end"
fi
sed 's/^/  /' $O/post2_tail.log; echo "  post2_tail: $(( $(date +%s) - t0 )) s"
for w in T I; do
  h=$(awk -F'\t' 'NR > 1 && $3 != ""' $O/$w/heard2.tsv 2>/dev/null | wc -l)
  [ "$h" -gt 0 ] && pass "asr_check heard $h take(s) of $w" || {
    bad "asr_check heard nothing for $w; its error, run again unfiltered:"
    CUDA_VISIBLE_DEVICES=0 asr $S/asr_check.py $WHISPER $O/${w}_raw/jobs_done.tsv $O/$w/heard_dbg.tsv $O/$w/final2 2>&1 | tail -15; }
  [ -s $O/$w/measure2.tsv ] || { bad "measure.py wrote nothing for $w:"; tail -15 $O/$w/measure2.log; }
done
# the raw teacher takes too, for comparison only (the gate is on the final takes, as the trial's numbers are)
(cd $R; CUDA_VISIBLE_DEVICES="" gsv python $S/measure.py --ref $RF/v12_071_clean.wav --centroid $CENTROID \
   --out $O/T/measure_raw.tsv $O/T_raw) > $O/measure_raw.log 2>&1
echo "  raw (before trim and DFN): ja sim_her $(col $O/T/measure_raw.tsv 0000_smoke_ja_t0.wav sim_her)," \
     "en sim_her $(col $O/T/measure_raw.tsv 0001_smoke_en_t0.wav sim_her)"

step "4b. the kana recogniser (sherpa-onnx ReazonSpeech, asr_kana.py) hears the Japanese final takes"
ln -sf $O/T/final2/0000_smoke_ja_t0.wav $O/kana/0000_teacher_ja.wav
ln -sf $O/I/final2/0000_smoke_iro_ja_t0.wav $O/kana/0001_irodori_ja.wav
printf 'teacher|%s\nirodori|%s\n' "$JA" "$JA" > $O/kana/lines.txt
gsv python /w/job/scripts/asr_kana.py $O/kana $O/kana/lines.txt > $O/kana.log 2>&1 || { tail -20 $O/kana.log; bad "kana recogniser run"; }
grep -v "^\s*$" $O/kana.log | tail -3 | sed 's/^/  /'
for k in 0 1; do
  c=$(awk -F'\t' -v k=$k '$1 == k {print $2}' $O/kana.log)
  awk -v c="$c" 'BEGIN {exit !(c == c + 0 && c <= 0.15)}' && pass "kana recogniser line $k CER $c <= 0.15" || bad "kana recogniser line $k CER '$c'"
done

step "5. gates (final takes)"
check_take "teacher ja" $O/T/measure2.tsv 0000_smoke_ja_t0.wav $TLO $THI 0.15
check_take "teacher en" $O/T/measure2.tsv 0001_smoke_en_t0.wav $TLO $THI 0.20
check_take "irodori ja" $O/I/measure2.tsv 0000_smoke_iro_ja_t0.wav $ILO 1.0 0.15

step "6. piper1-gpl loads her phone voice ($(basename "$PIPER_CKPT")) on the GPU and runs it"
if gpu_ok 4000; then
  mark "piper start"
  (cd /w/piper1-gpl; /w/piper-env/bin/python - "$PIPER_CKPT" <<'PY') > $O/piper.log 2>&1 && pass "piper loads and runs her checkpoint" || { tail -20 $O/piper.log; bad "piper load"; }
import sys, time, torch
import piper, piper.phonemize_japanese as pj
from piper.train.vits.lightning import VitsModel
print("piper from", piper.__file__, "| phonemes:", pj.JapanesePhonemizer().phonemize("今日はいい天気だね"))
t0 = time.time()
m = VitsModel.load_from_checkpoint(sys.argv[1], map_location="cuda").eval()
g = m.model_g
hp = dict(m.hparams)
print(f"loaded in {time.time() - t0:.1f}s: {sum(p.numel() for p in g.parameters()) / 1e6:.1f}M generator params on"
      f" {next(g.parameters()).device},", {k: hp[k] for k in ("num_symbols", "num_speakers", "sample_rate") if k in hp})
ids = torch.randint(1, int(hp.get("num_symbols", 100)) - 1, (1, 40), device="cuda")
with torch.no_grad():
    sid = torch.LongTensor([0]).cuda() if int(hp.get("num_speakers", 1)) > 1 else None
    out = g.infer(ids, torch.LongTensor([40]).cuda(), sid=sid, noise_scale=0.667, length_scale=1.0, noise_scale_w=0.8)
    torch.cuda.synchronize()
y = out[0] if isinstance(out, (tuple, list)) else out
print("infer ok:", tuple(y.shape), "finite", bool(torch.isfinite(y).all()), f"peak GPU memory {torch.cuda.max_memory_allocated() / 2**20:.0f} MiB")
assert torch.isfinite(y).all() and y.numel() > 1000
PY
  mark "piper end"
fi
grep -v -i warn $O/piper.log | tail -3 | sed 's/^/  /'

step "7. the GPU saw the work"
sleep 3; kill $GW 2>/dev/null; trap - EXIT
idle=$(cat $O/gpu_idle.txt)
peak=$(awk '{split($2, a, ","); print a[1]}' $O/gpu.log | sort -n | tail -1)
apps=$(grep -c "python" $O/gpu.log)
echo "  memory used at the start ${idle} MiB, peak ${peak} MiB; samples listing a python process: $apps of $(wc -l < $O/gpu.log)"
sed 's/^/  phase /' $O/phases.txt
awk '{split($2, a, ","); if (a[1] + 0 > m) {m = a[1] + 0; l = $0}} END {print "  at the peak: " l}' $O/gpu.log
awk -v p="$peak" -v i="$idle" 'BEGIN {exit !(p > i + 1000)}' && pass "nvidia-smi saw the jobs on the GPU (peak $peak MiB, start $idle MiB)" || bad "no GPU use seen"

if [ $fail = 0 ]; then
  st=$(date -u +%FT%TZ)
  v() { $1 -c "import importlib.metadata as m; print(' '.join(f'{p} {m.version(p)}' for p in '$2'.split()))" 2>/dev/null; }
  m2() { echo "sim $(col $1 $2 sim_her) f0 $(col $1 $2 f0_med) err $(col $1 $2 err)"; }
  {
    echo -e "gsv-env\t/w/gsv-env\tGPT-SoVITS $(git -C /w/GPT-SoVITS rev-parse --short=7 HEAD)\t$(v /w/gsv-env/bin/python 'torch transformers praat-parselmouth faster-whisper')\tteacher ja $(m2 $O/T/measure2.tsv 0000_smoke_ja_t0.wav); en $(m2 $O/T/measure2.tsv 0001_smoke_en_t0.wav)\t$st"
    echo -e "irodori-env\t/w/irodori-env\tIrodori-TTS $(git -C /w/irodori rev-parse --short=8 HEAD)\t$(v /w/irodori-env/bin/python 'torch')\tcloned her from 4 clips: $(m2 $O/I/measure2.tsv 0000_smoke_iro_ja_t0.wav)\t$st"
    echo -e "dfn-env\t/w/dfn-env\t$(v /w/dfn-env/bin/python 'deepfilternet torch')\tpost2.sh trimmed and cleaned 3 of 3 takes\t$st"
    echo -e "asr-env\t/w/asr-env\t$(v /w/asr-env/bin/python 'faster-whisper ctranslate2')\tlarge-v3 heard 3 of 3 right; kana recogniser (gsv-env sherpa-onnx $(v /w/gsv-env/bin/python sherpa-onnx | cut -d' ' -f2)) heard 2 of 2\t$st"
    echo -e "piper-env\t/w/piper-env\tpiper1-gpl $(git -C /w/piper1-gpl rev-parse --short=7 HEAD)\t$(v /w/piper-env/bin/python 'torch pyopenjtalk')\tloaded and ran $(basename "$PIPER_CKPT") on the GPU\t$st"
  } > $B/SETUP_OK
  cat $B/SETUP_OK
fi
# everything of this run (her timbre, private) onto the volume as one tar
( flock 9; tar cf $Y/range_build/range_build.tar.part -C /w range_build && mv -f $Y/range_build/range_build.tar.part $Y/range_build/range_build.tar ) 9> /w/locks/volume \
  && echo "  /w/range_build archived as $Y/range_build/range_build.tar ($(du -h $Y/range_build/range_build.tar | cut -f1))"
if [ $fail = 0 ]; then step SMOKE-PASSED; else rm -f $B/SETUP_OK; step SMOKE-FAILED; fi
