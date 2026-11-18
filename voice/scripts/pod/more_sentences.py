"""Add everyday Japanese sentences from Tatoeba (CC BY 2.0 FR) to her base list, for phonetic and prosodic
coverage. These are practice sounds for training the phone voice; they are thrown away afterwards.

Usage: python more_sentences.py <base sentences.txt> <tatoeba jpn_sentences.tsv> <out> --n 2600
Prefers casual sentences (no です/ます endings), skips Latin letters, digits, long or odd lines, and anything
intimate or sexual.
"""
import argparse, random, re, unicodedata

SKIP_WORDS = ["セックス", "エッチ", "えっち", "裸", "下着", "胸", "おっぱい", "乳", "性", "淫", "犯", "強姦", "売春",
              "ヌード", "キス", "抱い", "寝よう", "愛撫", "陰", "尻", "股", "精", "妊娠", "避妊", "子供", "子ども",
              "少女", "幼", "小学", "中学", "高校生", "児童", "赤ちゃん", "殺", "死ね", "自殺"]
OK_CHARS = re.compile(r"^[぀-ヿ㐀-鿿！-／：-？、。！？「」『』・ー〜…\s]+$")
POLITE = re.compile(r"(です|ます|でした|ました|ません|でしょう|ください)[。！？]?$")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base"); ap.add_argument("tatoeba"); ap.add_argument("out")
    ap.add_argument("--n", type=int, default=2600)
    ap.add_argument("--casual-share", type=float, default=0.7)
    ap.add_argument("--seed", type=int, default=19)
    a = ap.parse_args()
    base = [l.rstrip("\n") for l in open(a.base, encoding="utf-8") if l.strip()]
    seen = {l.partition("|")[2] for l in base}
    casual, polite = [], []
    for line in open(a.tatoeba, encoding="utf-8"):
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 3:
            continue
        t = unicodedata.normalize("NFKC", parts[2]).strip()
        t = t.replace("!", "！").replace("?", "？")
        if not (6 <= len(t) <= 34) or t in seen or not OK_CHARS.match(t):
            continue
        if any(w in t for w in SKIP_WORDS):
            continue
        seen.add(t)
        (polite if POLITE.search(t) else casual).append(t)
    rng = random.Random(a.seed)
    rng.shuffle(casual); rng.shuffle(polite)
    nc = min(len(casual), int(a.n * a.casual_share))
    picked = casual[:nc] + polite[: a.n - nc]
    rng.shuffle(picked)
    out = base + [f"ja|{t}" for t in picked]
    open(a.out, "w", encoding="utf-8").write("\n".join(out) + "\n")
    print(f"base {len(base)} + tatoeba {len(picked)} (casual {nc}) = {len(out)} lines; pool casual {len(casual)}, polite {len(polite)}")


if __name__ == "__main__":
    main()
