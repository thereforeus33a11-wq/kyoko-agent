"""Check what Piper's silence trim (Silero VAD, threshold 0.2, 0.25 s kept each side) took from each clip it
cached: a trim that cuts into sound (a whispered word the VAD does not call speech, a yelled tail) would train
the voice on audio that no longer says its text.
Usage: python trim_check.py <metadata.csv> <wavs dir> <cache dir> <voice config .onnx.json> [--out report.tsv]
Per clip: seconds kept against the wav, and seconds of sound cut at the start and at the end, where sound is a
20 ms frame within 45 dB of the clip's loudest frame and above -60 dBFS. Summary per speaker."""
import argparse
import json
import os

import numpy as np
import soundfile as sf
import torch
from piper.train.vits.utils import get_cache_id

ap = argparse.ArgumentParser()
ap.add_argument("csv")
ap.add_argument("wavs")
ap.add_argument("cache")
ap.add_argument("config")
ap.add_argument("--out", default=None)
ap.add_argument("--cut", type=float, default=0.05, help="seconds of sound cut that count as a cut into sound")
a = ap.parse_args()
cfg = json.load(open(a.config, encoding="utf-8"))
spk = cfg.get("speaker_id_map") or {}
multi = int(cfg.get("num_speakers", 1)) > 1
rows, summary = [], {}
for row_number, line in enumerate(open(a.csv, encoding="utf-8"), start=1):
    r = line.rstrip("\n").split("|")
    name, text = r[0], r[-1]
    sid = spk[r[1]] if multi else None
    p = os.path.join(a.cache, f"{get_cache_id(row_number, text, speaker_id=sid)}.audio.pt")
    if not os.path.exists(p):
        continue
    kept = torch.load(p).numpy()
    x, sr = sf.read(os.path.join(a.wavs, name), dtype="float32")
    if x.ndim > 1:
        x = x.mean(1)
    n = len(kept)
    start = 0
    if n < len(x):  # the cached audio is x[start:start + n]: find start by the samples around its loudest one
        m = int(np.argmax(np.abs(kept)))
        lo, hi = max(0, m - 128), min(n, m + 128)
        cand = np.flatnonzero(np.abs(x - kept[m]) <= 1e-7) - m
        cand = [int(c) for c in cand if 0 <= c <= len(x) - n]
        start = next((c for c in cand if np.allclose(x[c + lo:c + hi], kept[lo:hi], atol=1e-6)), -1)
    hop = int(0.02 * sr)
    fr = np.array([np.sqrt(np.mean(x[i:i + hop] ** 2) + 1e-12) for i in range(0, max(1, len(x) - hop), hop)])
    db = 20 * np.log10(fr)
    act = np.flatnonzero((db > db.max() - 45) & (db > -60))
    s0, s1 = (act[0] * hop / sr, (act[-1] + 1) * hop / sr) if len(act) else (0.0, 0.0)
    if start < 0:
        cut0 = cut1 = float("nan")
    else:
        k0, k1 = start / sr, (start + n) / sr
        cut0, cut1 = max(0.0, k0 - s0), max(0.0, s1 - k1)
    key = r[1] if multi else "-"
    rows.append((key, name, len(x) / sr, n / sr, cut0, cut1))
    s = summary.setdefault(key, {"clips": 0, "seconds_wav": 0.0, "seconds_kept": 0.0, "unmatched": 0,
                                 "cut_into_sound": 0, "worst": []})
    s["clips"] += 1
    s["seconds_wav"] += len(x) / sr
    s["seconds_kept"] += n / sr
    if start < 0:
        s["unmatched"] += 1
    elif max(cut0, cut1) > a.cut:
        s["cut_into_sound"] += 1
        s["worst"].append((round(max(cut0, cut1), 3), name))
for s in summary.values():
    s["worst"] = sorted(s["worst"], reverse=True)[:8]
    s["kept_share"] = round(s["seconds_kept"] / max(1e-9, s["seconds_wav"]), 4)
    s["seconds_wav"] = round(s["seconds_wav"], 1)
    s["seconds_kept"] = round(s["seconds_kept"], 1)
if a.out:
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("speaker\tname\twav_s\tkept_s\tsound_cut_start_s\tsound_cut_end_s\n")
        for row in rows:
            f.write("\t".join(str(round(v, 3)) if isinstance(v, float) else v for v in row) + "\n")
print(json.dumps(summary, indent=1))
