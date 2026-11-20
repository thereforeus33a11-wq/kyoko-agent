"""Her teacher voice speaks lines one SENTENCE at a time, and every sentence is heard back before it is kept.

Why: on lines with several sentences the teacher (GPT-SoVITS, her GPT fine-tuned on Japanese) sometimes
loses its place: it drops a sentence ("I am not mad." vanished from "I am not mad. I am just bored. There
is a difference."), says one twice, or slurs an ending (聞いてないし -> 聞いてなーしゅ). The owner heard
that as her being cut off in the middle of her sentences. So here:
  - a line is cut into sentences (at . ! ? 。 ！ ？ and at ? and ! inside quotes);
  - each sentence is spoken on its own, its edges trimmed by her actual sound (from 60 ms before the first
    sound within 30 dB of her speech to 100 ms after the last sound within 32 dB, so soft endings stay),
  - heard back with faster-whisper large-v3: English by word error, Japanese by kana reading (Open JTalk,
    as check_distill.py), mixed lines by characters of both; kept if within the threshold, else spoken
    again with another seed, up to --tries times, keeping the best attempt;
  - the kept sentences are joined with natural pauses (0.32 s after . ! ? 。 ！ ？, 0.2 s otherwise).
Each line becomes <out>/NNNN.wav; <out>/checked<i>.tsv lists every sentence, its tries and its error.

Usage (gsv env, from the GPT-SoVITS root, with the gsv() PYTHONPATH; needs faster-whisper in gsv-env):
  python speak_checked.py --gpt G --sovits S --out DIR --refs REFS.tsv --lines LINES --whisper DIR \
      [--seed 1234] [--tries 4] [--shard i/n] [--temperature 1.0] [--top-k 20]
"""
import argparse
import os
import re
import sys
import time
import unicodedata

import numpy as np
import soundfile as sf

SENT = re.compile(r"(?<=[.!?。！？])\s+|(?<=[。！？])")
LATIN = re.compile(r"[A-Za-z]")


def sentences(text):
    parts = [p.strip() for p in SENT.split(text.strip()) if p and p.strip()]
    # Keep tiny pieces ("Okay.") with the next sentence so each call has enough to say.
    out = []
    for p in parts:
        if out and len(re.sub(r"\W", "", out[-1])) < 4:
            out[-1] = out[-1] + " " + p
        else:
            out.append(p)
    return out or [text.strip()]


def levels(x, sr):
    fr = max(1, int(0.01 * sr)); n = max(1, len(x) // fr)
    return 20 * np.log10(np.sqrt(np.mean(x[:n * fr].reshape(n, fr).astype(np.float64) ** 2, axis=1)) + 1e-9)


def trim(x, sr):
    lv = levels(x, sr)
    if len(lv) < 3:
        return x
    sp = np.percentile(lv, 95)
    on = np.where(lv >= sp - 30)[0]; off = np.where(lv >= sp - 32)[0]
    if not len(on):
        return x
    a = max(0, int((on[0] / 100 - 0.06) * sr)); b = min(len(x), int(((off[-1] + 1) / 100 + 0.10) * sr))
    y = x[a:b].astype(np.float32).copy()
    k = min(len(y) // 2, int(0.008 * sr)); kout = min(len(y) // 2, int(0.05 * sr))
    if k:
        y[:k] *= np.linspace(0, 1, k)
    if kout:
        y[-kout:] *= np.linspace(1, 0, kout) ** 2
    return y


def plain(t):
    t = unicodedata.normalize("NFKC", t).lower()
    return re.sub(r"[^\w\s']", " ", t)


def words(t):
    return [w.strip("'") for w in plain(t).split() if w.strip("'")]


def edit(a, b):
    d = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(b) + 1):
            cur = d[j]
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (a[i - 1] != b[j - 1]))
            prev = cur
    return d[len(b)]


def reading(t, g2p):
    t = unicodedata.normalize("NFKC", t)
    out = []
    for piece in re.split(r"([A-Za-z][A-Za-z' ]*)", t):
        if not piece.strip():
            continue
        if LATIN.search(piece):
            out.append(re.sub(r"[^a-z]", "", piece.lower()))
        else:
            try:
                k = g2p(piece, kana=True)
            except Exception:
                k = piece
            k = "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in k)
            out.append("".join(c for c in k if not unicodedata.category(c).startswith(("P", "Z", "S"))))
    return "".join(out)


