"""Her breathing between phrases: her own breaths, placed where her lungs would need them.

The owner, on her breath: "Should sound like its coming from a human of the likes of her. Imagine her
diaphragm, her lungs, the size of her body, her chest rising and falling, her vocal cords making the
sounds." So this is a small model of her breathing while she talks, and the sound of it is her own
(breath_bank.py: four breaths from her voice actress's recordings). It is the model the phone's
OwnVoice follows; this file makes listening samples from sentence takes.

Her body: an adult woman, 157 cm, 55 kg. Vital capacity about 3.2 L. People talk on the middle of
that: a breath group uses roughly 0.3-0.6 L and ends near the resting level.

  - Air while speaking: about 0.12-0.16 L per second of her speech by mood (more when excited or loud).
  - A breath group: whole sentences, as many as fit in about 0.6 L (4-5 s of speech). When the next
    sentence would not fit, she breathes at that sentence boundary, never inside a sentence.
  - The breath: what the next group needs plus 0.08 L, drawn through the mouth at 1.1-2.0 L/s by mood, so
    a quick catch of 0.15-0.25 s before a short group and up to 0.5 s before a long one. (Her real
    catch before 3.4 s of speech took about 0.1 s.)
  - The hold: her voice starts 50-180 ms after the breath ends (the glottis closes, then speech).
  - Short openers are said on the air she has: a turn whose first group is under 1.3 s of speech starts
    with no audible breath, the way "Okay, okay." would; up to 4 s, half the time she starts on a quiet
    catch and half on no audible breath (she breathed while listening). Her takes show the same: a
    0.7 s pause in v12_065 with no audible breath at all.
  - Loudness of the breath follows how fast the air goes in: a catch is quietest; her real catch was
    30 dB under her speech and her fuller breath 22 dB under. Here a catch sits about 34 dB under her
    speech and a deep breath about 27 dB under (a little under her studio takes, which were close-miked),
    up or down a dB or two by mood.
  - As the air in a group runs down her voice falls a little, about 1.5 dB across the group, and comes
    back after the next breath: her chest rising and falling.
  - Pauses without a breath: about 0.32 s after a sentence, varied by +-15% and by mood (slower when
    calm or tired, quicker when annoyed or excited).

Moods: calm (her default: bored, cool), playful, annoyed, excited, tired.

Usage (demo): python breathe.py --bank DIR --out OUT.wav [--plain PLAIN.wav] [--seed 7]
       --turn MOOD:LINE.wav[+LINE2.wav...] [--turn ...]
LINE.wav files are speak_checked.py lines (sentences separated by exact silence), after edges.py.
--plain writes the same turns with the same pauses and no breath, to compare.
"""
import argparse
import json
import os
import sys

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "pod"))
from edges import features, split_joined  # noqa: E402

MOODS = {
    #           air L/s, breath-in L/s, level dB, hold s,       pause scale
    "calm":    (0.12, 1.4, -1.5, (0.10, 0.16), 1.10),
    "playful": (0.13, 1.6, -0.5, (0.07, 0.12), 0.95),
    "annoyed": (0.14, 1.8, 0.0, (0.05, 0.10), 0.90),
    "excited": (0.16, 2.0, 1.5, (0.05, 0.09), 0.85),
    "tired":   (0.12, 1.1, -2.5, (0.12, 0.18), 1.25),
}
GROUP_MAX_L = 0.6       # air for one breath group
RESERVE_L = 0.08        # what she breathes in beyond the group's need
OPENER_S = 1.3          # a first group this short is said on the air she has
SOFT_OPENER_S = 4.0     # up to this long, half the time she starts on a quiet catch, half on no breath
LEVEL = {"catch": -34.0, "soft": -31.0, "quick": -30.0, "deep": -27.0}   # dB re her speech
DECLINE_DB = 1.5        # her voice across one breath group


def speech_level(x, sr):
    return float(np.percentile(features(x, sr)[0], 95))


def plan_turn(durs, mood, rng):
    """For each sentence: ('breath', seconds of breath-in) or ('pause', seconds) before it."""
    air, _, _, hold, pscale = MOODS[mood]
    groups, cur = [], []
    for k, d in enumerate(durs):
        if cur and air * (sum(durs[i] for i in cur) + d) > GROUP_MAX_L:
            groups.append(cur); cur = []
        cur.append(k)
    groups.append(cur)
    events = [None] * len(durs)
    for g, idx in enumerate(groups):
        need = air * sum(durs[i] for i in idx) + RESERVE_L
        t_in = float(np.clip(need / MOODS[mood][1], 0.12, 0.65))
        first = idx[0]
        size = sum(durs[i] for i in idx)
        if g == 0 and (size < OPENER_S or (size < SOFT_OPENER_S and rng.random() < 0.5)):
            events[first] = ("none", 0.0, float(rng.uniform(*hold)))
        elif g == 0 and size < SOFT_OPENER_S:
            events[first] = ("breath", min(t_in, 0.2), float(rng.uniform(*hold)))
        else:
            events[first] = ("breath", t_in, float(rng.uniform(*hold)))
        for i in idx[1:]:
            events[i] = ("pause", 0.32 * pscale * float(rng.uniform(0.85, 1.15)), 0.0)
    return events, groups


