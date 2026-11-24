"""Measure the shape of short vocal noises (hums, yeahs, "oh really", "huh?", snorts, nose laughs, cackles, sighs,
clicks): round 1's sound-bank numbers plus what tells one noise from another.

Round 1's numbers (as the sound bank's snd_measure.py): length, loudness, peak and clipping, onset and offset,
voicing (share of the body frames, those within 30 dB of the take's loud level, that Praat finds clearly voiced),
median and 90th-percentile pitch of those frames only, HNR, centroid, hf_db (energy above 4 kHz against 80-4000 Hz
over the body), pulses (bursts), timbre (WavLM x-vector cosine to the centroid of the reference clips) and what the
ReazonSpeech kana recogniser hears.

Added here:
  pitch contour over the voiced body frames, in semitones (re 100 Hz), 50 ms median-smoothed:
    st_start, st_end   median of the first / last fifth of the voiced frames (at least 3 frames)
    st_peak, peak_pos  the highest smoothed point and where it lies in the voiced part (0 = start, 1 = end)
    rise_st            st_peak - st_start;  fall_st = st_peak - st_end;  net_st = st_end - st_start
    slope_st_s         least-squares slope of the contour (semitones per second)
    f0_start, f0_end   the same start and end in Hz
  mouth (voiced body frames only):
    f1_med, f2_med     median first and second formant (Praat Burg, 5 formants up to 5500 Hz)
    f1_p75, f1_p90     upper F1 levels (on a speaker's own speech these are her open vowels a and e)
    low_db             energy 80-600 Hz against 600-4000 Hz: high for a closed-mouth hum (all in the nasal murmur
                       and the low first formant), low for an open a or e
    hf_v               energy above 4 kHz against 80-4000 Hz
  burst:
    attack_ms          from the first frame within 30 dB of the loud level to the first within 3 dB of it
    core_s             frames within 10 dB of the loud level (the noise's core), in seconds
  laugh tail (the active span split at 70 %):
    head_voiced, tail_voiced   voiced share of the body frames before / after the split
    head_hf, tail_hf           hf_db before / after the split (a wheeze is breath noise: brighter, unvoiced)
  lufs_rms             RMS level - 0.7 dB where the take is too short for a BS.1770 block (under 0.4 s)

Usage (gsv env): [EMB_DEV=cuda] [REFS="a.wav b.wav ..."] python noise_measure.py <out.tsv> <wav or dir> ...
REFS: the clips whose WavLM centroid sim_her is measured against (default: her 4 clean reference clips).
"""
import glob, os, sys
import numpy as np, soundfile as sf, parselmouth, librosa
sys.path.insert(0, "/w/range/scripts")
from measure import k_loudness, Embedder
import sherpa_onnx

RF = "/w/yume/range_proto/refs"
REFS = os.environ.get("REFS", " ".join(f"{RF}/{n}_clean.wav" for n in ("v12_040", "v12_065", "v12_071", "yume_07"))).split()
M = sorted(glob.glob("/w/sherpa-onnx-*ja*"))[0]  # the ReazonSpeech kana recogniser
out = sys.argv[1]
files = []
for p in sys.argv[2:]:
    files += sorted(glob.glob(os.path.join(p, "*.wav"))) if os.path.isdir(p) else [p]
rec = sherpa_onnx.OfflineRecognizer.from_transducer(
    encoder=glob.glob(f"{M}/encoder-*.int8.onnx")[0], decoder=glob.glob(f"{M}/decoder-*.int8.onnx")[0],
    joiner=glob.glob(f"{M}/joiner-*.int8.onnx")[0], tokens=f"{M}/tokens.txt", num_threads=4)
emb = Embedder(os.environ.get("EMB_DEV", "cpu"))


def load(p):
    x, sr = sf.read(p, dtype="float32")
    return (x.mean(axis=1) if x.ndim > 1 else x), sr


c = np.mean([emb(*load(f)) for f in REFS], axis=0)
c /= np.linalg.norm(c)


def pad05(x, sr):  # WavLM needs a few frames: a take under 0.5 s is padded with silence for its timbre only
    return x if len(x) >= int(0.5 * sr) else np.concatenate([x, np.zeros(int(0.5 * sr) - len(x), np.float32)])


