"""The owner's listening pack for the chosen five-style voice (gsv-env). No voice data in this file.
Reads a scored pack folder (styles_eval.py + styles_eval_score.py run on it: wav/<voice>/seed<S>/sid<N>/NNNN.wav and
score/clips.tsv) and writes into --dest:
  NN_<style>.wav       the same lines in that style (sid), in line order, 0.8 s apart
  all_styles.wav       the five of them one after the other, normal soft whisper loud yell, 1.6 s between styles
  e974_then_sid0.wav   each line in today's phone voice (e974) and then in the new voice's sid 0, 0.6 s apart,
                       1.4 s between lines: does her normal voice stay her
  README.txt           every line's numbers in every style
Usage: python styles_eval_pack.py --pack DIR --voice eNNNN --base e974 --seed 1234 --dest DIR --title TEXT
"""
import argparse
import csv
import os

import numpy as np
import soundfile as sf

STYLES = ["normal", "soft", "whisper", "loud", "yell"]


def tsv(p):
    with open(p, encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", required=True); ap.add_argument("--voice", required=True); ap.add_argument("--base", default="e974")
    ap.add_argument("--seed", default="1234"); ap.add_argument("--dest", required=True); ap.add_argument("--title", default="")
    a = ap.parse_args()
    os.makedirs(a.dest, exist_ok=True)
    meta = {int(r["n"]): r for r in tsv(f"{a.pack}/lines/meta.tsv")}
    C = {(r["voice"], int(r["sid"]), int(r["n"])): r for r in tsv(f"{a.pack}/score/clips.tsv") if r["src"] == "gen" and r["seed"] == a.seed}
    ns = sorted(meta)
    wav = lambda v, sid, n: sf.read(f"{a.pack}/wav/{v}/seed{a.seed}/sid{sid}/{n:04d}.wav", dtype="float32")
    sr = 22050
    gap = lambda s: np.zeros(int(sr * s), np.float32)
    per_style = []
    for sid, s in enumerate(STYLES):
        parts = []
        for n in ns:
            x, sr = wav(a.voice, sid, n); parts += [x, gap(0.8)]
        y = np.concatenate(parts[:-1]); per_style.append(y)
        sf.write(f"{a.dest}/{sid + 1:02d}_{s}.wav", y, sr, subtype="PCM_16")
    allp = []
    for y in per_style:
        allp += [y, gap(1.6)]
    sf.write(f"{a.dest}/all_styles.wav", np.concatenate(allp[:-1]), sr, subtype="PCM_16")
    pair = []
    for n in ns:
        x0, _ = wav(a.base, 0, n); x1, _ = wav(a.voice, 0, n)
        pair += [x0, gap(0.6), x1, gap(1.4)]
    sf.write(f"{a.dest}/e974_then_sid0.wav", np.concatenate(pair[:-1]), sr, subtype="PCM_16")
    f = lambda r, k, fmt="{:.1f}": fmt.format(float(r[k])) if r.get(k, "") not in ("", "nan") else "-"
    out = [a.title, "",
           "Her voice data: private. Never commit, never upload. 22050 Hz mono 16-bit, as the phone's sherpa-onnx returns it",
           f"(each style at its own level: whisper and soft are quiet, loud and yell loud: set the volume on the whisper and turn",
           f"down for loud and yell). Spoken the phone's way (phone_test_lang.py: mixed phonemizer, codepoints, sherpa-onnx,",
           f"sid = the style), the scoring copy of the voice with noise seed {a.seed}.",
           "Files: 01_normal.wav .. 05_yell.wav = the lines below in that style, in this order, 0.8 s apart;",
           "all_styles.wav = the five files one after the other (normal, soft, whisper, loud, yell), 1.6 s between styles;",
           f"e974_then_sid0.wav = each line in today's phone voice ({a.base}) and then in the new voice's sid 0, 0.6 s apart,",
           "1.4 s between lines (does her normal voice stay her).",
           "Numbers (measured from these files): s = seconds; LUFS loudness; f0 = median pitch, Hz (her adult cap 345); HNR dB",
           "(her voiced speech 15-24, a whisper 1-5); hi = energy above 4 kHz against 80-4000 Hz, dB; tilt = 1-4 kHz against",
           "80-1000 Hz on voiced frames, dB (- for a whisper: no voiced frames); hr = share of the clip in voiced runs (a whisper",
           "<= 0.05); sim = WavLM timbre match to her 4 real clips / to the style's reference (normal: -); class = the style",
           "the classifier (trained on the style sets' own clips) puts the clip in; words = error of what faster-whisper heard",
           "(median of three hearings; Japanese kana reading error, English word error) and whether the words stand by the",
           "style's gate (2 of 3 hearings); heard = the middle hearing.",
           "Nobody has listened to these yet: the numbers are from measures and recognisers only.", ""]
    for k, n in enumerate(ns, 1):
        L = meta[n]
        out.append(f"{k}. ({L['kind']}) {L['text']}")
        for v, sid, lab in [(a.base, 0, f"{a.base} (today)")] + [(a.voice, s, f"{STYLES[s]} (sid {s})") for s in range(5)]:
            r = C.get((v, sid, n))
            if r is None:
                out.append(f"    {lab:18s} not measured"); continue
            ok = "stand" if r.get("w_ok") == "1" else "FAIL"
            out.append(f"    {lab:18s} {f(r, 'dur', '{:.2f}')} s  LUFS {f(r, 'lufs')}  f0 {f(r, 'f0_med', '{:.0f}')}  HNR {f(r, 'hnr')}  hi {f(r, 'hf_db')}"
                       f"  tilt {f(r, 'tilt_v')}  hr {f(r, 'hr_share', '{:.3f}')}  sim {f(r, 'sim_her', '{:.3f}')} / {f(r, 'sim_ref', '{:.3f}')}"
                       f"  class {r.get('pred', '')}  words {f(r, 'w_err', '{:.2f}')} {ok}")
            out.append(f"    {'':18s} heard: {r.get('heard', '')}")
        out.append("")
    open(f"{a.dest}/README.txt", "w", encoding="utf-8").write("\n".join(out) + "\n")
    print("PACK-DONE", a.dest, len(ns), "lines")


if __name__ == "__main__":
    main()
