"""A/B lines for her English: A = the app's katakana route, B = English IPA spliced between her Japanese phonemes."""
import json, re
cmu = {}
for l in open("/tmp/claude-0/cmudict/cmudict.dict", encoding="utf-8", errors="ignore"):
    w, *ph = l.split()
    if "(" in w: continue
    cmu[w] = [p for p in ph if not p.startswith("#")]
V = {"AA": "ɑː", "AE": "æ", "AO": "ɔː", "AW": "aʊ", "AY": "aɪ", "EH": "ɛ", "EY": "eɪ", "IH": "ɪ", "IY": "i",
     "OW": "oʊ", "OY": "ɔɪ", "UH": "ʊ", "UW": "uː"}
C = {"B": "b", "CH": "tʃ", "D": "d", "DH": "ð", "F": "f", "G": "ɡ", "HH": "h", "JH": "dʒ", "K": "k", "L": "l",
     "M": "m", "N": "n", "NG": "ŋ", "P": "p", "R": "ɹ", "S": "s", "SH": "ʃ", "T": "t", "TH": "θ", "V": "v",
     "W": "w", "Y": "j", "Z": "z", "ZH": "ʒ"}
def ipa(word):
    out = []
    for p in cmu[word.lower()]:
        base, st = p.rstrip("012"), p[-1] if p[-1].isdigit() else ""
        if base == "AH": v = "ʌ" if st == "1" else "ə"
        elif base == "ER": v = "ɜː" if st == "1" else "ɚ"
        elif base in V: v = V[base]
        else: out.append(C[base]); continue
        mark = "ˈ" if st == "1" else ("ˌ" if st == "2" else "")
        # espeak (which her base voice learned English from) writes the stress mark right before the vowel
        out.append(mark + v)
    return "".join(out)
LINES = [
    ("マジでファック、うざい。", [("ja", "マジで"), ("en", "fuck"), ("ja", "、うざい。")]),
    ("それ、シリアスリー？", [("ja", "それ、"), ("en", "seriously"), ("ja", "？")]),
    ("オーケー、ワットエバー。", [("en", "okay"), ("ja", "、"), ("en", "whatever"), ("ja", "。")]),
    ("ベイビー、こっち来て。", [("en", "baby"), ("ja", "、こっち来て。")]),
    ("グッドモーニング、起きた？", [("en", "good"), ("en", "morning"), ("ja", "、起きた？")]),
    ("シャットアップ、バカ。", [("en", "shut"), ("en", "up"), ("ja", "、バカ。")]),
    ("ノーウェイ、マジ？", [("en", "no"), ("en", "way"), ("ja", "、マジ？")]),
    ("サンキュー、ね。", [("en", "thank"), ("en", "you"), ("ja", "、ね。")]),
    ("あんたってほんとにクレイジー。", [("ja", "あんたってほんとに"), ("en", "crazy"), ("ja", "。")]),
    ("それ、マイフェイバリット。", [("ja", "それ、"), ("en", "my"), ("en", "favorite"), ("ja", "。")]),
]
out = [{"a": a, "segments": [(k, ipa(t) if k == "en" else t) for k, t in segs]} for a, segs in LINES]
json.dump(out, open("ab_lines.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for o in out: print(o["a"], "|", " ".join(t for k, t in o["segments"] if k == "en"))