def lv10(x, sr):
    fr = int(0.01 * sr); n = max(1, len(x) // fr)
    return 20 * np.log10(np.sqrt(np.mean(x[:n * fr].reshape(n, fr).astype(np.float64) ** 2, axis=1)) + 1e-9)


def bursts(lv, top):
    """Round 1's pulse count: peaks within 25 dB of the loud level, 6 dB above the dip since the last kept pulse and
    70 ms after it."""
    s = np.convolve(lv, np.ones(3) / 3, mode="same")
    pk = [i for i in range(1, len(s) - 1) if s[i] >= s[i - 1] and s[i] > s[i + 1] and s[i] >= top - 25]
    kept = []
    for i in pk:
        if not kept:
            kept.append(i); continue
        j = kept[-1]
        if i - j < 7:
            if s[i] > s[j]: kept[-1] = i
            continue
        if min(s[j], s[i]) - s[j:i + 1].min() >= 6:
            kept.append(i)
        elif s[i] > s[j]:
            kept[-1] = i
    return len(kept)


def band_db(x, sr, frames, lo1, hi1, lo2, hi2):
    """Energy in [lo1, hi1) against [lo2, hi2) Hz over the given 10 ms frames (dB), or None."""
    fr = int(0.01 * sr)
    if not len(frames): return None
    seg = np.concatenate([x[i * fr:(i + 1) * fr] for i in frames]).astype(np.float32)
    if len(seg) < 1024: seg = np.concatenate([seg, np.zeros(1024 - len(seg), np.float32)])
    S = np.abs(librosa.stft(seg, n_fft=1024, hop_length=256)) ** 2
    fq = librosa.fft_frequencies(sr=sr, n_fft=1024)
    a = S[(fq >= lo1) & (fq < hi1)].sum(); b = S[(fq >= lo2) & (fq < hi2)].sum()
    return float(10 * np.log10((a + 1e-12) / (b + 1e-12)))


def contour(ft, f0):
    """Shape of the pitch contour over the voiced frames given (times, Hz)."""
    if len(f0) < 6: return {}
    st = 12 * np.log2(f0 / 100.0)
    k = 5 if len(st) >= 10 else 3
    sm = np.array([np.median(st[max(0, i - k // 2):i + k // 2 + 1]) for i in range(len(st))])
    q = max(3, len(st) // 5)
    s0, s1 = float(np.median(st[:q])), float(np.median(st[-q:]))
    ip = int(np.argmax(sm)); pk = float(sm[ip])
    slope = float(np.polyfit(ft, st, 1)[0]) if np.ptp(ft) > 0 else 0.0
    hz = lambda s: 100.0 * 2 ** (s / 12)
    return dict(st_start=s0, st_end=s1, st_peak=pk, peak_pos=ip / max(1, len(st) - 1), rise_st=pk - s0, fall_st=pk - s1,
                net_st=s1 - s0, slope_st_s=slope, f0_start=hz(s0), f0_end=hz(s1))


cols = ["dur", "lufs", "lufs_rms", "peak_db", "n_clip", "onset", "offset", "active_s", "voiced_s", "voiced", "f0_med",
        "f0_p90", "hnr", "centroid", "hf_db", "bursts", "sim_her", "st_start", "st_end", "st_peak", "peak_pos", "rise_st",
        "fall_st", "net_st", "slope_st_s", "f0_start", "f0_end", "f1_med", "f2_med", "f1_p75", "f1_p90", "low_db", "hf_v",
        "attack_ms", "core_s", "head_voiced", "tail_voiced", "head_hf", "tail_hf", "kana"]
o = open(out, "w", encoding="utf-8"); o.write("file\t" + "\t".join(cols) + "\n")
for f in files:
    x, sr = load(f)
    if len(x) < int(0.05 * sr):
        continue
    lv = lv10(x, sr); top = np.percentile(lv, 98)
    act = np.where(lv >= top - 45)[0]
    on, off = (act[0] / 100, (act[-1] + 1) / 100) if len(act) else (0.0, len(x) / sr)
    a30 = lv >= top - 30
    snd = parselmouth.Sound(x.astype(np.float64), sampling_frequency=sr)
    pt = snd.to_pitch_ac(time_step=0.01, pitch_floor=75, pitch_ceiling=900)
    f0 = pt.selected_array["frequency"]; ft = pt.xs()
    idx = np.clip((ft * 100).astype(int), 0, len(lv) - 1)
    vmask = (f0 > 0) & a30[idx]
    vf, vt = f0[vmask], ft[vmask]
    voiced_s = len(vf) * 0.01
    body = max(1, int(a30.sum()))
    try:
        hv = snd.to_harmonicity_cc(time_step=0.01, minimum_pitch=75.0, silence_threshold=0.1, periods_per_window=1.0).values[0]
        hv = hv[hv > -200]; hnr = float(np.median(hv)) if len(hv) else float("nan")
    except Exception:
        hnr = float("nan")
    bodyf = np.where(a30)[0]
    hf = band_db(x, sr, bodyf, 4000, sr / 2, 80, 4000)
    fr = int(0.01 * sr)
    ab = np.concatenate([x[i * fr:(i + 1) * fr] for i in bodyf]) if len(bodyf) else x
    cen = float(np.mean(librosa.feature.spectral_centroid(y=ab.astype(np.float32), sr=sr, n_fft=1024, hop_length=256)))
    vfr = np.unique(idx[vmask])  # the voiced body frames (10 ms)
    low_db = band_db(x, sr, vfr, 80, 600, 600, 4000) if len(vfr) >= 3 else None
    hf_v = band_db(x, sr, vfr, 4000, sr / 2, 80, 4000) if len(vfr) >= 3 else None
    f1m = f2m = f1p75 = f1p90 = None
    if len(vt) >= 3:
        try:
            fm = snd.to_formant_burg(time_step=0.01, max_number_of_formants=5, maximum_formant=5500.0,
                                     window_length=0.025, pre_emphasis_from=50.0)
            F1 = np.array([fm.get_value_at_time(1, t) for t in vt]); F2 = np.array([fm.get_value_at_time(2, t) for t in vt])
            F1 = F1[np.isfinite(F1)]; F2 = F2[np.isfinite(F2)]
            if len(F1): f1m, f1p75, f1p90 = float(np.median(F1)), float(np.percentile(F1, 75)), float(np.percentile(F1, 90))
            if len(F2): f2m = float(np.median(F2))
        except Exception:
            pass
    sim = float("nan")
    try:
        e = emb(pad05(x, sr), sr); sim = float(np.dot(e, c))
    except Exception:
        pass
    i_on = int(np.argmax(lv >= top - 30)); i_pk = i_on + int(np.argmax(lv[i_on:] >= top - 3))
    a0, a1 = int(on * 100), int(off * 100)
    split = a0 + int(0.7 * (a1 - a0))
    vset = set(vfr.tolist())
    def share(lo, hi):
        fs = [i for i in range(lo, hi) if a30[i]] if hi > lo else []
        return (sum(i in vset for i in fs) / len(fs)) if fs else None
    head_v, tail_v = share(a0, split), share(split, min(a1, len(lv)))
    head_hf = band_db(x, sr, [i for i in range(a0, split) if a30[i]], 4000, sr / 2, 80, 4000)
    tail_hf = band_db(x, sr, [i for i in range(split, min(a1, len(lv))) if a30[i]], 4000, sr / 2, 80, 4000)
    pad = np.zeros(int(0.3 * sr), np.float32)
    st = rec.create_stream(); st.accept_waveform(sr, np.concatenate([pad, x, pad])); rec.decode_stream(st)
    lu = k_loudness(x.astype(np.float64), sr)
    m = dict(dur=len(x) / sr, lufs=lu, lufs_rms=20 * np.log10(np.sqrt(np.mean(x.astype(np.float64) ** 2)) + 1e-9) - 0.7,
             peak_db=20 * np.log10(np.max(np.abs(x)) + 1e-9), n_clip=int(np.sum(np.abs(x) >= 0.999)), onset=on, offset=off,
             active_s=off - on, voiced_s=voiced_s, voiced=len(vf) / body,
             f0_med=float(np.median(vf)) if voiced_s >= 0.06 else None,
             f0_p90=float(np.percentile(vf, 90)) if voiced_s >= 0.06 else None, hnr=hnr, centroid=cen, hf_db=hf,
             bursts=bursts(lv, top), sim_her=sim, f1_med=f1m, f2_med=f2m, f1_p75=f1p75, f1_p90=f1p90, low_db=low_db,
             hf_v=hf_v, attack_ms=float((i_pk - i_on) * 10), core_s=float((lv >= top - 10).sum() * 0.01),
             head_voiced=head_v, tail_voiced=tail_v, head_hf=head_hf, tail_hf=tail_hf, kana=st.result.text.strip())
    m.update(contour(vt, vf))
    fmt = lambda v: "" if v is None else (f"{v:.4f}" if isinstance(v, float) else str(v))
    o.write(f + "\t" + "\t".join(fmt(m.get(k)) for k in cols) + "\n"); o.flush()
o.close()
print("measured", len(files), "->", out)
