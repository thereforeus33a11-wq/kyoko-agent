"""Check the sound bank after round 3 was added beside rounds 1 and 2:
  - every earlier entry of sounds.json is unchanged and still first in its cell (round 3 only appends), and every
    earlier file is byte for byte as it was (sha256 list taken before the round wrote anything)
  - every entry has its file and every file in the bank its entry; no two takes are the same audio
  - round-3 files are 22050 Hz mono PCM 16, do not clip, have at most 8 takes per cell, take numbers that follow
    the cell's earlier ones, and are at or under the adult cap by both trackers' numbers in sounds.json (median <=
    345 Hz on clearly voiced frames; the final file's Praat median <= 345 Hz for a voiced style)
Usage: python noise_verify_r3.py <bank dir> <sounds.json before round 3> <sha256 list before round 3>
"""
import hashlib, json, os, re, sys
import numpy as np, soundfile as sf

bank, old_p, sha_p = sys.argv[1:4]
j = json.load(open(os.path.join(bank, "sounds.json"), encoding="utf-8"))
old = json.load(open(old_p, encoding="utf-8"))
bad = []
for s, cells in old["sounds"].items():
    for st, takes in cells.items():
        now = j["sounds"].get(s, {}).get(st, [])
        if now[:len(takes)] != takes: bad.append(f"{s}/{st}: an earlier entry changed")
        if any(t.get("round") == 3 for t in takes): bad.append(f"{s}/{st}: a round-3 entry in the earlier file")
for k in old:
    if k != "sounds" and j.get(k) != old[k]: bad.append(f"top-level {k} changed")
for l in open(sha_p, encoding="utf-8"):
    h, f = l.split(None, 1); f = f.strip()
    p = f if os.path.isabs(f) else os.path.join(bank, f)
    if not os.path.exists(p): bad.append(f"earlier file gone: {f}"); continue
    if hashlib.sha256(open(p, "rb").read()).hexdigest() != h: bad.append(f"earlier file changed: {f}")
listed, hashes, n3 = set(), {}, 0
for s, cells in j["sounds"].items():
    for st, takes in cells.items():
        if len(takes) > 8: bad.append(f"{s}/{st}: {len(takes)} takes")
        nums = [int(re.search(r"take_(\d+)", t["file"]).group(1)) for t in takes]
        if nums != list(range(1, len(nums) + 1)): bad.append(f"{s}/{st}: take numbers {nums}")
        for t in takes:
            p = os.path.join(bank, t["file"]); listed.add(os.path.normpath(p))
            if not os.path.exists(p): bad.append(f"missing {t['file']}"); continue
            x, sr = sf.read(p, dtype="int16")
            h = hashlib.sha1(x.tobytes()).hexdigest()
            if h in hashes: bad.append(f"same audio: {t['file']} = {hashes[h]}")
            hashes[h] = t["file"]
            if t.get("round") != 3: continue
            n3 += 1
            i = sf.info(p)
            if (i.samplerate, i.channels, i.subtype) != (22050, 1, "PCM_16"): bad.append(f"format {t['file']}: {i.samplerate} {i.channels} {i.subtype}")
            if np.max(np.abs(x.astype(np.int32))) >= 32767: bad.append(f"clips {t['file']}")
            pt = t.get("pitch") or {}
            for k in ("praat_clear_median_hz", "pyin_clear_median_hz"):
                if pt.get(k) is not None and pt[k] > 345: bad.append(f"over the cap {t['file']}: {k} {pt[k]}")
            if st != "whisper" and t.get("f0_median_hz") is not None and t["f0_median_hz"] > 345:
                bad.append(f"over the cap in the file {t['file']}: {t['f0_median_hz']}")
for root, _, fs in os.walk(bank):
    for f in fs:
        if f.endswith(".wav") and os.path.normpath(os.path.join(root, f)) not in listed:
            bad.append(f"not in sounds.json: {os.path.relpath(os.path.join(root, f), bank)}")
print(f"{n3} round-3 takes, {len(hashes)} takes in the bank; problems: {len(bad)}")
for b in bad: print("  " + b)
