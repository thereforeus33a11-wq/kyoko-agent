"""CPU real-time factor and size of Piper ONNX voices with onnxruntime, side by side on the same lines.
Usage: python rtf_onnx.py --lines L.tsv --config voice.onnx.json --threads 1 4 --repeats 3 name=model.onnx[:sid] ...
Each line's phoneme ids come from the mixed phonemizer (the ids the phone's codepoints map to). Models are run in
turn, line by line, repeat by repeat, the order rotated from line to line (so a busy machine slows them alike and
no model always goes first); RTF = synthesis seconds / audio seconds over all lines, the median of the repeats.
Name the first model twice (a=x.onnx b=x.onnx) for an A/A control: the spread it shows is the measuring noise.
One session per model and thread count; intra-op threads as given, one inter-op thread, sequential execution,
as on the phone."""
import argparse
import csv
import json
import os
import statistics as st
import sys
import time

import numpy as np
import onnxruntime as ort

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mix_phonemize import MixedPhonemizer  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--lines", required=True)
ap.add_argument("--config", required=True)
ap.add_argument("--threads", type=int, nargs="+", default=[1, 4])
ap.add_argument("--repeats", type=int, default=3)
ap.add_argument("--json", default=None)
ap.add_argument("models", nargs="+")
a = ap.parse_args()
cfg = json.load(open(a.config, encoding="utf-8"))
mp = MixedPhonemizer()
texts = [r["text"] for r in csv.DictReader(open(a.lines, encoding="utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE)]
ids = [np.array([mp.ids(t, cfg["phoneme_id_map"])], dtype=np.int64) for t in texts]
sr = cfg["audio"]["sample_rate"]
scales = np.array([0.667, 1.0, 0.8], dtype=np.float32)
models = []
for spec in a.models:
    name, rest = spec.split("=", 1)
    path, _, sid = rest.partition(":")
    models.append((name, path, int(sid) if sid else None))
out = {"lines": len(texts), "repeats": a.repeats, "models": {}}
for name, path, sid in models:
    out["models"][name] = {"path": path, "bytes": os.path.getsize(path), "sid": sid}
for t in a.threads:
    sess = {}
    for name, path, sid in models:
        so = ort.SessionOptions()
        so.intra_op_num_threads = t
        so.inter_op_num_threads = 1
        so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        sess[name] = ort.InferenceSession(path, so, providers=["CPUExecutionProvider"])
    rtf = {name: [] for name, _, _ in models}
    for r in range(a.repeats + 1):  # repeat 0 warms up
        took = {name: 0.0 for name, _, _ in models}
        audio = {name: 0.0 for name, _, _ in models}
        for k, x in enumerate(ids):
            for name, path, sid in models[k % len(models):] + models[:k % len(models)]:
                feed = {"input": x, "input_lengths": np.array([x.shape[1]], dtype=np.int64), "scales": scales}
                if sid is not None:
                    feed["sid"] = np.array([sid], dtype=np.int64)
                t0 = time.perf_counter()
                y = sess[name].run(None, feed)[0]
                took[name] += time.perf_counter() - t0
                audio[name] += y.shape[-1] / sr
        if r:
            for name in rtf:
                rtf[name].append(took[name] / audio[name])
    for name in rtf:
        out["models"][name][f"rtf_{t}_threads"] = round(st.median(rtf[name]), 4)
        out["models"][name][f"rtf_{t}_threads_all"] = [round(v, 4) for v in rtf[name]]
base = models[0][0]
for name in out["models"]:
    m, b = out["models"][name], out["models"][base]
    m["size_vs_" + base] = round(m["bytes"] / b["bytes"] - 1, 4)
    for t in a.threads:
        m[f"rtf_{t}_vs_{base}"] = round(m[f"rtf_{t}_threads"] / b[f"rtf_{t}_threads"] - 1, 4)
if a.json:
    json.dump(out, open(a.json, "w"), indent=1)
print(json.dumps(out, indent=1))
