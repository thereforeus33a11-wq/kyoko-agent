"""Signal processing of short vocal noises (round 3 of the sound bank): every output is made only from the takes
given, and the caller writes down exactly what was done to which take.

  whisper IN OUT                 a whispered copy: frame-wise LPC (order 2 + sr/1000 on a 25 ms Hann window, 75 %
                                 overlap; bandwidths widened, a_k x 0.94^k, as sharp LPC formants make the noise
                                 ring at F1, which a pitch tracker reads as a 500-650 Hz voice) keeps the vocal
                                 tract; the excitation is white noise of the residual's energy; the lows are
                                 rolled off (4th-order high-pass at 300 Hz); the band over 4 kHz is set to -13 dB
                                 against 80-4000 Hz (her whisper set's median); level = the source's active RMS -
                                 6 dB; then the WHOLE take is scaled so its peak is under -1 dBFS (round 2's
                                 whisperize.py clipped at 0.99 instead: its copies clipped)
  shift IN OUT ST [--world]      pitch shifted by ST semitones keeping the formants and the length: Praat's PSOLA
                                 (Manipulation, pitch tier x 2^(ST/12), overlap-add) or WORLD (harvest / cheaptrick /
                                 d4c, f0 x 2^(ST/12), the spectral envelope and aperiodicity kept)
  breakup IN OUT T [XF]          a laugh that breaks into breath: the take as it is up to T s, then its whispered copy
                                 (as `whisper`, at the voiced part's level - 3 dB) crossfaded in over XF s (0.08)
  tail IN OUT BREATH [GAP] [DB]  breath pulses after the take: each BREATH file (comma separated) trimmed to its own
                                 sound (-40 dB), 15 ms in, 40 ms out, at DB dB (-8) against the take's loud level,
                                 GAP s (0.06) apart, the first GAP s after the take's last sound
  slide IN OUT ST [FRAC] [CAP]   a rise that slides down: the take's pitch kept until its rise reaches FRAC
                                 (0.6) of its height (inside 35 % to CAP (75 %) of the voiced part), then from that point a
                                 glide down by ST semitones (linear in semitones) to the last voiced frame: WORLD (harvest / cheaptrick / d4c)
                                 resynthesis with the new f0, envelope and aperiodicity kept
  concat A B OUT [GAP]           B after A: A trimmed after its last sound (-45 dB) + 20 ms, GAP s (0.05) of A's own
                                 floor level noise, B from 10 ms before its first sound; 10 ms crossfades
Writes OUT at IN's rate (PCM 16) and prints one line: what was done.
"""
import sys
import numpy as np, soundfile as sf, librosa
from scipy.signal import lfilter, butter, sosfiltfilt


def load(p):
    x, sr = sf.read(p, dtype="float64", always_2d=True)
    return x.mean(axis=1), sr


