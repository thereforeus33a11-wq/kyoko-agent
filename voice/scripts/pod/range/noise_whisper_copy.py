"""Whispered copies by signal processing, as a fallback for a whisper cell no model filled: the best passing normal
takes of the noises named (from the gate's select_r2.tsv) are whispered by whisperize.py (her vocal tract kept by
LPC, the voice replaced by noise of the same energy, lows rolled off), so each keeps that take's timing and her
formants and has no pitch. They are kind W, style whisper, and the gate ranks them under every take a model whispered.

Usage (gsv env): python noise_whisper_copy.py <select_r2.tsv> <out dir> <cuts_w.tsv> <noise> [<noise> ...] [--top N]
"""
import csv, os, subprocess, sys
import soundfile as sf

args = sys.argv[1:]
top = 8
if "--top" in args:
    i = args.index("--top"); top = int(args[i + 1]); del args[i:i + 2]
sel, out, cuts, sounds = args[0], args[1], args[2], set(args[3:])
cand = os.path.join(os.path.dirname(os.path.abspath(sel)), "cand")
os.makedirs(out, exist_ok=True)
best = {}
for r in csv.DictReader(open(sel, encoding="utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE):
    if r["sound"] in sounds and r["style"] == "normal" and r["verdict"] == "pass":
        best.setdefault(r["sound"], []).append(r)
rows = []
for s, rs in best.items():
    seen = {}
    for r in sorted(rs, key=lambda r: -float(r["sim_her"] or 0)):
        if seen.get(r["name"], 0) >= 2: continue  # at most two copies of one job
        if sum(seen.values()) >= top: break
        seen[r["name"]] = seen.get(r["name"], 0) + 1
        src = os.path.join(cand, r["file"]); dst = os.path.join(out, "W__" + r["file"])
        subprocess.run([sys.executable, "/w/range/scripts/whisperize.py", src, dst], check=True, stdout=subprocess.DEVNULL)
        rows.append(["W__" + r["file"], src, s, "whisper", "W", r["way"], r["name"], "0.000", f"{sf.info(dst).duration:.3f}", "ok",
                     f"whisperize.py over the passing normal {s} {r['file']}"])
with open(cuts, "w", encoding="utf-8") as o:
    o.write("file\tsrc\tsound\tstyle\tkind\tway\tname\tfrom\tto\tstatus\tnote\n")
    for r in rows: o.write("\t".join(r) + "\n")
print("whispered copies:", len(rows))
