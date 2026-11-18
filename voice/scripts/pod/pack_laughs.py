"""One file per sound: every take of it (4 of her references x 3 takes), in order, with a gap; a TSV with each take's pitch."""
import glob, os, numpy as np, soundfile as sf, pyworld as pw
O = "/w/job/out/laughs"; OUT = f"{O}/review"; os.makedirs(OUT, exist_ok=True)
lines = [l.rstrip("\n").split("|", 1)[1] for l in open("/w/job/data/laugh_lines3.txt", encoding="utf-8") if l.strip()]
uniq = list(dict.fromkeys(lines)); refs = ["default_A", "default_C", "snap_B", "drunk_C"]
tsv = open(f"{OUT}/takes.tsv", "w", encoding="utf-8")
tsv.write("file\ttake\tvoice\ttry\tseconds\tmedian_hz\tp90_hz\tover_adult_cap\ttext\n")
for u, text in enumerate(uniq, 1):
    parts, take, sr = [], 0, 22050
    for ref in refs:
        for t, n in enumerate([i for i, l in enumerate(lines) if l == text], 1):
            f = f"{O}/{ref}/{n:04d}_b.wav"
            if not os.path.exists(f): continue
            x, sr = sf.read(f, dtype="float64"); take += 1
            f0, _ = pw.harvest(x, sr, f0_floor=70, f0_ceil=900); f0 = f0[f0 > 0]
            med = float(np.median(f0)) if len(f0) else 0.0; p90 = float(np.percentile(f0, 90)) if len(f0) else 0.0
            over = "yes" if (med > 345 or p90 > 500) else ""
            tsv.write(f"sound_{u:02d}.wav\t{take}\t{ref}\t{t}\t{len(x)/sr:.2f}\t{med:.0f}\t{p90:.0f}\t{over}\t{text}\n")
            parts += [x.astype(np.float32), np.zeros(int(sr * 0.9), dtype=np.float32)]
    sf.write(f"{OUT}/sound_{u:02d}.wav", np.concatenate(parts), sr, subtype="PCM_16")
print("PACKED", len(uniq))
