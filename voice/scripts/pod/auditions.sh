#!/usr/bin/env bash
# Mood auditions on CPU: each candidate reference reads the same 5 lines; brightened like her chosen voice;
# one file per mood, candidates A-D in order with a gap between them. Median pitch is logged per candidate.
set -uo pipefail
source /w/job/scripts/env.sh
cd $R
O=$J/out/aud; mkdir -p $O
S2=$(ls SoVITS_weights_v2ProPlus/y71_e12_*.pth); G1=GPT_weights_v2ProPlus/y52-e10.ckpt
run_one() {
  style=$1; cand=$2; clip=$3; text=$4
  d=$O/$style/$cand; mkdir -p $d
  CUDA_VISIBLE_DEVICES="" python $J/scripts/speak.py --device cpu --gpt $G1 --sovits $S2 --out $d \
     --ref $J/data/wavs/$clip.wav --ref-text "$text" --lines $J/out/aud_lines.txt --speed 1.08 --temperature 1.1 --top-k 25 > $d.log 2>&1
  fr=1.04; [ "$style" = mock_high ] && fr=1.0
  for w in $d/0???.wav; do [ -f "$w" ] || continue; python $J/scripts/younger.py $w ${w%.wav}_b.wav --semitones 1.0 --formant $fr; done
  echo "done $style $cand"
}
export -f run_one; export O J R S2 G1
N=0
while IFS=$'\t' read -r style cand clip text; do
  run_one "$style" "$cand" "$clip" "$text" &
  N=$((N+1)); if [ $((N % 3)) -eq 0 ]; then wait; fi
done < $J/out/aud_refs.tsv
wait
python - <<PY
import glob, numpy as np, soundfile as sf, pyworld as pw, os
O="$O"
for style in sorted(os.listdir(O)):
    if not os.path.isdir(f"{O}/{style}"): continue
    parts=[]; sr=None
    for cand in "ABCD":
        files=sorted(glob.glob(f"{O}/{style}/{cand}/0*_b.wav"))
        f0s=[]
        for f in files:
            x, sr = sf.read(f, dtype="float64")
            f0,t = pw.harvest(x, sr, f0_floor=70, f0_ceil=800); f0=f0[f0>0]
            if len(f0): f0s.append(f0)
            parts += [x.astype(np.float32), np.zeros(int(sr*0.35), dtype=np.float32)]
        allf=np.concatenate(f0s) if f0s else np.array([0.0])
        print(f"{style} {cand}: median {np.median(allf):.0f} Hz, p90 {np.percentile(allf,90):.0f} Hz, {len(files)} lines")
        parts.append(np.zeros(int(sr*1.5), dtype=np.float32))
    sf.write(f"{O}/audition_{style}.wav", np.concatenate(parts), sr, subtype="PCM_16")
PY
echo AUDITIONS-DONE
