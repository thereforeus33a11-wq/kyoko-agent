"""Her English words to the phonemes her phone voice reads (IPA codepoints), from en_ipa_table.json.

The reference implementation of the table: the phone's EnglishPhonemes.kt (to come) must give the
same codepoints for the same word. Everything a rule needs is in the table; this file only applies it.

    from en_phonemize import EnglishWords
    en = EnglishWords("en_ipa_table.json", "cmudict.dict")
    en.read("whatever")      -> Reading(route="en", source="cmu", ipa="wʌtˈɛvɚ")
    en.read("maji")          -> Reading(route="ja", source="ja_words", kana="まじ")
    en.ipa_words(["i", "dont", "care"]) -> "aɪ dˈoʊnt kˈɛɹ"

Command line (prints one word per line with how it was read):
    python en_phonemize.py [--table T] [--cmudict C] word ...
"""
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass
from typing import Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TABLE = os.path.join(HERE, "en_ipa_table.json")
# The pinned dictionary: $CMUDICT, else the pod's copy, else this machine's.
DEFAULT_CMUDICT = os.environ.get("CMUDICT") or next(
    (p for p in ("/w/job/data/cmudict.dict", "/tmp/claude-0/cmudict/cmudict.dict") if os.path.exists(p)),
    "/tmp/claude-0/cmudict/cmudict.dict")


@dataclass
class Reading:
    route: str  # "en" or "ja"
    source: str  # which step of latin_word_route read it
    ipa: str = ""  # English: IPA, words separated by " "
    kana: str = ""  # Japanese: kana for Open JTalk


def load_cmudict(path: str) -> Dict[str, List[str]]:
    """The phone's CmuDict.load: first pronunciation of each word, variants and comments skipped."""
    out: Dict[str, List[str]] = {}
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            body = line.split("#", 1)[0].strip()
            if not body:
                continue
            parts = [p for p in body.split(" ") if p]
            if len(parts) < 2 or "(" in parts[0]:
                continue
            out.setdefault(parts[0], parts[1:])
    return out


# ---------------------------------------------------------------------------------------------
# Romaji, a line-for-line port of KanaText.kt's Romaji object (strict and loose).

def _romaji_table() -> Dict[str, str]:
    t: Dict[str, str] = {}
    rows = {"": "あいうえお", "k": "かきくけこ", "s": "さしすせそ", "t": "たちつてと", "n": "なにぬねの",
            "h": "はひふへほ", "m": "まみむめも", "r": "らりるれろ", "g": "がぎぐげご", "z": "ざじずぜぞ",
            "d": "だぢづでど", "b": "ばびぶべぼ", "p": "ぱぴぷぺぽ"}
    for c, kana in rows.items():
        for k, v in enumerate("aiueo"):
            t[c + v] = kana[k]
    t.update({"ya": "や", "yu": "ゆ", "yo": "よ", "wa": "わ", "wo": "を", "shi": "し", "chi": "ち",
              "tsu": "つ", "fu": "ふ", "ji": "じ", "di": "でぃ", "du": "どぅ", "ti": "てぃ",
              "si": "し", "zi": "じ", "tu": "つ", "hu": "ふ",
              "fa": "ふぁ", "fi": "ふぃ", "fe": "ふぇ", "fo": "ふぉ", "je": "じぇ", "she": "しぇ",
              "che": "ちぇ", "ye": "いぇ", "wi": "うぃ", "we": "うぇ", "va": "ゔぁ", "vi": "ゔぃ",
              "vu": "ゔ", "ve": "ゔぇ", "vo": "ゔぉ"})
    for c, i in [("k", "き"), ("g", "ぎ"), ("n", "に"), ("h", "ひ"), ("m", "み"), ("r", "り"),
                 ("b", "び"), ("p", "ぴ"), ("d", "ぢ")]:
        t[c + "ya"] = i + "ゃ"; t[c + "yu"] = i + "ゅ"; t[c + "yo"] = i + "ょ"
    for c, i in [("sh", "し"), ("ch", "ち"), ("j", "じ")]:
        t[c + "a"] = i + "ゃ"; t[c + "u"] = i + "ゅ"; t[c + "o"] = i + "ょ"
    t["jya"] = "じゃ"; t["jyu"] = "じゅ"; t["jyo"] = "じょ"
    return t


_ROMAJI = _romaji_table()
_ROMAJI_MAX = max(len(k) for k in _ROMAJI)
_CONSONANTS = "bcdfghjkmnprstvwyz"


