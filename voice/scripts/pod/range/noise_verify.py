"""Check the sound bank after a round was added: every entry of sounds.json has its file and every file its entry,
files are 22050 Hz mono PCM 16, voiced takes are at or under the adult cap (median f0 <= 345 Hz), nothing clips, no
two takes in the bank are the same audio, and the earlier round's entries are exactly as they were.

Usage: python noise_verify.py <bank dir> <earlier sounds.json> <noise> [<noise> ...]   (the noises the new round added)
"""
import hashlib, json, os, sys
import numpy as np, soundfile as sf

bank, old_p, new = sys.argv[1], sys.argv[2], set(sys.argv[3:])
j = json.load(open(os.path.join(bank, "sounds.json"), encoding="utf-8"))
old = json.load(open(old_p, encoding="utf-8"))
bad = []
for s, cells in old["sounds"].items():
    if j["sounds"].get(s) != cells: bad.append(f"{s}: an earlier entry changed")
listed, hashes, n_new = set(), {}, 0
for s, cells in j["sounds"].items():
    for st, takes in cells.items():
        for t in takes:
            p = os.path.join(bank, t["file"]); listed.add(os.path.normpath(p))
            if not os.path.exists(p): bad.append(f"missing {t['file']}"); continue
            h = hashlib.sha1(sf.read(p, dtype="int16")[0].tobytes()).hexdigest()
            if h in hashes: bad.append(f"same audio: {t['file']} = {hashes[h]}")
            hashes[h] = t["file"]
            if s not in new: continue
            n_new += 1
            i = sf.info(p)
            if (i.samplerate, i.channels, i.subtype) != (22050, 1, "PCM_16"): bad.append(f"format {t['file']}: {i.samplerate} {i.channels} {i.subtype}")
            if t["f0_median_hz"] is not None and t["f0_median_hz"] > 345: bad.append(f"over the cap {t['file']}: {t['f0_median_hz']}")
            x = sf.read(p, dtype="float32")[0]
            if np.max(np.abs(x)) >= 0.999: bad.append(f"clips {t['file']}")
for s in new:
    d = os.path.join(bank, s)
    for root, _, fs in os.walk(d):
        for f in fs:
            if f.endswith(".wav") and os.path.normpath(os.path.join(root, f)) not in listed: bad.append(f"not in sounds.json: {root}/{f}")
print(f"{n_new} new takes in {len(new)} noises, {len(hashes)} takes in the bank; problems: {len(bad)}")
for b in bad: print("  " + b)
