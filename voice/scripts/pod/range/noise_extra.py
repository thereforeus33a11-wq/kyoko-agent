"""Extra numbers for short vocal noises, beside noise_measure.py (round 3 of the sound bank).

noise_measure.py tracks pitch with Praat only and looks at a noise as one piece. This adds, per file:
  pitch by a second tracker (librosa pyin) over the same body frames (within 30 dB of the loud level):
    py_med, py_p90, py_voiced      median / 90th percentile Hz and voiced share by pyin
    pr_med, pr_p90, pr_max          the same by Praat (cross-correlation, 75-900 Hz) for the record, and its
                                    highest 50 ms-smoothed point (a squeal shows here first)
  voice quality over the voiced frames (Praat): jitter_loc (%), shimmer_loc (%), and the spectral flatness of
    the body (median of the frames' flatness, 0 = tonal, 1 = white noise): a take made by signal processing is
    compared with her own takes of the same kind on these
  the course of the noise: the active span (-45 dB) cut in thirds; per third the voiced share (Praat), the
    median HNR, the energy above 4 kHz against 80-4000 Hz (hf) and the flatness: v1 v2 v3, hnr1 hnr2 hnr3,
    hf1 hf2 hf3, fl1 fl2 fl3 (a laugh that breaks into a wheeze: voicing and HNR fall, breath noise rises)
  clearly voiced frames (the adult cap's frames): body frames a tracker calls voiced AND whose HNR (Praat cc) is
    6 dB or more; a whisper's or a burst's noise is often "voiced" to Praat at 400-800 Hz with HNR under 5 dB:
    pr_cv_s, pr_cv_med, pr_cv_p90, pr_cv_max (Praat; max = the highest 5-frame median), py_cv_s, py_cv_med, py_cv_p90 (pyin), hr_share (share of the body
    frames in runs of 50 ms or more at HNR >= 10 dB: her whisper set's tonal-stretch measure)
  pulses: the active pulses (segments over the loud level - 20 dB, split by a dip of 8 dB lasting 30 ms):
    n_pulse, and for each the start, end, voiced share and median Praat f0 (pulses as JSON)
  effort: tilt_db (80-1000 against 1000-4000 Hz over the body) and hf_db again on the body
  edges of the take itself: the kana recogniser on its first and last 150 ms of sound (head_kana, tail_kana)
  edges against its source (when a cut table is given): the raw take's level in the 30 ms before the cut and
    after it (raw_pre_db, raw_post_db: against the noise's loud level in the raw), the gap from the cut's end
    to the next sound in the raw at the loud level - 25 dB (next_gap_s; none = nothing follows), the same
    backwards from the cut's start (prev_gap_s), and what the kana recogniser hears in the 0.6 s of the raw
    after the cut (kana_after)

Usage (gsv env): python noise_extra.py <out.tsv> [--cuts cuts.tsv[,cuts2.tsv]] <wav or dir> ...
  With --cuts, a file whose basename is in a cut table is checked against its source (the table's src, from,
  to columns: the raw take and the cut in seconds).
"""
import csv, glob, json, os, sys
import numpy as np, soundfile as sf, parselmouth, librosa
from parselmouth.praat import call
import sherpa_onnx

args = sys.argv[1:]
out = args.pop(0)
cutp = []
if args and args[0] == "--cuts":
    args.pop(0); cutp = args.pop(0).split(",")
files = []
for p in args:
    files += sorted(glob.glob(os.path.join(p, "*.wav"))) if os.path.isdir(p) else [p]
