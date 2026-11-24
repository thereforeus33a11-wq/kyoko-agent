"""Widen Piper's silence trim for the style clips so it never cuts into sound, in the cache Piper trains from.
Piper trims each clip to the span its VAD (Silero, threshold 0.2) calls speech, plus 0.25 s each side. On a
whisper (no voicing) and on some soft and yelled tails the VAD misses words, and the cached clip then no longer
says its text. For every row of the given speakers, the kept span becomes the VAD span united with the clip's
sound span (20 ms frames within 45 dB of its loudest frame and above -60 dBFS) plus 0.25 s each side, never past
the file. A clip the VAD did not cut into is left exactly as Piper cached it. The audio and spectrogram are
rewritten the way Piper writes them (spectrogram_torch, same settings); the phoneme ids are not touched.
Usage: python style_trim_fix.py <metadata.csv> <wavs dir> <cache dir> <voice config .onnx.json> --speakers soft whisper loud yell
       [--out changed.tsv] [--dry]"""
import argparse
import json
import os

import numpy as np
import soundfile as sf
import torch
from piper.train.vits.mel_processing import spectrogram_torch
from piper.train.vits.utils import get_cache_id

ap = argparse.ArgumentParser()
ap.add_argument("csv")
ap.add_argument("wavs")
ap.add_argument("cache")
ap.add_argument("config")
ap.add_argument("--speakers", nargs="+", required=True)
ap.add_argument("--keep", type=float, default=0.25)
ap.add_argument("--out", default=None)
ap.add_argument("--dry", action="store_true")
a = ap.parse_args()
cfg = json.load(open(a.config, encoding="utf-8"))
spk = cfg["speaker_id_map"]
changed, seen = [], {}
for row_number, line in enumerate(open(a.csv, encoding="utf-8"), start=1):
    r = line.rstrip("\n").split("|")
    name, speaker, text = r[0], r[1], r[-1]
    if speaker not in a.speakers:
        continue
    cid = get_cache_id(row_number, text, speaker_id=spk[speaker])
    pa, ps = os.path.join(a.cache, f"{cid}.audio.pt"), os.path.join(a.cache, f"{cid}.spec.pt")
    kept = torch.load(pa).numpy()
    x, sr = sf.read(os.path.join(a.wavs, name), dtype="float32")
    assert sr == 22050 and x.ndim == 1, name
    n = len(kept)
    start = 0
    if n < len(x):
        m = int(np.argmax(np.abs(kept)))
        lo, hi = max(0, m - 128), min(n, m + 128)
        cand = [int(c) for c in np.flatnonzero(np.abs(x - kept[m]) <= 1e-7) - m if 0 <= c <= len(x) - n]
        start = next((c for c in cand if np.allclose(x[c + lo:c + hi], kept[lo:hi], atol=1e-6)), -1)
        assert start >= 0, f"{name}: cached audio not found in the wav"
    hop = int(0.02 * sr)
    db = 20 * np.log10(np.array([np.sqrt(np.mean(x[i:i + hop] ** 2) + 1e-12) for i in range(0, max(1, len(x) - hop), hop)]))
    act = np.flatnonzero((db > db.max() - 45) & (db > -60))
    if not seen:  # this script writes spectrograms exactly as Piper does: check on the first clip
        again = spectrogram_torch(y=torch.FloatTensor(kept).unsqueeze(0), n_fft=1024, sampling_rate=22050,
                                  hop_size=256, win_size=1024, center=False).squeeze(0)
        assert torch.equal(again, torch.load(ps)), "spectrogram differs from Piper's cached one"
    seen[speaker] = seen.get(speaker, 0) + 1
    if not len(act):
        continue
    s0, s1 = act[0] * hop, (act[-1] + 1) * hop
    new0 = min(start, max(0, s0 - int(a.keep * sr)))
    new1 = max(start + n, min(len(x), s1 + int(a.keep * sr)))
    if (new0, new1) == (start, start + n):
        continue
    changed.append((speaker, name, round(len(x) / sr, 3), round(n / sr, 3), round((new1 - new0) / sr, 3),
                    round((start - new0) / sr, 3), round((new1 - start - n) / sr, 3)))
    if not a.dry:
        audio = torch.FloatTensor(x[new0:new1].copy())
        torch.save(audio, pa)
        torch.save(spectrogram_torch(y=audio.unsqueeze(0), n_fft=1024, sampling_rate=22050, hop_size=256,
                                     win_size=1024, center=False).squeeze(0), ps)
if a.out:
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("speaker\tname\twav_s\tpiper_kept_s\tnew_kept_s\tadded_at_start_s\tadded_at_end_s\n")
        for c in changed:
            f.write("\t".join(map(str, c)) + "\n")
summary = {s: {"clips": seen.get(s, 0), "widened": sum(1 for c in changed if c[0] == s),
               "seconds_added": round(sum(c[5] + c[6] for c in changed if c[0] == s), 1)} for s in a.speakers}
print(json.dumps({"dry": a.dry, "per_speaker": summary}, indent=1))
