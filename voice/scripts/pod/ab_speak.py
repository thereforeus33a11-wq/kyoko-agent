"""Speak each A/B line with her phone voice: A = katakana route, B = English IPA spliced in. Usage: ab_speak.py <sherpa dir> <ab_lines.json> <out dir>"""
import json, os, sys
import numpy as np, sherpa_onnx, soundfile as sf
from piper.phonemize_japanese import JapanesePhonemizer
d, src, out = sys.argv[1:4]; os.makedirs(out, exist_ok=True)
tts = sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
    vits=sherpa_onnx.OfflineTtsVitsModelConfig(model=f"{d}/model.onnx", tokens=f"{d}/tokens.txt"), num_threads=2)))
known = set(l.split(" ")[0] for l in open(f"{d}/tokens.txt", encoding="utf-8") if l.strip())
ph = JapanesePhonemizer()
PUNCT = {'、': ',', '。': '.', '？': '?', '！': '!'}
def say(phones):
    phones = [p for p in phones if p in known]
    g = sherpa_onnx.GenerationConfig(); g.sid = 0; g.speed = 1.0
    g.phoneme_codepoints = [[ord(c) for c in phones]]
    return tts.generate("", g)
parts, sr = [], 22050
log = open(f"{out}/ab.tsv", "w", encoding="utf-8")
for n, line in enumerate(json.load(open(src, encoding="utf-8"))):
    a = [p for s in ph.phonemize(line["a"]) for p in s]
    b = []
    segs = line["segments"]
    for j, (k, t) in enumerate(segs):
        if k == "ja":
            lead = [PUNCT[c] for c in t[:1] if c in PUNCT]
            body = t[1:] if lead else t
            if b and b[-1] == " " and lead: b.pop()
            b += lead
            if body.strip("、。？！"):
                ps = [p for s in ph.phonemize(body) for p in s]
                # a piece cut out of a line is not the end of a sentence
                if j < len(segs) - 1 and ps and ps[-1] == ".": ps = ps[:-1]
                b += ps
            elif body: b += [PUNCT[c] for c in body if c in PUNCT]
        else:
            if b and b[-1] != " ": b.append(" ")
            b += list(t); b.append(" ")
    for tag, phones in (("A", a), ("B", b)):
        r = say(phones); sr = r.sample_rate; x = np.asarray(r.samples, dtype=np.float32)
        sf.write(f"{out}/{n:02d}{tag}.wav", x, sr)
        parts += [np.zeros(int(sr * 0.06), np.float32), x, np.zeros(int(sr * (0.5 if tag == "A" else 1.2)), np.float32)]
        log.write(f"{n}\t{tag}\t{line['a']}\t{''.join(phones)}\n")
sf.write(f"{out}/english_AB.wav", np.concatenate(parts), sr, subtype="PCM_16")
print("AB-DONE")
