"""Build her English and mixed voice lines: normalize them the way the phone does, phonemize them,
check them, set aside held-out lines, order the English ones for phoneme coverage, and write the
teacher's input.

Usage (from voice/scripts/pod, with pyopenjtalk 0.4.1 and Piper's phonemize_japanese reachable):
    python build_lang_lines.py [--src lang_lines] [--out lang_lines/out] [--auto-tails 220]

Reads   <src>/en_*.txt (category = file name), <src>/tatoeba.tsv (category<TAB>text), <src>/mixed_*.txt
Writes  <out>/lines_lang.tsv  n, kind (en/mixed), category, split (train/holdout), rank, text, teacher lang, teacher text
        <out>/speak_lang.txt  "lang|teacher text", line n = row n of lines_lang.tsv (speak.py's input)
        <out>/coverage.txt    English symbol counts and the features the picker aimed at
        <out>/review.txt      words read by a fallback, banned words, dropped lines
The canonical text (column text) is what the phone's phonemizer will get for the same typed line:
her typing (lowercase, no apostrophes, romaji) after the persona pass of SpeechTextNormalizer.
"""
import argparse
import glob
import hashlib
import os
import random
import re
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from mix_phonemize import MixedPhonemizer  # noqa: E402

# SpeechTextNormalizer.CONTRACTIONS (opendroid app), the words she types without an apostrophe.
CONTRACTIONS = {
    "dont": "don't", "cant": "can't", "wont": "won't", "im": "I'm", "ive": "I've",
    "youre": "you're", "youve": "you've", "thats": "that's", "whats": "what's",
    "isnt": "isn't", "arent": "aren't", "wasnt": "wasn't", "werent": "weren't",
    "doesnt": "doesn't", "didnt": "didn't", "couldnt": "couldn't",
    "shouldnt": "shouldn't", "wouldnt": "wouldn't", "havent": "haven't",
    "hasnt": "hasn't", "theyre": "they're", "theres": "there's", "heres": "here's",
    "hes": "he's", "shes": "she's", "aint": "ain't",
    "youll": "you'll", "theyll": "they'll", "itll": "it'll", "thatll": "that'll",
    "whos": "who's", "hows": "how's", "wheres": "where's",
    "wouldve": "would've", "couldve": "could've", "shouldve": "should've",
    "theyve": "they've", "weve": "we've", "hadnt": "hadn't",
}
# Her canon's "never out of her mouth" list (kisaragi-voice): a line with one is flagged.
NEVER = set("""bro dude bestie queen slay vibe cringe sus bet ngl lowkey hella gonna wanna gotta yall aint
whatcha babe sweetie""".split())
NEVER_PHRASES = ["real talk", "no worries", "of course", "happy to", "let me know", "great question",
                 "i understand", "my bad", "thank you"]
TAILS = [" jan", " ne", " kedo", " yo", " ne", " jan", " shi"]
OPENERS = ["maji, ", "tch. ", "oi, ", "yabai. ", "heh. ", "baka. ", "mou. ", "hah? "]
EN_SYMBOLS_SKIP = set(" ,.?!ˈˌː")


def persona_pass(text: str) -> str:
    """The parts of SpeechTextNormalizer.normalize(personaVoice=true, lexicon=empty) her lines meet."""
    t = re.sub(r"[~〜～]+", "", text)
    t = re.sub(r"(?i)(?<![a-z0-9])w{3,}(?![a-z0-9])", "haha", t)
    t = re.sub(r"(?i)(?<![a-z0-9])fu{2,}n(?![a-z0-9])", "hmm", t)
    t = re.sub(r"(?<![A-Za-z0-9])(?<!\d )mm(?![A-Za-z0-9])", "hm", t)
    t = re.sub(r"(?<![\w'@._-])[A-Za-z][A-Za-z;']*(?![\w@_-])(?!\.\w)",
               lambda m: CONTRACTIONS.get(m.group(0), m.group(0)), t)
    t = re.sub(r"\s*\n+\s*", ". ", t.strip())
    t = re.sub(r"[ \t ]+", " ", t)
    t = re.sub(r"\s+([.,!?])", r"\1", t)
    return t.strip()


def key(text: str) -> str:
    return re.sub(r"[^a-z぀-ヿ一-鿿]", "", text.lower())


