"""Her breaths, cut from her voice actress's own recordings, for her breathing between phrases.

Why: the owner heard her teacher voice breathe "labored, forced, unnatural". What the teacher puts around a
sentence is a dark rumble and a short hum, not breath. Her real recordings show how she breathes: quick,
quiet catches through the mouth, bright (most energy 1.5-3.5 kHz), about 25-35 dB below her speech, and
often no audible breath at all. These are the breaths she takes on record:

  name   source        seconds        what it is
  catch  yume_07.wav   2.900-3.160    a quick catch of about 0.1 s and its fade, ~-30 dB (3.4 s of speech followed)
  soft   v12_040.wav   2.730-3.010    the slow, darker start of a fuller breath, ~-24 dB
  quick  v12_040.wav   3.050-3.360    the fast, brighter end of that breath, ~-23 dB
  deep   v12_040.wav   2.715-3.360    the whole fuller breath, about 0.65 s

Each is cut from its clip, the clip's own room noise is taken out (spectral subtraction against its
quietest 300 ms), it is resampled to --sr, and its level is stored against her speech level in the same
clip (95th percentile of 25 ms frame levels), so breathe.py can place it as loud as she would make it.

Never commit the output: it is her actress's voice (private, like own_voice).

Usage: python breath_bank.py --clips DIR_WITH_HER_WAVS --out DIR [--sr 32000]
Writes DIR/<name>.wav (float32 mono) and DIR/bank.json.
"""
import argparse
import json
import os
import sys

import numpy as np
import soundfile as sf
from scipy.signal import istft, resample_poly, stft

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "pod"))
from edges import features  # noqa: E402

BREATHS = [
    ("catch", "yume_07.wav", 2.900, 3.160),
    ("soft", "v12_040.wav", 2.730, 3.010),
    ("quick", "v12_040.wav", 3.050, 3.360),
    ("deep", "v12_040.wav", 2.715, 3.360),
]


def quietest(x, sr, win=0.3):
    lv = features(x, sr)[0]
    k = int(win * 100)
    sm = np.convolve(lv, np.ones(k) / k, mode="valid")
    i = int(np.argmin(sm))
    return x[int(i * 0.01 * sr):int((i * 0.01 + win) * sr)]


def denoise(seg, noise, sr):
    n = 1024 if sr > 30000 else 512
    _, _, S = stft(seg, sr, nperseg=n)
    _, _, N = stft(noise, sr, nperseg=n)
    nm = np.mean(np.abs(N), axis=1, keepdims=True)
    mag = np.abs(S)
    clean = np.maximum(mag - nm, 0.15 * mag)
    _, y = istft(clean * np.exp(1j * np.angle(S)), sr, nperseg=n)
    return y[:len(seg)].astype(np.float32)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--sr", type=int, default=32000)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    meta = {"sr": args.sr, "breaths": {}}
    for name, clip, a, b in BREATHS:
        x, sr = sf.read(os.path.join(args.clips, clip), dtype="float32")
        if x.ndim > 1:
            x = x.mean(1)
        speech = np.percentile(features(x, sr)[0], 95)
        seg = denoise(x[int(a * sr):int(b * sr)], quietest(x, sr), sr)
        g = np.gcd(sr, args.sr)
        y = resample_poly(seg, args.sr // g, sr // g).astype(np.float32)
        lv = features(y, args.sr)[0]
        sf.write(os.path.join(args.out, f"{name}.wav"), y, args.sr, subtype="FLOAT")
        meta["breaths"][name] = {
            "source": clip, "from": a, "to": b, "seconds": round(len(y) / args.sr, 3),
            # Level of the breath (90th percentile of its frames) against her speech in the same clip.
            "level_re_speech_db": round(float(np.percentile(lv, 90) - speech), 1),
        }
        print(f"{name}: {clip} {a:.3f}-{b:.3f}s, {len(y) / args.sr:.2f}s, "
              f"{meta['breaths'][name]['level_re_speech_db']} dB re her speech")
    with open(os.path.join(args.out, "bank.json"), "w") as f:
        json.dump(meta, f, indent=1)


if __name__ == "__main__":
    sys.exit(main())
