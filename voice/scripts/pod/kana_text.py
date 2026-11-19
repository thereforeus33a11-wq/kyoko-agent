"""Python mirror of the phone's KanaText.kt (opendroid core/voice/own): how her lines are read TODAY,
every Latin word turned into katakana from its CMU pronunciation before Open JTalk. Used for the
A side of the A/B (today's route) and for the kana a Japanese recogniser should hear for an English
word inside a Japanese-led line.

    from kana_text import KanaText, arpabet_to_katakana
    KanaText(cmu).convert("maji? that's crazy")  -> "まじ？ザッツ クレージー"
"""
import re
from typing import Callable, Dict, List, Optional

from en_phonemize import plain_latin, romaji_to_hiragana, romaji_to_katakana_loose

VOWELS = {"AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER", "EY", "IH", "IY", "OW", "OY", "UH", "UW"}
ROWS = {
    "": ["ア", "イ", "ウ", "エ", "オ"],
    "K": ["カ", "キ", "ク", "ケ", "コ"], "G": ["ガ", "ギ", "グ", "ゲ", "ゴ"],
    "S": ["サ", "シ", "ス", "セ", "ソ"], "Z": ["ザ", "ジ", "ズ", "ゼ", "ゾ"],
    "SH": ["シャ", "シ", "シュ", "シェ", "ショ"], "ZH": ["ジャ", "ジ", "ジュ", "ジェ", "ジョ"],
    "CH": ["チャ", "チ", "チュ", "チェ", "チョ"], "JH": ["ジャ", "ジ", "ジュ", "ジェ", "ジョ"],
    "T": ["タ", "ティ", "トゥ", "テ", "ト"], "D": ["ダ", "ディ", "ドゥ", "デ", "ド"],
    "TH": ["サ", "シ", "ス", "セ", "ソ"], "DH": ["ザ", "ジ", "ズ", "ゼ", "ゾ"],
    "N": ["ナ", "ニ", "ヌ", "ネ", "ノ"], "M": ["マ", "ミ", "ム", "メ", "モ"],
    "HH": ["ハ", "ヒ", "フ", "ヘ", "ホ"], "F": ["ファ", "フィ", "フ", "フェ", "フォ"],
    "V": ["バ", "ビ", "ブ", "ベ", "ボ"], "B": ["バ", "ビ", "ブ", "ベ", "ボ"],
    "P": ["パ", "ピ", "プ", "ペ", "ポ"], "L": ["ラ", "リ", "ル", "レ", "ロ"],
    "R": ["ラ", "リ", "ル", "レ", "ロ"], "W": ["ワ", "ウィ", "ウ", "ウェ", "ウォ"],
    "Y": ["ヤ", "イ", "ユ", "イェ", "ヨ"], "NG": ["ンガ", "ンギ", "ング", "ンゲ", "ンゴ"],
}
CODA = {"K": "ク", "G": "グ", "S": "ス", "Z": "ズ", "SH": "シュ", "ZH": "ジュ", "CH": "チ", "JH": "ジ", "T": "ト",
        "D": "ド", "TH": "ス", "DH": "ズ", "N": "ン", "M": "ム", "HH": "", "F": "フ", "V": "ブ", "B": "ブ", "P": "プ",
        "L": "ル", "R": "ル", "W": "ウ", "Y": "イ", "NG": "ング"}
SMALL = {0: "ャ", 2: "ュ", 3: "ェ", 4: "ョ"}
SHORT_VOWELS = {"AA", "AE", "AH", "EH", "IH", "UH", "AO"}
GEMINATING = {"P", "T", "K", "CH", "JH", "D", "G"}


def _base(p: str) -> str:
    return p.rstrip("012")


def _row(v: str, spelling: str) -> int:
    if v == "AA":
        return 4 if ("o" in spelling and "a" not in spelling) else 0
    return {"AE": 0, "AH": 0, "AW": 0, "AY": 0, "ER": 0, "EH": 3, "EY": 3, "IH": 1, "IY": 1,
            "AO": 4, "OW": 4, "OY": 4, "UH": 2, "UW": 2}.get(v, 0)


