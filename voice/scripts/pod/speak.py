"""Her fine-tuned GPT-SoVITS voice speaks lines, in-process (GPU or CPU).

Usage (from the GPT-SoVITS repo root, inside gsv-env, with PYTHONPATH as in run_train.sh):
  python /tmp/claude-0/voice/speak.py --gpt <GPT .ckpt> --sovits <SoVITS .pth> --out <dir> \
      --ref <3-10 s clip of her> --ref-text <its text> --lines <file, one "lang|text" per line>
  or, instead of --ref/--ref-text, --refs <tsv of "clip.wav<TAB>its text">: line n uses reference
  (n + --ref-offset) mod count, so a few of her clips take turns across the lines.
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
    ap.add_argument("--ref")
    ap.add_argument("--ref-text")
    ap.add_argument("--refs", help="tsv: clip path<TAB>its text; the clips take turns across lines")
    ap.add_argument("--ref-offset", type=int, default=0, help="shift the turns (a second take uses another clip)")
    ap.add_argument("--lines", required=True)
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--start", type=int, default=0, help="skip the first N lines (resume)")
    ap.add_argument("--speed", type=float, default=1.0, help="speaking speed factor (1.1 = 10%% faster)")
    ap.add_argument("--temperature", type=float, default=1.0, help="more = livelier, less = steadier")
    ap.add_argument("--top-k", type=int, default=15)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--half", action="store_true")
    ap.add_argument("--shard", default="0/1", help="i/n: only lines with index %% n == i")
    args = ap.parse_args()
    si, sn = (int(v) for v in args.shard.split("/"))
    if args.refs:
        refs = [l.rstrip("\n").split("\t", 1) for l in open(args.refs, encoding="utf-8") if l.strip() and not l.startswith("#")]
    elif args.ref and args.ref_text:
        refs = [[args.ref, args.ref_text]]
    else:
        ap.error("give --ref and --ref-text, or --refs")

    from TTS_infer_pack.TTS import TTS, TTS_Config

    config = TTS_Config({
        "custom": {
            "bert_base_path": "GPT_SoVITS/pretrained_models/chinese-roberta-wwm-ext-large",
            "cnhuhbert_base_path": "GPT_SoVITS/pretrained_models/chinese-hubert-base",
            "device": args.device,
            "is_half": args.half,
            "t2s_weights_path": args.gpt,
            "version": "v2ProPlus",
            "vits_weights_path": args.sovits,
        }
    })
    tts = TTS(config)
    os.makedirs(args.out, exist_ok=True)
    lines = [l.rstrip("\n") for l in open(args.lines, encoding="utf-8") if l.strip()]
    timing = open(os.path.join(args.out, f"timing{si}.tsv"), "a", encoding="utf-8")
    for n, line in enumerate(lines):
        if n < args.start or n % sn != si:
            continue
        lang, _, text = line.partition("|")
        path = os.path.join(args.out, f"{n:04d}.wav")
        if os.path.exists(path):
            continue
        t0 = time.time()
        chunks, sr = [], None
        ref, ref_text = refs[(n + args.ref_offset) % len(refs)]
        for sr, audio in tts.run({
            "text": text, "text_lang": lang,
            "ref_audio_path": ref, "prompt_text": ref_text, "prompt_lang": "ja",
            "top_k": args.top_k, "top_p": 1, "temperature": args.temperature, "text_split_method": "cut5",
            "batch_size": 1, "seed": args.seed + n, "repetition_penalty": 1.35,
            "parallel_infer": False, "speed_factor": args.speed,
            # The CUDA-graph decoder of this GPT-SoVITS commit cuts lines short on GPU.
            "use_cuda_graph": False,
        }):
            chunks.append(audio)
        audio = np.concatenate(chunks) if chunks else np.zeros(1, dtype=np.int16)
        sf.write(path, audio, sr)
        took = time.time() - t0
        dur = len(audio) / sr
        timing.write(f"{n}\t{lang}\t{dur:.2f}\t{took:.2f}\t{text}\t{os.path.basename(ref)}\n")
        timing.flush()
        print(f"[{n}] {dur:.1f}s audio in {took:.1f}s (RTF {took / max(dur, 0.01):.2f}): {text[:40]}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
