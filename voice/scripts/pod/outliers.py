"""Takes that don't sound like her usual self are left out of her phone voice's training set.

Why: the owner heard her voice "jump around", "like different people are talking with every other line".
The rotating references and the vocoder that caused most of it are gone in v2; this is the last gate before
the student learns: within each language, a take whose timbre or pitch stands far from the rest of her takes
is dropped, so the phone voice never learns that version of her.

For every clip of a dataset (DIR/metadata.csv as file|text, DIR/wavs/):
  - timbre: WavLM x-vector cosine to the centre of her reference clip(s) (as check_lang.py sim);
  - pitch: median f0 (pyworld harvest), in semitones.
A clip is dropped when its timbre is more than --z robust deviations (median and MAD of the dataset) under
the median, when its median pitch is more than --z robust deviations from the median either way, when it has
no pitch at all, or when its median pitch is over --max-p50 Hz (her adult range). Clips under 0.5 s are
padded with silence for the timbre model.
The original list stays as DIR/metadata.all.csv (and is what a second run reads), the kept list becomes
DIR/metadata.csv, every clip's numbers and reason go to DIR/outliers.tsv, the counts to DIR/outliers.json.

Usage (gsv env): python outliers.py --ds DIR --refs REFS.tsv --model WAVLM_DIR [--z 3.5] [--max-p50 345]
"""
import argparse
import json
import os
import shutil
import sys

from multiprocessing import Pool

import numpy as np
import soundfile as sf


def median_pitch(path):
    import pyworld as pw
    x, sr = sf.read(path, dtype="float32")
    x = x.mean(axis=1) if x.ndim > 1 else x
    f0, _ = pw.harvest(x.astype(np.float64), sr, f0_floor=70, f0_ceil=800)
    v = f0[f0 > 0]
    return float(np.median(v)) if len(v) else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ds", required=True); ap.add_argument("--refs", required=True)
    ap.add_argument("--model", required=True); ap.add_argument("--device", default="cuda")
    ap.add_argument("--z", type=float, default=3.5); ap.add_argument("--max-p50", type=float, default=345.0)
    ap.add_argument("--jobs", type=int, default=max(1, min(32, (os.cpu_count() or 2) - 4)))
    a = ap.parse_args()

    full = os.path.join(a.ds, "metadata.all.csv")
    if not os.path.exists(full):
        shutil.copyfile(os.path.join(a.ds, "metadata.csv"), full)
    rows = [l.rstrip("\n").split("|", 1) for l in open(full, encoding="utf-8") if l.strip()]
    paths = [os.path.join(a.ds, "wavs", name) for name, _ in rows]
    # Pitch on the CPUs while the GPU does timbre; the workers start before CUDA is touched.
    pool = Pool(min(a.jobs, len(paths) or 1))
    pitches = pool.map_async(median_pitch, paths, chunksize=8)

    import librosa
    import torch
    from transformers import AutoFeatureExtractor, WavLMForXVector
    fe = AutoFeatureExtractor.from_pretrained(a.model)
    model = WavLMForXVector.from_pretrained(a.model).to(a.device).eval()

    def embed(x, sr):
        if sr != 16000:
            x = librosa.resample(x, orig_sr=sr, target_sr=16000)
        if len(x) < 8000:
            x = np.pad(x, (0, 8000 - len(x)))
        inp = fe(x, sampling_rate=16000, return_tensors="pt", padding=True)
        with torch.no_grad():
            e = model(**{k: v.to(a.device) for k, v in inp.items()}).embeddings
        return torch.nn.functional.normalize(e, dim=-1)[0].cpu().numpy()

    def load(p):
        x, sr = sf.read(p, dtype="float32")
        return (x.mean(axis=1) if x.ndim > 1 else x), sr

    refs = [l.rstrip("\n").split("\t")[0] for l in open(a.refs, encoding="utf-8") if l.strip()]
    centre = np.mean([embed(*load(p)) for p in refs], axis=0)
    centre /= np.linalg.norm(centre)

    sims = np.array([float(np.dot(embed(*load(p)), centre)) for p in paths])
    p50s = np.array(pitches.get())
    pool.close(); pool.join()

    def robust(v):
        med = float(np.median(v)); mad = float(np.median(np.abs(v - med))) * 1.4826
        return med, max(mad, 1e-6)

    s_med, s_mad = robust(sims)
    voiced = p50s > 0
    st = np.where(voiced, 12 * np.log2(np.maximum(p50s, 1) / 100.0), 0.0)
    p_med, p_mad = robust(st[voiced]) if voiced.any() else (0.0, 1.0)
    kept, why_count = [], {"timbre": 0, "pitch": 0, "no_pitch": 0, "over_adult_range": 0}
    with open(os.path.join(a.ds, "outliers.tsv"), "w", encoding="utf-8") as rep:
        rep.write("file\tsim\tsim_z\tp50\tpitch_z\tkeep\twhy\ttext\n")
        for (name, text), s, p, t in zip(rows, sims, p50s, st):
            sz = (s - s_med) / s_mad
            pz = (t - p_med) / p_mad if p > 0 else float("nan")
            why = []
            if sz < -a.z:
                why.append("timbre")
            if p <= 0:
                why.append("no_pitch")
            elif abs(pz) > a.z:
                why.append("pitch")
            if p > a.max_p50:
                why.append("over_adult_range")
            for w in why:
                why_count[w] += 1
            rep.write(f"{name}\t{s:.4f}\t{sz:.2f}\t{p:.0f}\t{pz:.2f}\t{0 if why else 1}\t{','.join(why)}\t{text}\n")
            if not why:
                kept.append(f"{name}|{text}")
    with open(os.path.join(a.ds, "metadata.csv"), "w", encoding="utf-8") as f:
        f.write("\n".join(kept) + "\n")
    summary = {
        "clips": len(rows), "kept": len(kept), "dropped": len(rows) - len(kept), "why": why_count,
        "timbre_median": round(s_med, 4), "timbre_mad": round(s_mad, 4),
        "pitch_median_hz": round(float(100 * 2 ** (p_med / 12)), 1), "pitch_mad_semitones": round(p_mad, 2),
        "z": a.z, "max_p50_hz": a.max_p50,
    }
    json.dump(summary, open(os.path.join(a.ds, "outliers.json"), "w"), indent=1)
    print(f"outliers {a.ds}: kept {len(kept)} of {len(rows)}; dropped {why_count}; timbre median {s_med:.3f} "
          f"(MAD {s_mad:.3f}), pitch median {summary['pitch_median_hz']} Hz (MAD {p_mad:.2f} st)", flush=True)


if __name__ == "__main__":
    sys.exit(main())
