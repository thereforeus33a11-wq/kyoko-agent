"""The sherpa ReazonSpeech kana recogniser, phrase by phrase.

Why: check_lang.py prep gives the recogniser a whole take with 0.3 s of silence around it. On loud takes made of two
exclaimed sentences it often returns only ONE of them (the other sentence is dropped whole), although faster-whisper
hears the take right. Of 39 such takes probed in the loud set, 35 were heard right when each phrase was given on its
own, 32 with 1 s of silence around the take, 14 at -10 dB: the drop is the recogniser's, not the take's. A words gate
that reads this recogniser should read the better of its two hearings (whole take, phrase by phrase).

A phrase is a stretch of sound between pauses of 150 ms or more (the range trial's measure.py phrases(): frames
within 35 dB of the take's level, at least 300 ms long); 50 ms is kept on each side and each phrase gets the same
0.3 s of silence as check_lang.py gives a take.

Usage (gsv-env): python sherpa_phrases.py <out.tsv> <jobs> <wav or dir> [<wav or dir> ...]
Writes file, phrases, kana_hyp_phr. Library: hear(path) after init().
"""
import glob
import os
import sys
from multiprocessing import Pool

import numpy as np
import soundfile as sf

ASR_DIR = os.environ.get("SHERPA_JA", "/w/sherpa-onnx-zipformer-ja-reazonspeech-2024-08-01")
_W = {}


def init():
    import sherpa_onnx
    d = ASR_DIR
    _W["rec"] = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=f"{d}/encoder-epoch-99-avg-1.onnx", decoder=f"{d}/decoder-epoch-99-avg-1.onnx",
        joiner=f"{d}/joiner-epoch-99-avg-1.onnx", tokens=f"{d}/tokens.txt",
        num_threads=1, sample_rate=16000, feature_dim=80, decoding_method="greedy_search")


def phrases(x, sr):
    """(start, end) seconds of each phrase: as the range trial's measure.py."""
    fr = max(1, int(0.01 * sr)); n = max(1, len(x) // fr)
    lv = 20 * np.log10(np.sqrt(np.mean(x[:n * fr].reshape(n, fr).astype(np.float64) ** 2, axis=1)) + 1e-9)
    act = lv >= np.percentile(lv, 95) - 35
    out, start, gap = [], None, 0
    for i, a in enumerate(act):
        if a:
            if start is None:
                start = i
            gap = 0
        elif start is not None:
            gap += 1
            if gap >= 15:
                out.append((start, i - gap + 1)); start = None; gap = 0
    if start is not None:
        out.append((start, len(act)))
    return [(a / 100, b / 100) for a, b in out if b - a >= 30]


def hear(path):
    """(number of phrases, what the recogniser heard, the phrases joined)."""
    import librosa
    x, sr = sf.read(path, dtype="float32")
    if x.ndim > 1:
        x = x.mean(axis=1)
    if sr != 16000:
        x = librosa.resample(x, orig_sr=sr, target_sr=16000); sr = 16000
    rec = _W["rec"]; pad = np.zeros(int(0.3 * sr), dtype=np.float32); out = []
    ph = phrases(x, sr)
    for a, b in ph:
        seg = x[max(0, int((a - 0.05) * sr)):int((b + 0.05) * sr)]
        s = rec.create_stream(); s.accept_waveform(sr, np.concatenate([pad, seg, pad])); rec.decode_stream(s)
        out.append(s.result.text)
    return len(ph), "".join(out)


def _one(path):
    k, h = hear(path)
    return os.path.basename(path), k, h


def main():
    out, jobs = sys.argv[1], int(sys.argv[2])
    files = []
    for p in sys.argv[3:]:
        files += sorted(glob.glob(os.path.join(p, "*.wav"))) if os.path.isdir(p) else [p]
    with Pool(jobs, initializer=init) as pool, open(out, "w", encoding="utf-8") as o:
        o.write("file\tphrases\tkana_hyp_phr\n")
        for f, k, h in pool.imap(_one, files, chunksize=8):
            o.write(f"{f}\t{k}\t{h}\n")
    print(f"SHERPA-PHRASES-DONE {len(files)} takes into {out}")


if __name__ == "__main__":
    sys.exit(main())