def _romaji_parse(word: str, loose: bool) -> Optional[str]:
    out = []
    i = 0
    while i < len(word):
        c = word[i]
        if c in "-~":
            out.append("ー"); i += 1; continue
        if i + 1 < len(word) and c in _CONSONANTS and c != "n" and (word[i + 1] == c or (c == "t" and word[i + 1] == "c")):
            out.append("っ"); i += 1; continue
        matched = False
        for ln in range(_ROMAJI_MAX, 0, -1):
            if i + ln > len(word):
                continue
            kana = _ROMAJI.get(word[i:i + ln])
            if kana is None:
                continue
            out.append(kana); i += ln; matched = True
            break
        if matched:
            continue
        if c == "n":
            out.append("ん"); i += 1
            if i < len(word) and word[i] == "'":
                i += 1
            continue
        if not loose:
            return None
        if c == "r" and i > 0 and word[i - 1] in "aeiou":
            out.append("ー")
        elif c in "td":
            out.append("と" if c == "t" else "ど")
        elif c in _CONSONANTS or c in "lqx":
            k = {"l": "r", "q": "k", "x": "k", "c": "k"}.get(c, c)
            kana = _ROMAJI.get(k + "u")
            if kana:
                out.append(kana)
        i += 1
    return "".join(out)


def romaji_to_hiragana(word: str) -> Optional[str]:
    return _romaji_parse(word, loose=False)


def romaji_to_katakana_loose(word: str) -> str:
    return "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in (_romaji_parse(word, loose=True) or ""))


# ---------------------------------------------------------------------------------------------

_HELD = re.compile(r"([A-Za-z])\1{3,}")
_CURLY = re.compile(r"(?<=[A-Za-z])[’ʼ](?=[A-Za-z])")


def plain_latin(text: str) -> str:
    """KanaText.plainLatin: full-width Latin letters to ASCII, accents off Latin letters, curly apostrophes in words to '."""
    narrow = "".join(chr(ord(c) - 0xFEE0) if ("Ａ" <= c <= "Ｚ" or "ａ" <= c <= "ｚ") else c for c in text)
    nfd = unicodedata.normalize("NFD", narrow)
    bare = unicodedata.normalize("NFC", _strip_marks_after_latin(nfd))
    return _CURLY.sub("'", bare)


def _strip_marks_after_latin(s: str) -> str:
    # Java's \p{Mn} after [A-Za-z]: every nonspacing mark directly after a Latin letter (or after
    # such a mark) goes.
    out = []
    prev_latin = False
    for ch in s:
        if prev_latin and unicodedata.category(ch) == "Mn":
            continue
        out.append(ch)
        prev_latin = ("A" <= ch <= "Z") or ("a" <= ch <= "z")
    return "".join(out)


