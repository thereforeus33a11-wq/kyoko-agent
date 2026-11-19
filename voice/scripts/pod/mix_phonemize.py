"""Her lines, English, Japanese or both mixed, to the phonemes her phone voice reads.

Japanese (kana, kanji, her romaji words) goes through Piper's own JapanesePhonemizer (Open JTalk,
pyopenjtalk 0.4.1, the same labels the phone's JNI build makes). English goes through
en_ipa_table.json (en_phonemize.py). The rules for cutting a line into sentences and segments and
for joining them are written in the table's "segmentation" and "boundaries" sections; this file is
their reference implementation, and the phone's Kotlin port must give the same codepoints.

    from mix_phonemize import MixedPhonemizer
    mp = MixedPhonemizer()
    mp.phonemize("maji? that's crazy ne")   -> [['m','a','↓','d','ʑ','i','?'], ['ð','ˈ','æ','t','s',' ',...]]
    mp.teacher("i pay 500 yen ne")          -> ("ja", "i pay five hundred yen ね")

Command line:
    mix_phonemize.py say "<text>" ...                 phonemes and segments of each text
    mix_phonemize.py csv <in.csv> <out.csv> --config <voice .onnx.json>
                                                      wav|text -> wav|text|phoneme ids (Piper ids)
    mix_phonemize.py golden <texts.txt> <out.tsv>     text<TAB>codepoints (hex) per sentence, for the phone's test
    mix_phonemize.py teacher <lines.txt>              canonical text -> lang|teacher text

A pure Japanese sentence (no Latin word, no English number) is handed to Open JTalk whole, exactly
as Piper's phonemize_japanese does, so her Japanese stays byte-identical to what e800 learned.
"""
import importlib.util
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from en_phonemize import DEFAULT_CMUDICT, DEFAULT_TABLE, EnglishWords, Reading, plain_latin  # noqa: E402

PIPER_SRC_DEFAULT = "/w/piper1-gpl/src"


