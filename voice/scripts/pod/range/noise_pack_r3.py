"""Owner sample pack of the sound bank's round-3 takes: per noise and style, the round-3 takes in take order, 0.6 s
apart, one wav per cell, levelled as the phone plays them (whisper -30, soft -27, normal -23, loud -20 LUFS, peak
under -1 dBFS; at most +30 dB), and README.txt with each take's file, how it was made (way, kind, the line or the
processing and its source take), and its numbers: length, pitch by both trackers (clearly voiced frames), contour,
mouth, pulses, the course thirds, the edges against the raw line, voice quality, loudness as made, timbre, what
both recognisers heard and the tagger's first guesses. The bank files keep their own level (sounds.json has it).

Usage (gsv env): python noise_pack_r3.py <bank dir> <jobs tsv ...> -- <out dir> <head text file> [<tail text file>]
"""
import json, os, sys
import numpy as np, soundfile as sf
sys.path.insert(0, "/w/range/scripts")
from measure import k_loudness

args = sys.argv[1:]
cut = args.index("--")
bank, jobs_ps, rest = args[0], args[1:cut], args[cut + 1:]
out, head = rest[0], rest[1]; tail = rest[2] if len(rest) > 2 else None
os.makedirs(out, exist_ok=True)
TARGET = {"whisper": -30.0, "soft": -27.0, "normal": -23.0, "loud": -20.0}
text = {}
for p in jobs_ps:
    for l in open(p, encoding="utf-8"):
        q = l.rstrip("\n").split("\t")
        if len(q) == 6: text[q[0]] = (q[5], q[3] if q[3] != "-" else "")
        elif len(q) >= 7: text[q[0]] = (q[6], "")
j = json.load(open(os.path.join(bank, "sounds.json"), encoding="utf-8"))
SR = j["sample_rate"]
gap = np.zeros(int(0.6 * SR), np.float32)
gates = j.get("round3", {}).get("gates", {})
lines = open(head, encoding="utf-8").read().rstrip("\n").split("\n") + [""]
f1 = lambda v, d=0, u="": "-" if v is None else f"{v:.{d}f}{u}"
for s, cells in j["sounds"].items():
    new = {st: [t for t in takes if t.get("round") == 3] for st, takes in cells.items()}
    if not any(new.values()): continue
    lines += [f"== {s}: {gates.get(s, '')}", ""]
    for st in ("normal", "soft", "whisper", "loud"):
        takes = new.get(st)
        if not takes: continue
        parts = []
        lines.append(f"{s}_{st}.wav  ({len(takes)} round-3 takes; the cell now holds {len(cells[st])})")
        for t in takes:
            y, sr = sf.read(os.path.join(bank, t["file"]), dtype="float32")
            l = k_loudness(y.astype(np.float64), sr)
            if not np.isfinite(l): l = 20 * np.log10(np.sqrt(np.mean(y.astype(np.float64) ** 2)) + 1e-9) - 0.7
            g = min(10 ** ((TARGET[st] - l) / 20), 10 ** (30 / 20), 10 ** (-1 / 20) / (np.max(np.abs(y)) + 1e-9))
            parts += [y * g, gap]
            src = t["source"]
            line, cap = text.get(src["job"], ("", ""))
            if src["way"] == "P":
                how = f"made by signal processing: {src.get('note', '')}"
            else:
                how = f"way {src['way']} ({src['how']}); {src['kind']}: {line}" + (f" [caption: {cap}]" if cap else "")
            pt = t.get("pitch") or {}
            c = t.get("contour") or {}
            mo = t.get("mouth") or {}
            bu = t.get("burst") or {}
            co = t.get("course") or {}
            q = t.get("quality") or {}
            ed = t.get("edges") or {}
            pitch = (f"pitch {f1(pt.get('praat_clear_median_hz'))} Hz (Praat) / {f1(pt.get('pyin_clear_median_hz'))} Hz (pyin), "
                     f"p90 {f1(pt.get('praat_clear_p90_hz'))} / {f1(pt.get('pyin_clear_p90_hz'))}")
            con = (f"; contour {c['f0_start_hz']:.0f}->{c['f0_end_hz']:.0f} Hz (rise {c['rise_st']:.1f} st, fall {c['fall_st']:.1f}, "
                   f"net {c['net_st']:+.1f}, peak at {c['peak_pos']:.2f})" if c.get("f0_start_hz") and c.get("rise_st") is not None else "")
            mou = f"; F1 {f1(mo.get('f1_hz'))} Hz, low band {f1(mo.get('low_band_db'), 0)} dB, tilt {f1(mo.get('tilt_db'), 1)} dB"
            cv = co.get("voiced") or [None] * 3; ch = co.get("hnr_db") or [None] * 3; cf = co.get("hf_db") or [None] * 3
            cou = (f"; thirds: voiced {f1(cv[0], 2)}/{f1(cv[1], 2)}/{f1(cv[2], 2)}, HNR {f1(ch[0], 0)}/{f1(ch[1], 0)}/{f1(ch[2], 0)} dB, "
                   f"over 4 kHz {f1(cf[0], 0)}/{f1(cf[1], 0)}/{f1(cf[2], 0)} dB")
            edg = (f"; edges: raw {f1(ed.get('raw_before_db'), 0)} dB before, {f1(ed.get('raw_after_db'), 0)} dB after, next sound "
                   f"{'none' if ed.get('next_sound_gap_s') is None else f1(ed['next_sound_gap_s'] * 1000, 0, ' ms')} after"
                   if src["way"] != "P" else "")
            lu = f"{t['lufs']:.1f} LUFS" + (f" in the file ({t['lufs'] - t['gain_db']:.1f} as made)" if t.get("gain_db") else " as made")
            tg = "; ".join(x.replace(":", " ") for x in (t.get("tagger") or "").split(";")[:3])
            lines.append(f"  {os.path.basename(t['file'])[:-4]}  synthetic, {how}")
            lines.append(f"           {t['duration_s']:.2f} s, {pitch}{con}")
            lines.append(f"           voiced {f1(t.get('voiced_share'), 2)} (pyin {f1(t.get('pyin_voiced_share'), 2)}), HNR {f1(t.get('hnr_db'), 1)} dB, "
                         f"{bu.get('pulses')} pulse(s), attack {f1(bu.get('attack_ms'))} ms{mou}")
            lines.append(f"           jitter {f1(q.get('jitter_pct'), 1)} %, shimmer {f1(q.get('shimmer_pct'), 1)} %, flatness {f1(q.get('flatness'), 3)}{cou}{edg}")
            lines.append(f"           {lu}, sim {f1(t.get('sim_her'), 2)}, heard: whisper {t.get('heard_whisper') or '-'} | kana {t.get('heard_kana') or '-'}"
                         f" (first 150 ms {t.get('head_kana') or '-'}, last {t.get('tail_kana') or '-'})")
            lines.append(f"           tagger: {tg}")
        sf.write(os.path.join(out, f"{s}_{st}.wav"), np.concatenate(parts[:-1]), SR, subtype="PCM_16")
        lines.append("")
if tail and os.path.exists(tail):
    lines += open(tail, encoding="utf-8").read().rstrip("\n").split("\n")
open(os.path.join(out, "README.txt"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("pack:", len([f for f in os.listdir(out) if f.endswith(".wav")]), "wavs in", out)
