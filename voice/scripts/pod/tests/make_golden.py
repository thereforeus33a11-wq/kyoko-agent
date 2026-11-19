"""Write the golden parity set for the phone's Kotlin port (EnglishPhonemes.kt and the mixed joiner):
texts that touch every row of en_ipa_table.json, every reading path, both switch directions and the
normalization cases, with the codepoints mix_phonemize.py gives for them.

Usage: python tests/make_golden.py [out.tsv]   (needs pyopenjtalk 0.4.1 and Piper's phonemize_japanese)
The Kotlin test reads the same file and must give the same codepoints for every line.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
POD = os.path.dirname(HERE)
sys.path.insert(0, POD)
from mix_phonemize import MixedPhonemizer  # noqa: E402

HAND = [
    # switches, both directions, with and without a pause
    "maji? that's crazy ne", "あんたってほんとに crazy だね", "それ、seriously?", "baby、こっち来て。",
    "i pay 500 yen ne", "maji de, i fucking love her", "ii jan. keep that one", "you wa?",
    "マジで crazy じゃん", "今日 tension low なんだけど", "え、really？", "ねえ、come on", "その joke つまんない",
    "this is so dasai no?", "oi, wake up", "tch. whatever", "dont care shi", "you like her desho",
    "kabukicho tonight. lets go", "ichiman. cash. up front", "oniisan~ ichiman for that question",
    "konbini coffee. trash", "omae ga basic da yo. kuso", "sore ga mou, honto ni iya",
    "look all you want, touching is money, wakatta?", "this bag 30000 yen. who buy this",
    "あと5 minutes", "it's 500円", "3時に meet しよう", "meet at 3", "4", "４人で行く",
    # pure Japanese, whole sentence to Open JTalk
    "5時に来て", "ふーん、そうなんだ？ へぇ〜。", "は？なにそれ、マジでうける。", "ねえ　ちょっと", "「ほんと」って言った。",
    "テンション上がる", "マイペースでいいじゃん",
    # sentences, terminals, pauses
    "okay, whatever.", "dont care. not free", "you pay?", "shut up!", "why?! seriously", "whatever... fine",
    "whatever…", "yes; no: maybe", "t-shirt too small", "kimo-ossan", "no - never", "wait (really) no",
    "\"quoted\" words", "it costs 1.5 times more", "Mr. Tanaka is here.", "e.g. this one", "at 7 a.m. i sleep",
    "it's 3:30. come on, hurry up", "where you from?", "yes i am", "who are you?", "what are you looking at?",
    "salt & pepper", "me + you", "@ home", "1 = 1",
    # normalization
    "don’t", "ｏｋ ｆｉｎｅ", "café", "Pokémon", "NOOOO", "sooooo good", "mmmmm", "zzzzz", "OK", "DJ night",
    "ID please", "USB", "NHK news", "LINE me", "I'm here", "IM here", "i'M here",
    # reading paths
    "tanoshikatta", "hontoni", "gunpla", "rizz", "hostface", "skinships", "emojis", "ghosted", "chillin",
    "tiktoking", "nightclubbing", "x", "q", "bitchy", "lmao", "omg", "idk", "btw", "tbh", "thx", "pls",
    # numbers
    "0", "13", "105", "1,299", "2026", "1000000", "1st", "2nd", "3rd", "4th", "12th", "20th", "21st", "7:05",
    "10:00", "0.25", "007", "50%", "¥500", "$1", "$20", "５",
    # dotted letters, joined words, romaji CMU knows, lowercase letter words and units
    "11 p.m.", "a.m.", "a.m.?", "e.g.", "i.e. no", "o.k. fine", "U.S.A. is far jan", "see you at 11 p.m. Then we go",
    "x.com", "Dr. Tanaka is here", "tl;dr whatever", "TL;DR ok", "kawaii dake ja dame desu ka", "sou dane",
    "friday is hanakin", "im 158 cm", "i ran 5 km today", "my bf said hi", "dm me rn", "CM ugh",
    # a Japanese piece Open JTalk gives nothing for
    "thanks ＾＾", "so good ※。", "nice ※ day", "nice ※, day", "its 35° today", "where you from ※", "※ hi",
    # unreadable
    "안녕", "...", "♡",
]


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "fixtures", "golden_mixed.tsv")
    with open(os.path.join(POD, "en_ipa_table.json"), encoding="utf-8") as f:
        t = json.load(f)
    cases = list(HAND)
    for w, wf in t["weak_forms"]["words"].items():
        cases += [f"so {w} what", f"tell {w}"]
    for w in t["word_overrides"]["words"]:
        cases.append(w)
    for w in t["caps_as_letters"]["words"]:
        cases.append(w.upper())
    for l in t["letters"]:
        cases.append(f"{l.upper()}{l.upper()}")
    for w in t["ja_words"]["words"]:
        cases.append(f"ok {w}")
    for w in t["segmentation"]["joined_words"]["words"]:
        cases.append(f"so {w}")
    # One word per suffix rule (none of them in CMU).
    cases += ["tiktok's", "hoodies", "skinships", "boxeses", "tiktoked", "ghosted", "snored", "tiktoking",
              "vibin", "emojily", "cleverest", "gummies", "cheapnesses", "choker", "stammers", "affectations"]
    seen, uniq = set(), []
    for c in cases:
        if c not in seen:
            seen.add(c); uniq.append(c)
    mp = MixedPhonemizer()
    with open(out, "w", encoding="utf-8") as g:
        g.write("# text<TAB>phonemes as hex codepoints, sentences separated by ' / '; NULL = not readable (another voice says it)\n")
        g.write("# made by tests/make_golden.py from en_ipa_table.json; the phone's port must give the same for every line\n")
        for c in uniq:
            ph = mp.phonemize(c)
            enc = "NULL" if ph is None else " / ".join(" ".join(f"{ord(ch):04x}" for ch in s) for s in ph)
            g.write(f"{c}\t{enc}\n")
    print(f"{len(uniq)} cases -> {out}")


if __name__ == "__main__":
    main()
