"""Write the phone's parity fixture: what mix_phonemize.py gives for her lines, with everything the
phone's Kotlin port (EnglishPhonemes.kt, MixedPhonemes.kt) needs to give the same without pyopenjtalk.

    python tests/make_phone_fixture.py <out.json.gz> [--lines lang_lines/out/lines_lang.tsv]

Cases: every text of tests/fixtures/golden_mixed.tsv and every line of lines_lang.tsv (her training
lines). For each: the sentences' phonemes (one string per sentence; each phoneme is one codepoint),
or null when the line is not readable. Beside them:
  cmu       the CMU entries the reference looked up and found (absent words stay absent), so the
            Kotlin test needs no 3.6 MB dictionary;
  labels    Open JTalk's labels (pyopenjtalk 0.4.1 == the phone's JNI build) for every sentence the
            reference handed to Open JTalk, keyed by that sentence;
  words     how each Latin word of the cases is read (route, source, IPA or kana; final and not);
  numbers   each number token's English words.
Needs pyopenjtalk 0.4.1 and Piper's phonemize_japanese (PIPER_SRC=<piper1-gpl>/src), and CMUDICT.
"""
import argparse
import csv
import gzip
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
POD = os.path.dirname(HERE)
sys.path.insert(0, POD)
from en_phonemize import DEFAULT_CMUDICT, DEFAULT_TABLE, EnglishWords, load_cmudict  # noqa: E402
from mix_phonemize import MixedPhonemizer, load_japanese_phonemizer  # noqa: E402


class RecordingDict(dict):
    """The CMU dictionary, noting every word looked up that it has."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.found = set()

    def __contains__(self, key):
        hit = super().__contains__(key)
        if hit:
            self.found.add(key)
        return hit

    def get(self, key, default=None):
        if super().__contains__(key):
            self.found.add(key)
        return super().get(key, default)

    def __getitem__(self, key):
        v = super().__getitem__(key)
        self.found.add(key)
        return v


class RecordingJTalk:
    """pyopenjtalk for Piper's JapanesePhonemizer, noting each sentence's labels."""

    def __init__(self, real):
        self.real = real
        self.labels = {}
        self._sentence = None

    def run_frontend(self, sentence, **kw):
        self._sentence = sentence
        return self.real.run_frontend(sentence, **kw)

    def make_label(self, njd):
        labels = self.real.make_label(njd)
        prev = self.labels.setdefault(self._sentence, list(labels))
        assert prev == list(labels), self._sentence
        return labels

    def __getattr__(self, name):
        return getattr(self.real, name)


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--lines", default=os.path.join(POD, "lang_lines", "out", "lines_lang.tsv"))
    ap.add_argument("--golden", default=os.path.join(HERE, "fixtures", "golden_mixed.tsv"))
    ap.add_argument("--table", default=DEFAULT_TABLE)
    ap.add_argument("--cmudict", default=DEFAULT_CMUDICT)
    a = ap.parse_args(argv)

    cmu = RecordingDict(load_cmudict(a.cmudict))
    ja = load_japanese_phonemizer()
    jtalk = RecordingJTalk(ja.pyopenjtalk)
    ja.pyopenjtalk = jtalk
    mp = MixedPhonemizer(a.table, a.cmudict, ja=ja)
    mp.en.cmu = cmu

    texts, seen = [], set()

    def add(text, source):
        if text and text not in seen:
            seen.add(text)
            texts.append((text, source))

    golden = {}
    with open(a.golden, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            text, enc = line.split("\t")
            golden[text] = enc
            add(text, "golden")
    with open(a.lines, encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            add(r["text"], f"lines:{r['kind']}:{r['split']}")

    cases = []
    for text, source in texts:
        ph = mp.phonemize(text)
        if source == "golden":
            enc = "NULL" if ph is None else " / ".join(" ".join(f"{ord(c):04x}" for c in s) for s in ph)
            assert enc == golden[text], f"golden_mixed.tsv is stale for {text!r}: run tests/make_golden.py"
        cases.append({"text": text, "source": source, "phonemes": None if ph is None else ["".join(s) for s in ph]})

    # Every Latin word and number token of the cases, read on its own.
    words, numbers = {}, {}
    for text, _ in texts:
        for plan in mp.plan(text):
            for t in plan.toks:
                if t.kind == "word" and t.word not in words:
                    rows = []
                    for final in (False, True):
                        r = mp.en.read(t.word, final=final)
                        rows.append([r.route, r.source, r.ipa if r.route == "en" else r.kana])
                    words[t.word] = rows
                elif t.kind == "num" and t.text not in numbers:
                    numbers[t.text] = " ".join(mp.en.spell_number(t.text))

    out = {
        "about": "Made by voice/scripts/pod/tests/make_phone_fixture.py from mix_phonemize.py; the phone's "
                 "MixedPhonemes must give the same phonemes for every case. Do not edit by hand.",
        "table_sha256": sha256(a.table),
        "cmudict_sha256": sha256(a.cmudict),
        "cmu": {w: " ".join(cmu[w]) for w in sorted(cmu.found)},
        "labels": jtalk.labels,
        "words": words,
        "numbers": numbers,
        "cases": cases,
    }
    data = json.dumps(out, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    opener = gzip.open if a.out.endswith(".gz") else open
    with opener(a.out, "wb") as g:
        g.write(data)
    n_null = sum(1 for c in cases if c["phonemes"] is None)
    print(f"{len(cases)} cases ({n_null} unreadable), {len(out['cmu'])} CMU entries, "
          f"{len(out['labels'])} Open JTalk sentences, {len(words)} words, {len(numbers)} numbers; "
          f"{len(data) / 1e6:.2f} MB raw -> {a.out} ({os.path.getsize(a.out) / 1e6:.2f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
