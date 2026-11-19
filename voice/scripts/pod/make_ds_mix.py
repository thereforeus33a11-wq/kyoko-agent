"""Put her bilingual Piper set together: Japanese replay lines from her stage-1 set (so her Japanese is
not forgotten) and the checked English and mixed lines from check_lang.py, in one folder Piper reads.

Usage (piper-env, from /w/piper1-gpl):
  python make_ds_mix.py --ja-ds /w/job/out/ds --lang-ds /w/job/out/lang/ds_lang \
      --lines /w/job/data/lang/lines_lang.tsv --out /w/job/out/ds_mix [--ja-n 1500] [--max-en 2400]
Writes <out>/wavs (links), <out>/metadata.csv (file|text), <out>/val_ids.txt (the held-out English and
mixed lines, and --ja-val Japanese lines, all left out of training), <out>/summary.txt.
Every Japanese replay line is checked to phonemize exactly as Piper's own JapanesePhonemizer does
(what e800 learned); a line with Latin letters or one of her_test.txt's lines is left out.
"""
import argparse
import csv
import hashlib
import os
import re
import sys

import soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from mix_phonemize import MixedPhonemizer, load_japanese_phonemizer  # noqa: E402


def meta(path):
    out = []
    for line in open(path, encoding="utf-8"):
        line = line.rstrip("\n")
        if line:
            name, _, text = line.partition("|")
            out.append((name, text))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ja-ds", required=True)
    ap.add_argument("--lang-ds", required=True)
    ap.add_argument("--lines", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ja-n", type=int, default=1500)
    ap.add_argument("--ja-val", type=int, default=20, help="Japanese lines that only validate (watch for forgetting)")
    ap.add_argument("--max-en", type=int, default=2400, help="English training lines, best-covering first")
    ap.add_argument("--her-test", default=os.path.join(HERE, "her_test.txt"))
    a = ap.parse_args()
    ja_ph = load_japanese_phonemizer()
    mp = MixedPhonemizer(ja=ja_ph)
    os.makedirs(os.path.join(a.out, "wavs"), exist_ok=True)
    test = {l.split("|", 1)[-1].strip() for l in open(a.her_test, encoding="utf-8") if l.strip()}

    ja_rows, skipped = [], {"latin": 0, "her_test": 0, "parity": 0, "missing": 0}
    for name, text in sorted(meta(os.path.join(a.ja_ds, "metadata.csv")), key=lambda r: hashlib.sha256(r[1].encode()).hexdigest()):
        if len(ja_rows) >= a.ja_n + a.ja_val:
            break
        if re.search(r"[A-Za-zＡ-Ｚａ-ｚ]", text):
            skipped["latin"] += 1; continue
        if text.strip() in test:
            skipped["her_test"] += 1; continue
        if not os.path.exists(os.path.join(a.ja_ds, "wavs", name)):
            skipped["missing"] += 1; continue
        if mp.phonemize(text) != ja_ph.phonemize(text):
            skipped["parity"] += 1
            print("parity mismatch, left out:", text, file=sys.stderr)
            continue
        ja_rows.append((name, text))

    lines = {int(r["n"]): r for r in csv.DictReader(open(a.lines, encoding="utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE)}
    val = {l.strip() for l in open(os.path.join(a.lang_ds, "val_ids.txt"), encoding="utf-8") if l.strip()}
    lang_rows, counts = [], {"en": 0, "mixed": 0, "holdout": 0, "en_over_max": 0, "unreadable": 0}
    for name, text in meta(os.path.join(a.lang_ds, "metadata.csv")):
        r = lines[int(name[5:9])]
        if r["split"] == "holdout":
            counts["holdout"] += 1
        elif r["kind"] == "en":
            if int(r["rank"]) >= a.max_en:
                counts["en_over_max"] += 1; continue
            counts["en"] += 1
        else:
            counts["mixed"] += 1
        if mp.phonemize(text) is None:
            counts["unreadable"] += 1; continue
        lang_rows.append((name, text))

    with open(os.path.join(a.out, "metadata.csv"), "w", encoding="utf-8") as f:
        for src, rows in ((a.ja_ds, ja_rows), (a.lang_ds, lang_rows)):
            for name, text in rows:
                dst = os.path.join(a.out, "wavs", name)
                if os.path.lexists(dst):
                    os.remove(dst)
                os.symlink(os.path.abspath(os.path.join(src, "wavs", name)), dst)
                f.write(f"{name}|{text}\n")
    kept_val = [n for n, _ in lang_rows if n in val] + [n for n, _ in ja_rows[a.ja_n:]]
    open(os.path.join(a.out, "val_ids.txt"), "w", encoding="utf-8").write("\n".join(kept_val) + "\n")

    def hours(src, rows):
        return sum(sf.info(os.path.join(src, "wavs", n)).duration for n, _ in rows) / 3600

    summary = (f"Japanese replay {len(ja_rows)} lines, {hours(a.ja_ds, ja_rows):.2f} h (left out: {skipped})\n"
               f"English/mixed {len(lang_rows)} lines, {hours(a.lang_ds, lang_rows):.2f} h ({counts}); "
               f"validation {len(kept_val)}\n")
    open(os.path.join(a.out, "summary.txt"), "w", encoding="utf-8").write(summary)
    print(summary, end="")


if __name__ == "__main__":
    main()
