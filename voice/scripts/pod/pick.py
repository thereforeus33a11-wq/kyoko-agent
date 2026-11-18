"""Score each trained checkpoint pair by how clearly it says unseen lines (Japanese ASR, CER by reading).
Usage: python pick.py <eval lines> <dir with one subdir per pair> -> prints a table, writes choice.json"""
import glob, json, os, sys
import numpy as np, soundfile as sf
import check_distill as cd

class A: asr_dir = "/w/sherpa-onnx-zipformer-ja-reazonspeech-2024-08-01"
cd.init(A)
lines = [l.rstrip("\n").partition("|")[2] for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
rows = []
for d in sorted(glob.glob(os.path.join(sys.argv[2], "*/"))):
    errs, durs = [], []
    for n, text in enumerate(lines):
        p = os.path.join(d, f"{n:04d}.wav")
        if not os.path.exists(p):
            errs.append(1.0); continue
        x, sr = sf.read(p, dtype="float32")
        x = x.mean(axis=1) if x.ndim > 1 else x
        s = cd.REC.create_stream(); s.accept_waveform(sr, x); cd.REC.decode_stream(s)
        errs.append(min(1.0, cd.cer(cd.reading(text), cd.reading(s.result.text)))); durs.append(len(x) / sr)
    rows.append((float(np.mean(errs)), float(np.mean([e > 0.25 for e in errs])), os.path.basename(d.rstrip("/"))))
    print(f"{rows[-1][2]}\tmean CER {rows[-1][0]:.3f}\tbad lines {rows[-1][1]:.0%}\tavg {np.mean(durs) if durs else 0:.1f}s", flush=True)
best = min(rows)
json.dump({"pair": best[2], "cer": best[0], "all": rows}, open(os.path.join(sys.argv[2], "choice.json"), "w"))
print("BEST", best[2])
