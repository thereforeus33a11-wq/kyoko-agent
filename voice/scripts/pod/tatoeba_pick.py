"""Pick English sentences from Tatoeba for her voice lines: the textbook English a Japanese school
teaches (Tatoeba's English-Japanese pairs come largely from the Tanaka corpus of school sentences)
and plain everyday lines. Tatoeba sentences are CC BY 2.0 FR (https://tatoeba.org); this run used the
en-ja subset of the sentence-transformers/parallel-sentences-tatoeba copy on Hugging Face.

Usage: python tatoeba_pick.py <english<TAB>japanese .tsv> <out.tsv> [--school 500] [--everyday 260]
Out: category<TAB>text, lowercase, in her typing (no apostrophes; the voice's normalizer puts them
back the way the phone does).
"""
import argparse
import random
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from en_phonemize import EnglishWords, DEFAULT_CMUDICT, DEFAULT_TABLE  # noqa: E402

# Words she never says (her canon, "never out of her mouth"), words that make her a child, and
# topics a voice corpus does not need.
BANNED = set("""
bro dude bestie queen slay vibe vibes cringe sus bet ngl lowkey hella gonna wanna gotta yall aint whatcha babe sweetie
sorry thank thanks thankful grateful please apologize apology pardon excuse
mom mommy mum dad daddy mother father mothers fathers parents parent grandma grandpa grandmother grandfather uncle aunt
son sons daughter daughters wife husband wives husbands children child kids kid baby babies boy boys toy toys
teacher teachers homework classmate classmates kindergarten elementary student students pupil pupils principal grade
die died dies dead death kill killed kills murder murdered suicide war wars gun guns bomb soldier soldiers army enemy
cancer funeral grave hospital sick disease illness doctor nurse patient blood hurt injured accident accidents
sex sexy naked nude kiss kissed kissing breast breasts
god gods jesus christ church pray prayed prayer bible heaven hell soul sin religion
president government election politics political minister king queen prince princess emperor
sir madam mr mrs miss ms shall whom thee thou thy hath
""".split())

ALLOWED_CAPS = set("""I I'm I'll I've I'd English Japanese Japan Tokyo Christmas OK TV
Monday Tuesday Wednesday Thursday Friday Saturday Sunday
January February March April May June July August September October November December""".split())

# Textbook patterns and exam words (Japanese high school English).
SCHOOL = [r"\bas far as\b", r"\bi'?d rather\b", r"\bwould rather\b", r"\bhad better\b", r"\bnot only\b",
          r"\bbut also\b", r"\bthe more\b", r"\bno matter\b", r"\bit is no use\b", r"\bcannot help\b",
          r"\bcan'?t help\b", r"\btoo \w+ to\b", r"\benough to\b", r"\bused to\b", r"\bso that\b",
          r"\bin order to\b", r"\bas soon as\b", r"\bas long as\b", r"\beven if\b", r"\beven though\b",
          r"\balthough\b", r"\bunless\b", r"\bwhether\b", r"\bhowever\b", r"\btherefore\b", r"\bin spite of\b",
          r"\binstead of\b", r"\baccording to\b", r"\bbecause of\b", r"\bin case\b", r"\bi wish\b",
          r"\bif i were\b", r"\bshould have\b", r"\bmust have\b", r"\bmight have\b", r"\bit seems\b",
          r"\bit takes\b", r"\bit'?s not that\b", r"\bmake sense\b", r"\bon the other hand\b", r"\bwhat if\b",
          r"\bhow come\b", r"\bit is said\b", r"\bnot \w+ at all\b", r"\bbe supposed to\b", r"\bsupposed to\b",
          r"\bas if\b", r"\bso \w+ that\b", r"\bsuch a\b", r"\bboth \w+ and\b", r"\beither\b", r"\bneither\b",
          r"\bwhoever\b", r"\bwhatever\b", r"\bwherever\b", r"\bwhenever\b", r"\bit'?s worth\b", r"\bby the time\b",
          r"\bin the end\b", r"\bat least\b", r"\bat most\b", r"\bafter all\b", r"\bin fact\b", r"\bto be honest\b"]
