"""Give every random node of a Piper ONNX voice a fixed seed, so two voices (or two runs) can be compared with the
same noise. The voice's noise is drawn inside the graph (RandomNormalLike for the duration predictor's noise and
the prior sample), and onnxruntime seeds those from the clock unless the node carries a seed; with one, each node
draws the same sequence in every new session, call after call. Nothing else in the graph changes.
Usage: python seed_onnx.py <in.onnx> <out.onnx> <seed>"""
import sys

import onnx
from onnx import helper

RANDOM_OPS = {"RandomNormal", "RandomNormalLike", "RandomUniform", "RandomUniformLike", "Multinomial", "Bernoulli"}

src, dst, seed = sys.argv[1], sys.argv[2], float(sys.argv[3])
m = onnx.load(src)
done = []


def walk(graph):
    for node in graph.node:
        if node.op_type in RANDOM_OPS:
            keep = [a for a in node.attribute if a.name != "seed"]
            del node.attribute[:]
            node.attribute.extend(keep + [helper.make_attribute("seed", seed)])
            done.append(f"{node.op_type}:{node.name}")
        for a in node.attribute:
            if a.type == onnx.AttributeProto.GRAPH:
                walk(a.g)
            for g in a.graphs:
                walk(g)


walk(m.graph)
assert done, "no random nodes found"
onnx.save(m, dst)
print(f"seed {seed:g} on {len(done)} random nodes: {done}")