cuts = {}
for p in cutp:
    for r in csv.DictReader(open(p, encoding="utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE):
        cuts[os.path.basename(r["file"])] = r
M = sorted(glob.glob("/w/sherpa-onnx-*ja*"))[0]  # the ReazonSpeech kana recogniser
rec = sherpa_onnx.OfflineRecognizer.from_transducer(
    encoder=glob.glob(f"{M}/encoder-*.int8.onnx")[0], decoder=glob.glob(f"{M}/decoder-*.int8.onnx")[0],
    joiner=glob.glob(f"{M}/joiner-*.int8.onnx")[0], tokens=f"{M}/tokens.txt", num_threads=2)


def load(p):
    x, sr = sf.read(p, dtype="float32", always_2d=True)
    return x.mean(axis=1), sr


def kana(x, sr):
    if len(x) < int(0.03 * sr): return ""
    pad = np.zeros(int(0.3 * sr), np.float32)
    s = rec.create_stream(); s.accept_waveform(sr, np.concatenate([pad, x.astype(np.float32), pad])); rec.decode_stream(s)
    return s.result.text.strip()


def lv10(x, sr):
    fr = int(0.01 * sr); n = max(1, len(x) // fr)
    return 20 * np.log10(np.sqrt(np.mean(x[:n * fr].reshape(n, fr).astype(np.float64) ** 2, axis=1)) + 1e-9)


def band(x, sr, frames, lo1, hi1, lo2, hi2):
    fr = int(0.01 * sr)
    frames = [i for i in frames if (i + 1) * fr <= len(x)]
    if len(frames) < 3: return None
    seg = np.concatenate([x[i * fr:(i + 1) * fr] for i in frames]).astype(np.float32)
    if len(seg) < 1024: seg = np.concatenate([seg, np.zeros(1024 - len(seg), np.float32)])
    S = np.abs(librosa.stft(seg, n_fft=1024, hop_length=256)) ** 2
    fq = librosa.fft_frequencies(sr=sr, n_fft=1024)
    a = S[(fq >= lo1) & (fq < hi1)].sum(); b = S[(fq >= lo2) & (fq < hi2)].sum()
    return float(10 * np.log10((a + 1e-12) / (b + 1e-12)))


def flat_frames(x, sr):
    """Spectral flatness per 10 ms frame (80 Hz-8 kHz, 1024-point frames centred on each 10 ms frame)."""
    hop = int(0.01 * sr)
    F = librosa.feature.spectral_flatness(y=x.astype(np.float32), n_fft=1024, hop_length=hop, center=True)[0]
    return F


def segments(lv, top):
    s = np.convolve(lv, np.ones(3) / 3, mode="same")
    on = s >= top - 20
    segs, i = [], 0
    while i < len(s):
        if on[i]:
            j = i
            while j < len(s) and on[j]: j += 1
            segs.append([i, j]); i = j
        else:
            i += 1
    merged = []
    for a, b in segs:
        if merged:
            pa, pb = merged[-1]
            gap = s[pb:a]
            dip = (min(s[pa:pb].max(), s[a:b].max()) - gap.min()) if len(gap) else 0
            if (a - pb) < 3 or dip < 8:
                merged[-1] = [pa, b]; continue
        merged.append([a, b])
    return merged


cols = ["py_med", "py_p90", "py_voiced", "pr_med", "pr_p90", "pr_max", "pr_cv_s", "pr_cv_med", "pr_cv_p90", "pr_cv_max",
        "py_cv_s", "py_cv_med", "py_cv_p90", "hr_share", "jitter_loc", "shimmer_loc", "flat",
        "v1", "v2", "v3", "hnr1", "hnr2", "hnr3", "hf1", "hf2", "hf3", "fl1", "fl2", "fl3", "n_pulse", "pulses",
        "tilt_db", "hf_body", "head_kana", "tail_kana", "raw_pre_db", "raw_post_db", "next_gap_s", "prev_gap_s",
        "kana_after"]
o = open(out, "w", encoding="utf-8"); o.write("file\t" + "\t".join(cols) + "\n")
for f in files:
    x, sr = load(f)
    if len(x) < int(0.05 * sr): continue
    lv = lv10(x, sr); top = float(np.percentile(lv, 98))
    act = np.where(lv >= top - 45)[0]
    a0, a1 = (int(act[0]), int(act[-1]) + 1) if len(act) else (0, len(lv))
    a30 = lv >= top - 30
    snd = parselmouth.Sound(x.astype(np.float64), sampling_frequency=sr)
    pt = snd.to_pitch_ac(time_step=0.01, pitch_floor=75, pitch_ceiling=900)
    f0 = pt.selected_array["frequency"]; ft = pt.xs()
    idx = np.clip((ft * 100).astype(int), 0, len(lv) - 1)
    vm = (f0 > 0) & a30[idx]
    vf = f0[vm]
    d = {}
    try:
        hv = snd.to_harmonicity_cc(time_step=0.01, minimum_pitch=75.0, silence_threshold=0.1, periods_per_window=1.0)
        H = hv.values[0]; ht = hv.xs()
        hidx = np.clip((ht * 100).astype(int), 0, len(lv) - 1)
    except Exception:
        H = np.array([]); hidx = np.array([], int)
    hfr = np.full(len(lv), -200.0)
    for j in range(len(H)): hfr[hidx[j]] = max(hfr[hidx[j]], H[j])
    cvp = vm & (hfr[idx] >= 6)
    d["pr_cv_s"] = float(cvp.sum() * 0.01)
    if cvp.sum() >= 6:
        cf = f0[cvp]
        d["pr_cv_med"], d["pr_cv_p90"] = float(np.median(cf)), float(np.percentile(cf, 90))
        d["pr_cv_max"] = float(max(np.median(cf[max(0, i - 2):i + 3]) for i in range(len(cf))))
    hr = hfr >= 10; run = np.zeros(len(lv), bool); i = 0
    while i < len(lv):
        if hr[i]:
            j = i
            while j < len(lv) and hr[j]: j += 1
            if j - i >= 5: run[i:j] = True
            i = j
        else:
            i += 1
    d["hr_share"] = float((run & a30).sum() / max(1, a30.sum()))
    if len(vf) >= 6:
        d["pr_med"], d["pr_p90"] = float(np.median(vf)), float(np.percentile(vf, 90))
        sm = np.array([np.median(vf[max(0, i - 2):i + 3]) for i in range(len(vf))])
        d["pr_max"] = float(sm.max())
    try:
        hop = int(0.01 * sr)
        py, pvf, _ = librosa.pyin(x, fmin=65, fmax=900, sr=sr, frame_length=2048, hop_length=hop)
        pi = np.clip(np.arange(len(py)), 0, len(lv) - 1)
        pm = pvf & a30[pi] & np.isfinite(py)
        d["py_voiced"] = float(pm.sum() / max(1, a30.sum()))
        cvy = pm & (hfr[pi] >= 6)
        d["py_cv_s"] = float(cvy.sum() * 0.01)
        if cvy.sum() >= 6: d["py_cv_med"], d["py_cv_p90"] = float(np.median(py[cvy])), float(np.percentile(py[cvy], 90))
        if pm.sum() >= 6:
            d["py_med"], d["py_p90"] = float(np.median(py[pm])), float(np.percentile(py[pm], 90))
    except Exception:
        pass
    try:
        pp = call(snd, "To PointProcess (periodic, cc)", 75, 600)
        d["jitter_loc"] = 100 * call(pp, "Get jitter (local)", 0, 0, 0.0001, 0.02, 1.3)
        d["shimmer_loc"] = 100 * call([snd, pp], "Get shimmer (local)", 0, 0, 0.0001, 0.02, 1.3, 1.6)
        for k in ("jitter_loc", "shimmer_loc"):
            if not np.isfinite(d[k]): d.pop(k)
    except Exception:
        pass
    F = flat_frames(x, sr)
    body = [i for i in range(len(lv)) if a30[i] and i < len(F)]
    if body: d["flat"] = float(np.median(F[body]))
    vset = set(np.unique(idx[vm]).tolist())
    th = [a0 + (a1 - a0) * k // 3 for k in range(4)]
    for k in range(3):
        fr = [i for i in range(th[k], th[k + 1]) if a30[i]]
        if not fr: continue
        d[f"v{k + 1}"] = sum(i in vset for i in fr) / len(fr)
        hs = [H[j] for j in range(len(H)) if th[k] <= hidx[j] < th[k + 1] and a30[hidx[j]] and H[j] > -200]
        if hs: d[f"hnr{k + 1}"] = float(np.median(hs))
        d[f"hf{k + 1}"] = band(x, sr, fr, 4000, sr / 2, 80, 4000)
        ff = [F[i] for i in fr if i < len(F)]
        if ff: d[f"fl{k + 1}"] = float(np.median(ff))
    sg = segments(lv, top)
    pul = []
    for a, b in sg:
        fr = [i for i in range(a, b)]
        pv = [f0[j] for j in range(len(f0)) if a <= idx[j] < b and vm[j]]
        pul.append(dict(t0=a / 100, t1=b / 100, voiced=round(sum(i in vset for i in fr) / max(1, len(fr)), 2),
                        f0=round(float(np.median(pv)), 1) if len(pv) >= 3 else None))
    d["n_pulse"] = len(sg); d["pulses"] = json.dumps(pul)
    bf = np.where(a30)[0].tolist()
    d["tilt_db"] = band(x, sr, bf, 80, 1000, 1000, 4000); d["hf_body"] = band(x, sr, bf, 4000, sr / 2, 80, 4000)
    on, off = a0 / 100, a1 / 100
    d["head_kana"] = kana(x[:min(len(x), int((on + 0.15) * sr))], sr)
    d["tail_kana"] = kana(x[max(0, int((off - 0.15) * sr)):], sr)
    c = cuts.get(os.path.basename(f))
    if c and c.get("from") not in (None, "") and os.path.exists(c["src"]):
        y, sr2 = load(c["src"])
        if sr2 != sr: y = librosa.resample(y, orig_sr=sr2, target_sr=sr)
        ly = lv10(y, sr)
        t0, t1 = int(float(c["from"]) * 100), int(float(c["to"]) * 100)
        seg = ly[t0:t1]
        rtop = float(np.percentile(seg, 98)) if len(seg) else top
        pre = ly[max(0, t0 - 3):t0]; post = ly[t1:t1 + 3]
        d["raw_pre_db"] = float(pre.max() - rtop) if len(pre) else None
        d["raw_post_db"] = float(post.max() - rtop) if len(post) else None
        # where the noise itself ends inside the cut (-45 dB of its loud level) and what follows it in the raw
        sact = np.where(seg >= rtop - 45)[0]
        n_end = t0 + (int(sact[-1]) + 1 if len(sact) else len(seg)); n_on = t0 + (int(sact[0]) if len(sact) else 0)
        nxt = np.where(ly[n_end:] >= rtop - 25)[0]
        d["next_gap_s"] = float(nxt[0]) / 100 if len(nxt) else None
        prv = np.where(ly[:n_on] >= rtop - 25)[0]
        d["prev_gap_s"] = float(n_on - (prv[-1] + 1)) / 100 if len(prv) else None
        d["kana_after"] = kana(y[int(t1 / 100 * sr):int((t1 / 100 + 0.6) * sr)], sr)
    fmt = lambda v: "" if v is None else (f"{v:.4f}" if isinstance(v, float) else str(v))
    o.write(f + "\t" + "\t".join(fmt(d.get(k)) for k in cols) + "\n"); o.flush()
o.close()
print("extra", len(files), "->", out)
