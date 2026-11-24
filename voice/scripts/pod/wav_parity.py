"""Compare the waveforms two runs of phone_test_lang.py wrote, line by line.
Usage: python wav_parity.py <dir A> <dir B> [--json out.json] [--tol 1e-4]
Per line: same length or not, max |A-B|, RMS of A-B against RMS of A (dB), bit-identical or not. "same" means
every line has the same length and max |A-B| <= tol (float error; a 16-bit sample step is 3.1e-5)."""
import argparse
import glob
import json
import os

import numpy as np
import soundfile as sf

ap = argparse.ArgumentParser()
ap.add_argument("a")
ap.add_argument("b")
ap.add_argument("--json", default=None)
ap.add_argument("--tol", type=float, default=1e-4)
a = ap.parse_args()
rows = []
for pa in sorted(glob.glob(os.path.join(a.a, "*.wav"))):
    pb = os.path.join(a.b, os.path.basename(pa))
    x, _ = sf.read(pa, dtype="float32")
    y, _ = sf.read(pb, dtype="float32")
    same_len = len(x) == len(y)
    n = min(len(x), len(y))
    d = x[:n] - y[:n]
    rms_a = float(np.sqrt(np.mean(x[:n] ** 2)) + 1e-12)
    rms_d = float(np.sqrt(np.mean(d ** 2)))
    rows.append(dict(line=os.path.basename(pa), len_a=len(x), len_b=len(y), same_len=same_len,
                     max_abs=float(np.max(np.abs(d))) if n else 0.0,
                     diff_db=round(20 * np.log10(rms_d / rms_a), 1) if rms_d > 0 else None,
                     identical=bool(same_len and np.array_equal(x, y))))
same = all(r["same_len"] and r["max_abs"] <= a.tol for r in rows) and bool(rows)
out = dict(a=a.a, b=a.b, lines=len(rows), same=same, tol=a.tol,
           identical_lines=sum(r["identical"] for r in rows), same_length_lines=sum(r["same_len"] for r in rows),
           max_abs=max((r["max_abs"] for r in rows), default=None), per_line=rows)
if a.json:
    json.dump(out, open(a.json, "w"), indent=1)
print(json.dumps({k: v for k, v in out.items() if k != "per_line"}))
for r in rows:
    print(f"  {r['line']}  len {r['len_a']}/{r['len_b']}  max|A-B| {r['max_abs']:.3g}  diff {r['diff_db']} dB  identical {r['identical']}")
