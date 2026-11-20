"""Trim each take to her speech. The start: 80 ms before the first word (faster-whisper's word start is
reliable). The end: NOT whisper's word end, which comes early and clipped the ends of her words; instead
the last 10 ms frame within 0.8 s after it whose level is no more than END_DB below the line's speech level
(so soft and devoiced endings like a whispered "-su" stay), plus 120 ms of room and an 80 ms fade out.
The teacher tends to add an inhale before a line and a trailing breath after it; this cuts most of them.

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
    END_DB = 32.0
    if words:
        fr = int(0.01 * sr); nfr = len(x) // fr
        lv = 20 * np.log10(np.sqrt(np.mean(x[:nfr * fr].reshape(nfr, fr) ** 2, axis=1)) + 1e-9)
        speech = np.percentile(lv, 95)
        s0 = max(0.0, words[0].start - 0.08)
        w_end = int(words[-1].end * 100); look = min(nfr, w_end + 80)
        loud = [i for i in range(max(0, w_end - 30), look) if lv[i] >= speech - END_DB]
        end_f = (loud[-1] + 1) if loud else w_end
        s1 = min(len(x) / sr, end_f / 100 + 0.12)
        x = x[int(s0 * sr):int(s1 * sr)]
    k = min(len(x) // 2, int(0.01 * sr)); kout = min(len(x) // 2, int(0.08 * sr))
    if k > 0:
        x[:k] *= np.linspace(0, 1, k)
    if kout > 0:
        x[-kout:] *= np.linspace(1, 0, kout) ** 2
    sf.write(out, x, sr, subtype="PCM_16")
print(f"trimmed {len(files)} takes in {a.src} (shard {a.shard})")
