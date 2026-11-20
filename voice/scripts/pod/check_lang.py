"""Check her teacher's English and mixed takes, keep the best take of each line, brighten it like her
Japanese data, and write a Piper dataset.

Steps (each writes its own TSV under <work>, so a step can be rerun alone):
  asr   English recognition (faster-whisper large-v3, fp16, language en, beam 5, no conditioning on
        previous text, Whisper's English normalizer). English lines: WER. English-led mixed lines:
        the Japanese words are left out of the reference and extra words in the hypothesis are not
        counted (word error = substitutions + deletions). Runs in the asr env, one GPU per shard.
  prep  For every take: brighten (younger.py settings), 22050 Hz mono 16-bit, pitch (WORLD harvest on
        voiced frames, p50 and p90), length per phoneme; Japanese-led lines are recognised with the
        Japanese recogniser (asr_kana.py's way) and scored by kana error, English words expected as
        the katakana the phone reads them as today. Runs in gsv-env on all CPUs.
  sim   Timbre: WavLM speaker-verification x-vector cosine to her real clips (brightened the same
        way), for every take and for a sample of her Japanese training clips. gsv-env, GPU.
  pick  The best take that passes, copied into <out>/wavs; metadata.csv, val_ids.txt (held-out lines),
        report_lang.tsv, summary.txt and teacher_stats.json (the student is held to these).

Usage:
  check_lang.py asr  --lines L --raw R --work W --shard i/n [--device cuda] [--model DIR]
  check_lang.py prep --lines L --raw R --work W [--jobs N]
  check_lang.py sim  --work W --refs REFS.tsv --ja-wavs DIR [--model DIR]
  check_lang.py pick --lines L --work W --out DS [--ja-wavs DIR]
<raw> holds one folder per take (A, B, ...) of speak.py output (NNNN.wav = row n of lines_lang.tsv).
"""
import argparse
import csv
import glob
import json
import math
import os
import random
import re
import subprocess
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

MAX_WER = 0.15
MAX_KANA = 0.25
MAX_P90 = 500.0
MAX_MEDIAN = 345.0
MAX_EN_OVER_JA_ST = 1.5


def read_lines(path):
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE))
    for r in rows:
        r["n"] = int(r["n"])
    return rows


def takes_in(raw):
    return sorted(d for d in os.listdir(raw) if os.path.isdir(os.path.join(raw, d)))


def edit_ops(ref, hyp):
    """(substitutions + deletions, insertions) of the best alignment of word lists."""
    n, m = len(ref), len(hyp)
    d = [[(0, 0)] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        d[i][0] = (i, 0)
    for j in range(1, m + 1):
        d[0][j] = (0, j)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            sub = d[i - 1][j - 1]
            sub = (sub[0] + (ref[i - 1] != hyp[j - 1]), sub[1])
            dele = (d[i - 1][j][0] + 1, d[i - 1][j][1])
            ins = (d[i][j - 1][0], d[i][j - 1][1] + 1)
            d[i][j] = min(sub, dele, ins, key=lambda x: x[0] + x[1])
    return d[n][m]


def cer(a, b):
    d = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        p, d[0] = d[0], i
        for j, cb in enumerate(b, 1):
            p, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, p + (ca != cb))
    return d[len(b)] / max(1, len(a))


def line_parts(mp, text):
    """English reference words, Japanese size, and whether the line is English-led."""
    en_words, ja_units = [], 0
    for plan in mp.plan(text):
        if plan.verbatim:
            ja_units += math.ceil(sum(1 for c in plan.text if not c.isspace()) / 2)
            continue
        for seg in plan.segments:
            for t in seg.toks:
                if seg.route == "en":
                    if t.kind == "word":
                        en_words.append(t.word if t.reading is None or t.reading.source != "time" else t.text)
                    elif t.kind == "num":
                        en_words += mp.en.spell_number(t.text)
                elif t.kind == "word":
                    ja_units += 1
                elif t.kind in ("ja", "num"):
                    ja_units += math.ceil(len(t.text) / 2)
    return en_words, ja_units, len(en_words) >= ja_units


