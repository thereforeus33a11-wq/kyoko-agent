"""Brighten a voice toward a younger adult: small pitch raise + small formant raise (WORLD vocoder).
Usage: python younger.py in.wav out.wav --semitones 1.0 --formant 1.04
Kept deliberately small: a young adult woman, never a child's range.
"""
import argparse, numpy as np, soundfile as sf, pyworld as pw

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp"); ap.add_argument("out")
    ap.add_argument("--semitones", type=float, default=1.0)
    ap.add_argument("--formant", type=float, default=1.04)
    a = ap.parse_args()
    # Hard limits: stay in an adult voice.
    st = max(-3.0, min(2.0, a.semitones)); fr = max(0.95, min(1.08, a.formant))
    x, sr = sf.read(a.inp, dtype="float64")
    if x.ndim > 1: x = x.mean(axis=1)
    f0, t = pw.harvest(x, sr, f0_floor=70, f0_ceil=700)
    sp = pw.cheaptrick(x, f0, t, sr); ap_ = pw.d4c(x, f0, t, sr)
    f0 = f0 * (2 ** (st / 12))
    # Formant raise: read the envelope at f/fr, so its peaks move up by fr.
    bins = sp.shape[1]; idx = np.arange(bins) / fr
    lo = np.floor(idx).astype(int).clip(0, bins - 1); hi = (lo + 1).clip(0, bins - 1); w = idx - np.floor(idx)
    sp2 = sp[:, lo] * (1 - w) + sp[:, hi] * w
    y = pw.synthesize(np.ascontiguousarray(f0), np.ascontiguousarray(sp2), np.ascontiguousarray(ap_), sr)
    y = y / max(1e-9, np.abs(y).max()) * min(0.95, np.abs(x).max() * 1.0 + 1e-9)
    sf.write(a.out, y.astype(np.float32), sr, subtype="PCM_16")

if __name__ == "__main__":
    main()
