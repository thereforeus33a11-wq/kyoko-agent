"""Per-block numbers of a Lightning run's TensorBoard scalars (the loss curves in numbers).

For every block of BLOCK epochs (975-999, 1000-1024, ... with --start 975 --block 25): the mean of every training
scalar logged in that block, and every validation scalar with the epoch it was logged at. Values that are not finite
are counted per tag. Several version dirs may be given in order (a run restarted from a kept checkpoint writes a new
version): for an epoch logged by more than one, the last dir given wins.
Usage: python tb_epochs.py <version dir> [<version dir> ...] [--start 975] [--block 25] [--json out.json] [--tsv out.tsv]
"""
import argparse
import bisect
import glob
import json
import math

from tensorboard.backend.event_processing.event_accumulator import EventAccumulator

TRAIN = ["loss_g", "loss_d", "train_mel", "train_kl", "train_dur", "train_fm", "train_gen", "train_disc"]
VAL_PREFIX = "val"


def read_dir(d):
    ev = {}
    for f in sorted(glob.glob(f"{d}/events.out.tfevents.*")):
        ea = EventAccumulator(f, size_guidance={"scalars": 0})
        ea.Reload()
        for tag in ea.Tags()["scalars"]:
            ev.setdefault(tag, []).extend((e.step, e.value) for e in ea.Scalars(tag))
    ep = sorted(ev.get("epoch", []))
    steps = [s for s, _ in ep]
    per = {}  # tag -> epoch -> [values]
    for tag, vals in ev.items():
        if tag in ("epoch", "hp_metric"):
            continue
        for s, v in vals:
            i = bisect.bisect_right(steps, s) - 1
            if i < 0:
                continue
            per.setdefault(tag, {}).setdefault(int(round(ep[i][1])), []).append(v)
    return per


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--start", type=int, default=975)
    ap.add_argument("--block", type=int, default=25)
    ap.add_argument("--json", default=None)
    ap.add_argument("--tsv", default=None)
    a = ap.parse_args()
    merged = {}
    for d in a.dirs:
        for tag, eps in read_dir(d).items():
            for e, v in eps.items():
                merged.setdefault(tag, {})[e] = v
    nonfinite = {t: sum(1 for vs in eps.values() for x in vs if not math.isfinite(x)) for t, eps in merged.items()}
    tags = [t for t in TRAIN if t in merged] + sorted(t for t in merged if t not in TRAIN and not t.startswith(VAL_PREFIX)
                                                     and t not in ("iters",))
    blocks = []
    last_epoch = max((e for eps in merged.values() for e in eps), default=a.start - 1)
    b0 = a.start
    while b0 <= last_epoch:
        b1 = b0 + a.block - 1
        row = {"epochs": f"{b0}-{b1}"}
        n_ep = 0
        for t in tags:
            vs = [x for e in range(b0, b1 + 1) for x in merged[t].get(e, []) if math.isfinite(x)]
            row[t] = float(f"{sum(vs) / len(vs):.6g}") if vs else None
            if t == "loss_g":
                n_ep = len({e for e in range(b0, b1 + 1) if e in merged[t]})
        row["epochs_logged"] = n_ep
        blocks.append(row)
        b0 += a.block
    val = []
    vtags = sorted(t for t in merged if t.startswith(VAL_PREFIX))
    for e in sorted({e for t in vtags for e in merged[t]}):
        r = {"epoch": e}
        for t in vtags:
            vs = merged[t].get(e)
            r[t] = float(f"{vs[-1]:.6g}") if vs else None
        val.append(r)
    out = {"train_blocks": blocks, "val": val, "nonfinite": nonfinite, "tags": tags, "val_tags": vtags}
    if a.json:
        json.dump(out, open(a.json, "w"), indent=1)
    if a.tsv:
        with open(a.tsv, "w") as f:
            f.write("\t".join(["epochs"] + tags + ["epochs_logged"]) + "\n")
            for r in blocks:
                f.write("\t".join(str(r[k]) for k in ["epochs"] + tags + ["epochs_logged"]) + "\n")
            f.write("\n" + "\t".join(["epoch"] + vtags) + "\n")
            for r in val:
                f.write("\t".join(str(r[k]) for k in ["epoch"] + vtags) + "\n")
    print("nonfinite", nonfinite)
    for r in blocks:
        print(r)
    for r in val:
        print(r)


if __name__ == "__main__":
    main()