# ---------------------------------------------------------------------------------------------- asr
def english_normalizer(mp):
    """Whisper's EnglishTextNormalizer (whisper-normalizer package); without it, a plain one: lower
    case, digits spelled the way the table spells them, punctuation off."""
    try:
        from whisper_normalizer.english import EnglishTextNormalizer
        return EnglishTextNormalizer()
    except ImportError:
        print("whisper-normalizer not installed: using the plain normalizer", file=sys.stderr)

    def plain(text):
        t = text.lower().replace("’", "'")
        t = re.sub(r"[¥$€]?\d[\d,.:]*(?:st|nd|rd|th)?%?", lambda m: " " + " ".join(mp.en.spell_number(m.group(0))) + " ", t)
        t = re.sub(r"[^a-z' ]+", " ", t)
        return " ".join(w.strip("'") for w in t.split() if w.strip("'"))
    return plain


def cmd_asr(a):
    import numpy as np
    from faster_whisper import WhisperModel
    from faster_whisper.audio import decode_audio
    from mix_phonemize import MixedPhonemizer
    mp = MixedPhonemizer()
    norm = english_normalizer(mp)
    si, sn = (int(v) for v in a.shard.split("/"))
    model = WhisperModel(a.model, device=a.device, compute_type="float16")
    rows = [r for r in read_lines(a.lines) if r["n"] % sn == si]
    out = open(os.path.join(a.work, f"asr_{si}.tsv"), "w", encoding="utf-8")
    out.write("n\ttake\terr\tn_ref\tref\thyp\n")
    for r in rows:
        en_words, _, en_led = line_parts(mp, r["text"])
        if not en_words or not en_led:
            continue
        ref = norm(" ".join(en_words)).split()
        for take in takes_in(a.raw):
            wav = os.path.join(a.raw, take, f"{r['n']:04d}.wav")
            if not os.path.exists(wav):
                continue
            # 0.3 s of silence either side: a take cut tight to her first sound (edges.py) would
            # otherwise often lose its first word to the recogniser, not to the take.
            audio = decode_audio(wav, sampling_rate=16000)
            pad = np.zeros(int(0.3 * 16000), dtype=audio.dtype)
            segs, _ = model.transcribe(np.concatenate([pad, audio, pad]), language="en", beam_size=5,
                                       condition_on_previous_text=False, without_timestamps=True, vad_filter=False)
            hyp_raw = " ".join(s.text.strip() for s in segs)
            hyp = norm(hyp_raw).split()
            sd, ins = edit_ops(ref, hyp)
            err = (sd + ins) / max(1, len(ref)) if r["kind"] == "en" else sd / max(1, len(ref))
            out.write(f"{r['n']}\t{take}\t{err:.3f}\t{len(ref)}\t{' '.join(ref)}\t{hyp_raw.replace(chr(9), ' ')}\n")
            out.flush()
    out.close()
    print(f"asr shard {si}/{sn} done")


# --------------------------------------------------------------------------------------------- prep
_W = {}


def _prep_init(a):
    import sherpa_onnx
    from mix_phonemize import MixedPhonemizer
    from en_phonemize import load_cmudict
    from kana_text import KanaText
    d = a.asr_dir
    _W["a"] = a
    _W["rec"] = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=f"{d}/encoder-epoch-99-avg-1.onnx", decoder=f"{d}/decoder-epoch-99-avg-1.onnx",
        joiner=f"{d}/joiner-epoch-99-avg-1.onnx", tokens=f"{d}/tokens.txt",
        num_threads=1, sample_rate=16000, feature_dim=80, decoding_method="greedy_search")
    _W["mp"] = MixedPhonemizer()
    _W["kt"] = KanaText(_W["mp"].en.cmu)