def arpabet_to_katakana(phones: List[str], spelling: str = "") -> str:
    """Arpabet.toKatakana, line for line."""
    split: List[str] = []
    for k, p in enumerate(phones):
        b = _base(p)
        nxt = _base(phones[k + 1]) if k + 1 < len(phones) else None
        if b == "ER" and nxt is not None and nxt in VOWELS:
            split.append("AH" + p[2:]); split.append("R")
        else:
            split.append(p)
    ph = [_base(p) for p in split]
    stress = [int(p[-1]) if p and p[-1].isdigit() else -1 for p in split]
    out: List[str] = []

    def ends(s):
        return "".join(out).endswith(s)

    def vowel_tail(i):
        v = ph[i]
        final = i == len(ph) - 1
        stressed = stress[i] >= 1
        next_is_vowel = i + 1 < len(ph) and ph[i + 1] in VOWELS
        if v == "AW":
            out.append("ウ")
        elif v in ("AY", "OY"):
            out.append("イ")
        elif v == "EY":
            out.append("イ" if (final or next_is_vowel) else "ー")
        elif v == "ER":
            if not next_is_vowel:
                out.append("ー")
        elif v in ("IY", "UW", "OW"):
            if stressed or final:
                out.append("ー")
        elif v == "AO":
            if stressed and (final or next_is_vowel):
                out.append("ー")

    def vowel(consonant, i):
        v = ph[i]
        r = _row(v, spelling)
        if consonant in ("K", "G") and v == "AE":
            kana = ROWS[consonant][1] + "ャ"
        else:
            kana = ROWS.get(consonant, ROWS[""])[r]
        out.append(kana)
        vowel_tail(i)

    i = 0
    while i < len(ph):
        p = ph[i]
        if p in VOWELS:
            vowel("", i); i += 1; continue
        nxt = ph[i + 1] if i + 1 < len(ph) else None
        if nxt == "Y" and p != "Y" and i + 2 < len(ph) and ph[i + 2] in VOWELS and p in ROWS:
            v = ph[i + 2]
            r = _row(v, spelling)
            i_kana = ROWS[p][1]
            out.append(i_kana if r == 1 else i_kana + SMALL.get(r, ""))
            vowel_tail(i + 2)
            i += 3; continue
        if nxt is not None and nxt in VOWELS:
            vowel(p, i + 1); i += 2; continue
        after = ph[i + 2] if i + 2 < len(ph) else None
        if ((p == "T" and nxt == "S") or (p == "D" and nxt == "Z")) and after not in VOWELS:
            if i > 0 and ph[i - 1] in SHORT_VOWELS:
                out.append("ッ")
            out.append("ツ" if p == "T" else "ズ")
            i += 2; continue
        word_final = nxt is None
        if p == "R" and i > 0 and ph[i - 1] in VOWELS:
            if not ends("ー"):
                out.append("ー")
        elif p == "M" and nxt in ("B", "P", "M"):
            out.append("ン")
        elif p == "NG" and nxt in ("K", "G"):
            out.append("ン")
        else:
            if word_final and p in GEMINATING and i > 0 and ph[i - 1] in SHORT_VOWELS:
                out.append("ッ")
            out.append(CODA.get(p, ""))
        i += 1
    return "".join(out)


