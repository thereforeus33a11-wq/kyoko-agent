"""Per-speaker inference settings inside a multi-speaker Piper ONNX voice, for a player (sherpa-onnx 2.0.x on the phone)
that can only set noise_scale and noise_scale_w for the whole model and length_scale through the per-call speed.

The Piper graph takes `scales` = [noise_scale, length_scale, noise_scale_w] (float32 [3]) and `sid` (int64 [1]). This
adds one small table T (float32 [num_speakers, 3]) and, in front of every node that reads `scales`:
    scales_sid = scales * reshape(gather(T, sid), [3])
so each speaker's settings are the player's settings times that speaker's row: a row of 1, 1, 1 leaves a speaker
exactly as it was (multiplying by 1.0 is exact, so its samples are bit-identical), and the per-call speed still works
on top (sherpa sends length_scale = 1 / speed; the row scales it). Nothing else in the graph changes.
Usage: python sid_scales_onnx.py <in.onnx> <out.onnx> '<json: {"1": [ns_mult, ls_mult, nsw_mult], ...}>'
Speakers not named keep 1, 1, 1. No voice data in this file."""
import json
import sys

import numpy as np
import onnx
from onnx import helper, numpy_helper


def main():
    src, dst, spec = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])
    m = onnx.load(src)
    g = m.graph
    names = {i.name for i in g.input}
    assert {"scales", "sid"} <= names, f"no scales/sid input: {names}"
    n_spk = None
    for p in m.metadata_props:
        if p.key == "n_speakers":
            n_spk = int(p.value)
    n_spk = n_spk or (max(int(k) for k in spec) + 1)
    T = np.ones((n_spk, 3), np.float32)
    for k, row in spec.items():
        T[int(k)] = np.asarray(row, np.float32)
    g.initializer.append(numpy_helper.from_array(T, "sid_scale_table"))
    g.initializer.append(numpy_helper.from_array(np.array([3], np.int64), "sid_scale_shape"))
    for node in g.node:
        for i, x in enumerate(node.input):
            if x == "scales":
                node.input[i] = "scales_sid"
    new = [helper.make_node("Gather", ["sid_scale_table", "sid"], ["sid_scale_row2"], axis=0, name="sid_scale_gather"),
           helper.make_node("Reshape", ["sid_scale_row2", "sid_scale_shape"], ["sid_scale_row"], name="sid_scale_reshape"),
           helper.make_node("Mul", ["scales", "sid_scale_row"], ["scales_sid"], name="sid_scale_mul")]
    nodes = new + list(g.node)
    del g.node[:]
    g.node.extend(nodes)
    onnx.checker.check_model(m)
    onnx.save(m, dst)
    print("per-speaker scale rows (noise_scale, length_scale, noise_scale_w multipliers):", T.tolist())


if __name__ == "__main__":
    main()
