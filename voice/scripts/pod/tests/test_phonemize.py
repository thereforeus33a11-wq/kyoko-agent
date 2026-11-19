"""Tests for en_phonemize.py and mix_phonemize.py (run: python -m unittest discover -s tests -v).

The Japanese parts need pyopenjtalk 0.4.1 and Piper's phonemize_japanese.py (installed piper, or
PIPER_SRC=<piper1-gpl>/src); without them those tests are skipped. CMUDICT points at cmudict.dict.
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
POD = os.path.dirname(HERE)
sys.path.insert(0, POD)

from en_phonemize import EnglishWords, load_cmudict, plain_latin, romaji_to_hiragana  # noqa: E402
from mix_phonemize import MixedPhonemizer, phonemes_to_ids  # noqa: E402

CMUDICT = os.environ.get("CMUDICT", "/tmp/claude-0/cmudict/cmudict.dict")
TABLE = os.path.join(POD, "en_ipa_table.json")
FIX = os.path.join(HERE, "fixtures")


def read_lines(path):
    with open(path, encoding="utf-8") as f:
        return [l.rstrip("\n") for l in f]


def rows(name):
    for line in read_lines(os.path.join(FIX, name)):
        if line and not line.startswith("#"):
            yield line.split("\t")


def tokens():
    out = {}
    for line in read_lines(os.path.join(FIX, "tokens.txt")):
        if not line:
            continue
        sym, _, i = line.rpartition(" ")
        out[sym] = int(i)
    return out


try:
    import pyopenjtalk  # noqa: F401
    from mix_phonemize import load_japanese_phonemizer
    JA = load_japanese_phonemizer()
except Exception:  # pragma: no cover
    JA = None

CMU = load_cmudict(CMUDICT)
EN = EnglishWords(TABLE, CMUDICT, cmu=CMU)
MP = MixedPhonemizer(TABLE, CMUDICT, ja=JA) if JA is not None else None


class TableTest(unittest.TestCase):
    def test_cmudict_is_the_pinned_one(self):
        import hashlib
        with open(TABLE, encoding="utf-8") as f:
            want = json.load(f)["cmudict"]["sha256"]
        with open(CMUDICT, "rb") as f:
            self.assertEqual(hashlib.sha256(f.read()).hexdigest(), want)

    def test_every_symbol_has_an_id(self):
        ids = tokens()
        t = EN.t
        texts = list(t["vowels"].values()) + list(t["consonants"].values()) + list(t["stress_marks"].values())
        texts += [v for d in t["vowels_by_stress"].values() for v in d.values()]
        texts += [v for d in t["r_vowel_before_vowel"]["vowels"].values() for v in d.values()]
        texts += [w["ipa"] for w in t["weak_forms"]["words"].values()]
        texts += [w["strong"] for w in t["weak_forms"]["words"].values() if "strong" in w]
        texts += [t["boundaries"][k] for k in ("word", "clause", "after_clause", "switch", "sentence_end_default")]
        texts += list(set(t["segmentation"]["terminal_punct"].values()))
        for text in texts:
            for c in text:
                self.assertIn(c, ids, f"{c!r} (U+{ord(c):04X}) from {text!r} has no id in tokens.txt")
        self.assertNotIn("g", "".join(texts), "ASCII g is another id: use U+0261")

    def test_arpabet_entries_convert(self):
        for w, p in EN.t["word_overrides"]["words"].items():
            EN.arpabet_to_ipa(p.split())
        for w, p in EN.t["letters"].items():
            EN.arpabet_to_ipa(p.split())
        for rule in EN.t["suffixes"]["rules"]:
            if rule["add"] not in EN.t["suffixes"]["voicing"]:
                EN.arpabet_to_ipa(rule["add"].split())

    def test_ja_words_are_kana(self):
        for w, kana in EN.t["ja_words"]["words"].items():
            self.assertEqual(w, w.lower())
            self.assertTrue(kana and all("぀" <= c <= "ヿ" for c in kana), (w, kana))

    def test_number_words_are_in_cmu(self):
        n = EN.t["numbers"]
        words = [w for w in n["ones"] + n["tens"] if w] + [n["hundred"], n["point"], n["oh"], n["percent"], n["o_clock"]]
        words += [w for _, w in n["scales"]] + list(n["ordinal_words"].values())
        words += list(n["currency_before"].values()) + list(n["currency_singular"].values())
        for w in words:
            self.assertEqual(EN.read(w).route, "en", w)


class WordTest(unittest.TestCase):
    def test_words(self):
        for word, route, source, want in rows("en_words.tsv"):
            r = EN.read(word)
            got = r.ipa if r.route == "en" else r.kana
            self.assertEqual((r.route, r.source, got), (route, source, want), word)

    def test_strong_form_at_segment_end(self):
        self.assertEqual(EN.read("from", final=True).ipa, "fɹˈʌm")
        self.assertEqual(EN.read("from").ipa, "fɹʌm")
        self.assertEqual(EN.read("you", final=True).ipa, "juː")  # pronouns stay weak

    def test_numbers(self):
        for tok, want in rows("en_numbers.tsv"):
            self.assertEqual(" ".join(EN.spell_number(tok)), want, tok)

    def test_plain_latin(self):
        self.assertEqual(plain_latin("ｏｋ café don’t"), "ok cafe don't")
        self.assertEqual(plain_latin("が"), "が")  # kana keep their voiced marks
        self.assertEqual(plain_latin("Pokémon"), "Pokemon")

    def test_romaji(self):
        self.assertEqual(romaji_to_hiragana("kitte"), "きって")
        self.assertEqual(romaji_to_hiragana("shinjuku"), "しんじゅく")
        self.assertIsNone(romaji_to_hiragana("crazy"))


class SentenceTest(unittest.TestCase):
    def setUp(self):
        self.mp = MP or MixedPhonemizer(TABLE, CMUDICT, ja=_NoJapanese())

    def test_split(self):
        sp = self.mp.split_sentences
        self.assertEqual(sp("ok. fine"), ["ok.", "fine"])
        self.assertEqual(sp("it costs 1.5 man"), ["it costs 1.5 man"])
        self.assertEqual(sp("whatever... fine"), ["whatever... fine"])
        self.assertEqual(sp("Mr. Tanaka is here."), ["Mr. Tanaka is here."])
        self.assertEqual(sp("は？なにそれ。うける"), ["は？", "なにそれ。", "うける"])
        self.assertEqual(sp("why? because."), ["why?", "because."])

    def test_english_only_needs_no_japanese(self):
        mp = MixedPhonemizer(TABLE, CMUDICT, ja=_NoJapanese())
        self.assertEqual(["".join(s) for s in mp.phonemize("okay, whatever.")], ["ˌoʊkˈeɪ, wˌʌtˈɛvɚ."])

    def test_teacher_text(self):
        mp = self.mp
        self.assertEqual(mp.teacher("meet at 5 ok?"), ("en", "meet at five ok?"))
        self.assertEqual(mp.teacher("salt & pepper"), ("en", "salt and pepper"))
        self.assertEqual(mp.teacher("i pay 500 yen ne"), ("ja", "i pay five hundred yen ね"))
        self.assertEqual(mp.teacher("ii jan. keep that one"), ("ja", "いいじゃん. keep that one"))

    def test_ids_are_pipers(self):
        id_map = {k: [v] for k, v in tokens().items()}
        ph = ["h", "ˈ", "a"]
        self.assertEqual(phonemes_to_ids(ph, id_map),
                         [id_map["^"][0], 0, id_map["h"][0], 0, id_map["ˈ"][0], 0, id_map["a"][0], 0, id_map["$"][0]])


@unittest.skipIf(MP is None, "pyopenjtalk / Piper's phonemize_japanese not available")
class MixedTest(unittest.TestCase):
    def test_fixtures(self):
        for text, want in rows("mixed.tsv"):
            got = MP.phonemize(text)
            self.assertIsNotNone(got, text)
            self.assertEqual(" / ".join("".join(s) for s in got), want, text)

    def test_pure_japanese_is_pipers(self):
        lines = [l.split("|", 1)[-1].strip() for l in read_lines(os.path.join(POD, "her_test.txt")) if l.strip()]
        lines += ["は？なにそれ、マジでうける。", "べつに。あんたには関係ないし。", "ちょっと、聞いてんの？",
                  "５００円だよ。", "「ほんと」って言った。", "ねえ　ちょっと"]
        for text in lines:
            self.assertEqual(MP.phonemize(text), JA.phonemize(text), text)

    def test_every_phoneme_has_an_id(self):
        ids = tokens()
        for text, _ in rows("mixed.tsv"):
            for s in MP.phonemize(text):
                for p in s:
                    self.assertIn(p, ids, (text, p))

    def test_unreadable_is_none(self):
        self.assertIsNone(MP.phonemize("안녕"))
        self.assertEqual(MP.phonemize("..."), [])


class _NoJapanese:
    def phonemize(self, text):
        raise AssertionError(f"Japanese phonemizer called for {text!r}")


if __name__ == "__main__":
    unittest.main()
