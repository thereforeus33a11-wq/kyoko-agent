"""Write a run's PROGRESS.md from its logs (no data in it but numbers): the state, the per-epoch report lines of
styles_patch.py (speed, the conditioning per sid), the kept checkpoints and their volume copies, and the loss curves
in numbers (tb_epochs.py's json). Hand-written notes are read from --notes and put at the top, unchanged.
Usage: python styles_progress.py --out PROGRESS.md --notes notes.md --log train.log [--log ...] --copylog keep_copy.log
       [--copylog ...] --keep-dir DIR --vol-dir DIR --tb-json tb.json --epochs 1750 --start 975 [--state TEXT]
"""
import argparse
import datetime
import json
import os
import re
import shutil
import subprocess

EP = re.compile(r"\[styles_patch\] epoch (\d+); (\d+) batches, epoch wall ([\d.]+) s, ([\d.]+) it/s")
COND = re.compile(r"mean \|cond\| per sid dec ([\d.e\- ]+), dp ([\d.e\- ]+), flow ([\d.e\- ]+), enc_q ([\d.e\- ]+);")
MEM = re.compile(r"peak GPU memory ([\d.]+) GiB allocated, ([\d.]+) GiB reserved")
SIDS = re.compile(r"lines per sid \[([\d, ]+)\], batches holding every sid (\d+)/(\d+)")
COPY = re.compile(r"^(\S+) copied (keep-epoch=(\d+)\.ckpt) \((\d+) bytes, sha256 ([0-9a-f]+)\) in (\d+) s")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--notes", default=None)
    ap.add_argument("--log", action="append", default=[])
    ap.add_argument("--copylog", action="append", default=[])
    ap.add_argument("--keep-dir", required=True)
    ap.add_argument("--vol-dir", required=True)
    ap.add_argument("--tb-json", default=None)
    ap.add_argument("--epochs", type=int, required=True)
    ap.add_argument("--start", type=int, default=975)
    ap.add_argument("--state", default="")
    a = ap.parse_args()

    eps = {}
    for lf in a.log:
        if not os.path.exists(lf):
            continue
        for line in open(lf, errors="replace").read().replace("\r", "\n").split("\n"):
            m = EP.search(line)
            if not m:
                continue
            e = int(m.group(1))
            r = dict(batches=int(m.group(2)), wall=float(m.group(3)), its=float(m.group(4)))
            c = COND.search(line)
            if c:
                r["cond"] = {k: c.group(i + 1).split() for i, k in enumerate(["dec", "dp", "flow", "enc_q"])}
            mm = MEM.search(line)
            if mm:
                r["mem"] = (float(mm.group(1)), float(mm.group(2)))
            s = SIDS.search(line)
            if s:
                r["sids"] = s.group(1)
                r["allsid"] = f"{s.group(2)}/{s.group(3)}"
            eps[e] = r  # a restarted run's line for the same epoch wins
    copies = {}
    for cf in a.copylog:
        if not os.path.exists(cf):
            continue
        for line in open(cf, errors="replace"):
            m = COPY.search(line.strip())
            if m:
                copies[int(m.group(3))] = dict(t=m.group(1), bytes=int(m.group(4)), sha=m.group(5), s=int(m.group(6)))
    kept = set()
    for d in (a.keep_dir, a.vol_dir):
        if os.path.isdir(d):
            for f in os.listdir(d):
                m = re.fullmatch(r"keep-epoch=(\d+)\.ckpt", f)
                if m:
                    kept.add(int(m.group(1)))
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    L = [f"# Five-style training: progress (updated {now})", ""]
    if a.notes and os.path.exists(a.notes):
        L += [open(a.notes).read().rstrip(), ""]
    L += ["## State (written by styles_progress.py from the logs)", ""]
    if a.state:
        L += [f"- {a.state}"]
    if eps:
        last = max(eps)
        done = last - a.start + 1
        total = a.epochs - a.start
        recent = [eps[e]["wall"] for e in sorted(eps)[-25:]]
        mw = sum(recent) / len(recent)
        left = a.epochs - 1 - last
        L += [f"- last finished epoch {last}: {done} of {total} epochs done ({100 * done / total:.1f} %); "
              f"mean epoch wall over the last {len(recent)} epochs {mw:.1f} s; about {left * mw / 3600:.2f} h left "
              f"for {left} epochs (validation every 25th epoch not counted)",
              f"- epoch wall over the whole run: min {min(r['wall'] for r in eps.values()):.1f} s, "
              f"max {max(r['wall'] for r in eps.values()):.1f} s, sum {sum(r['wall'] for r in eps.values()) / 3600:.2f} h"]
        r = eps[last]
        if "mem" in r:
            L += [f"- peak GPU memory (epoch {last}): {r['mem'][0]} GiB allocated, {r['mem'][1]} GiB reserved"]
        if "sids" in r:
            L += [f"- lines per sid in epoch {last}: [{r['sids']}], batches holding every sid {r['allsid']}"]
    du = shutil.disk_usage("/")
    L += [f"- / free: {du.free / 1e9:.1f} GB"]
    try:
        g = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu",
                            "--format=csv,noheader"], capture_output=True, text=True, timeout=10).stdout.strip()
        L += [f"- GPU (memory used, total, utilisation): {g}"]
    except Exception as ex:  # reporting only
        L += [f"- GPU: nvidia-smi failed ({ex})"]
    L += ["", "## Kept checkpoints", "",
          "Full checkpoints: all on /w; on the volume only the newest (it is too small for all; keep_rotate.sh). "
          "Slims (generator inference weights, slim_ckpt.py): /w/piper-styles-keep/slim, each also fetched off the pod.", "",
          "| epoch | full on /w | full on the volume | copied to the volume (UTC) | bytes | sha256 | slim on /w | slim fetched |",
          "|---|---|---|---|---|---|---|---|"]
    sdir = os.path.join(a.keep_dir, "slim")
    fetched = set()
    if os.path.exists(os.path.join(sdir, "fetched.txt")):
        fetched = {ln.split()[0] for ln in open(os.path.join(sdir, "fetched.txt")) if ln.strip()}
    for e in sorted(kept | set(copies)):
        b = f"keep-epoch={e}.ckpt"
        loc = "yes" if os.path.exists(os.path.join(a.keep_dir, b)) else "no"
        vol = "yes" if (os.path.exists(os.path.join(a.vol_dir, b)) and os.path.exists(os.path.join(a.vol_dir, b + ".sha256"))) else "no"
        sl = f"keep-epoch={e}.gen.pt"
        slim = "yes" if os.path.exists(os.path.join(sdir, sl + ".sha256")) else "no"
        c = copies.get(e)
        L += [f"| {e} | {loc} | {vol} | {c['t'] if c else ''} | {c['bytes'] if c else ''} | "
              f"{c['sha'][:16] if c else ''} | {slim} | {'yes' if sl in fetched else 'no'} |"]
    if a.tb_json and os.path.exists(a.tb_json):
        tb = json.load(open(a.tb_json))
        tags = tb["tags"]
        L += ["", "## Training losses, mean per block of 25 epochs (TensorBoard scalars)", "",
              "| epochs | " + " | ".join(tags) + " |", "|---" * (len(tags) + 1) + "|"]
        for r in tb["train_blocks"]:
            L += [f"| {r['epochs']} ({r['epochs_logged']} logged) | " + " | ".join(
                "" if r[t] is None else (f"{r[t]:.3g}" if t.startswith("lr") else f"{r[t]:.4f}") for t in tags) + " |"]
        vt = tb["val_tags"]
        L += ["", "## Validation (148 held-out lines)", "", "| epoch | " + " | ".join(vt) + " |", "|---" * (len(vt) + 1) + "|"]
        for r in tb["val"]:
            L += [f"| {r['epoch']} | " + " | ".join("" if r[t] is None else f"{r[t]:.4f}" for t in vt) + " |"]
        nf = {t: n for t, n in tb["nonfinite"].items() if n}
        L += ["", f"- non-finite logged values: {nf if nf else 'none'}"]
    if eps:
        L += ["", "## Conditioning per sid (mean |cond|, sid 0..4), every 25th epoch and the last", "",
              "| epoch | wall s | it/s | dec | dp | flow | enc_q |", "|---|---|---|---|---|---|---|"]
        show = sorted(e for e in eps if (e - a.start + 1) % 25 == 0 or e == a.start)
        if max(eps) not in show:
            show.append(max(eps))
        for e in show:
            r = eps[e]
            c = r.get("cond", {})
            L += [f"| {e} | {r['wall']:.1f} | {r['its']:.2f} | " + " | ".join(" ".join(c.get(k, [])) for k in
                                                                          ["dec", "dp", "flow", "enc_q"]) + " |"]
    open(a.out + ".tmp", "w").write("\n".join(L) + "\n")
    os.replace(a.out + ".tmp", a.out)
    print("wrote", a.out, "last epoch", max(eps) if eps else None, "kept", sorted(kept))


if __name__ == "__main__":
    main()
