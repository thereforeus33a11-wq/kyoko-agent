"""Put her five-style Piper set together: one multi-speaker metadata (wav|speaker|text) in the format piper1-gpl
46c3c71 reads with --model.num_speakers > 1, her normal set (ds_mix, all of it, as stage2_lang.sh used it) as
speaker "normal" and the checked style sets as "soft", "whisper", "loud", "yell", in that order of first
appearance, so Piper's speaker_id_map is exactly normal 0, soft 1, whisper 2, loud 3, yell 4.

Usage (piper-env, from /w/piper1-gpl):
  python styles_ds.py --ds-mix /w/job/out/v2/ds_mix --style soft=/w/range_v1/soft/ds --style whisper=... \
      --style loud=... --style yell=... --lines-dir /w/job/scripts/range --lang-lines /w/job/data/lang/lines_lang.tsv \
      --her-test /w/job/data/her_test.txt --exclude yell=<file of wav names> --out <dir> --score <dir>
Writes <out>/wavs (links), <out>/metadata.csv, <out>/val_ids.txt (every set's held-out lines: never trained),
<out>/counts.json, <out>/excluded.tsv, and <score>/lines.tsv: the scoring set (each style's held-out lines with
its sid, her 60 held-out bilingual lines and her_test.txt with sid 0, the excluded lines with their style's sid).
Rows are taken as the sets' metadata.csv and val_ids.txt are now; every text is read once with the mixed
phonemizer, and a line it cannot read stops the build (Piper would stop on it too).
"""
import argparse
import csv
import json
import os
import re
import sys

import soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from mix_phonemize import MixedPhonemizer  # noqa: E402

SPEAKERS = ["normal", "soft", "whisper", "loud", "yell"]


def meta(path):
    out = []
    for line in open(path, encoding="utf-8"):
        line = line.rstrip("\n")
        if line:
            name, _, text = line.partition("|")
            out.append((name, text))
    return out


def ids(path):
    return [l.strip() for l in open(path, encoding="utf-8") if l.strip()]