def lv10(x, sr):
    fr = int(0.01 * sr); n = max(1, len(x) // fr)
    return 20 * np.log10(np.sqrt(np.mean(x[:n * fr].reshape(n, fr) ** 2, axis=1)) + 1e-12)


def act_rms(v, sr):
    fr = int(0.01 * sr); n = len(v) // fr
    lv = np.sqrt(np.mean(v[:n * fr].reshape(n, fr) ** 2, axis=1))
    th = np.percentile(lv, 95) * 10 ** (-35 / 20)
    return float(np.sqrt(np.mean(lv[lv >= th] ** 2)))


def peak_safe(y, db=-1.0):
    pk = np.max(np.abs(y)) + 1e-12
    return y * min(1.0, 10 ** (db / 20) / pk)


def whisper(x, sr, seed=7, bright=False, bw=0.97):
    """bright: no de-emphasis (aspiration noise is flatter than a voice: her whisper set's energy over 4 kHz is
    8-10 dB above her synthetic voiced sets'); bw: LPC bandwidth expansion (a_k x bw^k): sharp LPC formants make
    the noise ring at F1, which a pitch tracker reads as a voice at 500-650 Hz (round 2's whispered copies)."""
    order = int(2 + sr / 1000)
    pre = lfilter([1, -0.97], [1], x)
    win = int(0.025 * sr); hop = win // 4; w = np.hanning(win)
    rng = np.random.default_rng(seed)
    out = np.zeros(len(x) + win); norm = np.zeros(len(x) + win)
    for s in range(0, len(x) - win, hop):
        fr = pre[s:s + win] * w
        if np.sum(fr ** 2) < 1e-10: continue
        A = librosa.lpc(fr, order=order)
        if not np.all(np.isfinite(A)): continue
        A = A * bw ** np.arange(len(A))
        res = lfilter(A, [1], fr); g = np.sqrt(np.mean(res ** 2))
        y = lfilter([1], A, rng.standard_normal(win) * g) * w
        if not np.all(np.isfinite(y)) or np.max(np.abs(y)) > 50 * (np.max(np.abs(fr)) + 1e-9): continue  # unstable frame
        out[s:s + win] += y; norm[s:s + win] += w ** 2
    y = out[:len(x)] / np.maximum(norm[:len(x)], 1e-3)
    if not bright: y = lfilter([1], [1, -0.97], y)
    y = sosfiltfilt(butter(4, 300, "highpass", fs=sr, output="sos"), y)
    y *= act_rms(x, sr) / max(act_rms(y, sr), 1e-12) * 10 ** (-6 / 20)
    return y


def hf_db(y, sr):
    S = np.abs(librosa.stft(y.astype(np.float32), n_fft=1024, hop_length=256)) ** 2
    f = librosa.fft_frequencies(sr=sr, n_fft=1024)
    return float(10 * np.log10((S[f >= 4000].sum() + 1e-12) / (S[(f >= 80) & (f < 4000)].sum() + 1e-12)))


def match_hf(y, sr, target):
    """Scale the band over 4 kHz so its energy against 80-4000 Hz is `target` dB (her real breaths: -7 dB median;
    her whisper set: -13 dB)."""
    if sr <= 8000: return y
    lo = sosfiltfilt(butter(4, 4000, "lowpass", fs=sr, output="sos"), y); hi = y - lo
    for _ in range(3):
        d = target - hf_db(lo + hi, sr)
        hi = hi * 10 ** (d / 20)
    return lo + hi


def shift_psola(x, sr, st):
    import parselmouth
    from parselmouth.praat import call
    snd = parselmouth.Sound(x, sampling_frequency=sr)
    man = call(snd, "To Manipulation", 0.01, 75, 600)
    pt = call(man, "Extract pitch tier")
    call(pt, "Multiply frequencies", snd.xmin, snd.xmax, 2 ** (st / 12))
    call([pt, man], "Replace pitch tier")
    return call(man, "Get resynthesis (overlap-add)").values[0][:len(x)]


def shift_world(x, sr, st):
    import pyworld as pw
    f0, t = pw.harvest(x, sr, f0_floor=70, f0_ceil=900, frame_period=5.0)
    sp = pw.cheaptrick(x, f0, t, sr); ap = pw.d4c(x, f0, t, sr)
    return pw.synthesize(f0 * 2 ** (st / 12), sp, ap, sr, frame_period=5.0)[:len(x)]


def fades(y, sr):
    """15 ms in, 60 ms out, as the bank's cuts."""
    y = y.copy(); k = min(len(y) // 2, int(0.015 * sr)); ko = min(len(y) // 2, int(0.06 * sr))
    y[:k] *= np.linspace(0, 1, k); y[-ko:] *= np.linspace(1, 0, ko) ** 2
    return y


def span(x, sr, th):
    lv = lv10(x, sr); a = np.where(lv >= lv.max() - th)[0]
    return (a[0] / 100, (a[-1] + 1) / 100) if len(a) else (0.0, len(x) / sr)


def ramp(n, up=True):
    r = np.linspace(0, 1, max(1, n)); return r if up else r[::-1]


op = sys.argv[1]
if op == "whisper":
    x, sr = load(sys.argv[2]); out = sys.argv[3]
    y = peak_safe(match_hf(whisper(x, sr, bright=True, bw=0.94), sr, -13.0))
    how = "whispered copy (LPC with bandwidth expansion 0.94, noise excitation, 300 Hz high-pass, the band over 4 kHz set to -13 dB as her whisper set's, -6 dB, peak scaled under -1 dBFS)"
elif op == "shift":
    x, sr = load(sys.argv[2]); out = sys.argv[3]; st = float(sys.argv[4])
    y = shift_world(x, sr, st) if "--world" in sys.argv else shift_psola(x, sr, st)
    y = peak_safe(y); how = f"pitch shifted {st:+.1f} semitones, formants kept ({'WORLD' if '--world' in sys.argv else 'Praat PSOLA'})"
elif op == "breakup":
    x, sr = load(sys.argv[2]); out = sys.argv[3]; T = float(sys.argv[4]); XF = float(sys.argv[5]) if len(sys.argv) > 5 else 0.08
    w = match_hf(whisper(x, sr, bright=True, bw=0.94), sr, -7.0)
    i0 = int(T * sr); n = int(XF * sr)
    vr = act_rms(x[:i0], sr) if i0 > int(0.1 * sr) else act_rms(x, sr)
    w *= vr / max(act_rms(w[i0:], sr), 1e-12) * 10 ** (-3 / 20)
    g = np.concatenate([np.ones(i0), ramp(n, False), np.zeros(max(0, len(x) - i0 - n))])[:len(x)]
    y = peak_safe(x * g + w * (1 - g))
    how = f"voiced up to {T:.2f} s, then its own whispered copy (LPC, bandwidth 0.94, the band over 4 kHz set to -7 dB as her real breaths') crossfaded in over {XF * 1000:.0f} ms at the voiced part's level - 3 dB"
elif op == "tail":
    x, sr = load(sys.argv[2]); out = sys.argv[3]; bs = sys.argv[4].split(",")
    gap = float(sys.argv[5]) if len(sys.argv) > 5 else 0.06; db = float(sys.argv[6]) if len(sys.argv) > 6 else -8.0
    top = lv10(x, sr).max(); _, off = span(x, sr, 45)
    y = list(x[:int(off * sr)]); fl = np.zeros(int(gap * sr))
    parts = []
    for b in bs:
        z, zr = load(b)
        if zr != sr: z = librosa.resample(z, orig_sr=zr, target_sr=sr)
        a0, a1 = span(z, sr, 40); z = z[int(a0 * sr):int(a1 * sr)].copy()
        k = int(0.015 * sr); ko = int(0.04 * sr)
        z[:k] *= ramp(k); z[-ko:] *= ramp(ko, False)
        z *= 10 ** ((top + db - lv10(z, sr).max()) / 20)
        y += list(fl) + list(z); parts.append(f"{len(z) / sr * 1000:.0f} ms")
    y = peak_safe(np.concatenate([np.array(y), np.zeros(int(0.25 * sr))]))
    how = f"{len(bs)} breath pulse(s) ({', '.join(parts)}) appended {gap * 1000:.0f} ms apart at {db:+.0f} dB against the take's loud level"
elif op == "slide":
    import pyworld as pw
    x, sr = load(sys.argv[2]); out = sys.argv[3]; st = float(sys.argv[4]); frac = float(sys.argv[5]) if len(sys.argv) > 5 else 0.6
    cap = float(sys.argv[6]) if len(sys.argv) > 6 else 0.75
    f0, t = pw.harvest(x, sr, f0_floor=70, f0_ceil=900, frame_period=5.0)
    sp = pw.cheaptrick(x, f0, t, sr); ap = pw.d4c(x, f0, t, sr)
    v = np.where(f0 > 0)[0]
    if len(v) < 10: sys.exit("slide: no voice")
    st_v = 12 * np.log2(f0[v] / 100.0)
    sm = np.array([np.median(st_v[max(0, i - 4):i + 5]) for i in range(len(v))])
    q = max(3, len(v) // 5); s0 = np.median(sm[:q]); pk = sm.max()
    reach = np.where(sm >= s0 + frac * (pk - s0))[0]
    k = int(reach[0]) if len(reach) else int(0.6 * (len(v) - 1))
    k = min(max(k, int(0.35 * (len(v) - 1))), int(cap * (len(v) - 1)))
    ip = v[k]; il = v[-1]
    base = float(np.median(f0[max(0, ip - 4):ip + 5][f0[max(0, ip - 4):ip + 5] > 0]))
    r = np.clip((np.arange(len(f0)) - ip) / max(1, il - ip), 0, 1)
    f1 = np.where((f0 > 0) & (np.arange(len(f0)) > ip), base * 2 ** (-st * r / 12), f0)
    y = peak_safe(pw.synthesize(f1, sp, ap, sr, frame_period=5.0)[:len(x)])
    how = f"the rise kept until it reaches {frac:.0%} of its height ({t[ip]:.2f} s, inside 35-{cap:.0%} of the voiced part), then the pitch glides down {st:.1f} semitones to its last voiced frame (WORLD resynthesis)"
elif op == "concat":
    a, sr = load(sys.argv[2]); b, sr2 = load(sys.argv[3]); out = sys.argv[4]
    gap = float(sys.argv[5]) if len(sys.argv) > 5 else 0.05
    if sr2 != sr: b = librosa.resample(b, orig_sr=sr2, target_sr=sr)
    _, aoff = span(a, sr, 45); bon, _ = span(b, sr, 45)
    a = a[:int((aoff + 0.02) * sr)].copy(); b = b[max(0, int((bon - 0.01) * sr)):].copy()
    k = int(0.01 * sr); a[-k:] *= ramp(k, False); b[:k] *= ramp(k)
    fl = np.random.default_rng(3).standard_normal(int(gap * sr)) * 10 ** (np.percentile(lv10(a, sr), 5) / 20)
    y = peak_safe(np.concatenate([a, fl, b])); how = f"two takes joined, {gap * 1000:.0f} ms apart, 10 ms crossfades"
else:
    sys.exit(f"unknown op {op}")
y = fades(y, sr)
sf.write(out, y.astype(np.float32), sr, subtype="PCM_16")
print(how)
