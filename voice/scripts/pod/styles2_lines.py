"""Rejudging the five-style voice: build the scoring lines (piper-env, from /w/piper1-gpl). No voice data in this file.

  python styles2_lines.py --new NEW.txt --old OLD_lines.tsv --config VOICE.onnx.json --tokens tokens.txt \
      --train META [META ...] --lists LIST [LIST ...] --private PRIVATE.list --out lines.tsv --report report.json

NEW.txt: style<TAB>kind<TAB>text, one new line per row (kind ja / en / mixed).
OLD_lines.tsv: yesterday's scoring set (score/lines.tsv: n, sid, style, group, kind, name, ref, text); kept as it is.
Every new line is checked, and the build stops if one fails:
  - not in any training metadata (--train: wav|text or wav|speaker|text files) nor in any line list (--lists: the
    sets' line lists, the bilingual lines, her_test.txt, yesterday's scoring lines): exact after normalising (NFKC,
    lower case, no punctuation or spaces), and no near copy (difflib ratio >= 0.8 on the normalised text);
  - no phrase of her private clips' transcripts (--private: path|speaker|lang|text): no common run of 8 or more
    normalised characters; only the new line is printed, never the transcript;
  - phonemized the phone's way (mix_phonemize.MixedPhonemizer, the voice's phoneme_id_map) to ids without error, every
    phoneme a token of the voice (tokens.txt), and its kind (ja / en / mixed) as the text says.
Writes lines.tsv: yesterday's rows, then the new ones (n from 1000: soft 1000.., whisper 1100.., loud 1200..,
yell 1300..; group <style>_new; ref empty).
"""
import argparse
import csv
import difflib
import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from mix_phonemize import MixedPhonemizer  # noqa: E402

STYLES = ["normal", "soft", "whisper", "loud", "yell"]


def norm(t):
    t = unicodedata.normalize("NFKC", t).lower()
    return "".join(c for c in t if not unicodedata.category(c).startswith(("P", "Z", "S", "C")))


def kind_of(text, ja_words=()):
    """ja / en / mixed by the script; a Latin word that is one of her romaji words (the English table's ja_words, read
    the Japanese way) counts as Japanese, so "baka! not that one" is mixed, as the sets' line lists call it."""
    latin = bool(re.search(r"[A-Za-z]", text))
    if latin and any(w.lower() in ja_words for w in re.findall(r"[A-Za-z]+", text)):
        return "mixed"
    kana = bool(re.search(r"[぀-ヿ一-鿿]", text))
    return "mixed" if latin and kana else ("en" if latin else "ja")


