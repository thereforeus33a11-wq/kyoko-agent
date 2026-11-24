"""Is the timbre measure fair to a short take? Long takes of a style set that pass the timbre gate well are cut to
shorter lengths (the start of the take, and the middle), and each piece is scored exactly as a take is (WavLM
x-vector cosine to her 4-clip centroid and to the style's reference clip, the range trial's measure.py). The same
voice in the same take: any drop is the measure's, not the take's.

First run on the yell set (2026-11-24): takes that score 0.96 whole (3.7 s) score 0.85 cut to 1.0 s, 0.88 at 1.5 s,
0.91 at 2.0 s, 0.93 at 2.5 s, and the cut pieces pass the gate as rarely as real takes of those lengths.

Usage (gsv-env, cwd /w/GPT-SoVITS with gsv() PYTHONPATH):
  python len_probe.py <style dir, e.g. /w/range_v1/yell> <batch> <name filter, e.g. _yell_ja_> <style reference wav>
                      [takes=60] [sim_her gate=0] [sim_ref gate=0]
Reads <style dir>/measure/<batch>/measure.tsv and <style dir>/final/; writes <style dir>/measure/len_probe.json.
"""
import csv, json, os, sys
import numpy as np
sys.path.insert(0, "/w/range/scripts")
from measure import Embedder, load

O, bn, flt, ref = sys.argv[1:5]
N = int(sys.argv[5]) if len(sys.argv) > 5 else 60
gh = float(sys.argv[6]) if len(sys.argv) > 6 else 0.0
gr = float(sys.argv[7]) if len(sys.argv) > 7 else 0.0
RF = "/w/yume/range_proto/refs"
emb = Embedder("cpu")
cs = [emb(*load(f"{RF}/{c}_clean.wav")) for c in ("v12_040", "v12_065", "v12_071", "yume_07")]
c = np.mean(cs, axis=0); c /= np.linalg.norm(c)
r = emb(*load(ref))
rows = [x for x in csv.DictReader(open(f"{O}/measure/{bn}/measure.tsv", encoding="utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE)
        if flt in x["file"] and float(x["dur"]) >= 3.0 and float(x["sim_her"]) >= 0.93 and float(x["sim_ref"]) >= 0.93][:N]
res = {}
for d in (0.8, 1.0, 1.2, 1.5, 2.0, 2.5, 3.0):
    sh, sr_, mh, mr = [], [], [], []
    for x in rows:
        y, sr = load(f"{O}/final/{os.path.basename(x['file'])}")
        k = int(d * sr)
        if len(y) < k:
            continue
        a = y[:k]; m0 = (len(y) - k) // 2; b = y[m0:m0 + k]
        ea, eb = emb(a, sr), emb(b, sr)
        sh.append(float(ea @ c)); sr_.append(float(ea @ r)); mh.append(float(eb @ c)); mr.append(float(eb @ r))
    res[f"{d:.1f} s"] = dict(takes=len(sh), start_sim_her=round(float(np.median(sh)), 4), start_sim_ref=round(float(np.median(sr_)), 4),
                             middle_sim_her=round(float(np.median(mh)), 4), middle_sim_ref=round(float(np.median(mr)), 4),
                             share_of_starts_passing_both_gates=round(float(np.mean((np.array(sh) >= gh) & (np.array(sr_) >= gr))), 3))
    print(d, res[f"{d:.1f} s"], flush=True)
full = dict(takes=len(rows), sim_her=round(float(np.median([float(x["sim_her"]) for x in rows])), 4),
            sim_ref=round(float(np.median([float(x["sim_ref"]) for x in rows])), 4), dur=round(float(np.median([float(x["dur"]) for x in rows])), 2))
json.dump(dict(note="long takes (>= 3 s, both sims >= 0.93) cut to shorter lengths and scored as a take is",
               gates=dict(sim_her=gh, sim_ref=gr), whole_takes=full, cut=res), open(f"{O}/measure/len_probe.json", "w"), indent=1)
print("LEN-PROBE-DONE", full)