def load_japanese_phonemizer():
    """Piper's JapanesePhonemizer: from the installed piper, or from its source file (PIPER_SRC)."""
    try:
        from piper.phonemize_japanese import JapanesePhonemizer  # type: ignore
        return JapanesePhonemizer()
    except Exception:
        pass
    src = os.environ.get("PIPER_SRC", PIPER_SRC_DEFAULT)
    path = os.path.join(src, "piper", "phonemize_japanese.py")
    spec = importlib.util.spec_from_file_location("piper_phonemize_japanese", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Piper's phonemize_japanese.py not found under {src} (set PIPER_SRC)")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.JapanesePhonemizer()


# Piper's _SENTENCE_END_PATTERN (phonemize_japanese.py at piper1-gpl 46c3c71), plus an ASCII "." that ends
# a sentence: followed by optional closers and then whitespace or the end, and not part of "..".
_SENT_END = re.compile(r"(?:[。．！？!?]+|(?<!\.)\.(?!\.)(?=[」』）】〉》”’\"')\]]*(?:\s|$)))[」』）】〉》”’\"')\]\s]*")
# Single letters each with a dot (a.m., p.m., e.g., U.S.A.): one word, its dots dropped, said as letters.
_DOTTED = re.compile(r"[A-Za-z](?:\.[A-Za-z])+\.?(?![A-Za-z])")
_DOTTED_WORD = re.compile(r"[A-Za-z](?:\.[A-Za-z])+")
_NUMBER = re.compile(r"[¥￥$€]?[0-9０-９]+(?:[,.:][0-9０-９]+)*(?:(?:st|nd|rd|th)(?![A-Za-z]))?%?")
_EN_PUNCT = set("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~") | set("…‥—–―“”‘’")


def _is_latin(c: str) -> bool:
    return ("a" <= c <= "z") or ("A" <= c <= "Z")


def _is_digit(c: str) -> bool:
    return ("0" <= c <= "9") or ("０" <= c <= "９")


@dataclass
class Tok:
    kind: str  # word, num, space, punct, ja
    text: str
    start: int
    end: int
    route: str = ""  # en / ja for word, num, ja
    reading: object = None
    word: str = ""  # what an English word token is read as (its text, the word for & + @ =, a dotted or joined word's letters)
    dotted: bool = False  # single letters with dots (a.m., U.S.A.): said as letter names


@dataclass
class Segment:
    route: str
    toks: List[Tok] = field(default_factory=list)


@dataclass
class SentencePlan:
    text: str
    toks: List[Tok]
    segments: List[Segment]
    pauses: List[bool]  # pauses[k]: a clause mark between segments k-1 and k (pauses[0] unused)
    terminal: str  # ".", "?" or "!"
    trailing: str  # the sentence's own characters after its last word
    verbatim: bool  # pure Japanese: Open JTalk gets the whole sentence


class MixedPhonemizer:
    def __init__(self, table: str = DEFAULT_TABLE, cmudict: str = DEFAULT_CMUDICT, ja=None):
        self.en = EnglishWords(table, cmudict)
        seg = self.en.t["segmentation"]
        self.abbrev = set(seg["abbreviations"])
        self.edge = set(seg["ja_edge_punct"])
        self.spaces = set(chr(c) for c in seg["space_codepoints"])
        self.clause = set(seg["clause_punct"]) | {"..."}
        self.terminal = seg["terminal_punct"]
        self.dropped = set(seg["dropped_punct"])
        self.joined = sorted(seg["joined_words"]["words"].items(), key=lambda kv: -len(kv[0]))
        b = self.en.t["boundaries"]
        self.word_sep, self.clause_mark, self.after_clause = b["word"], b["clause"], b["after_clause"]
        self.switch, self.end_default = b["switch"], b["sentence_end_default"]
        self.symbols = self.en.t["symbols"]["words"]
        self.time_words = {k: v.split() for k, v in self.en.t["numbers"]["time_words"].items()}
        self._ja = ja

    @property
    def ja(self):
        if self._ja is None:
            self._ja = load_japanese_phonemizer()
        return self._ja

    # -- sentences ---------------------------------------------------------------------------
    def split_sentences(self, text: str) -> List[str]:
        out, start = [], 0
        for m in _SENT_END.finditer(text):
            if m.group(0).startswith(".") and not m.group(0).startswith(".."):
                before = text[start:m.start()]
                word = re.search(r"([A-Za-z][A-Za-z.]*)$", before)
                if word and (word.group(1).lower() in self.abbrev or _DOTTED_WORD.fullmatch(word.group(1))):
                    continue
            if self._piper_decimal(text, m):
                continue
            s = text[start:m.end()].strip()
            if s:
                out.append(s)
            start = m.end()
        tail = text[start:].strip()
        if tail:
            out.append(tail)
        return out

    @staticmethod
    def _piper_decimal(text: str, m) -> bool:
        if m.group(0) != ".":
            return False
        before = text[m.start() - 1] if m.start() > 0 else ""
        after = text[m.end()] if m.end() < len(text) else ""
        return before.isdigit() and after.isdigit()

    # -- tokens ------------------------------------------------------------------------------
    def tokenize(self, s: str) -> List[Tok]:
        toks: List[Tok] = []
        i, n = 0, len(s)
        while i < n:
            c = s[i]
            if _is_latin(c):
                # A word typed with marks inside (tl;dr) is one word (segmentation.joined_words).
                joined = next(((k, w) for k, w in self.joined if s[i:i + len(k)].lower() == k
                               and not (i + len(k) < n and _is_latin(s[i + len(k)]))), None)
                if joined:
                    toks.append(Tok("word", s[i:i + len(joined[0])], i, i + len(joined[0]), word=joined[1]))
                    i += len(joined[0])
                    continue
                m = _DOTTED.match(s, i)
                if m:
                    toks.append(Tok("word", m.group(0), i, m.end(), word=m.group(0).replace(".", ""), dotted=True))
                    i = m.end()
                    continue
                j = i + 1
                while j < n and (_is_latin(s[j]) or (s[j] == "'" and j + 1 < n and _is_latin(s[j + 1]))):
                    j += 1
                toks.append(Tok("word", s[i:j], i, j))
                i = j
                continue
            m = _NUMBER.match(s, i) if (_is_digit(c) or (c in "¥￥$€" and i + 1 < n and _is_digit(s[i + 1]))) else None
            if m:
                toks.append(Tok("num", m.group(0), i, m.end()))
                i = m.end()
                continue
            if c in self.spaces:
                j = i
                while j < n and s[j] in self.spaces:
                    j += 1
                toks.append(Tok("space", s[i:j], i, j))
                i = j
                continue
            if c == "-" and i > 0 and _is_latin(s[i - 1]) and i + 1 < n and _is_latin(s[i + 1]):
                # A hyphen inside a word (t-shirt, kimo-ossan) is only a word break.
                toks.append(Tok("space", c, i, i + 1))
                i += 1
                continue
            if s.startswith("..", i):
                j = i
                while j < n and s[j] == ".":
                    j += 1
                toks.append(Tok("punct", "...", i, j))
                i = j
                continue
            if c in _EN_PUNCT:
                toks.append(Tok("punct", c, i, i + 1))
                i += 1
                continue
            j = i
            while j < n and not (_is_latin(s[j]) or _is_digit(s[j]) or s[j] in self.spaces or s[j] in _EN_PUNCT):
                j += 1
            run_start, run_end = i, j
            lead = []
            while run_start < run_end and s[run_start] in self.edge:
                lead.append(Tok("punct", s[run_start], run_start, run_start + 1))
                run_start += 1
            trail = []
            while run_end > run_start and s[run_end - 1] in self.edge:
                trail.insert(0, Tok("punct", s[run_end - 1], run_end - 1, run_end))
                run_end -= 1
            toks += lead
            if run_end > run_start:
                toks.append(Tok("ja", s[run_start:run_end], run_start, run_end, route="ja"))
            toks += trail
            i = j
        return toks

    def _punct_kind(self, tok: Tok, prev: Optional[Tok]) -> str:
        t = tok.text
        if t == "." and prev is not None and prev.kind == "word" and prev.text.lower() in self.abbrev:
            return "dropped"
        if t in self.symbols:
            return "symbol"
        if t in self.terminal:
            return "terminal"
        if t in self.clause:
            return "clause"
        return "dropped"

    # -- plan --------------------------------------------------------------------------------
    def plan(self, text: str) -> List[SentencePlan]:
        text = plain_latin(text)
        sentences = [(s, self.tokenize(s)) for s in self.split_sentences(text)]
        for _, toks in sentences:
            for t in toks:
                if t.kind == "word":
                    t.word = t.word or t.text
                    t.reading = self.en.read_dotted(t.word) if t.dotted else self.en.read(t.word)
                    t.route = t.reading.route
            # A symbol next to an English word (&, +, @, =) is said as an English word.
            for k, t in enumerate(toks):
                if t.kind == "punct" and t.text in self.symbols and self._between_english(toks, k):
                    t.kind, t.route, t.word = "word", "en", self.symbols[t.text]
                    t.reading = self.en.read(t.word)
        # A number is said in the language of the nearest word; Japanese with no letter or digit (°, ※, ＾) is no word.
        line_words = [t for _, toks in sentences for t in toks if self._is_word(t)]
        for _, toks in sentences:
            words = [t for t in toks if self._is_word(t)]
            for k, t in enumerate(toks):
                if t.kind != "num":
                    continue
                after = [w for w in words if w.start >= t.end]
                before = [w for w in words if w.end <= t.start]
                if re.search(r"(?:st|nd|rd|th)%?$", t.text) or t.text[:1] in "$€":
                    t.route = "en"
                elif after:
                    t.route = after[0].route
                elif before:
                    t.route = before[-1].route
                else:
                    t.route = line_words[0].route if line_words else "ja"
            # am / pm right after an English number is said as letters (7am, 7 pm).
            for k, t in enumerate(toks):
                if t.kind == "word" and t.word.lower() in self.time_words and k > 0:
                    j = k - 1
                    while j >= 0 and toks[j].kind == "space":
                        j -= 1
                    if j >= 0 and toks[j].kind == "num" and toks[j].route == "en":
                        t.route = "en"
                        t.reading = Reading("en", "time", ipa=self.en.arpabet_to_ipa(self.time_words[t.word.lower()]))
        return [self._plan_sentence(s, toks) for s, toks in sentences]

    @staticmethod
    def _is_word(t: Tok) -> bool:
        return t.kind == "word" or (t.kind == "ja" and any(c.isalnum() for c in t.text))

    def _between_english(self, toks: List[Tok], k: int) -> bool:
        prev = next((t for t in reversed(toks[:k]) if t.kind in ("word", "ja", "num")), None)
        nxt = next((t for t in toks[k + 1:] if t.kind in ("word", "ja", "num")), None)
        return (prev is not None and prev.kind == "word" and prev.route == "en") or \
               (nxt is not None and nxt.kind == "word" and nxt.route == "en")

    def _plan_sentence(self, s: str, toks: List[Tok]) -> SentencePlan:
        content = [k for k, t in enumerate(toks) if t.kind in ("word", "num", "ja")]
        segments: List[Segment] = []
        pauses: List[bool] = []
        for idx, k in enumerate(content):
            t = toks[k]
            if segments and segments[-1].route == t.route:
                prev_k = content[idx - 1]
                segments[-1].toks += toks[prev_k + 1:k + 1]
                continue
            if segments:
                prev_k = content[idx - 1]
                pauses.append(any(toks[j].kind == "punct" and self._punct_kind(toks[j], toks[j - 1]) in ("clause", "terminal")
                                  for j in range(prev_k + 1, k)))
            else:
                pauses.append(False)
            segments.append(Segment(t.route, [t]))
        trailing_toks = toks[content[-1] + 1:] if content else toks
        trailing = s[toks[content[-1]].end:] if content else s
        terminal = self.end_default
        marks = [t.text for t in trailing_toks if t.kind == "punct"]
        mapped = [self.terminal[m] for m in marks if m in self.terminal]
        if "?" in mapped:
            terminal = "?"
        elif "!" in mapped:
            terminal = "!"
        verbatim = all(t.route == "ja" for t in toks if t.kind in ("word", "num", "ja")) and \
            not any(t.kind == "word" for t in toks)
        return SentencePlan(s, toks, segments, pauses, terminal, trailing, verbatim)

    # -- phonemes ----------------------------------------------------------------------------
    def _en_segment(self, seg: Segment, ends_sentence: bool) -> str:
        parts: List[str] = []  # word IPA and clause marks
        content = [t for t in seg.toks if t.kind in ("word", "num")]
        # A function word is said strong only where it ends the sentence (where you from?).
        last = content[-1] if (content and ends_sentence) else None
        prev: Optional[Tok] = None
        for t in seg.toks:
            if t.kind == "word":
                if t.reading is not None and t.reading.source in ("time", "dotted"):
                    ipa = t.reading.ipa
                else:
                    ipa = self.en.read(t.word, final=(t is last)).ipa
                if ipa:
                    parts.append(ipa)
            elif t.kind == "num":
                words = self.en.spell_number(t.text)
                for k, w in enumerate(words):
                    ipa = self.en.read(w, final=(t is last and k == len(words) - 1)).ipa
                    if ipa:
                        parts.append(ipa)
            elif t.kind == "punct":
                if self._punct_kind(t, prev) in ("clause", "terminal") and parts and parts[-1] != self.clause_mark:
                    parts.append(self.clause_mark)
            prev = t
        out = ""
        for k, p in enumerate(parts):
            if p == self.clause_mark:
                if k < len(parts) - 1:
                    out += self.clause_mark + self.after_clause
                continue
            if out and not out.endswith(self.after_clause) and not out.endswith(self.word_sep):
                out += self.word_sep
            out += p
        return out

    def _ja_text(self, plan: SentencePlan, seg: Segment, last: bool) -> str:
        s = plan.text
        out = []
        toks = seg.toks
        for k, t in enumerate(toks):
            if t.kind == "word":
                out.append(t.reading.kana)
            elif t.kind == "space":
                prev_w = k > 0 and toks[k - 1].kind == "word"
                next_w = k + 1 < len(toks) and toks[k + 1].kind == "word"
                if not (prev_w or next_w):
                    out.append(t.text)
            else:
                out.append(s[t.start:t.end])
        text = "".join(out)
        if last:
            text += plan.trailing
        return text

    def _ja_phonemes(self, text: str) -> List[str]:
        return [p for sent in self.ja.phonemize(text) for p in sent]

    def phonemize(self, text: str, strict: bool = True) -> Optional[List[List[str]]]:
        """One list of single-codepoint phonemes per sentence. None (strict) when a piece that has
        letters or digits gives nothing (Open JTalk refused it), as the phone's phonemizeAll does."""
        out: List[List[str]] = []
        for plan in self.plan(text):
            if plan.verbatim:
                ph = self._ja_phonemes(plan.text)
                if ph:
                    out.append(ph)
                elif strict and any(c.isalnum() for c in plan.text):
                    return None
                continue
            # Japanese pieces first: one that gives nothing (※, ＾, °) is left out, with no boundary
            # of its own, and the pieces around it join as if it were not there.
            ja_ph = {}
            for k, seg in enumerate(plan.segments):
                if seg.route == "ja":
                    jt = self._ja_text(plan, seg, k == len(plan.segments) - 1)
                    ph = self._ja_phonemes(jt)
                    if not ph and strict and any(c.isalnum() for c in jt):
                        return None
                    ja_ph[k] = ph
            said = [k for k, seg in enumerate(plan.segments)
                    if seg.route == "en" or any(p not in (".", "?") for p in ja_ph[k])]
            phones: List[str] = []
            prev = None
            for k in said:
                seg, last = plan.segments[k], k == said[-1]
                if seg.route == "en":
                    piece = list(self._en_segment(seg, last))
                else:
                    piece = ja_ph[k]
                    if not last and piece[-1] in (".", "?"):
                        piece = piece[:-1]
                if prev is not None:
                    pause = any(plan.pauses[j] for j in range(prev + 1, k + 1))
                    phones += list(self.clause_mark + self.after_clause) if pause else list(self.switch)
                phones += piece
                prev = k
            if said and plan.segments[said[-1]].route == "en":
                phones.append(plan.terminal)
            # A switch that ended up next to nothing (an empty piece) leaves no stray space.
            while phones and phones[0] in (" ", ","):
                phones.pop(0)
            if phones:
                out.append(phones)
        return out

    def ids(self, text: str, id_map: dict) -> Optional[List[int]]:
        """Piper's phonemes_to_ids per sentence (^ _ p _ p _ ... $), concatenated, as its dataset does."""
        sents = self.phonemize(text)
        if sents is None:
            return None
        ids: List[int] = []
        for ph in sents:
            ids += phonemes_to_ids(ph, id_map)
        return ids

    # -- teacher -----------------------------------------------------------------------------
    def teacher(self, text: str) -> Tuple[str, str]:
        """(text_lang, text) for GPT-SoVITS: English numbers spelled out, Japanese-route Latin words
        as kana, so the teacher says what the student will read. 'en' when nothing is Japanese,
        else 'ja' (GPT-SoVITS's Japanese-English mixed mode)."""
        pieces, any_ja = [], False
        for plan in self.plan(text):
            s = plan.text
            if plan.verbatim or not plan.segments:
                pieces.append(s)
                any_ja = any_ja or plan.verbatim
                continue
            out = [s[:plan.segments[0].toks[0].start]]
            for k, seg in enumerate(plan.segments):
                if k > 0:
                    out.append(s[plan.segments[k - 1].toks[-1].end:seg.toks[0].start])
                if seg.route == "ja":
                    any_ja = True
                    out.append(self._ja_text(plan, seg, last=False))
                    continue
                pos = seg.toks[0].start
                for t in seg.toks:
                    said = None
                    if t.kind == "num":
                        said = " ".join(self.en.spell_number(t.text))
                    elif t.kind == "word" and t.reading is not None and t.reading.source == "time":
                        said = ("" if s[t.start - 1:t.start].isspace() else " ") + t.word.lower()[0] + ".m."
                    elif t.kind == "word" and t.dotted:
                        said = " ".join(t.word.upper())
                    elif t.kind == "word" and t.word != t.text:
                        said = t.word
                    if said is not None:
                        out.append(s[pos:t.start]); out.append(said); pos = t.end
                out.append(s[pos:seg.toks[-1].end])
            out.append(plan.trailing)
            pieces.append("".join(out))
        return ("ja" if any_ja else "en"), " ".join(pieces)


def phonemes_to_ids(phonemes: List[str], id_map: dict) -> List[int]:
    """piper.phoneme_ids.phonemes_to_ids at 46c3c71 (BOS, PAD, then each phoneme and PAD, EOS)."""
    try:
        from piper.phoneme_ids import phonemes_to_ids as piper_ids  # type: ignore
        return piper_ids(phonemes, id_map=id_map)
    except Exception:
        pass
    ids = list(id_map["^"]) + list(id_map["_"])
    for p in phonemes:
        if p not in id_map:
            raise KeyError(f"phoneme {p!r} has no id")
        ids += list(id_map[p]) + list(id_map["_"])
    return ids + list(id_map["$"])


def _cmd_say(mp: MixedPhonemizer, texts: List[str]) -> None:
    for text in texts:
        print(text)
        for plan in mp.plan(text):
            segs = " | ".join(f"{g.route}:{''.join(plan.text[t.start:t.end] for t in g.toks)}" for g in plan.segments)
            print(f"  [{plan.text}] {'verbatim' if plan.verbatim else segs} end={plan.terminal}")
        ph = mp.phonemize(text)
        print("  ->", None if ph is None else " / ".join("".join(s) for s in ph))
        print("  teacher:", "|".join(mp.teacher(text)))


def main(argv: List[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["say", "csv", "golden", "teacher"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--table", default=DEFAULT_TABLE)
    ap.add_argument("--cmudict", default=DEFAULT_CMUDICT)
    ap.add_argument("--config", help="Piper voice config (.onnx.json) whose phoneme_id_map gives the ids")
    a = ap.parse_args(argv)
    mp = MixedPhonemizer(a.table, a.cmudict)
    if a.cmd == "say":
        _cmd_say(mp, a.args)
    elif a.cmd == "csv":
        src, dst = a.args
        id_map = json.load(open(a.config, encoding="utf-8"))["phoneme_id_map"]
        bad = 0
        with open(src, encoding="utf-8") as f, open(dst, "w", encoding="utf-8") as g:
            for line in f:
                line = line.rstrip("\n")
                if not line:
                    continue
                wav, text = line.split("|", 1)[0], line.split("|")[-1]
                ids = mp.ids(text, id_map)
                if ids is None:
                    bad += 1
                    print("unreadable:", line, file=sys.stderr)
                    continue
                g.write(f"{wav}|{text}|{' '.join(map(str, ids))}\n")
        print(f"wrote {dst}; {bad} line(s) unreadable", file=sys.stderr)
    elif a.cmd == "golden":
        src, dst = a.args
        with open(src, encoding="utf-8") as f, open(dst, "w", encoding="utf-8") as g:
            g.write("# text<TAB>sentence phonemes as hex codepoints, sentences separated by ' / '; NULL = not readable\n")
            for line in f:
                text = line.rstrip("\n")
                if not text or text.startswith("#"):
                    continue
                ph = mp.phonemize(text)
                enc = "NULL" if ph is None else " / ".join(" ".join(f"{ord(c):04x}" for c in s) for s in ph)
                g.write(f"{text}\t{enc}\n")
    elif a.cmd == "teacher":
        for line in open(a.args[0], encoding="utf-8"):
            text = line.rstrip("\n")
            if text:
                print("|".join(mp.teacher(text)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