EXAM = set("""apparently obviously probably necessary impossible responsible experience opportunity relationship
environment advantage disadvantage decision situation attitude independent embarrassed disappointed confident
suppose expect admit realize recognize consider describe explain complain insist refuse pretend manage afford deserve
avoid regret promise imagine remind persuade prefer particular especially exactly completely absolutely definitely
basically actually certainly honestly surprisingly unfortunately fortunately anyway otherwise nevertheless
ridiculous terrible awful annoying boring curious jealous nervous serious stubborn generous selfish honest polite rude
convenient comfortable expensive reasonable delicious favorite opinion reason result effort chance habit rumor
promise secret mistake trouble difference advice permission patience courage""".split())


def her_typing(text: str) -> str:
    t = text.strip().replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    t = t.lower().replace("'", "")
    t = re.sub(r"\s+", " ", t)
    t = t.rstrip("!").rstrip()
    if not t.endswith(("?", ".")):
        t += "."
    # A plain statement ends without a full stop, the way she types; questions keep theirs.
    if t.endswith(".") and not t.endswith(".."):
        t = t[:-1]
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("out")
    ap.add_argument("--school", type=int, default=500)
    ap.add_argument("--everyday", type=int, default=260)
    ap.add_argument("--questions-only", action="store_true", default=True,
                    help="everyday lines are questions only (the school lines carry the statements)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--table", default=DEFAULT_TABLE)
    ap.add_argument("--cmudict", default=DEFAULT_CMUDICT)
    a = ap.parse_args()
    en = EnglishWords(a.table, a.cmudict)
    seen, school, everyday = set(), [], []
    reasons = {}
    with open(a.src, encoding="utf-8") as f:
        english = [line.split("\t", 1)[0].strip() for line in f]
    # Words seen in lowercase somewhere: a capitalised first word that never is, is a name.
    lower_words = set(w for e in english for w in re.findall(r"\b[a-z][a-z']*", e))
    for e in english:
        if True:
            key = re.sub(r"[^a-z ]", "", e.lower())
            if not e or key in seen:
                continue
            seen.add(key)
            why = reject(e, en, lower_words)
            if why:
                reasons[why] = reasons.get(why, 0) + 1
                continue
            low = e.lower()
            is_school = any(re.search(p, low) for p in SCHOOL) or len(set(re.findall(r"[a-z']+", low)) & EXAM) > 0
            if is_school:
                school.append(e)
            elif not a.questions_only or e.endswith("?"):
                everyday.append(e)
    rnd = random.Random(a.seed)
    rnd.shuffle(school); rnd.shuffle(everyday)
    out = pick(school, a.school, "school") + pick(everyday, a.everyday, "qa")
    with open(a.out, "w", encoding="utf-8") as g:
        for cat, e in out:
            g.write(f"{cat}\t{her_typing(e)}\n")
    print(f"school pool {len(school)}, everyday pool {len(everyday)}; wrote {len(out)} to {a.out}")
    print("rejected:", ", ".join(f"{k} {v}" for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])))


def reject(e: str, en: EnglishWords, lower_words: set):
    if not e.isascii():
        return "not ascii"
    if re.search(r"[0-9]", e):
        return "digits"
    if not e.endswith((".", "?", "!")) or re.search(r"[;:\"()\-]", e):
        return "punctuation"
    words = re.findall(r"[A-Za-z']+", e)
    if not 3 <= len(words) <= 15:
        return "length"
    for k, w in enumerate(words):
        if w[0].isupper() and k > 0 and w not in ALLOWED_CAPS:
            return "name"
    if words[0] not in ALLOWED_CAPS and words[0].lower() not in lower_words:
        return "name"
    # She dodges these: without the apostrophe they read as other words (ill, well, shell, wed).
    if re.search(r"\b(i|we|he|she)'(ll|d)\b", e, re.I):
        return "ill/well"
    if re.search(r"\b(deserve to live|want to live|end it all|doll|dolls)\b", e, re.I):
        return "banned word"
    low = [w.lower().strip("'") for w in words]
    if any(w in BANNED or w.replace("'s", "") in BANNED for w in low):
        return "banned word"
    for w in low:
        r = en.read(w)
        if r.route != "en" or r.source in ("compound", "letter"):
            return "not plain English"
    if len(e) > 90:
        return "length"
    return None


def pick(pool, n, cat):
    """n lines, spread over openings: at most 3 lines share their first two words."""
    out, openings = [], {}
    for e in pool:
        op = " ".join(e.lower().split()[:2])
        if openings.get(op, 0) >= 3:
            continue
        openings[op] = openings.get(op, 0) + 1
        out.append((cat, e))
        if len(out) >= n:
            break
    return out


if __name__ == "__main__":
    main()
