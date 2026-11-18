"""Check each generated clip against its text with Japanese speech recognition, keep the clean ones,
brighten them (younger.py settings), resample to 22050 Hz mono 16-bit, and write the Piper CSV.

Usage: python check_distill.py <raw dir> <sentences.txt> <out dir> [--max-cer 0.25] [--jobs N]
Outputs: <out>/wavs/*.wav, <out>/metadata.csv ("file.wav|text"), <out>/report.tsv
"""
import argparse, os, subprocess, sys, unicodedata
from multiprocessing import Pool

import numpy as np
import soundfile as sf

A = None
REC = None


def norm(t):
    t = unicodedata.normalize("NFKC", t)
    return "".join(ch for ch in t if not unicodedata.category(ch).startswith(("P", "Z", "S")))


def kata_to_hira(t):
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in t)


def cer(ref, hyp):
    r, h = list(ref), list(hyp)
    if not r:
        return 0.0 if not h else 1.0
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = d[j]
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev = cur
    return d[len(h)] / len(r)


def reading(t):
    # Compare by reading (kana), so a kanji/kana spelling difference is not an error.
    import pyopenjtalk
    try:
        return kata_to_hira(norm(pyopenjtalk.g2p(t, kana=True)))
    except Exception:
        return kata_to_hira(norm(t))


def brighten(x, sr, st, fr):
    import pyworld as pw
    st = max(-3.0, min(2.0, st)); fr = max(0.95, min(1.08, fr))  # adult range only
    x = x.astype(np.float64)
    f0, t = pw.harvest(x, sr, f0_floor=70, f0_ceil=700)
    sp = pw.cheaptrick(x, f0, t, sr); ap_ = pw.d4c(x, f0, t, sr)
    f0 = f0 * (2 ** (st / 12))
    bins = sp.shape[1]; idx = np.arange(bins) / fr
    lo = np.floor(idx).astype(int).clip(0, bins - 1); hi = (lo + 1).clip(0, bins - 1); w = idx - np.floor(idx)
    sp2 = sp[:, lo] * (1 - w) + sp[:, hi] * w
    y = pw.synthesize(np.ascontiguousarray(f0), np.ascontiguousarray(sp2), np.ascontiguousarray(ap_), sr)
    return y / max(1e-9, np.abs(y).max()) * min(0.95, np.abs(x).max() + 1e-9)


def init(args):
    global A, REC
    A = args
    import sherpa_onnx
    d = args.asr_dir
    REC = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=f"{d}/encoder-epoch-99-avg-1.onnx", decoder=f"{d}/decoder-epoch-99-avg-1.onnx",
        joiner=f"{d}/joiner-epoch-99-avg-1.onnx", tokens=f"{d}/tokens.txt",
        num_threads=1, sample_rate=16000, feature_dim=80, decoding_method="greedy_search")


def one(item):
    n, text = item
    src = f"{A.raw}/{n:04d}.wav"
    if not os.path.exists(src):
        return None
    x, sr = sf.read(src, dtype="float32")
    if x.ndim > 1:
        x = x.mean(axis=1)
    dur = len(x) / sr
    s = REC.create_stream(); s.accept_waveform(sr, x); REC.decode_stream(s)
    hyp = s.result.text
    e = cer(reading(text), reading(hyp))
    ok = e <= A.max_cer and 0.5 <= dur <= 15
    row = f"{n}\t{'keep' if ok else 'drop'}\t{e:.2f}\t{dur:.1f}\t{text}\t{hyp}"
    if not ok:
        return (row, None)
    name = f"yume_{n:04d}.wav"
    tmp = f"{A.out}/wavs/_b_{name}"
    sf.write(tmp, brighten(x, sr, A.semitones, A.formant).astype(np.float32), sr, subtype="PCM_16")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp, "-ac", "1", "-ar", "22050",
                    "-sample_fmt", "s16", f"{A.out}/wavs/{name}"], check=True)
    os.remove(tmp)
    return (row, f"{name}|{text}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("raw"); ap.add_argument("sentences"); ap.add_argument("out")
    ap.add_argument("--max-cer", type=float, default=0.25)
    ap.add_argument("--semitones", type=float, default=1.0)
    ap.add_argument("--formant", type=float, default=1.04)
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--asr-dir", default="/w/sherpa-onnx-zipformer-ja-reazonspeech-2024-08-01")
    a = ap.parse_args()
    lines = [l.rstrip("\n") for l in open(a.sentences, encoding="utf-8") if l.strip()]
    items = [(n, l.partition("|")[2]) for n, l in enumerate(lines)]
    os.makedirs(f"{a.out}/wavs", exist_ok=True)
    kept, report = [], []
    with Pool(a.jobs, initializer=init, initargs=(a,)) as pool:
        for k, res in enumerate(pool.imap(one, items, chunksize=4)):
            if res is None:
                continue
            report.append(res[0])
            if res[1]:
                kept.append(res[1])
            if k % 200 == 0:
                print(f"{k}/{len(items)} checked, {len(kept)} kept", flush=True)
    open(f"{a.out}/metadata.csv", "w", encoding="utf-8").write("\n".join(kept) + "\n")
    open(f"{a.out}/report.tsv", "w", encoding="utf-8").write("\n".join(report) + "\n")
    total = sum(sf.info(f"{a.out}/wavs/{k.split('|')[0]}").duration for k in kept)
    print(f"kept {len(kept)} of {len(report)} clips, {total/60:.1f} min of audio")


if __name__ == "__main__":
    main()