JAPANESE_WORDS = {
    "ne": "ね", "nee": "ねえ", "nene": "ねね", "momo": "もも", "ayame": "あやめ", "reina": "れいな", "yume": "ゆめ",
    "kisaragi": "きさらぎ", "baka": "ばか", "dame": "だめ", "hai": "はい", "oi": "おい", "tch": "ちっ", "chi": "ちっ",
    "heh": "へっ", "hah": "はっ", "hm": "ふーん", "hmm": "ふーん", "mm": "んー", "mmm": "んー", "ugh": "うっ",
    "pff": "ぷっ", "pfft": "ぷっ", "tsk": "ちっ", "ara": "あら", "mama": "まま", "papa": "ぱぱ", "san": "さん",
    "chan": "ちゃん", "kun": "くん", "sama": "さま", "desu": "です", "masu": "ます", "kimo": "きも", "uzai": "うざい",
    "maji": "まじ", "dasai": "ださい", "gachi": "がち", "urusee": "うるせえ", "urusai": "うるさい", "yabai": "やばい",
    "sugoi": "すごい", "kawaii": "かわいい", "ossan": "おっさん", "oniisan": "おにいさん", "senpai": "せんぱい",
    "betsu": "べつ", "ni": "に", "sore": "それ", "demo": "でも", "ano": "あの", "nani": "なに", "nande": "なんで",
    "itadakimasu": "いただきます", "tadaima": "ただいま", "otsukare": "おつかれ", "mukatsuku": "むかつく",
    "jiwaru": "じわる", "choroi": "ちょろい", "yoyuu": "よゆう", "bibitteru": "びびってる",
    "kashikomarimashita": "かしこまりました", "hatachi": "はたち", "zako": "ざこ", "un": "うん", "ee": "ええ",
    "ii": "いい", "nya": "にゃ", "e": "え", "kusa": "くさ", "muri": "むり", "yoshi": "よし", "de": "で", "yo": "よ",
    "mo": "も", "ko": "こ",
}
ENGLISH_SAYINGS = {
    "ok": "オッケー", "okay": "オッケー", "k": "オッケー", "lol": "ロル", "bro": "ブロ", "yeah": "イェー", "yep": "イェップ",
    "nope": "ノープ", "bye": "バイバイ", "hi": "ハイ", "hey": "ヘイ", "yes": "イエス", "no": "ノー", "wow": "ワオ",
    "omg": "オーマイガー", "haha": "ははっ", "ha": "はっ", "hahaha": "あははっ", "i": "アイ", "a": "ア", "the": "ザ",
    "you": "ユー", "to": "トゥ", "of": "オブ", "and": "アンド", "is": "イズ", "it": "イット", "in": "イン", "my": "マイ",
    "me": "ミー",
}
LETTERS = {"a": "エー", "b": "ビー", "c": "シー", "d": "ディー", "e": "イー", "f": "エフ", "g": "ジー", "h": "エイチ",
           "i": "アイ", "j": "ジェー", "k": "ケー", "l": "エル", "m": "エム", "n": "エヌ", "o": "オー", "p": "ピー",
           "q": "キュー", "r": "アール", "s": "エス", "t": "ティー", "u": "ユー", "v": "ブイ", "w": "ダブリュー",
           "x": "エックス", "y": "ワイ", "z": "ゼット"}
PUNCTUATION = {".": "。", ",": "、", "?": "？", "!": "！", ":": "、", ";": "、", "-": "、", '"': "「", "(": "、", ")": "、"}
_HELD = re.compile(r"([A-Za-z])\1{3,}")


def _latin(c: str) -> bool:
    return ("a" <= c <= "z") or ("A" <= c <= "Z")


class KanaText:
    def __init__(self, cmu: Dict[str, List[str]]):
        self.pron: Callable[[str], Optional[List[str]]] = cmu.get

    def convert(self, typed: str) -> str:
        text = plain_latin(typed)
        out: List[str] = []
        i, last_latin = 0, False
        while i < len(text):
            c = text[i]
            if _latin(c):
                j = i
                while j < len(text) and (_latin(text[j]) or (text[j] == "'" and j + 1 < len(text) and _latin(text[j + 1]))):
                    j += 1
                if last_latin:
                    out.append(" ")
                out.append(self.word(text[i:j]))
                last_latin = True
                i = j
                continue
            if c in " \t":
                i += 1
                continue
            if text.startswith("...", i):
                out.append("、"); i += 3; last_latin = False; continue
            if c in ".," and i > 0 and text[i - 1].isdigit() and i + 1 < len(text) and text[i + 1].isdigit():
                out.append(c); last_latin = False
            else:
                out.append(PUNCTUATION.get(c, c)); last_latin = False
            i += 1
        return "".join(out)

    def word(self, typed: str) -> str:
        raw = _HELD.sub(lambda m: m.group(1) * 3, typed)
        lower = raw.lower()
        if lower in JAPANESE_WORDS:
            return JAPANESE_WORDS[lower]
        if lower in ENGLISH_SAYINGS:
            return ENGLISH_SAYINGS[lower]
        if not lower:
            return ""
        all_caps = 2 <= len(raw) <= 5 and all(ch.isupper() for ch in raw)
        if all_caps and self.pron(lower) is None:
            return "".join(LETTERS.get(ch, "") for ch in lower)
        p = self.pron(lower)
        if p is not None:
            return arpabet_to_katakana(p, lower)
        if "'" not in lower:
            h = romaji_to_hiragana(lower)
            if h is not None:
                return h
        if len(raw) == 1:
            return LETTERS.get(lower[0], "")
        return romaji_to_katakana_loose(lower.replace("'", ""))
