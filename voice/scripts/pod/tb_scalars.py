"""Dump a Lightning run's TensorBoard scalars: for each tag, the count, first, last, min, max, and whether every
value is finite. Usage: python tb_scalars.py <lightning_logs/version_N dir> [--json out.json] [--tags a b ...]"""
import argparse
import glob
import json
import math

from tensorboard.backend.event_processing.event_accumulator import EventAccumulator

ap = argparse.ArgumentParser()
ap.add_argument("logdir")
ap.add_argument("--json", default=None)
ap.add_argument("--tags", nargs="*", default=None)
a = ap.parse_args()
out = {}
for f in sorted(glob.glob(f"{a.logdir}/events.out.tfevents.*")):
    ea = EventAccumulator(f, size_guidance={"scalars": 0})
    ea.Reload()
    for tag in ea.Tags()["scalars"]:
        if a.tags and tag not in a.tags:
            continue
        v = [e.value for e in ea.Scalars(tag)]
        s = [e.step for e in ea.Scalars(tag)]
        out.setdefault(tag, {"values": [], "steps": []})
        out[tag]["values"] += v
        out[tag]["steps"] += s
summary = {}
for tag, d in sorted(out.items()):
    v = d["values"]
    summary[tag] = dict(n=len(v), first=round(v[0], 5), last=round(v[-1], 5), min=round(min(v), 5), max=round(max(v), 5),
                        all_finite=all(math.isfinite(x) for x in v), last_step=d["steps"][-1])
if a.json:
    json.dump(summary, open(a.json, "w"), indent=1)
for tag, s in summary.items():
    print(tag, s)
