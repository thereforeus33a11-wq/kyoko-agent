"""Trim each take to its words: faster-whisper word timings, a short breath of room kept on each side
(60 ms before the first word, 150 ms after the last), 10 ms fades. The teacher tends to add an inhale
before a line and a trailing breath after it; this cuts them.

Usage (asr env): python trim_words.py <whisper model dir> <src dir> <dst dir> [--shard i/n]
"""
import argparse, glob, os
import numpy as np, soundfile as sf
from faster_whisper import WhisperModel

ap = argparse.ArgumentParser()
ap.add_argument("model"); ap.add_argument("src"); ap.add_argument("dst"); ap.add_argument("--shard", default="0/1")
a = ap.parse_args()
i, n = map(int, a.shard.split("/"))
m = WhisperModel(a.model, device="cuda", compute_type="float16")
os.makedirs(a.dst, exist_ok=True)
files = sorted(glob.glob(os.path.join(a.src, "[0-9]*.wav")))[i::n]
for f in files:
    out = os.path.join(a.dst, os.path.basename(f))
    if os.path.exists(out):
        continue
    x, sr = sf.read(f, dtype="float32")
    if x.ndim > 1:
        x = x.mean(axis=1)
    try:
        segs, info = m.transcribe(f, word_timestamps=True, vad_filter=False, beam_size=5)
        words = [w for s in segs for w in (s.words or [])]
    except Exception:
        words = []
    if words:
        s0 = max(0.0, words[0].start - 0.06); s1 = min(len(x) / sr, words[-1].end + 0.15)
        x = x[int(s0 * sr):int(s1 * sr)]
    k = min(len(x) // 2, int(0.01 * sr))
    if k > 0:
        x[:k] *= np.linspace(0, 1, k); x[-k:] *= np.linspace(1, 0, k)
    sf.write(out, x, sr, subtype="PCM_16")
print(f"trimmed {len(files)} takes in {a.src} (shard {a.shard})")