def error(lang, text, heard, g2p):
    if lang == "en" and not re.search(r"[぀-ヿ一-鿿]", text):
        r, h = words(text), words(heard)
        return edit(r, h) / max(1, len(r))
    r, h = reading(text, g2p), reading(heard, g2p)
    return edit(list(r), list(h)) / max(1, len(r))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gpt", required=True); ap.add_argument("--sovits", required=True)
    ap.add_argument("--out", required=True); ap.add_argument("--refs", required=True)
    ap.add_argument("--lines", required=True); ap.add_argument("--whisper", required=True)
    ap.add_argument("--seed", type=int, default=1234); ap.add_argument("--tries", type=int, default=4)
    ap.add_argument("--temperature", type=float, default=1.0); ap.add_argument("--top-k", type=int, default=20)
    ap.add_argument("--speed", type=float, default=1.0); ap.add_argument("--shard", default="0/1")
    ap.add_argument("--max-err-en", type=float, default=0.10); ap.add_argument("--max-err-ja", type=float, default=0.12)
    args = ap.parse_args()
    si, sn = (int(v) for v in args.shard.split("/"))
    refs = [l.rstrip("\n").split("\t", 1) for l in open(args.refs, encoding="utf-8") if l.strip()]
    ref, ref_text = refs[0]

    from TTS_infer_pack.TTS import TTS, TTS_Config
    import pyopenjtalk
    from faster_whisper import WhisperModel

    tts = TTS(TTS_Config({"custom": {
        "bert_base_path": "GPT_SoVITS/pretrained_models/chinese-roberta-wwm-ext-large",
        "cnhuhbert_base_path": "GPT_SoVITS/pretrained_models/chinese-hubert-base",
        "device": "cuda", "is_half": False, "t2s_weights_path": args.gpt,
        "version": "v2ProPlus", "vits_weights_path": args.sovits}}))
    asr = WhisperModel(args.whisper, device="cuda", compute_type="float16")
    os.makedirs(args.out, exist_ok=True)
    lines = [l.rstrip("\n") for l in open(args.lines, encoding="utf-8") if l.strip()]
    log = open(os.path.join(args.out, f"checked{si}.tsv"), "a", encoding="utf-8")

    def say(text, lang, seed):
        chunks, sr = [], 32000
        for sr, audio in tts.run({
            "text": text, "text_lang": lang, "ref_audio_path": ref, "prompt_text": ref_text, "prompt_lang": "ja",
            "top_k": args.top_k, "top_p": 1, "temperature": args.temperature, "text_split_method": "cut0",
            "batch_size": 1, "seed": seed, "repetition_penalty": 1.35, "parallel_infer": False,
            "speed_factor": args.speed, "use_cuda_graph": False}):
            chunks.append(audio)
        if not chunks:
            return np.zeros(1, np.float32), sr
        x = np.concatenate(chunks)
        x = x.astype(np.float32) / 32768.0 if x.dtype == np.int16 else x.astype(np.float32)
        return trim(x, sr), sr

    def hear(x, sr, lang):
        import librosa
        y = librosa.resample(x, orig_sr=sr, target_sr=16000) if sr != 16000 else x
        segs, _ = asr.transcribe(y, language=("ja" if lang == "ja" else "en"), beam_size=5, vad_filter=False)
        return "".join(s.text for s in segs).strip()

    for n, line in enumerate(lines):
        if n % sn != si:
            continue
        path = os.path.join(args.out, f"{n:04d}.wav")
        if os.path.exists(path):
            continue
        lang, _, text = line.partition("|")
        t0 = time.time(); parts, sr = [], 32000
        for k, s in enumerate(sentences(text)):
            limit = args.max_err_en if (lang == "en" and not re.search(r"[぀-ヿ一-鿿]", s)) else args.max_err_ja
            best = None
            for t in range(args.tries):
                x, sr = say(s, lang, args.seed + n * 101 + k * 17 + t * 7919)
                heard = hear(x, sr, lang)
                e = error(lang, s, heard, pyopenjtalk.g2p)
                if best is None or e < best[0]:
                    best = (e, x, heard, t + 1)
                if e <= limit:
                    break
            e, x, heard, tries = best
            log.write(f"{n}\t{k}\t{tries}\t{e:.3f}\t{s}\t{heard}\n"); log.flush()
            pause = 0.32 if re.search(r"[.!?。！？]$", s) else 0.2
            parts += [x, np.zeros(int(sr * pause), np.float32)]
        audio = np.concatenate(parts[:-1]) if len(parts) > 1 else parts[0]
        sf.write(path, audio, sr, subtype="PCM_16")
        print(f"[{n}] {len(audio) / sr:.1f}s in {time.time() - t0:.1f}s: {text[:40]}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