def longest_common(a, b):
    m = difflib.SequenceMatcher(None, a, b, autojunk=False).find_longest_match(0, len(a), 0, len(b))
    return m.size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--new", required=True); ap.add_argument("--old", required=True)
    ap.add_argument("--config", required=True); ap.add_argument("--tokens", required=True)
    ap.add_argument("--train", nargs="+", default=[]); ap.add_argument("--lists", nargs="+", default=[])
    ap.add_argument("--private", default="")
    ap.add_argument("--out", required=True); ap.add_argument("--report", required=True)
    a = ap.parse_args()
    known = {l.rsplit(" ", 1)[0] for l in open(a.tokens, encoding="utf-8") if l.strip()}
    id_map = json.load(open(a.config, encoding="utf-8"))["phoneme_id_map"]
    mp = MixedPhonemizer()
    table = os.environ.get("ENGLISH_TABLE", os.path.join(HERE, "en_ipa_table.json"))
    ja_words = set(json.load(open(table, encoding="utf-8"))["ja_words"]["words"])

    refs = {}   # normalised text -> source file (for the report: the file, never its text)
    for p in a.train:
        for line in open(p, encoding="utf-8"):
            line = line.rstrip("\n")
            if line:
                refs.setdefault(norm(line.split("|")[-1]), os.path.basename(os.path.dirname(os.path.dirname(p))) + "/" + os.path.basename(p))
    for p in a.lists:
        with open(p, encoding="utf-8") as f:
            first = f.readline(); f.seek(0)
            if "\ttext" in first:   # a TSV with a header: its text columns
                for r in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
                    for c in ("text", "teacher_text"):
                        if r.get(c):
                            refs.setdefault(norm(r[c]), os.path.basename(p))
                continue
            for line in f:
                line = line.rstrip("\n")
                if line:
                    refs.setdefault(norm(line.split("\t")[-1].split("|")[-1]), os.path.basename(p))
    refs.pop("", None)
    private = []
    if a.private:
        for line in open(a.private, encoding="utf-8"):
            if line.strip():
                private.append(norm(line.rstrip("\n").split("|")[-1]))
    ref_list = list(refs)

    old = list(csv.DictReader(open(a.old, encoding="utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE))
    cols = list(old[0].keys())
    new = [l.rstrip("\n").split("\t") for l in open(a.new, encoding="utf-8") if l.strip()]
    problems, rows, seen = [], [], {}
    count = {s: 0 for s in STYLES[1:]}
    oov = []
    for style, kind, text in new:
        k = norm(text)
        why = []
        if k in seen:
            why.append(f"twice in the new lines (also row {seen[k]})")
        seen[k] = len(rows)
        if k in refs:
            why.append(f"exact copy of a line in {refs[k]}")
        else:
            for r in ref_list:
                sm = difflib.SequenceMatcher(None, k, r, autojunk=False)
                if sm.real_quick_ratio() >= 0.8 and sm.quick_ratio() >= 0.8 and sm.ratio() >= 0.8:
                    why.append(f"near copy (ratio {sm.ratio():.2f}) of a line in {refs[r]}"); break
        for pv in private:
            if longest_common(k, pv) >= 8:
                why.append("shares a run of 8+ characters with one of her private clips' transcripts"); break
        if kind_of(text, ja_words) != kind:
            why.append(f"kind is {kind_of(text, ja_words)}, not {kind}")
        try:
            sents = mp.phonemize(text)
            ids = mp.ids(text, id_map)
            missing = sorted({p for s in sents for p in s if p not in known})
            if not ids:
                why.append("no phoneme ids")
            if missing:
                why.append(f"phonemes without a token {missing}")
        except Exception as e:  # noqa: BLE001
            why.append(f"phonemizer failed: {type(e).__name__}: {e}"); sents = []
        if kind != "ja":
            for w in re.findall(r"[A-Za-z']+", text):
                wl = w.lower()
                if wl not in mp.en.cmu and wl.replace("'", "") not in mp.en.cmu:
                    oov.append(w)
        sid = STYLES.index(style)
        n = 900 + 100 * sid + count[style]
        count[style] += 1
        if why:
            problems.append(dict(n=n, style=style, text=text, why=why))
        rows.append(dict(n=n, sid=sid, style=style, group=f"{style}_new", kind=kind, name=f"{style}_new_{count[style]:03d}",
                         ref="", text=text, n_ph=sum(len(s) for s in sents)))
    rep = dict(new_lines=len(rows), per_style=count, problems=problems, english_words_not_in_cmu=sorted(set(oov)),
               refs_checked=len(refs), private_checked=len(private),
               per_style_kind={s: {kd: sum(1 for r in rows if r["style"] == s and r["kind"] == kd) for kd in ("ja", "en", "mixed")} for s in STYLES[1:]})
    json.dump(rep, open(a.report, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for p in problems:
        print("PROBLEM", p["n"], p["style"], p["text"], "|", "; ".join(p["why"]))
    print(json.dumps({k: v for k, v in rep.items() if k != "problems"}, ensure_ascii=False))
    if problems:
        print("LINES-FAILED", len(problems)); sys.exit(1)
    with open(a.out + ".tmp", "w", encoding="utf-8") as o:
        o.write("\t".join(cols) + "\n")
        for r in old:
            o.write("\t".join(r[c] for c in cols) + "\n")
        for r in rows:
            o.write("\t".join(str(r.get(c, "")) for c in cols) + "\n")
    os.replace(a.out + ".tmp", a.out)
    print("LINES-DONE", len(old), "old +", len(rows), "new")


if __name__ == "__main__":
    main()
