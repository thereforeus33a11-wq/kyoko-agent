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

    def speech(i, start):
        # Voiced, or a bright consonant, or loud enough to be her even when breathy (a whispered
        # "いや" is not voiced, and is 10-18 dB under her speech; the rumble stays 21 dB or more under).
        return (voi[i] >= 0.55 and lv[i] > sp - 32) or (cen[i] > 1500 and lv[i] > sp - (30 if start else 32)) \
            or lv[i] > sp - 18

    # Her words: runs of speech frames (30 ms gaps bridged) at least 60 ms long that reach within
    # 25 dB of her speech level. A soft first word ("my", "no", "which") is one; the rumble is not
    # (not voiced, dark).
    sp_mask = np.array([speech(k, False) for k in range(len(lv))])
    runs = []
    for r in _runs(sp_mask):
        if runs and r[0] - runs[-1][1] <= 3:
            runs[-1] = (runs[-1][0], r[1])
        else:
            runs.append(r)
    words = [r for r in runs if r[1] - r[0] + 1 >= 6 and lv[r[0]:r[1] + 1].max() > sp - 25]
    if not words:
        return None

    def snort(c):
        """A short, low hum (the teacher's snort): at most 120 ms within 22 dB, centroid under 400 Hz."""
        loud = lv[c[0]:c[1] + 1] > sp - 22
        return loud.sum() <= 12 and loud.any() and np.mean(cen[c[0]:c[1] + 1][loud]) < 400

    stop = len(lv) - 1
    while len(words) > 1 and words[-1][0] - words[-2][1] > 6 and snort(words[-1]):
        stop = words.pop()[0] - 1
    # Start: the first word, grown back over a consonant onset: an "s", "sh" or "f" (bright, above
    # 3 kHz, within 38 dB) for up to 200 ms, an "h" or aspiration (1.5-3 kHz, within 30 dB) or a
    # breathy attack (within 20 dB) for up to 100 ms, with one frame's grace.
    a, i, miss, n_fric, n_asp = words[0][0], words[0][0] - 1, 0, 0, 0
    while i >= 0:
        if cen[i] > 3000 and lv[i] > sp - 38 and n_fric < 20:
            a, miss, n_fric = i, 0, n_fric + 1
        elif (cen[i] > 1500 and lv[i] > sp - 30 or lv[i] > sp - 20) and n_asp < 10:
            a, miss, n_asp = i, 0, n_asp + 1
        else:
            miss += 1
            if miss > 1:
                break
        i -= 1
    # End: the last word, grown forward over her voice's decay (voiced, within 38 dB), a final
    # "s" (bright, above 3 kHz, within 38 dB), a released "t" or "k" (1.5-3 kHz, within 32 dB), and
    # the breathy release of a final consonant, whatever its colour, while it stays within 24 dB
    # (the dark tail after "back", "work" or "drink" is part of the word: without it a listener
    # hears "bat"), with 3 frames' grace (the closure in "st"), at most 400 ms, never into a snort.
    b, i, miss = words[-1][1], words[-1][1] + 1, 0
    while i <= min(stop, words[-1][1] + 40):
        if (voi[i] >= 0.5 and lv[i] > sp - 38) or (cen[i] > 3000 and lv[i] > sp - 38) \
                or (cen[i] > 1500 and lv[i] > sp - 32) or lv[i] > sp - 24:
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
