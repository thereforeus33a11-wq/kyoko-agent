"""Cut single dry tongue clicks out of raw takes. A dental click ("tsk") is a short broadband transient with no
frication after it; a spoken voiceless チッ has a 50-110 ms affricate burst. On 2 ms frames, a click is kept when:
  loud      its peak is within 12 dB of the take's loudest 2 ms frame
  width     the frames within 10 dB of its peak span at most 16 ms
  dry       nothing from 10 to 60 ms after the peak (outside that span) comes within 20 dB of it
  clean     nothing from 60 to 6 ms before the peak comes within 20 dB of it
  isolated  nothing else within 150 ms either side (outside 10 ms) comes within 15 dB of it
  floor     the take's quiet level (10th percentile of its frames) is at least 30 dB under it
Each click is cut from 150 ms before its peak to 200 ms after (15 ms fade in, 60 ms fade out, the click untouched).

Usage: python noise_clicks.py <meta.tsv> <out dir> <cuts.tsv> <clicks.tsv> <label>=<raw dir> ...
  meta.tsv: name, sound, style, kind, post, way (only jobs whose sound is "click" are read)
Writes <out dir>/<label>__<raw stem>_k<n>.wav, rows in cuts.tsv (the sound bank's cut table: file, src, sound,
style, kind K, way, name, from, to, status, note) and clicks.tsv (file, peak_s, width_ms, dry_db, clean_db, iso_db,
floor_db).
"""
import glob, os, re, sys
import numpy as np, soundfile as sf

meta_p, out, cuts_p, clicks_p = sys.argv[1:5]
pairs = [a.split("=", 1) for a in sys.argv[5:]]
meta = {}
for l in open(meta_p, encoding="utf-8"):
    p = l.rstrip("\n").split("\t")
    if p[0] != "name" and len(p) >= 6 and p[1] == "click":
        meta[p[0]] = dict(sound=p[1], style=p[2], way=p[5])
os.makedirs(out, exist_ok=True)
rows, crow = [], []
H = 0.002
for lab, d in pairs:
    for f in sorted(glob.glob(os.path.join(d, "[0-9]*.wav"))):
        m = re.match(r"(\d{4})_(.+)_t(\d+)\.wav", os.path.basename(f))
        if not m or m.group(2) not in meta: continue
        mt = meta[m.group(2)]
        x, sr = sf.read(f, dtype="float32")
        if x.ndim > 1: x = x.mean(axis=1)
        h = int(H * sr); n = len(x) // h
        if n < 100: continue
        lv = 20 * np.log10(np.sqrt(np.mean(x[:n * h].reshape(n, h).astype(np.float64) ** 2, axis=1)) + 1e-9)
        top = lv.max(); floor = np.percentile(lv, 10)
        ms = lambda t: int(round(t / 1000 / H))
        k = 0
        for p in range(1, n - 1):
            if not (lv[p] >= top - 12 and lv[p] >= lv[p - 1] and lv[p] > lv[p + 1]): continue
            a = p
            while a > 0 and lv[a - 1] > lv[p] - 10: a -= 1
            b = p
            while b < n - 1 and lv[b + 1] > lv[p] - 10: b += 1
            width = (b - a + 1) * H * 1000
            if width > 16: continue
            post = lv[max(b + 1, p + ms(10)):min(n, p + ms(60))]
            pre = lv[max(0, p - ms(60)):max(0, min(a, p - ms(6)))]
            win = np.r_[lv[max(0, p - ms(150)):max(0, p - ms(10))], lv[min(n, p + ms(10)):min(n, p + ms(150))]]
            dry = lv[p] - (post.max() if len(post) else -200); clean = lv[p] - (pre.max() if len(pre) else -200)
            iso = lv[p] - (win.max() if len(win) else -200); fl = lv[p] - floor
            if dry < 20 or clean < 20 or iso < 15 or fl < 30: continue
            t = (p + 0.5) * H
            s0, s1 = max(0, int((t - 0.15) * sr)), min(len(x), int((t + 0.20) * sr))
            y = x[s0:s1].copy()
            ki, ko = int(0.015 * sr), int(0.06 * sr)
            y[:ki] *= np.linspace(0, 1, ki); y[-ko:] *= np.linspace(1, 0, ko) ** 2
            name = f"{lab}__{os.path.basename(f)[:-4]}_k{k}.wav"; k += 1
            sf.write(os.path.join(out, name), y, sr, subtype="PCM_16")
            note = f"click at {t:.3f} s: width {width:.0f} ms, dry {dry:.0f} dB, clean {clean:.0f} dB, iso {iso:.0f} dB, floor {fl:.0f} dB"
            rows.append([name, f, mt["sound"], mt["style"], "K", mt["way"], m.group(2), f"{s0 / sr:.3f}", f"{s1 / sr:.3f}", "ok", note])
            crow.append([name, f"{t:.3f}", f"{width:.0f}", f"{dry:.1f}", f"{clean:.1f}", f"{iso:.1f}", f"{fl:.1f}"])
with open(cuts_p, "a", encoding="utf-8") as o:
    for r in rows: o.write("\t".join(map(str, r)) + "\n")
with open(clicks_p, "w", encoding="utf-8") as o:
    o.write("file\tpeak_s\twidth_ms\tdry_db\tclean_db\tiso_db\tfloor_db\n")
    for r in crow: o.write("\t".join(r) + "\n")
print("clicks:", len(rows), "cut from", len({r[1] for r in rows}), "takes")
