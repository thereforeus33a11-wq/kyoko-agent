"""Control for the style words gate (gsv-env): the styles' held-out lines spoken in her NORMAL voice (sid 0 of a
candidate, and e974) and judged by each line's own style rule (styles_eval_score.words_all, by_line). If her normal
voice misses the same share of these lines, the shortfall is the voice's (Piper's) reading of these lines, not the
style's. Reads a folder made like the scoring one (styles_eval.py items / asr / wer / measure on it).
Usage: python styles_eval_ctrl.py --out DIR [--main DIR]   writes DIR/score/ctrl.json and prints the table, beside
the main run's numbers for the same lines spoken in their own style (its score/clips.tsv)."""
import argparse
import json
import os
import sys

sys.path.insert(0, "/w/job/scripts")
import numpy as np  # noqa: E402
import styles_eval_score as S  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--main", default="/w/range_build/styles/eval")
a = ap.parse_args()
meta = {int(r["n"]): r for r in S.tsv(f"{a.out}/lines/meta.tsv")}
items = S.tsv(f"{a.out}/items.tsv")
M = {r["id"]: r for r in S.tsv(f"{a.out}/measure.tsv") if r["status"] == "ok"}
W = S.words_all(a, meta, items, M, by_line=True)
main = [r for r in S.tsv(f"{a.main}/score/clips.tsv") if r["src"] == "gen"]
res = {}
for v in sorted({it["voice"] for it in items}):
    for s in S.STYLES[1:]:
        ids = [it["id"] for it in items if it["voice"] == v and meta[int(it["n"])]["group"] == f"{s}_val"]
        ok = [W[i]["w_ok"] for i in ids if i in W and W[i]["w_ok"] == W[i]["w_ok"]]
        er = [W[i]["w_err"] for i in ids if i in W and W[i]["w_err"] == W[i]["w_err"]]
        own = [r for r in main if r["voice"] == v and r["seed"] == "1234" and r["group"] == f"{s}_val"]
        own_ok = [float(r["w_ok"]) for r in own if r["w_ok"] not in ("", "nan")]
        res[f"{v}/{s}"] = dict(lines=len(ids), sid0_words_share=round(float(np.mean(ok)), 3) if ok else None,
                               sid0_words_err=round(float(np.mean(er)), 3) if er else None,
                               own_style_words_share=round(float(np.mean(own_ok)), 3) if own_ok else None)
        print(f"{v:6s} {s:8s} lines {len(ids):3d}  spoken normal (sid 0): words stand {res[f'{v}/{s}']['sid0_words_share']}"
              f"  mean err {res[f'{v}/{s}']['sid0_words_err']}  | spoken in its own style: {res[f'{v}/{s}']['own_style_words_share']}")
os.makedirs(f"{a.out}/score", exist_ok=True)
json.dump(res, open(f"{a.out}/score/ctrl.json", "w"), indent=1)
print("CTRL-DONE")
