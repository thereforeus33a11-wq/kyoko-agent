"""Make a Piper ONNX voice loadable by sherpa-onnx 2.x: add its metadata and write tokens.txt.
Usage: python sherpa_meta.py model.onnx model.onnx.json outdir"""
import json, os, sys, onnx
model, cfg_path, out = sys.argv[1:4]
cfg = json.load(open(cfg_path, encoding="utf-8"))
m = onnx.load(model)
meta = {"model_type": "vits", "comment": "piper", "language": "Japanese", "voice": "ja", "version": 1,
        "has_espeak": 0, "has_g2pw": 0, "n_speakers": cfg["num_speakers"], "sample_rate": cfg["audio"]["sample_rate"]}
del m.metadata_props[:]
for k, v in meta.items():
    p = m.metadata_props.add(); p.key = k; p.value = str(v)
os.makedirs(out, exist_ok=True)
onnx.save(m, os.path.join(out, "model.onnx"))
dropped = []
with open(os.path.join(out, "tokens.txt"), "w", encoding="utf-8") as f:
    for s, i in cfg["phoneme_id_map"].items():
        if s == "\n":
            continue
        if len(s) != 1:   # merged English vowel clusters from the base: one codepoint per token only
            dropped.append(s); continue
        f.write(f"{s} {i[0] if isinstance(i, list) else i}\n")
print("metadata", meta, "dropped tokens", dropped)