def brighten(x, sr, st=1.0, fr=1.04):
    """check_distill.brighten: the same small pitch and formant raise as all her data (adult range only)."""
    import numpy as np
    import pyworld as pw
    st = max(-3.0, min(2.0, st)); fr = max(0.95, min(1.08, fr))
    x = x.astype(np.float64)
    f0, t = pw.harvest(x, sr, f0_floor=70, f0_ceil=700)
    sp = pw.cheaptrick(x, f0, t, sr); ap_ = pw.d4c(x, f0, t, sr)
    f0 = f0 * (2 ** (st / 12))
    bins = sp.shape[1]; idx = np.arange(bins) / fr
    lo = np.floor(idx).astype(int).clip(0, bins - 1); hi = (lo + 1).clip(0, bins - 1); w = idx - np.floor(idx)
    sp2 = sp[:, lo] * (1 - w) + sp[:, hi] * w
    y = pw.synthesize(np.ascontiguousarray(f0), np.ascontiguousarray(sp2), np.ascontiguousarray(ap_), sr)
    return y / max(1e-9, np.abs(y).max()) * min(0.95, np.abs(x).max() + 1e-9)


def pitch(x, sr):
    import numpy as np
    import pyworld as pw
    f0, _ = pw.harvest(x.astype(np.float64), sr, f0_floor=70, f0_ceil=800)
    v = f0[f0 > 0]
    if len(v) == 0:
        return 0.0, 0.0, 0
    return float(np.median(v)), float(np.percentile(v, 90)), int(len(v))


def kana_norm(s):
    import pyopenjtalk
    s = unicodedata.normalize("NFKC", s)
    try:
        k = pyopenjtalk.g2p(s, kana=True)
    except Exception:
        k = s
    return re.sub(r"[\s、。？！?!〜ー…・,.’'\"]", "", k)


def expected_kana(text):
    """What a Japanese recogniser should hear: Japanese as Open JTalk reads it, English words as the
    phone's katakana route (KanaText) spells them."""
    mp, kt = _W["mp"], _W["kt"]
    parts = []
    for plan in mp.plan(text):
        if plan.verbatim:
            parts.append(plan.text)
            continue
        for k, seg in enumerate(plan.segments):
            if seg.route == "ja":
                parts.append(mp._ja_text(plan, seg, k == len(plan.segments) - 1))
            else:
                for t in seg.toks:
                    if t.kind == "word":
                        parts.append(kt.word(t.word if t.reading.source != "time" else t.text))
                    elif t.kind == "num":
                        parts += [kt.word(w) for w in mp.en.spell_number(t.text)]
    return kana_norm("".join(parts))


def _prep_one(item):
    import numpy as np
    import soundfile as sf
    n, text, kind, take = item
    a = _W["a"]
    src = os.path.join(a.raw, take, f"{n:04d}.wav")
    if not os.path.exists(src):
        return None
    x, sr = sf.read(src, dtype="float32")
    if x.ndim > 1:
        x = x.mean(axis=1)
    dur = len(x) / sr
    phones = _W["mp"].phonemize(text) or []
    n_ph = sum(len(s) for s in phones)
    _, _, en_led = line_parts(_W["mp"], text)
    kana_err, hyp = "", ""
    if not en_led:
        rec = _W["rec"]
        pad = np.zeros(int(0.3 * sr), dtype=np.float32)
        s = rec.create_stream(); s.accept_waveform(sr, np.concatenate([pad, x, pad])); rec.decode_stream(s)
        hyp = s.result.text
        kana_err = f"{cer(expected_kana(text), kana_norm(hyp) if hyp else ''):.3f}"
    out_dir = os.path.join(a.work, "bright", take)
    os.makedirs(out_dir, exist_ok=True)
    tmp = os.path.join(out_dir, f"_b_{n:04d}.wav")
    dst = os.path.join(out_dir, f"{n:04d}.wav")
    # A student take is her phone voice, already bright: only resampled.
    y0 = x if a.no_brighten else brighten(x, sr, a.semitones, a.formant).astype(np.float32)
    sf.write(tmp, y0, sr, subtype="PCM_16")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp, "-ac", "1", "-ar", "22050", "-sample_fmt", "s16", dst],
                   check=True)
    os.remove(tmp)
    y, ysr = sf.read(dst, dtype="float32")
    p50, p90, nv = pitch(y, ysr)
    return f"{n}\t{take}\t{dur:.2f}\t{n_ph}\t{p50:.1f}\t{p90:.1f}\t{nv}\t{kana_err}\t{hyp}"


