# Build the sentence list her trained voice will read to make the phone-voice training set.
# Sources: ITA corpus (public domain) + plain casual lines in her register (no intimate content).
# Output: sentences.txt as "lang|text", one per line.
import os, re

ITA = "/tmp/claude-0/research/ita-corpus"
out = []

# ITA: recitation (phonetic coverage) + emotion. Format "ID:kanji,kana" -> keep kanji text.
for fn in ("recitation_transcript_utf8.txt", "emotion_transcript_utf8.txt"):
    for line in open(os.path.join(ITA, fn), encoding="utf-8"):
        line = line.strip()
        if not line or ":" not in line:
            continue
        text = line.split(":", 1)[1].split(",")[0].strip()
        if text:
            out.append(("ja", text))

CASUAL = [
 "ねえ、今どこにいんの？","まあいいけど。","てか、お腹すいた。","うける、なにそれ。","ふーん、で？",
 "べつに、なんでもない。","ちょっと待って、今行く。","えー、めんどくさい。","はいはい、わかったってば。","そういうとこだよ、ほんと。",
 "今日さむくない？","もう眠いんだけど。","あとでね。","なにしてんの、あんた。","知らないし。",
 "ま、そんな感じ。","だから言ったじゃん。","は？意味わかんない。","いいじゃん、べつに。","それな。",
 "やばい、まじで。","ちょっとだけね。","もう行かなきゃ。","で、どうすんの？","きょうは無理。",
 "アラームを七時にセットして。","音楽かけて、なんでもいい。","ライト消して。","タイマー十分で。","それ、ちゃんとできた？",
 "明日の天気は？","この曲いいよね。","写真撮ってよ。","静かにして、ちょっと考えてる。","おっけー、やっとく。",
 "お腹いっぱい。","のど渇いた。","足いたい、歩きすぎ。","今日はよく寝た。","なんか飽きた。",
 "コンビニ寄ってこ。","ラーメン食べたい。","コーヒー飲む？","また今度ね。","じゃ、おやすみ。",
 "一、二、三、四、五。","三時半に起こして。","二千円しかない。","十一月十七日、おぼえとく。","九時には出るから。",
 "きょうは火曜日だっけ？","はんぶんこしよ。","ぎゅってして、じゃなくて。","しゅわしゅわのやつ飲みたい。","ちょっときょうは静かだね。",
 "うん、それでいい。","やだ、さむい。","あはは、なにそれ。","んー、どっちでもいい。","ほら、言ったとおりでしょ。",
]
out += [("ja", t) for t in CASUAL]

# A little English in katakana, her accent.
EN_KANA = ["オッケー、わかった。","ジャストキディング。","まあ、ナイスじゃん。","それ、マジ？","ワンモアタイム。"]
out += [("ja", t) for t in EN_KANA]

# De-dup, keep order.
seen=set(); uniq=[]
for lang,t in out:
    if t not in seen:
        seen.add(t); uniq.append((lang,t))
open("sentences.txt","w",encoding="utf-8").write("\n".join(f"{l}|{t}" for l,t in uniq)+"\n")
print(len(uniq),"sentences ->", "sentences.txt")
