"""Her fine-tuned GPT-SoVITS voice speaks lines. CPU, in-process.

Usage (from the GPT-SoVITS repo root, inside gsv-env, with PYTHONPATH as in run_train.sh):
  python /tmp/claude-0/voice/speak.py --gpt <GPT .ckpt> --sovits <SoVITS .pth> --out <dir> \
      --ref <3-10 s clip of her> --ref-text <its text> --lines <file, one "lang|text" per line>
Each line becomes <out>/NNNN.wav; timings go to <out>/timing.tsv.
"""
import argparse
import os
import sys
import time

import numpy as np
import soundfile as sf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gpt", required=True)
    ap.add_argument("--sovits", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ref", required=True)
    ap.add_argument("--ref-text", required=True)
    ap.add_argument("--lines", required=True)
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--start", type=int, default=0, help="skip the first N lines (resume)")
    args = ap.parse_args()

    from TTS_infer_pack.TTS import TTS, TTS_Config

    config = TTS_Config({
        "custom": {
            "bert_base_path": "GPT_SoVITS/pretrained_models/chinese-roberta-wwm-ext-large",
            "cnhuhbert_base_path": "GPT_SoVITS/pretrained_models/chinese-hubert-base",
            "device": "cpu",
            "is_half": False,
            "t2s_weights_path": args.gpt,
            "version": "v2ProPlus",
            "vits_weights_path": args.sovits,
        }
    })
    tts = TTS(config)
    os.makedirs(args.out, exist_ok=True)
    lines = [l.rstrip("\n") for l in open(args.lines, encoding="utf-8") if l.strip()]
    timing = open(os.path.join(args.out, "timing.tsv"), "a", encoding="utf-8")
    for n, line in enumerate(lines):
        if n < args.start:
            continue
        lang, _, text = line.partition("|")
        path = os.path.join(args.out, f"{n:04d}.wav")
        if os.path.exists(path):
            continue
        t0 = time.time()
        chunks, sr = [], None
        for sr, audio in tts.run({
            "text": text, "text_lang": lang,
            "ref_audio_path": args.ref, "prompt_text": args.ref_text, "prompt_lang": "ja",
            "top_k": 15, "top_p": 1, "temperature": 1, "text_split_method": "cut5",
            "batch_size": 1, "seed": args.seed + n, "repetition_penalty": 1.35,
            "parallel_infer": False, "speed_factor": 1.0,
        }):
            chunks.append(audio)
        audio = np.concatenate(chunks) if chunks else np.zeros(1, dtype=np.int16)
        sf.write(path, audio, sr)
        took = time.time() - t0
        dur = len(audio) / sr
        timing.write(f"{n}\t{lang}\t{dur:.2f}\t{took:.2f}\t{text}\n")
        timing.flush()
        print(f"[{n}] {dur:.1f}s audio in {took:.1f}s (RTF {took / max(dur, 0.01):.2f}): {text[:40]}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
