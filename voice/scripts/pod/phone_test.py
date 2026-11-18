"""Speak test lines the way the phone will: Piper's Japanese phonemizer -> codepoints -> sherpa-onnx.
Usage: python phone_test.py <sherpa dir> <lines file> <out dir>"""
import os, sys, time
import sherpa_onnx, soundfile as sf
from piper.phonemize_japanese import JapanesePhonemizer
d, lines_path, out = sys.argv[1:4]
os.makedirs(out, exist_ok=True)
tts = sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
    vits=sherpa_onnx.OfflineTtsVitsModelConfig(model=f"{d}/model.onnx", tokens=f"{d}/tokens.txt"), num_threads=2)))
ph = JapanesePhonemizer()
for n, line in enumerate(l.rstrip("\n") for l in open(lines_path, encoding="utf-8") if l.strip()):
    text = line.partition("|")[2] or line
    g = sherpa_onnx.GenerationConfig(); g.sid = 0; g.speed = 1.0
    g.phoneme_codepoints = [[ord(c) for c in s] for s in ph.phonemize(text)]
    t0 = time.time(); a = tts.generate("", g); took = time.time() - t0
    sf.write(f"{out}/{n:04d}.wav", a.samples, a.sample_rate)
    print(f"{n}\t{len(a.samples)/a.sample_rate:.2f}s\tRTF {took/max(0.01, len(a.samples)/a.sample_rate):.3f}\t{text}", flush=True)
