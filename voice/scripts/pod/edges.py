"""Where her speech really starts and ends in a teacher take, and nothing around it.

Why: the owner heard "heavy breathing or snorting" at the start and end of her lines and in the pauses,
"labored, forced" breath. Measured on the teacher's sentences, that is not breath. Her real recordings
(yume_07, v12_040) breathe in short and quiet: about -30 to -35 dB below her speech and bright (most energy
1.5-3 kHz), and mostly they don't make an audible breath at all. The teacher puts other sounds there:
  - a low rumble (most energy 100-700 Hz, not voiced) from about -28 to -36 dB, up to 0.8 s before a
    sentence and after one: it sounds like heavy nose breathing;
  - a short voiced "hmph" (80-120 ms, low, up to about -16 dB) after a dip at the end of a sentence:
    the snort.
The earlier trims kept everything within 30-32 dB of her speech, so they kept both.

What counts as her speech here, frame by frame (10 ms steps, 25 ms windows):
  - voiced (normalised autocorrelation peak >= 0.55 at 80-400 Hz) and within 32 dB of her speech level
    (95th percentile); or
  - a consonant: bright (spectral centroid > 1.5 kHz) and within 30 dB (start) or 32 dB (end), so an
    "s", "h" or a released "t" stays and the rumble does not.
The span runs from the first to the last strong frame (within 15 dB of her speech), grown outward over
frames that count as speech, allowing 2 (start) or 3 (end) frames that don't (the closure of an "st"),
at most 250 ms before and 400 ms after. A short, low, voiced blob after a dip at either end (under
120 ms within 22 dB, a 60 ms dip below 27 dB, centroid under 700 Hz) is the snort, and the span stops
before it. Inside the span, a stretch of 100 ms or more that is not speech, quiet (27 dB down) and
dark (centroid under 900 Hz) is rumble in a comma pause and is lowered by 20 dB.
The kept span starts 10 ms early with a 10 ms fade in, and ends 50 ms late with a 60 ms fade out, so
her endings decay as they were spoken.

Library: span(x, sr) -> (start, end) samples; clean(x, sr) -> trimmed audio.
Command line: python edges.py --dir SRC DST [--shard i/n]
  For lines joined by speak_checked.py (sentences separated by runs of exact silence, 0.15 s or longer):
  every sentence is cleaned on its own and the line is joined again with the same pauses.
"""
import argparse
import os
import sys

import numpy as np


def features(x, sr, hop=0.01, win=0.025):
    """Per frame: level (dB), spectral centroid (Hz), share above 4 kHz, voicing (0-1)."""
    h, w = int(hop * sr), int(win * sr)
    x = np.asarray(x, np.float64)
    if len(x) < w:
        x = np.pad(x, (0, w - len(x)))
    n = 1 + (len(x) - w) // h
    idx = np.arange(w)[None, :] + h * np.arange(n)[:, None]
    f = x[idx] * np.hanning(w)
    nfft = 1 << int(np.ceil(np.log2(2 * w)))
    p = np.abs(np.fft.rfft(f, nfft, axis=1)) ** 2
    fr = np.fft.rfftfreq(nfft, 1 / sr)
    tot = p.sum(1) + 1e-20
    lv = 10 * np.log10(tot / (w * nfft) + 1e-12)
    cen = (p * fr).sum(1) / tot
    hf = p[:, fr > 4000].sum(1) / tot
    ac = np.fft.irfft(p, nfft, axis=1)[:, :w]
    ac = ac / (ac[:, :1] + 1e-20)
    lo, hi = int(sr / 400), int(sr / 80)
    voi = ac[:, lo:hi].max(1).clip(0, 1)
    return lv, cen, hf, voi


def _runs(mask):
    out, i, n = [], 0, len(mask)
    while i < n:
        if mask[i]:
            j = i
            while j + 1 < n and mask[j + 1]:
                j += 1
            out.append((i, j))
            i = j + 1
        else:
            i += 1
    return out


