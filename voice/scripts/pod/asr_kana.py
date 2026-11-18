import sys, glob, unicodedata, re
import numpy as np, soundfile as sf, sherpa_onnx, pyopenjtalk
M = "/tmp/claude-0/voice/sherpa-onnx-zipformer-ja-reazonspeech-2024-08-01"
rec = sherpa_onnx.OfflineRecognizer.from_transducer(
    encoder=f"{M}/encoder-epoch-99-avg-1.int8.onnx", decoder=f"{M}/decoder-epoch-99-avg-1.int8.onnx",
    joiner=f"{M}/joiner-epoch-99-avg-1.int8.onnx", tokens=f"{M}/tokens.txt", num_threads=2)
def kana(s):
    s = unicodedata.normalize("NFKC", s)
    k = pyopenjtalk.g2p(s, kana=True)
    return re.sub(r"[\s、。？！?!〜ー…・,.’']", "", k)
def cer(a, b):
    d = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        p, d[0] = d[0], i
        for j, cb in enumerate(b, 1):
            p, d[j] = d[j], min(d[j] + 1, d[j-1] + 1, p + (ca != cb))
    return d[len(b)] / max(1, len(a))
refs = [l.rstrip("\n").split("|")[-1] for l in open(sys.argv[2], encoding="utf-8") if l.strip()]
tot = []
for i, w in enumerate(sorted(glob.glob(sys.argv[1] + "/0*.wav"))):
    x, sr = sf.read(w, dtype="float32")
    if x.ndim > 1: x = x.mean(1)
    pad = np.zeros(int(0.3 * sr), dtype=np.float32); x = np.concatenate([pad, x, pad])
    s = rec.create_stream(); s.accept_waveform(sr, x); rec.decode_stream(s)
    hyp = s.result.text; c = cer(kana(refs[i]), kana(hyp) if hyp else ""); tot.append(c)
    print(f"{i}\t{c:.2f}\t{refs[i]}\t| {hyp}")
print(f"mean kana CER {np.mean(tot):.3f}, median {np.median(tot):.3f}, lines over 0.25: {sum(c > 0.25 for c in tot)}/{len(tot)}")
