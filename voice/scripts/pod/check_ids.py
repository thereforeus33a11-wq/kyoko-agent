"""Check that the phoneme ids Piper cached for each line are the mixed phonemizer's (what the phone
gives the voice). Usage: python check_ids.py <metadata.csv> <cache dir> <voice config .onnx.json>"""
import json
import os
import sys

import torch
from piper.train.vits.utils import get_cache_id

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mix_phonemize import MixedPhonemizer  # noqa: E402

csv_path, cache, config = sys.argv[1:4]
id_map = json.load(open(config, encoding="utf-8"))["phoneme_id_map"]
mp = MixedPhonemizer()
ok = bad = missing = 0
for row_number, line in enumerate(open(csv_path, encoding="utf-8"), start=1):
    text = line.rstrip("\n").split("|")[-1]
    path = os.path.join(cache, f"{get_cache_id(row_number, text)}.phonemes.pt")
    if not os.path.exists(path):
        missing += 1
        continue
    if torch.load(path).tolist() == mp.ids(text, id_map):
        ok += 1
    else:
        bad += 1
        print("ids differ:", text)
print(f"cached ids: {ok} match, {bad} differ, {missing} not cached")
sys.exit(1 if bad else 0)