def _frames(x, sr):
    lv, cen, hf, voi = features(x, sr)
    if len(lv) < 3:
        return None
    sp = np.percentile(lv, 95)
    strong = lv > sp - 15
    if not strong.any():
        return None

    def speech(i, start):
        return (voi[i] >= 0.55 and lv[i] > sp - 32) or (cen[i] > 1500 and lv[i] > sp - (30 if start else 32))

    # Sound that is not a dark, quiet stretch: speech, consonants and anything within 20 dB.
    act = np.array([speech(k, False) or lv[k] > sp - 20 for k in range(len(lv))])
    clusters = []
    for r in _runs(act):
        if clusters and r[0] - clusters[-1][1] <= 5:
            clusters[-1] = (clusters[-1][0], r[1])
        else:
            clusters.append(r)
    clusters = [c for c in clusters if lv[c[0]:c[1] + 1].max() > sp - 22]

    def snort(c):
        """A short, low hum (the teacher's snort): at most 120 ms within 22 dB, centroid under 400 Hz."""
        loud = lv[c[0]:c[1] + 1] > sp - 22
        return loud.sum() <= 12 and np.mean(cen[c[0]:c[1] + 1][loud]) < 400

    stop = len(lv) - 1
    while len(clusters) > 1 and clusters[-1][0] - clusters[-2][1] > 6 and snort(clusters[-1]):
        stop = clusters.pop()[0] - 1
    if not clusters:
        return None
    first = int(np.argmax(strong))
    seg = strong[:clusters[-1][1] + 1]
    last = len(seg) - 1 - int(np.argmax(seg[::-1])) if seg.any() else clusters[-1][1]
    # Start: grow back over speech (2 frames' grace), then over a breathy attack within 20 dB (40 ms).
    a, miss, i = first, 0, first - 1
    while i >= max(0, first - 25):
        if speech(i, True):
            a, miss = i, 0
        else:
            miss += 1
            if miss > 2:
                break
        i -= 1
    k = 0
    while a - 1 >= 0 and k < 4 and lv[a - 1] > sp - 20:
        a, k = a - 1, k + 1
    # End: grow forward over speech (3 frames' grace: the closure in "st"), never into a snort.
    b, miss, i = last, 0, last + 1
    while i <= min(stop, last + 40):
        if speech(i, False):
            b, miss = i, 0
        else:
            miss += 1
            if miss > 3:
                break
        i += 1
    rumble = []
    quiet = np.array([not speech(k, False) and lv[k] < sp - 27 and cen[k] < 900 for k in range(len(lv))])
    for r0, r1 in _runs(quiet[a:b + 1]):
        if r1 - r0 + 1 >= 10:
            rumble.append((a + r0, a + r1))
    return a, b, rumble


def span(x, sr):
    """(start, end) in samples of her speech in one sentence take; the whole take if none is found."""
    fr = _frames(x, sr)
    if fr is None:
        return 0, len(x)
    a, b, _ = fr
    h, w = int(0.01 * sr), int(0.025 * sr)
    return max(0, a * h - int(0.01 * sr)), min(len(x), b * h + w + int(0.05 * sr))


def clean(x, sr):
    """One sentence take with only her speech: trimmed, faded, comma-pause rumble lowered."""
    x = np.asarray(x, np.float32)
    fr = _frames(x, sr)
    if fr is None:
        return x.copy()
    a, b, rumble = fr
    h, w = int(0.01 * sr), int(0.025 * sr)
    y = x.copy()
    ramp = int(0.015 * sr)
    for r0, r1 in rumble:
        s0, s1 = r0 * h + w // 2, r1 * h + w // 2
        g = np.ones(len(y), np.float32)
        g[s0:s1] = 0.1
        g[max(0, s0 - ramp):s0] = np.linspace(1, 0.1, s0 - max(0, s0 - ramp))
        g[s1:min(len(y), s1 + ramp)] = np.linspace(0.1, 1, min(len(y), s1 + ramp) - s1)
        y *= g
    s, e = max(0, a * h - int(0.01 * sr)), min(len(y), b * h + w + int(0.05 * sr))
    y = y[s:e].copy()
    k_in, k_out = min(len(y) // 2, int(0.01 * sr)), min(len(y) // 2, int(0.06 * sr))
    if k_in:
        y[:k_in] *= np.sin(np.linspace(0, np.pi / 2, k_in)) ** 2
    if k_out:
        y[-k_out:] *= np.cos(np.linspace(0, np.pi / 2, k_out)) ** 2
    return y


def split_joined(x, sr, min_gap=0.15):
    """Sentences of a speak_checked.py line and the pauses between them (runs of exact zeros)."""
    z = x == 0
    gaps = [(a, b) for a, b in _runs(z) if b - a + 1 >= int(min_gap * sr)]
    pieces, pauses, pos = [], [], 0
    for a, b in gaps:
        if a > pos:
            pieces.append(x[pos:a]); pauses.append(b - a + 1)
        pos = b + 1
    if pos < len(x):
        pieces.append(x[pos:])
    if pieces and len(pauses) >= len(pieces):
        pauses = pauses[:len(pieces) - 1]
    return pieces, pauses


def clean_line(x, sr):
    pieces, pauses = split_joined(x, sr)
    if not pieces:
        return x
    out = []
    for k, p in enumerate(pieces):
        out.append(clean(p, sr))
        if k < len(pauses):
            out.append(np.zeros(pauses[k], np.float32))
    return np.concatenate(out)


def main():
    import soundfile as sf
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", nargs=2, metavar=("SRC", "DST"), required=True)
    ap.add_argument("--shard", default="0/1")
    args = ap.parse_args()
    si, sn = (int(v) for v in args.shard.split("/"))
    src, dst = args.dir
    os.makedirs(dst, exist_ok=True)
    names = sorted(f for f in os.listdir(src) if f.endswith(".wav"))
    done = 0
    for n, f in enumerate(names):
        if n % sn != si:
            continue
        x, sr = sf.read(os.path.join(src, f), dtype="float32")
        if x.ndim > 1:
            x = x.mean(1)
        sf.write(os.path.join(dst, f), clean_line(x, sr), sr, subtype="PCM_16")
        done += 1
    print(f"edges: cleaned {done} lines from {src} into {dst}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
