"""Speak lines with a phone voice the way the phone does: text -> phoneme codepoints -> sherpa-onnx.
  --route mixed  the new route: English to IPA from en_ipa_table.json, Japanese through Open JTalk
  --route kana   today's route: every Latin word to katakana (KanaText) and all of it through Open JTalk
Usage: python phone_test_lang.py <sherpa dir> <lines> <out dir> [--route mixed|kana] [--sid N]
<lines>: lines_lang.tsv-style TSV (n, text columns) or one "lang|text" / text per line.
--sid: the speaker id every line is spoken with (a multi-speaker voice: her style), as the phone passes it.
--float: write the samples sherpa returns as 32-bit float (default 16-bit PCM), for exact comparisons.
--noise-scale, --noise-scale-w, --length-scale: the voice's inference settings (sherpa-onnx's VITS model config, one
value for every speaker of the loaded model, as the app's OfflineTtsVitsModelConfig); left out, sherpa's defaults
(0.667, 0.8, 1.0: Piper's), exactly as before.
Each line n becomes <out>/NNNN.wav; <out>/phone_test.tsv has n, seconds, RTF, phonemes, text.
"""
import argparse
import csv
import os
import sys
import time

import numpy as np
import sherpa_onnx
import soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from mix_phonemize import MixedPhonemizer  # noqa: E402


def read_lines(path):
    with open(path, encoding="utf-8") as f:
        first = f.readline()
        f.seek(0)
        if first.startswith("n\t"):
            return [(int(r["n"]), r["text"]) for r in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE)]
        return [(k, l.rstrip("\n").split("|", 1)[-1]) for k, l in enumerate(l for l in f if l.strip())]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sherpa"); ap.add_argument("lines"); ap.add_argument("out")
    ap.add_argument("--route", choices=["mixed", "kana"], default="mixed")
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--sid", type=int, default=0)
    ap.add_argument("--float", action="store_true")
    ap.add_argument("--noise-scale", type=float)
    ap.add_argument("--noise-scale-w", type=float)
    ap.add_argument("--length-scale", type=float)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    knobs = {k: v for k, v in (("noise_scale", a.noise_scale), ("noise_scale_w", a.noise_scale_w),
                               ("length_scale", a.length_scale)) if v is not None}
    tts = sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
        vits=sherpa_onnx.OfflineTtsVitsModelConfig(model=f"{a.sherpa}/model.onnx", tokens=f"{a.sherpa}/tokens.txt", **knobs),
        num_threads=a.threads)))
    if knobs:
        print("inference settings", knobs)
    known = {l.rsplit(" ", 1)[0] for l in open(f"{a.sherpa}/tokens.txt", encoding="utf-8") if l.strip()}
    mp = MixedPhonemizer()
    kana = None
    if a.route == "kana":
        from kana_text import KanaText
        kana = KanaText(mp.en.cmu)
    log = open(os.path.join(a.out, "phone_test.tsv"), "w", encoding="utf-8")
    for n, text in read_lines(a.lines):
        sents = mp.ja.phonemize(kana.convert(text)) if kana else mp.phonemize(text)
        if not sents:
            log.write(f"{n}\t0\t0\t\t{text}\n")
            continue
        missing = sorted({p for s in sents for p in s if p not in known})
        if missing:
            print(f"{n}: phonemes without an id {missing}", file=sys.stderr)
        g = sherpa_onnx.GenerationConfig(); g.sid = a.sid; g.speed = 1.0
        g.phoneme_codepoints = [[ord(c) for c in s if c in known] for s in sents]
        t0 = time.time()
        r = tts.generate("", g)
        took = time.time() - t0
        x = np.asarray(r.samples, dtype=np.float32)
        sf.write(os.path.join(a.out, f"{n:04d}.wav"), x, r.sample_rate, subtype="FLOAT" if a.float else "PCM_16")
        dur = len(x) / r.sample_rate
        log.write(f"{n}\t{dur:.2f}\t{took / max(0.01, dur):.3f}\t{' / '.join(''.join(s) for s in sents)}\t{text}\n")
        log.flush()
    log.close()
    print("PHONE-TEST-DONE", a.out)


if __name__ == "__main__":
    main()