def guess_kind(text):
    latin = bool(re.search(r"[A-Za-z]", text))
    kana = bool(re.search(r"[぀-ヿ一-鿿]", text))
    return "mixed" if latin and kana else ("en" if latin else "ja")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ds-mix", required=True)
    ap.add_argument("--style", action="append", required=True, help="name=ds dir, in sid order after normal")
    ap.add_argument("--lines-dir", required=True, help="folder with lines_<style>.tsv (kind<TAB>text, line n = wav number)")
    ap.add_argument("--lang-lines", required=True)
    ap.add_argument("--her-test", required=True)
    ap.add_argument("--exclude", action="append", default=[], help="style=file of wav names left out of training")
    ap.add_argument("--out", required=True)
    ap.add_argument("--score", required=True)
    a = ap.parse_args()

    styles = [s.split("=", 1) for s in a.style]
    assert [n for n, _ in styles] == SPEAKERS[1:], f"styles must be given in sid order {SPEAKERS[1:]}"
    excluded = {}
    for spec in a.exclude:
        st, path = spec.split("=", 1)
        excluded[st] = set(ids(path))
    mp = MixedPhonemizer()
    lang = {int(r["n"]): r for r in csv.DictReader(open(a.lang_lines, encoding="utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE)}

    sets = [("normal", a.ds_mix)] + styles
    rows = {s: {"train": [], "val": []} for s in SPEAKERS}   # (name, text, kind, wav path)
    report = {}
    seen = {}
    excl_rows = []
    for sid, (spk, d) in enumerate(sets):
        m = meta(os.path.join(d, "metadata.csv"))
        val = set(ids(os.path.join(d, "val_ids.txt")))
        names = {n for n, _ in m}
        assert val <= names, f"{spk}: held-out ids not in metadata: {sorted(val - names)[:5]}"
        table = None
        if spk != "normal":
            table = [l.rstrip("\n").split("\t", 1) for l in open(os.path.join(a.lines_dir, f"lines_{spk}.tsv"), encoding="utf-8")]
        ex = excluded.get(spk, set())
        assert ex <= names, f"{spk}: excluded ids not in metadata: {sorted(ex - names)}"
        text_mismatch = 0
        for name, text in m:
            if name in seen:
                raise SystemExit(f"wav name {name} in both {seen[name]} and {spk}")
            seen[name] = spk
            wav = os.path.realpath(os.path.join(d, "wavs", name))
            assert os.path.exists(wav), f"missing wav {wav}"
            if spk == "normal":
                kind = lang[int(name[5:9])]["kind"] if name.startswith("lang_") else "ja"
            else:
                k = int(name.rsplit("_", 1)[1][:4])
                kind = {"mix": "mixed"}.get(table[k][0], table[k][0])
                if table[k][1].strip() != text.strip():
                    text_mismatch += 1
            if mp.phonemize(text) is None:
                raise SystemExit(f"{spk} {name}: the mixed phonemizer cannot read {text!r}")
            if name in ex:
                excl_rows.append((spk, sid, name, text, kind, wav))
                continue
            rows[spk]["val" if name in val else "train"].append((name, text, kind, wav))
        report[spk] = {"text_differs_from_line_list": text_mismatch}

    os.makedirs(os.path.join(a.out, "wavs"), exist_ok=True)
    # Validation rows first, one of each speaker in turn: the first five rows name the speakers in sid order
    # (Piper numbers them by first appearance) and Piper's 5 test clips (the first 5 validation rows) are one per style.
    order = []
    vals = [list(rows[s]["val"]) for s in SPEAKERS]
    while any(vals):
        for sid, v in enumerate(vals):
            if v:
                order.append((SPEAKERS[sid], v.pop(0)))
    val_names = [r[0] for _, r in order]
    for s in SPEAKERS:
        order += [(s, r) for r in rows[s]["train"]]
    assert [s for s, _ in order[:5]] == SPEAKERS
    with open(os.path.join(a.out, "metadata.csv"), "w", encoding="utf-8") as f:
        for spk, (name, text, kind, wav) in order:
            dst = os.path.join(a.out, "wavs", name)
            if os.path.lexists(dst):
                os.remove(dst)
            os.symlink(wav, dst)
            f.write(f"{name}|{spk}|{text}\n")
    open(os.path.join(a.out, "val_ids.txt"), "w", encoding="utf-8").write("\n".join(val_names) + "\n")
    with open(os.path.join(a.out, "excluded.tsv"), "w", encoding="utf-8") as f:
        f.write("speaker\tname\tkind\ttext\n")
        for spk, sid, name, text, kind, wav in excl_rows:
            f.write(f"{spk}\t{name}\t{kind}\t{text}\n")

    counts = {}
    total_train = sum(len(rows[s]["train"]) for s in SPEAKERS)
    total_sec = 0.0
    for sid, s in enumerate(SPEAKERS):
        c = {"sid": sid}
        for part in ("train", "val"):
            rs = rows[s][part]
            sec = sum(sf.info(r[3]).duration for r in rs)
            by = {}
            for r in rs:
                by[r[2]] = by.get(r[2], 0) + 1
            c[part] = {"lines": len(rs), "minutes": round(sec / 60, 2), "by_kind": dict(sorted(by.items()))}
            if part == "train":
                total_sec += sec
        c["excluded"] = sum(1 for r in excl_rows if r[0] == s)
        c.update(report[s])
        counts[s] = c
    for s in SPEAKERS:
        t = counts[s]["train"]
        t["share_of_lines"] = round(t["lines"] / total_train, 4)
        t["share_of_audio"] = round(t["minutes"] * 60 / total_sec, 4)
    counts["_total"] = {"train_lines": total_train, "train_hours": round(total_sec / 3600, 3),
                        "val_lines": len(val_names), "excluded": len(excl_rows)}
    json.dump(counts, open(os.path.join(a.out, "counts.json"), "w"), indent=1, ensure_ascii=False)

    # The scoring set.
    os.makedirs(a.score, exist_ok=True)
    out = []
    for r in (r for r in lang.values() if r["split"] == "holdout"):
        out.append(dict(sid=0, style="normal", group="holdout_lang", kind=r["kind"], text=r["text"], ref="", name=f"lang_{int(r['n']):04d}"))
    for t in (l.split("|", 1)[-1].strip() for l in open(a.her_test, encoding="utf-8") if l.strip()):
        out.append(dict(sid=0, style="normal", group="her_test", kind="ja", text=t, ref="", name=""))
    for sid, s in enumerate(SPEAKERS):
        if s == "normal":
            continue
        for name, text, kind, wav in rows[s]["val"]:
            out.append(dict(sid=sid, style=s, group=f"{s}_val", kind=kind, text=text, ref=wav, name=name))
    for spk, sid, name, text, kind, wav in excl_rows:
        out.append(dict(sid=sid, style=spk, group=f"{spk}_{kind}_excluded", kind=kind, text=text, ref=wav, name=name))
    keys = ["n", "sid", "style", "group", "kind", "name", "ref", "text"]
    with open(os.path.join(a.score, "lines.tsv"), "w", encoding="utf-8") as f:
        f.write("\t".join(keys) + "\n")
        for n, r in enumerate(out):
            assert "\t" not in r["text"] and "\n" not in r["text"]
            r["n"] = n
            f.write("\t".join(str(r[k]) for k in keys) + "\n")
    groups = {}
    for r in out:
        groups[r["group"]] = groups.get(r["group"], 0) + 1
    counts["_scoring_set"] = groups
    json.dump(counts, open(os.path.join(a.out, "counts.json"), "w"), indent=1, ensure_ascii=False)
    print(json.dumps(counts, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