def en_features(phones_sentences, plan_segments_en):
    """English symbol counts plus the features the picker covers: consonant clusters, word-final
    consonants, r/l, th, v."""
    c = Counter()
    for word in plan_segments_en:
        letters = [ch for ch in word if ch not in "ˈˌ"]
        for ch in letters:
            if ch not in EN_SYMBOLS_SKIP:
                c["sym:" + ch] += 1
        cons = [ch for ch in letters if ch in CONSONANTS]
        s = "".join("C" if ch in CONSONANTS else ("V" if ch in VOWELS else "") for ch in letters)
        c["cluster"] += len(re.findall(r"CC", s))
        if letters and letters[-1] in CONSONANTS:
            c["final:" + letters[-1]] += 1
        for ch in cons:
            if ch in "ɹl":
                c["rl"] += 1
            if ch in "θð":
                c["th"] += 1
            if ch == "v":
                c["v"] += 1
    return c


CONSONANTS = set("bdfhjklmnprstvwzŋðθʃʒɡɹ")
VOWELS = set("aeiouæɑɔəɚɛɜɪʊʌ")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.path.join(HERE, "lang_lines"))
    ap.add_argument("--out", default=os.path.join(HERE, "lang_lines", "out"))
    ap.add_argument("--auto-tails", type=int, default=220, help="English statements given one of her tails or openers")
    ap.add_argument("--holdout-en", type=int, default=40)
    ap.add_argument("--holdout-mixed", type=int, default=20)
    ap.add_argument("--min-count", type=int, default=200, help="each English symbol at least this often")
    ap.add_argument("--seed", type=int, default=11)
    a = ap.parse_args()
    mp = MixedPhonemizer()
    rnd = random.Random(a.seed)

    raw = []  # (category, typed text)
    for path in sorted(glob.glob(os.path.join(a.src, "en_*.txt")) + sorted(glob.glob(os.path.join(a.src, "mixed_*.txt")))):
        cat = os.path.basename(path)[:-4]
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#"):
                raw.append((cat, line))
    tat = os.path.join(a.src, "tatoeba.tsv")
    if os.path.exists(tat):
        for line in open(tat, encoding="utf-8"):
            cat, _, text = line.rstrip("\n").partition("\t")
            if text:
                raw.append(("tatoeba_" + cat, text))

    # Her tails and openers on some plain English statements (the canon's small switches).
    statements = [t for c, t in raw if c in ("en_street", "en_jflavour") and not t.endswith("?") and len(t.split()) >= 3]
    rnd.shuffle(statements)
    for k, t in enumerate(statements[:a.auto_tails]):
        if k % 3 == 2:
            raw.append(("mixed_auto", OPENERS[k % len(OPENERS)] + t))
        else:
            raw.append(("mixed_auto", t.rstrip(".") + TAILS[k % len(TAILS)]))

    os.makedirs(a.out, exist_ok=True)
    review = open(os.path.join(a.out, "review.txt"), "w", encoding="utf-8")
    seen, items = set(), []
    fallback = Counter()
    for cat, typed in raw:
        text = persona_pass(typed)
        k = key(text)
        if not k or k in seen:
            continue
        seen.add(k)
        low = text.lower()
        bad = [w for w in re.findall(r"[a-z']+", low) if w in NEVER] + \
            [p for p in NEVER_PHRASES if re.search(r"\b" + re.escape(p) + r"\b", low)]
        if bad:
            review.write(f"banned\t{', '.join(bad)}\t{text}\n")
            continue
        phones = mp.phonemize(text)
        if not phones:
            review.write(f"unreadable\t\t{text}\n")
            continue
        plans = mp.plan(text)
        has_ja = any(seg.route == "ja" for p in plans for seg in p.segments) or any(p.verbatim for p in plans)
        has_en = any(seg.route == "en" for p in plans for seg in p.segments)
        en_words = []
        for p in plans:
            for seg in p.segments:
                for t in seg.toks:
                    if t.kind == "word" and t.route == "en":
                        en_words.append(t.reading.ipa)
                        if t.reading.source in ("compound", "letter", "suffix"):
                            fallback[(t.reading.source, t.text.lower())] += 1
                    elif t.kind == "word" and t.route == "ja" and t.reading.source in ("romaji", "loose"):
                        fallback[(t.reading.source, t.text.lower())] += 1
                    elif t.kind == "num" and t.route == "en":
                        en_words += [mp.en.read(w).ipa for w in mp.en.spell_number(t.text)]
        kind = "mixed" if has_ja else "en"
        if kind == "en" and cat.startswith("mixed"):
            review.write(f"no japanese\t{cat}\t{text}\n")
        if not has_en and cat.startswith("en"):
            review.write(f"no english\t{cat}\t{text}\n")
        lang, teacher = mp.teacher(text)
        items.append(dict(kind=kind, cat=cat, text=text, lang=lang, teacher=teacher,
                          feats=en_features(phones, en_words), n_ph=sum(len(s) for s in phones)))
    for (src, w), n in sorted(fallback.items()):
        review.write(f"fallback {src}\t{w}\t{n}\n")

    # Held-out lines: never trained on, spoken by the teacher for scoring.
    en_items = [it for it in items if it["kind"] == "en"]
    mixed_items = [it for it in items if it["kind"] == "mixed"]
    for group, n in ((en_items, a.holdout_en), (mixed_items, a.holdout_mixed)):
        order = sorted(group, key=lambda it: hashlib.sha256(it["text"].encode()).hexdigest())
        for it in order[:n]:
            it["split"] = "holdout"
    for it in items:
        it.setdefault("split", "train")

    # Greedy coverage order for English training lines: fill each symbol's deficit first.
    pool = [it for it in en_items if it["split"] == "train"]
    target = Counter()
    for it in pool:
        for f in it["feats"]:
            target[f] = a.min_count if f.startswith("sym:") else 0
    have = Counter()
    left = list(pool)
    rnd.shuffle(left)

    def gain(it):
        g = sum(min(v, max(0, target[f] - have[f])) for f, v in it["feats"].items() if target[f])
        return g / max(1.0, it["n_ph"] ** 0.5)

    # Lazy greedy: a line's gain only falls as others are picked, so a stale gain is an upper bound.
    import heapq
    heap = [(-gain(it), k) for k, it in enumerate(left)]
    heapq.heapify(heap)
    ranked, taken = [], set()
    while heap:
        neg, k = heapq.heappop(heap)
        if -neg <= 0:
            break
        g = gain(left[k])
        if heap and g < -heap[0][0]:
            heapq.heappush(heap, (-g, k))
            continue
        if g <= 0:
            break
        ranked.append(left[k]); taken.add(k); have.update(left[k]["feats"])
    left = [it for k, it in enumerate(left) if k not in taken]
    ranked += left  # the rest, in seeded random order
    for r, it in enumerate(ranked):
        it["rank"] = r
    for it in items:
        it.setdefault("rank", -1)

    rows = sorted(items, key=lambda it: (it["kind"] != "en", it["split"] != "train", it["rank"] if it["rank"] >= 0 else 10**6, it["text"]))
    with open(os.path.join(a.out, "lines_lang.tsv"), "w", encoding="utf-8") as f, \
            open(os.path.join(a.out, "speak_lang.txt"), "w", encoding="utf-8") as g:
        f.write("n\tkind\tcategory\tsplit\trank\ttext\tteacher_lang\tteacher_text\n")
        for n, it in enumerate(rows):
            f.write(f"{n}\t{it['kind']}\t{it['cat']}\t{it['split']}\t{it['rank']}\t{it['text']}\t{it['lang']}\t{it['teacher']}\n")
            g.write(f"{it['lang']}|{it['teacher']}\n")

    total = Counter()
    for it in pool:
        total.update(it["feats"])
    with open(os.path.join(a.out, "coverage.txt"), "w", encoding="utf-8") as c:
        cats = Counter(it["cat"] for it in items)
        c.write(f"lines: {len(items)} ({len(en_items)} English, {len(mixed_items)} mixed); holdout "
                f"{sum(1 for it in items if it['split'] == 'holdout')}\n")
        c.write("by category: " + ", ".join(f"{k} {v}" for k, v in sorted(cats.items())) + "\n")
        c.write(f"English training lines: {len(pool)}; symbol counts (target {a.min_count}):\n")
        for f, v in sorted(total.items(), key=lambda kv: kv[1]):
            if f.startswith("sym:"):
                c.write(f"  {f[4:]}\t{v}{'  LOW' if v < a.min_count else ''}\n")
        c.write("features: " + ", ".join(f"{k} {v}" for k, v in sorted(total.items()) if not k.startswith("sym:")) + "\n")
    review.close()
    print(open(os.path.join(a.out, "coverage.txt"), encoding="utf-8").read())


if __name__ == "__main__":
    main()
