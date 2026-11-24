"""Word error of the English (and English-led mixed) soft takes, the v2 bilingual set's way (check_lang.py asr):
Whisper's EnglishTextNormalizer on both sides; English lines (substitutions + deletions + insertions) / words;
English-led mixed lines: the Japanese words are left out of the reference and extra words in what was heard
are not counted, (substitutions + deletions) / English words.
One addition (2026-11-24): she types "its fine", "lets stay" without the apostrophe (the persona pass leaves these
two as typed), the recogniser writes "It's fine", "Let's stay", and the normalizer then expands only the heard side
("it is", "let us"), so a take spoken exactly right scored 0.29-0.33. The error is therefore also taken with the
apostrophes inside words removed on BOTH sides before normalizing (its = it's, lets = let's, crows = crow's: the
same sounds), and the lower of the two is the take's error. err_plain keeps the first one.

Usage (asr-env): python en_wer.py <lines.tsv> <heard.tsv> <out.tsv>
"""
import csv, re, sys

sys.path.insert(0, "/w/job/scripts")
from check_lang import edit_ops, english_normalizer  # noqa: E402

lines_p, heard_p, out_p = sys.argv[1:4]
norm = english_normalizer(None)
strip = lambda t: re.sub(r"(?<=[A-Za-z])['’](?=[A-Za-z])", "", t)
rows = {int(r["n"]): r for r in csv.DictReader(open(lines_p, encoding="utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE)}
out = open(out_p, "w", encoding="utf-8")
out.write("file\tlang\terr\tn_ref\tref\thyp\terr_plain\n")
n = 0
for r in csv.DictReader(open(heard_p, encoding="utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE):
    if r["lang"] != "en":
        continue
    line = rows[int(r["file"][:4])]

    def err(f):
        ref = norm(f(line["en_ref"])).split(); hyp = norm(f(r["heard"] or "")).split()
        sd, ins = edit_ops(ref, hyp)
        return ((sd + ins) / max(1, len(ref)) if line["kind"] == "en" else sd / max(1, len(ref))), ref, hyp
    e1, ref, hyp = err(lambda t: t)
    e2, _, _ = err(strip)
    out.write(f"{r['file']}\ten\t{min(e1, e2):.3f}\t{len(ref)}\t{' '.join(ref)}\t{' '.join(hyp)}\t{e1:.3f}\n"); n += 1
out.close()
print(f"en_wer: {n} takes scored into {out_p}")
