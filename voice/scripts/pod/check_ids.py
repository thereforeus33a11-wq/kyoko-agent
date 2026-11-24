"""Check that the phoneme ids Piper cached for each line are the mixed phonemizer's (what the phone
gives the voice). Usage: python check_ids.py <metadata.csv> <cache dir> <voice config .onnx.json>
A multi-speaker metadata (wav|speaker|text) is read with the config's speaker_id_map, as Piper names its cache."""
import json
import os
import sys

import torch
from piper.train.vits.utils import get_cache_id

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mix_phonemize import MixedPhonemizer  # noqa: E402

csv_path, cache, config = sys.argv[1:4]
cfg = json.load(open(config, encoding="utf-8"))
id_map = cfg["phoneme_id_map"]
speakers = cfg.get("speaker_id_map") or {}
multi = int(cfg.get("num_speakers", 1)) > 1
mp = MixedPhonemizer()
ok = bad = missing = 0
per_speaker = {}
for row_number, line in enumerate(open(csv_path, encoding="utf-8"), start=1):
    row = line.rstrip("\n").split("|")
    text = row[-1]
    speaker_id = speakers[row[1]] if multi else None
    path = os.path.join(cache, f"{get_cache_id(row_number, text, speaker_id=speaker_id)}.phonemes.pt")
    tally = per_speaker.setdefault(row[1] if multi else "-", [0, 0, 0])
    if not os.path.exists(path):
        missing += 1
        tally[2] += 1
        continue
    if torch.load(path).tolist() == mp.ids(text, id_map):
        ok += 1
        tally[0] += 1
    else:
        bad += 1
        tally[1] += 1
        print("ids differ:", text)
if multi:
    for name, (o, b, m) in per_speaker.items():
        print(f"  {name} (sid {speakers[name]}): {o} match, {b} differ, {m} not cached")
print(f"cached ids: {ok} match, {bad} differ, {missing} not cached")
sys.exit(1 if bad or (multi and missing) else 0)