def cmd_prep(a):
    from multiprocessing import Pool
    rows = read_lines(a.lines)
    items = [(r["n"], r["text"], r["kind"], take) for take in takes_in(a.raw) for r in rows]
    out = open(os.path.join(a.work, "prep.tsv"), "w", encoding="utf-8")
    out.write("n\ttake\tdur\tn_ph\tp50\tp90\tn_voiced\tkana_err\tkana_hyp\n")
    with Pool(a.jobs, initializer=_prep_init, initargs=(a,)) as pool:
        for k, res in enumerate(pool.imap_unordered(_prep_one, items, chunksize=4)):
            if res:
                out.write(res + "\n")
            if k % 500 == 0:
                print(f"prep {k}/{len(items)}", flush=True)
    out.close()


# ---------------------------------------------------------------------------------------------- sim
def cmd_sim(a):
    import numpy as np
    import soundfile as sf
    import torch
    import librosa
    from transformers import AutoFeatureExtractor, WavLMForXVector
    fe = AutoFeatureExtractor.from_pretrained(a.model)
    model = WavLMForXVector.from_pretrained(a.model).to(a.device).eval()

    def embed(x, sr):
        if sr != 16000:
            x = librosa.resample(x, orig_sr=sr, target_sr=16000)
        # The x-vector's convolutions need about 0.1 s; a very short take (a word cut tight) is padded
        # with silence to 0.5 s instead of stopping the whole check.
        if len(x) < 8000:
            x = np.pad(x, (0, 8000 - len(x)))
        inp = fe(x, sampling_rate=16000, return_tensors="pt", padding=True)
        with torch.no_grad():
            e = model(**{k: v.to(a.device) for k, v in inp.items()}).embeddings
        e = torch.nn.functional.normalize(e, dim=-1)
        return e[0].cpu().numpy()

    refs = [l.rstrip("\n").split("\t")[0] for l in open(a.refs, encoding="utf-8") if l.strip()]
    ref_e = []
    for p in refs:
        x, sr = sf.read(p, dtype="float32")
        if x.ndim > 1:
            x = x.mean(axis=1)
        # The takes were brightened like her data unless --no-brighten: compare like with like.
        ref_e.append(embed(x if a.no_brighten else brighten(x, sr).astype(np.float32), sr))
    centre = np.mean(ref_e, axis=0); centre /= np.linalg.norm(centre)
    out = open(os.path.join(a.work, "sim.tsv"), "w", encoding="utf-8")
    out.write("n\ttake\tsim\n")
    for take in sorted(os.listdir(os.path.join(a.work, "bright"))):
        for p in sorted(glob.glob(os.path.join(a.work, "bright", take, "[0-9]*.wav"))):
            x, sr = sf.read(p, dtype="float32")
            out.write(f"{int(os.path.basename(p)[:4])}\t{take}\t{float(np.dot(embed(x, sr), centre)):.4f}\n")
    out.close()
    ja = sorted(glob.glob(os.path.join(a.ja_wavs, "*.wav")))
    random.Random(5).shuffle(ja)
    sims = []
    for p in ja[:200]:
        x, sr = sf.read(p, dtype="float32")
        sims.append(float(np.dot(embed(x, sr), centre)))
    json.dump({"ja_sim_median": float(np.median(sims)) if sims else None, "ja_n": len(sims)},
              open(os.path.join(a.work, "sim_ja.json"), "w"))
    print("sim done; Japanese median", np.median(sims) if sims else None)


