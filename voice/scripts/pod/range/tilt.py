"""Is a take's hi band (measure.py hf_db: energy above 4 kHz against 80-4000 Hz on all sounding frames) her VOICE
being brighter, or consonant and breath noise? Per take, on voiced frames only (normalised autocorrelation peak
>= 0.55 at 80-400 Hz, within 25 dB of the take's level; edges.py features):
  hf_v     energy above 4 kHz against 80-4000 Hz, voiced frames only (dB)
  tilt_v   energy 1-4 kHz against 80-1000 Hz, voiced frames only (dB): spectral tilt of the voice, lower = darker
  hf_unv   share of the take's energy above 4 kHz that lies in frames that are NOT voiced (0-1)
Usage (gsv-env): python tilt.py <out.tsv> <jobs> <dir> [<dir> ...]"""
import glob, os, sys
from multiprocessing import Pool
import numpy as np, soundfile as sf
sys.path.insert(0, "/w/job/scripts")
from edges import features


def one(p):
    x, sr = sf.read(p, dtype="float32")
    if x.ndim > 1: x = x.mean(axis=1)
    if len(x) < 0.3 * sr:
        return None
    h, w = int(0.01 * sr), int(0.025 * sr)
    lv, cen, hf, voi = features(x, sr)
    n = len(lv)
    idx = np.arange(w)[None, :] + h * np.arange(n)[:, None]
    xx = np.asarray(x, np.float64)
    if len(xx) < w: return None
    f = xx[idx] * np.hanning(w)
    nfft = 1 << int(np.ceil(np.log2(2 * w)))
    P = np.abs(np.fft.rfft(f, nfft, axis=1)) ** 2
    fr = np.fft.rfftfreq(nfft, 1 / sr)
    sp = np.percentile(lv, 95)
    act = lv >= sp - 35
    v = act & (voi >= 0.55) & (lv >= sp - 25)
    if v.sum() < 10:
        return None
    hi = fr >= 4000; lo = (fr >= 80) & (fr < 4000); mid = (fr >= 1000) & (fr < 4000); low = (fr >= 80) & (fr < 1000)
    db = lambda a, b: 10 * np.log10((a + 1e-12) / (b + 1e-12))
    Pv = P[v]
    hf_all = P[act][:, hi].sum()
    return (os.path.basename(p), db(Pv[:, hi].sum(), Pv[:, lo].sum()), db(Pv[:, mid].sum(), Pv[:, low].sum()),
            float(P[act & ~v][:, hi].sum() / (hf_all + 1e-12)), float(v.sum() / max(1, act.sum())))


if __name__ == "__main__":
    out, jobs = sys.argv[1], int(sys.argv[2])
    files = []
    for d in sys.argv[3:]:
        files += sorted(glob.glob(os.path.join(d, "[0-9]*.wav")))
    with Pool(jobs) as pool, open(out, "w") as o:
        o.write("file\thf_v\ttilt_v\thf_unv\tvoiced_share\n")
        for r in pool.imap(one, files, chunksize=16):
            if r:
                o.write(f"{r[0]}\t{r[1]:.3f}\t{r[2]:.3f}\t{r[3]:.3f}\t{r[4]:.3f}\n")
    print("TILT-DONE", len(files))