def kind_for(t_in, mood):
    if t_in < 0.25:
        return "catch"
    if t_in < 0.42:
        return "soft" if mood in ("calm", "tired") else "quick"
    return "deep"


def render_breath(bank, sr, t_in, mood, speech_db, rng):
    kind = kind_for(t_in, mood)
    # Never the same breath twice: the fuller breath also lends its slow start (soft) and fast end
    # (quick), every crop starts somewhere else, and each is drawn a few percent faster or slower.
    pool = {"catch": ["catch"], "soft": ["soft", "deep"], "quick": ["quick", "deep"], "deep": ["deep"]}[kind]
    src = bank[pool[int(rng.integers(0, len(pool)))]]
    rate = float(rng.uniform(0.94, 1.06))
    src = resample_poly(src, 100, int(round(rate * 100))).astype(np.float32)
    n = int(t_in * sr)
    if len(src) > n:
        off = int(rng.integers(0, len(src) - n + 1))
        y = src[off:off + n].copy()
    elif len(src) < n * 0.8:
        up = min(1.3, n / len(src))                      # stretch a little, never past 30%
        y = resample_poly(src, int(round(up * 100)), 100).astype(np.float32)
    else:
        y = src.copy()
    k_in = max(1, int(0.35 * len(y))); k_out = max(1, min(len(y) // 3, int(0.03 * sr)))
    y[:k_in] *= np.sin(np.linspace(0, np.pi / 2, k_in)) ** 2
    y[-k_out:] *= np.cos(np.linspace(0, np.pi / 2, k_out)) ** 2
    lv = features(y, sr)[0]
    have = float(np.percentile(lv, 90))
    want = speech_db + LEVEL[kind] + MOODS[mood][2] + float(rng.uniform(-1, 1))
    return y * np.float32(10 ** ((want - have) / 20)), kind


def render_turn(pieces, mood, bank, sr, rng, breathe=True, log=None):
    durs = [len(p) / sr for p in pieces]
    events, groups = plan_turn(durs, mood, rng)
    speech_db = speech_level(np.concatenate(pieces), sr)
    gain_at = {}
    for idx in groups:
        total = sum(durs[i] for i in idx); t = 0.0
        for i in idx:
            gain_at[i] = (t / max(total, 1e-6), (t + durs[i]) / max(total, 1e-6)); t += durs[i]
    out = []
    for i, (p, ev) in enumerate(zip(pieces, events)):
        what, t_in, hold = ev
        if what == "breath":
            b, kind = render_breath(bank, sr, t_in, mood, speech_db, rng)   # drawn either way: same pauses
            if breathe:
                out += [b, np.zeros(int(hold * sr), np.float32)]
                if log is not None:
                    log.append(f"  breath ({kind}, {len(b) / sr:.2f}s) + hold {hold:.2f}s before: sentence {i + 1}")
            else:
                out.append(np.zeros(len(b) + int(hold * sr), np.float32))
        elif what == "none":
            out.append(np.zeros(int(hold * sr), np.float32))
            if log is not None and breathe:
                log.append(f"  no audible breath (short opener) before: sentence {i + 1}")
        else:
            out.append(np.zeros(int(t_in * sr), np.float32))
        a, b = gain_at[i]
        ramp = 10 ** (-DECLINE_DB * np.linspace(a, b, len(p)) / 20)
        out.append((p * ramp).astype(np.float32))
    return np.concatenate(out)


def load_bank(d, sr):
    meta = json.load(open(os.path.join(d, "bank.json")))
    if meta["sr"] != sr:
        raise SystemExit(f"bank is {meta['sr']} Hz, takes are {sr} Hz")
    return {k: sf.read(os.path.join(d, f"{k}.wav"), dtype="float32")[0] for k in meta["breaths"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--plain"); ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--turn", action="append", required=True, help="MOOD:LINE.wav[+LINE2.wav...]")
    ap.add_argument("--gap", type=float, nargs=2, default=(1.2, 1.7), help="seconds between turns")
    args = ap.parse_args()
    turns, sr = [], None
    for t in args.turn:
        mood, files = t.split(":", 1)
        if mood not in MOODS:
            raise SystemExit(f"mood {mood}: one of {', '.join(MOODS)}")
        pieces = []
        for f in files.split("+"):
            x, sr = sf.read(f, dtype="float32")
            pieces += split_joined(x, sr)[0]
        turns.append((mood, pieces))
    bank = load_bank(args.bank, sr)
    for path, breathe in ((args.out, True), (args.plain, False)):
        if not path:
            continue
        rng = np.random.default_rng(args.seed)       # same pauses in both
        out, log = [np.zeros(int(0.4 * sr), np.float32)], []
        for n, (mood, pieces) in enumerate(turns):
            log.append(f"turn {n + 1} ({mood}, {len(pieces)} sentences)")
            out.append(render_turn(pieces, mood, bank, sr, rng, breathe, log))
            out.append(np.zeros(int(rng.uniform(*args.gap) * sr), np.float32))
        sf.write(path, np.concatenate(out), sr, subtype="PCM_16")
        if breathe:
            print("\n".join(log))
        print(f"wrote {path}")


if __name__ == "__main__":
    sys.exit(main())