# --------------------------------------------------------------------------------------------- pick
def _tsv(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE))


def cmd_pick(a):
    import numpy as np
    import shutil
    import soundfile as sf
    from mix_phonemize import MixedPhonemizer
    mp = MixedPhonemizer()
    rows = {r["n"]: r for r in read_lines(a.lines)}
    asr, prep, sim = {}, {}, {}
    for p in glob.glob(os.path.join(a.work, "asr_*.tsv")):
        for r in _tsv(p):
            asr[(int(r["n"]), r["take"])] = r
    for r in _tsv(os.path.join(a.work, "prep.tsv")):
        prep[(int(r["n"]), r["take"])] = r
    for r in _tsv(os.path.join(a.work, "sim.tsv")):
        sim[(int(r["n"]), r["take"])] = float(r["sim"])
    sim_ja = None
    if os.path.exists(os.path.join(a.work, "sim_ja.json")):
        sim_ja = json.load(open(os.path.join(a.work, "sim_ja.json")))["ja_sim_median"]
    takes = sorted({t for (_, t) in prep})
    os.makedirs(os.path.join(a.out, "wavs"), exist_ok=True)
    report = open(os.path.join(a.out, "report_lang.tsv"), "w", encoding="utf-8")
    report.write("n\tkind\tsplit\ttake\tkeep\twhy\terr\tp50\tp90\tsim\tdur\ttext\n")
    chosen = {}
    for n, r in sorted(rows.items()):
        en_words, _, en_led = line_parts(mp, r["text"])
        best, best_key = None, None
        for take in takes:
            pr = prep.get((n, take))
            if pr is None:
                continue
            why = []
            dur, n_ph = float(pr["dur"]), max(1, int(pr["n_ph"]))
            if not 0.4 <= dur <= 15 or not 0.03 <= dur / n_ph <= 0.25:
                why.append("length")
            if en_led:
                ar = asr.get((n, take))
                err = float(ar["err"]) if ar else 1.0
                n_ref = int(ar["n_ref"]) if ar else len(en_words)
                if (n_ref >= 4 and err > MAX_WER) or (n_ref < 4 and err > 0):
                    why.append("asr")
            else:
                err = float(pr["kana_err"] or 1.0)
                if err > MAX_KANA:
                    why.append("kana")
            p50, p90 = float(pr["p50"]), float(pr["p90"])
            if p90 > MAX_P90 or p50 <= 0:
                why.append("pitch")
            s = sim.get((n, take))
            if a.min_sim is not None and s is not None and s < a.min_sim:
                why.append("timbre")
            report.write(f"{n}\t{r['kind']}\t{r['split']}\t{take}\t{0 if why else 1}\t{','.join(why)}\t{err:.3f}\t"
                         f"{p50:.0f}\t{p90:.0f}\t{'' if s is None else f'{s:.3f}'}\t{dur:.2f}\t{r['text']}\n")
            if why:
                continue
            k = (err, p90 / 1000.0, -(s or 0.0))
            if best_key is None or k < best_key:
                best, best_key = (take, err, p50, p90, s), k
        if best:
            chosen[n] = best
    report.close()

    # Her English must not drift up from her Japanese: an excited, higher English sounds younger.
    ja_p50 = None
    if a.ja_wavs:
        ja = sorted(glob.glob(os.path.join(a.ja_wavs, "*.wav")))
        random.Random(5).shuffle(ja)
        vals = []
        for p in ja[:200]:
            x, sr = sf.read(p, dtype="float32")
            vals.append(pitch(x, sr)[0])
        ja_p50 = float(np.median([v for v in vals if v > 0])) if vals else None
    dropped_high = 0
    en_ns = [n for n in chosen if rows[n]["kind"] == "en"]
    if ja_p50:
        cap = ja_p50 * 2 ** (MAX_EN_OVER_JA_ST / 12)
        en_ns.sort(key=lambda n: chosen[n][2])
        while en_ns and float(np.median([chosen[n][2] for n in en_ns])) > cap:
            gone = en_ns.pop()
            del chosen[gone]
            dropped_high += 1

    meta, val = [], []
    for n, (take, err, p50, p90, s) in sorted(chosen.items()):
        name = f"lang_{n:04d}.wav"
        shutil.copy(os.path.join(a.work, "bright", take, f"{n:04d}.wav"), os.path.join(a.out, "wavs", name))
        meta.append(f"{name}|{rows[n]['text']}")
        if rows[n]["split"] == "holdout":
            val.append(name)
    open(os.path.join(a.out, "metadata.csv"), "w", encoding="utf-8").write("\n".join(meta) + "\n")
    open(os.path.join(a.out, "val_ids.txt"), "w", encoding="utf-8").write("\n".join(val) + "\n")

    def stats(kind, split=None):
        ns = [n for n in chosen if rows[n]["kind"] == kind and (split is None or rows[n]["split"] == split)]
        errs = [chosen[n][1] for n in ns]
        p50s = [chosen[n][2] for n in ns]
        sims = [chosen[n][4] for n in ns if chosen[n][4] is not None]
        return dict(lines=len(ns), err_median=float(np.median(errs)) if errs else None,
                    err_mean=float(np.mean(errs)) if errs else None,
                    p50_median=float(np.median(p50s)) if p50s else None,
                    sim_median=float(np.median(sims)) if sims else None)

    all_p50 = [chosen[n][2] for n in chosen]
    summary = {
        "lines_in": len(rows), "kept": len(chosen), "dropped_for_pitch_drift": dropped_high,
        "en": stats("en"), "mixed": stats("mixed"), "en_holdout": stats("en", "holdout"),
        "mixed_holdout": stats("mixed", "holdout"),
        "corpus_p50_median": float(np.median(all_p50)) if all_p50 else None,
        "ja_p50_median": ja_p50, "ja_sim_median": sim_ja,
    }
    checks = {
        "median pitch <= %d Hz" % MAX_MEDIAN: summary["corpus_p50_median"] is not None and summary["corpus_p50_median"] <= MAX_MEDIAN,
        "English within %.1f semitones of Japanese" % MAX_EN_OVER_JA_ST: (ja_p50 is None) or (
            summary["en"]["p50_median"] is not None and 12 * math.log2(summary["en"]["p50_median"] / ja_p50) <= MAX_EN_OVER_JA_ST),
        "English timbre >= Japanese - 0.05": (sim_ja is None) or (summary["en"]["sim_median"] is not None and summary["en"]["sim_median"] >= sim_ja - 0.05),
    }
    summary["checks"] = checks
    json.dump(summary, open(os.path.join(a.out, "teacher_stats.json"), "w"), indent=1)
    with open(os.path.join(a.out, "summary.txt"), "w", encoding="utf-8") as f:
        f.write(json.dumps(summary, indent=1) + "\n")
    print(json.dumps(summary, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["asr", "prep", "sim", "pick"])
    ap.add_argument("--lines")
    ap.add_argument("--raw")
    ap.add_argument("--work", required=True)
    ap.add_argument("--out")
    ap.add_argument("--shard", default="0/1")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--model")
    ap.add_argument("--refs")
    ap.add_argument("--ja-wavs")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 4) - 4))
    ap.add_argument("--asr-dir", default="/w/sherpa-onnx-zipformer-ja-reazonspeech-2024-08-01")
    ap.add_argument("--semitones", type=float, default=1.0)
    ap.add_argument("--formant", type=float, default=1.04)
    ap.add_argument("--min-sim", type=float, default=None, help="drop takes below this timbre cosine")
    ap.add_argument("--no-brighten", action="store_true", help="prep: the takes are her phone voice, already brightened")
    a = ap.parse_args()
    os.makedirs(a.work, exist_ok=True)
    {"asr": cmd_asr, "prep": cmd_prep, "sim": cmd_sim, "pick": cmd_pick}[a.cmd](a)


if __name__ == "__main__":
    main()
