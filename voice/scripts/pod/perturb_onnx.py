"""Test helper: make the speaker conditioning of a five-style ONNX voice non-zero (random), to show that the
sid sherpa is given really reaches the graph. Usage: perturb_onnx.py in.onnx out.onnx"""
import sys, numpy as np, onnx
from onnx import numpy_helper
m = onnx.load(sys.argv[1])
print("inputs", [(i.name, [d.dim_value or d.dim_param for d in i.type.tensor_type.shape.dim]) for i in m.graph.input])
print("metadata", {p.key: p.value for p in m.metadata_props})
rng = np.random.default_rng(0)
hit = []
for init in m.graph.initializer:
    a = numpy_helper.to_array(init)
    if a.ndim >= 2 and a.shape[1] == 32 and not a.any():
        new = (rng.standard_normal(a.shape) * 0.05).astype(a.dtype)
        init.CopyFrom(numpy_helper.from_array(new, init.name))
        hit.append((init.name, a.shape))
    elif a.ndim == 2 and a.shape == (5, 32):
        hit.append((init.name + " (embedding, kept)", a.shape))
print("perturbed", hit)
onnx.save(m, sys.argv[2])
