#!/usr/bin/env bash
# Stage 1 for her English: her teacher voice (GPT-SoVITS) speaks her English and mixed lines, a few of
# her real Japanese clips taking turns as the reference; every take is checked, brightened like her
# Japanese data, and the best take of each line goes into the Piper set.
#   MODE=pilot  the 60 held-out lines, with her GPT (e10) and with the pretrained GPT (s1v3), both on
#               her SoVITS: two accent strengths. Writes pilot/choice.txt (GPT_CHOICE=her|base overrides).
#   MODE=full   every line, two takes (another seed, the next reference clip), the checks, the set.
# Log to /w/logs/stage1_lang_<mode>.log; ends with STAGE1-LANG-DONE.
set -euo pipefail
source /w/job/scripts/lang_env.sh
MODE=${MODE:-full}
step() { echo "=== $(date -u +%H:%M:%S) $*"; }
# GPUs on this pod (the run was planned on 4; the migration pod has 3).
NG=${NG:-$(nvidia-smi -L | wc -l)}
mkdir -p $OL
make_refs $OL/refs.tsv
cat $OL/refs.tsv | cut -f1

speak_set() {  # speak_set <gpt> <lines file> <out dir> <seed> <ref offset> <shards>
  local gpt=$1 lines=$2 out=$3 seed=$4 off=$5 shards=$6 i
  mkdir -p $out
  for i in $(seq 0 $((shards - 1))); do
    CUDA_VISIBLE_DEVICES=$(( i % NG )) gsv python $J/scripts/speak.py --gpt $gpt --sovits $S2 --out $out \
      --refs $OL/refs.tsv --ref-offset $off --seed $seed --lines $lines --shard $i/$shards $SPEAK_LANG_OPTS \
      > $out.speak_$i.log 2>&1 &
  done
  wait
  echo "$(ls $out/*.wav 2>/dev/null | wc -l) clips in $out"
}

check_set() {  # check_set <lines tsv> <raw dir with take folders> <work> <out ds>
  local lines=$1 raw=$2 work=$3 out=$4 i
  mkdir -p $work
  for i in $(seq 0 $((NG - 1))); do
    CUDA_VISIBLE_DEVICES=$i asr $J/scripts/check_lang.py asr --lines $lines --raw $raw --work $work \
      --shard $i/$NG --model $WHISPER > $work/asr_$i.log 2>&1 &
  done
  wait
  gsv python $J/scripts/check_lang.py prep --lines $lines --raw $raw --work $work --jobs $(( $(nproc) - 4 )) > $work/prep.log 2>&1
  CUDA_VISIBLE_DEVICES=0 gsv python $J/scripts/check_lang.py sim --work $work --refs $OL/refs.tsv --ja-wavs $JA_DS/wavs \
    --model $WAVLM > $work/sim.log 2>&1 || echo "timbre check failed (see $work/sim.log); going on without it"
  gsv python $J/scripts/check_lang.py pick --lines $lines --work $work --out $out --ja-wavs $JA_DS/wavs | tail -40
}

if [ "$MODE" = pilot ]; then
  P=$OL/pilot; rm -rf $P; mkdir -p $P
  # The held-out lines, renumbered 0..59 so file NNNN.wav is row NNNN.
  python3 - "$LANG_IN/lines_lang.tsv" "$P" <<'PY'
import csv, sys
src, out = sys.argv[1:3]
rows = [r for r in csv.DictReader(open(src, encoding="utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE) if r["split"] == "holdout"]
with open(f"{out}/lines.tsv", "w", encoding="utf-8") as f, open(f"{out}/speak.txt", "w", encoding="utf-8") as g:
    f.write("\t".join(rows[0].keys()) + "\n")
    for k, r in enumerate(rows):
        r["n"] = str(k)
        f.write("\t".join(r.values()) + "\n")
        g.write(f"{r['teacher_lang']}|{r['teacher_text']}\n")
print(len(rows), "pilot lines")
PY
  step "pilot: her GPT and the pretrained GPT at the same time, spread over $NG GPUs"
  speak_set $G_HER $P/speak.txt $P/her_raw/A 1234 0 2 &
  (
    mkdir -p $P/base_raw/A
    for i in 2 3; do
      CUDA_VISIBLE_DEVICES=$(( i % NG )) gsv python $J/scripts/speak.py --gpt $G_BASE --sovits $S2 --out $P/base_raw/A \
        --refs $OL/refs.tsv --seed 1234 --lines $P/speak.txt --shard $((i - 2))/2 $SPEAK_LANG_OPTS > $P/base_speak_$i.log 2>&1 &
    done
    wait
  ) &
  wait
  for g in her base; do
    step "pilot checks: $g"
    check_set $P/lines.tsv $P/${g}_raw $P/${g}_work $P/${g}_ds > $P/${g}_summary.txt
    gsv python - "$P/${g}_work/bright/A" "$P/pilot_${g}.wav" <<'PY'
import glob, sys, numpy as np, soundfile as sf
parts, sr = [], 22050
for f in sorted(glob.glob(sys.argv[1] + "/[0-9]*.wav")):
    x, sr = sf.read(f, dtype="float32"); parts += [x, np.zeros(int(sr * 0.6), np.float32)]
sf.write(sys.argv[2], np.concatenate(parts), sr, subtype="PCM_16")
PY
  done
  python3 - "$P" "${GPT_CHOICE:-}" <<'PY'
import json, sys
p, forced = sys.argv[1:3]
s = {g: json.load(open(f"{p}/{g}_ds/teacher_stats.json")) for g in ("her", "base")}
w = {g: (s[g]["en"]["err_median"] if s[g]["en"]["err_median"] is not None else 1.0) for g in s}
# Her own GPT carries her Japanese rhythm into English: keep it unless the pretrained one reads
# clearly better (median WER lower by more than 0.03).
choice = forced or ("base" if w["base"] + 0.03 < w["her"] else "her")
for g in s:
    e, m = s[g]["en"], s[g]["mixed"]
    print(f"{g}: kept {s[g]['kept']}/60, English WER median {e['err_median']}, mean {e['err_mean']}, "
          f"pitch median {e['p50_median']}, timbre {e['sim_median']}; mixed err median {m['err_median']}")
print("choice:", choice, "(forced)" if forced else "")
open(f"{p}/choice.txt", "w").write(choice + "\n")
PY
  step STAGE1-LANG-DONE
  exit 0
fi

# --- full
CHOICE=${GPT_CHOICE:-$(cat $OL/pilot/choice.txt 2>/dev/null || echo her)}
GPT=$G_HER; [ "$CHOICE" = base ] && GPT=$G_BASE
echo "teacher GPT: $CHOICE ($GPT), SoVITS $S2" | tee $OL/teacher.txt
step "take A"
speak_set $GPT $LANG_IN/speak_lang.txt $OL/raw/A 1234 0 8
step "take B (other seed, next reference)"
speak_set $GPT $LANG_IN/speak_lang.txt $OL/raw/B 9876 1 8
step checks
rm -rf $OL/ds_lang
check_set $LANG_IN/lines_lang.tsv $OL/raw $OL/work $OL/ds_lang | tee $OL/summary.txt
step STAGE1-LANG-DONE
