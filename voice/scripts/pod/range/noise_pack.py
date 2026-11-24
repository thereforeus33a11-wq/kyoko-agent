"""Owner sample pack of the sound bank's round-2 noises: every kept take of each noise and style, in take order,
0.6 s apart, one wav per noise/style, levelled as the phone plays them (whisper -30, soft -27, normal -23, loud -20
LUFS, peak under -1 dBFS; a take under 0.4 s is levelled by its RMS), and README.txt with each take's source, how it
was made, the line it was cut from, and its numbers (as round 1's snd_pack.py, plus the contour, mouth, burst and
the gate each noise passed). The bank files keep their own level (sounds.json has it).

Usage (gsv env): python noise_pack.py <bank dir with sounds.json> <jobs tsv ...> -- <out dir> [<extra README text file>]
"""
import json, os, sys
import numpy as np, soundfile as sf
sys.path.insert(0, "/w/range/scripts")
from measure import k_loudness

args = sys.argv[1:]
cut = args.index("--")
bank, jobs_ps, rest = args[0], args[1:cut], args[cut + 1:]
out = rest[0]; extra = rest[1] if len(rest) > 1 else None
os.makedirs(out, exist_ok=True)
TARGET = {"whisper": -30.0, "soft": -27.0, "normal": -23.0, "loud": -20.0}
text = {}
for p in jobs_ps:
    for l in open(p, encoding="utf-8"):
        q = l.rstrip("\n").split("\t")
        if len(q) >= 6: text[q[0]] = (q[-1], q[3] if len(q) == 6 and q[3] != "-" else "")
j = json.load(open(os.path.join(bank, "sounds.json"), encoding="utf-8"))
SR = j["sample_rate"]
gap = np.zeros(int(0.6 * SR), np.float32)
ORDER = ["fuun", "un", "unun", "hee", "hah", "hah_snap", "pfft", "heh", "bark", "cackle", "mm", "mmm", "haa", "click"]
lines = ["Her sound bank, round 2: her own noises (built 2026-11-24). Owner sample pack (private: her voice, never",
         "commit or upload).", "",
         "One wav per noise and style: every kept take in take order, 0.6 s apart, each levelled here as the phone",
         "would play it (whisper -30, soft -27, normal -23, loud -20 LUFS, peak under -1 dBFS); the bank files keep the",
         "level they were made at. The bank: /w/range_v1/sounds on the pod, beside round 1 (sounds.json has every number),",
         "archived as /workspace/yume/range_v1_archive/sounds.tar (round 1 alone: sounds_r1.tar).", "",
         "Per take: how it was made and the line it was cut from; length; median pitch (none = no voice); the pitch",
         "contour (start -> end in Hz, the rise and the net change in semitones); mouth (F1, the first formant, and the low",
         "band: energy under 600 Hz against 600-4000 Hz; a closed-mouth hum has F1 ~250 Hz and +15..+25 dB, her open",
         "vowels F1 640-780 Hz and ~+5 dB); loudness as made; sim (WavLM timbre cosine to her 4 real clips; short noises",
         "score low by nature, so compare within one noise only); what the speech recogniser heard; and the sound",
         "tagger's first guesses (an AudioSet classifier; it has no class for most of these noises).", ""]
gates = j.get("round2", {}).get("gates", {})
for s in ORDER:
    cells = j["sounds"].get(s)
    if not cells: continue
    lines.append(f"== {s}: {gates.get(s, '')}")
    lines.append("")
    for st in ("normal", "soft", "whisper", "loud"):
        takes = cells.get(st)
        if not takes: continue
        parts = []
        lines.append(f"{s}_{st}.wav  ({len(takes)} takes)")
        for k, t in enumerate(takes, 1):
            y, sr = sf.read(os.path.join(bank, t["file"]), dtype="float32")
            l = k_loudness(y.astype(np.float64), sr)
            if not np.isfinite(l): l = 20 * np.log10(np.sqrt(np.mean(y.astype(np.float64) ** 2)) + 1e-9) - 0.7
            g = min(10 ** ((TARGET[st] - l) / 20), 10 ** (30 / 20), 10 ** (-1 / 20) / (np.max(np.abs(y)) + 1e-9))
            parts += [y * g, gap]
            src = t["source"]
            line, cap = text.get(src["job"], ("", ""))
            how = f"way {src['way']} ({src['how']}); {src['kind']}: {line}" + (f" [caption: {cap}]" if cap else "")
            if src.get("note"): how += f" [{src['note']}]"
            f0 = f"{t['f0_median_hz']:.0f} Hz" if t["f0_median_hz"] else "none"
            c = t.get("contour") or {}
            con = (f", contour {c['f0_start_hz']:.0f}->{c['f0_end_hz']:.0f} Hz (rise {c['rise_st']:.1f} st, net {c['net_st']:+.1f})"
                   if c.get("f0_start_hz") else "")
            mo = t.get("mouth") or {}
            mou = f", F1 {mo['f1_hz']:.0f} Hz, low band {mo['low_band_db']:+.0f} dB" if mo.get("f1_hz") and mo.get("low_band_db") is not None else ""
            bu = t.get("burst") or {}
            bur = f", {bu['pulses']} pulse{'s' if bu['pulses'] != 1 else ''}, attack {bu['attack_ms']:.0f} ms" if bu else ""
            sim = f"{t['sim_her']:.2f}" if t["sim_her"] is not None else "-"
            lu = f"{t['lufs']:.1f} LUFS" + (f" in the file ({t['lufs'] - t['gain_db']:.1f} as made, raised to be held in 16 bits)" if t.get("gain_db") else " as made")
            tg = "; ".join(x.replace(":", " ") for x in (t.get("tagger") or "").split(";")[:3])
            lines.append(f"  take_{k:02d}  synthetic, {how}")
            lines.append(f"           {t['duration_s']:.2f} s, pitch {f0}{con}{mou}{bur}, {lu}, sim {sim}, heard: {t['heard'] or '-'}")
            lines.append(f"           tagger: {tg}")
        sf.write(os.path.join(out, f"{s}_{st}.wav"), np.concatenate(parts[:-1]), SR, subtype="PCM_16")
        lines.append("")
if extra and os.path.exists(extra):
    lines += open(extra, encoding="utf-8").read().rstrip("\n").split("\n")
open(os.path.join(out, "README.txt"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("pack:", len([f for f in os.listdir(out) if f.endswith(".wav")]), "wavs in", out)