class EnglishWords:
    def __init__(self, table_path: str = DEFAULT_TABLE, cmudict_path: str = DEFAULT_CMUDICT,
                 cmu: Optional[Dict[str, List[str]]] = None):
        with open(table_path, encoding="utf-8") as f:
            self.t = json.load(f)
        self.cmu = cmu if cmu is not None else load_cmudict(cmudict_path)
        t = self.t
        self.vowels = t["vowels"]
        self.vowels_by_stress = t["vowels_by_stress"]
        self.consonants = t["consonants"]
        self.stress_marks = t["stress_marks"]
        self.r_vowel_before_vowel = t["r_vowel_before_vowel"]["vowels"]
        self.weak = t["weak_forms"]["words"]
        self.overrides = {w: p.split() for w, p in t["word_overrides"]["words"].items()}
        self.caps_letters = set(t["caps_as_letters"]["words"])
        self.letters = {k: v.split() for k, v in t["letters"].items()}
        self.ja_words = t["ja_words"]["words"]
        self.suffix_rules = t["suffixes"]["rules"]
        self.voicing = t["suffixes"]["voicing"]
        self.sibilants = set(t["suffixes"]["sibilants"])
        self.voiceless = set(t["suffixes"]["voiceless"])
        self.t_d = set(t["suffixes"]["t_d"])
        self.min_base = t["suffixes"]["min_base_letters"]
        self.min_part = t["compound"]["min_part"]
        self.held_keep = t["held_letter"]["keep"]
        self.num = t["numbers"]

    # -- ARPAbet ---------------------------------------------------------------------------
    def arpabet_to_ipa(self, phones: List[str]) -> str:
        out = []
        for k, p in enumerate(phones):
            if p == "_":
                out.append(" ")
                continue
            base = p.rstrip("012")
            stress = p[len(base):] or None
            if base in self.vowels_by_stress or base in self.vowels:
                v = self.vowels_by_stress.get(base, {}).get(stress or "0") or self.vowels[base]
                nxt = phones[k + 1].rstrip("012") if k + 1 < len(phones) else ""
                if base in self.r_vowel_before_vowel and (nxt in self.vowels or nxt in self.vowels_by_stress):
                    # hurry HH ER1 IY0: the r is said before the next vowel (hˈɜːɹi), as espeak writes it.
                    v = self.r_vowel_before_vowel[base][stress or "0"]
                out.append(self.stress_marks.get(stress or "", "") + v)
            elif base in self.consonants:
                out.append(self.consonants[base])
            else:
                raise ValueError(f"unknown ARPAbet phone {p!r}")
        return "".join(out)

    def _known(self, w: str) -> Optional[List[str]]:
        if w in self.overrides:
            return self.overrides[w]
        return self.cmu.get(w)

    def _held_variants(self, w: str) -> List[str]:
        """sooo -> [sooo, so, soo]: each run of 3 identical letters cut to 1, then to 2."""
        out = [w]
        if re.search(r"([a-z])\1\1", w):
            out.append(re.sub(r"([a-z])\1\1", r"\1", w))
            out.append(re.sub(r"([a-z])\1\1", r"\1\1", w))
        return out

    def _last_phone(self, phones: List[str]) -> str:
        return phones[-1].rstrip("012") if phones else ""

    def _suffix(self, w: str) -> Optional[List[str]]:
        for rule in self.suffix_rules:
            suf = rule["suffix"]
            if not w.endswith(suf) or len(w) <= len(suf):
                continue
            for b in rule["bases"]:
                cut = len(w) - b["drop"]
                if cut < self.min_base:
                    continue
                if b.get("double") and not (cut >= 1 and w[cut - 1] == w[cut]):
                    continue
                base = w[:cut] + b.get("append", "")
                phones = self._known(base)
                if phones is None:
                    continue
                if b.get("sibilant") and self._last_phone(phones) not in self.sibilants:
                    continue
                return phones + self._suffix_phones(rule["add"], phones)
        return None

    def _suffix_phones(self, add: str, base: List[str]) -> List[str]:
        last = self._last_phone(base)
        if add in self.voicing:
            v = self.voicing[add]
            if "after_sibilant" in v and last in self.sibilants:
                return v["after_sibilant"].split()
            if "after_t_d" in v and last in self.t_d:
                return v["after_t_d"].split()
            if last in self.voiceless:
                return v["after_voiceless"].split()
            return v["else"].split()
        return add.split()

    def _compound(self, w: str) -> Optional[List[str]]:
        for i in range(len(w) - self.min_part, self.min_part - 1, -1):
            left, right = self._known(w[:i]), self._known(w[i:])
            if left is not None and right is not None:
                return left + right
        return None

    def letters_ipa(self, word: str) -> str:
        phones: List[str] = []
        ls = [c for c in word.lower() if c in self.letters]
        for k, c in enumerate(ls):
            ps = list(self.letters[c])
            if k < len(ls) - 1:
                ps = [p[:-1] + "2" if p.endswith("1") else p for p in ps]
            phones += ps
        return self.arpabet_to_ipa(phones)

    # -- one word ---------------------------------------------------------------------------
    def read(self, typed: str, final: bool = False) -> Reading:
        """How one Latin word (letters with ' inside) is read. final: last word of its English segment."""
        raw = _HELD.sub(lambda m: m.group(1) * self.held_keep, typed).strip("'")
        lower = raw.lower()
        if not lower:
            return Reading("en", "empty", ipa="")
        if lower in self.ja_words:
            return Reading("ja", "ja_words", kana=self.ja_words[lower])
        if 2 <= len(raw) <= 5 and raw.isascii() and raw.isalpha() and raw.isupper():
            known = any(self._known(v) is not None or v in self.weak for v in self._held_variants(lower))
            if lower in self.caps_letters or not known:
                return Reading("en", "caps", ipa=self.letters_ipa(lower))
        if lower in self.weak:
            wf = self.weak[lower]
            return Reading("en", "weak", ipa=wf["strong"] if (final and "strong" in wf) else wf["ipa"])
        if lower in self.overrides:
            return Reading("en", "override", ipa=self.arpabet_to_ipa(self.overrides[lower]))
        for v in self._held_variants(lower):
            if v in self.cmu:
                return Reading("en", "cmu", ipa=self.arpabet_to_ipa(self.cmu[v]))
            if v != lower and v in self.overrides:
                return Reading("en", "override", ipa=self.arpabet_to_ipa(self.overrides[v]))
            if v != lower and v in self.weak:
                return Reading("en", "weak", ipa=self.weak[v]["ipa"])
        if "'" in lower:
            bare = lower.replace("'", "")
            if bare in self.overrides:
                return Reading("en", "override", ipa=self.arpabet_to_ipa(self.overrides[bare]))
            if bare in self.cmu:
                return Reading("en", "cmu", ipa=self.arpabet_to_ipa(self.cmu[bare]))
        s = self._suffix(lower)
        if s is not None:
            return Reading("en", "suffix", ipa=self.arpabet_to_ipa(s))
        if "'" not in lower:
            h = romaji_to_hiragana(lower)
            if h is not None:
                return Reading("ja", "romaji", kana=h)
        c = self._compound(lower.replace("'", ""))
        if c is not None:
            return Reading("en", "compound", ipa=self.arpabet_to_ipa(c))
        if len(lower) == 1 and lower in self.letters:
            return Reading("en", "letter", ipa=self.letters_ipa(lower))
        return Reading("ja", "loose", kana=romaji_to_katakana_loose(lower.replace("'", "")))

    def ipa_words(self, words: List[str]) -> str:
        """English words already known to be English: IPA joined by spaces (the last word may be strong)."""
        out = []
        for k, w in enumerate(words):
            r = self.read(w, final=(k == len(words) - 1))
            if r.route != "en":
                raise ValueError(f"{w!r} is read as Japanese ({r.source})")
            if r.ipa:
                out.append(r.ipa)
        return " ".join(out)

    # -- numbers ----------------------------------------------------------------------------
    def spell_int(self, n: int) -> List[str]:
        ones, tens = self.num["ones"], self.num["tens"]
        if n < 0 or n > self.num["max"]:
            raise ValueError(n)
        if n < 20:
            return [ones[n]]
        if n < 100:
            return [tens[n // 10]] + ([ones[n % 10]] if n % 10 else [])
        if n < 1000:
            return [ones[n // 100], self.num["hundred"]] + (self.spell_int(n % 100) if n % 100 else [])
        for value, name in self.num["scales"]:
            if n >= value:
                return self.spell_int(n // value) + [name] + (self.spell_int(n % value) if n % value else [])
        raise AssertionError(n)

    def ordinal(self, words: List[str]) -> List[str]:
        last = words[-1]
        ow = self.num["ordinal_words"]
        if last in ow:
            last = ow[last]
        elif last.endswith("y"):
            last = last[:-1] + "ieth"
        else:
            last = last + "th"
        return words[:-1] + [last]

    def spell_number(self, token: str) -> List[str]:
        """A number token (digits, with , . : inside, ordinal suffix, currency before, % after) to English words."""
        tok = unicodedata.normalize("NFKC", token)
        currency = None
        for sym, word in self.num["currency_before"].items():
            s = unicodedata.normalize("NFKC", sym)
            if tok.startswith(s):
                currency, tok = word, tok[len(s):]
                break
        percent = tok.endswith("%")
        if percent:
            tok = tok[:-1]
        suffix = None
        for suf in self.num["ordinal_suffixes"]:
            if tok.lower().endswith(suf) and tok[:-len(suf)].isdigit():
                suffix, tok = suf, tok[:-len(suf)]
                break
        words: List[str]
        sep = self.num["thousands_separator"]
        if re.fullmatch(r"\d{1,3}(?:,\d{3})+", tok):
            tok = tok.replace(sep, "")
        if re.fullmatch(r"\d{1,2}:\d{2}", tok):
            h, m = tok.split(":")
            words = self.spell_int(int(h))
            mi = int(m)
            if mi == 0:
                words += [self.num["o_clock"]]
            elif mi < 10:
                words += [self.num["oh"]] + self.spell_int(mi)
            else:
                words += self.spell_int(mi)
        elif re.fullmatch(r"\d+\.\d+", tok):
            a, b = tok.split(".")
            words = self._spell_digits_or_int(a) + [self.num["point"]] + [self.num["ones"][int(d)] for d in b]
        elif re.fullmatch(r"\d+", tok):
            words = self._spell_digits_or_int(tok)
            if suffix:
                words = self.ordinal(words)
        else:
            # Anything else made of digits and marks: digit by digit.
            words = [self.num["ones"][int(d)] for d in tok if d.isdigit()]
        if percent:
            words.append(self.num["percent"])
        if currency:
            if words == ["one"]:
                currency = self.num["currency_singular"].get(currency, currency)
            words.append(currency)
        return words

    def _spell_digits_or_int(self, digits: str) -> List[str]:
        if len(digits) > 1 and digits.startswith("0"):
            return [self.num["ones"][int(d)] for d in digits]
        if int(digits) > self.num["max"]:
            return [self.num["ones"][int(d)] for d in digits]
        return self.spell_int(int(digits))


def main(argv: List[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", default=DEFAULT_TABLE)
    ap.add_argument("--cmudict", default=DEFAULT_CMUDICT)
    ap.add_argument("words", nargs="+")
    a = ap.parse_args(argv)
    en = EnglishWords(a.table, a.cmudict)
    for w in a.words:
        if re.fullmatch(r"[¥￥$€]?[0-9０-９][0-9０-９,.:]*(?:st|nd|rd|th)?%?", w):
            print(w, "number", " ".join(en.spell_number(w)), sep="\t")
            continue
        r = en.read(w)
        print(w, r.route, r.source, r.ipa or r.kana, sep="\t")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
