"""Scoring the five-style run (one multi-speaker phone voice: sids 0 normal, 1 soft, 2 whisper, 3 loud, 4 yell).
No voice data in this file. Every step reads and writes under --out (default /w/range_build/styles/eval).

  lines   (gsv-env)       lines/meta.tsv: each scoring line (score/lines.tsv) with the language its words are judged
                          in (glang: en for English and English-led mixed lines, else ja), the English reference words,
                          the kana a Japanese recogniser should hear for a Japanese-led mixed line (English words as the
                          phone's katakana, check_lang.expected_kana), and its phoneme count (mixed phonemizer)
  sets    (any)           sets.tsv: the style sets' own clips (each set's training clips, not its held-out lines, a fixed
                          random sample per set: the classifier's training data and the sets' own bands) and the real
                          held-out clips of the scoring lines (`ref` column)
  items   (any)           items.tsv: every wav to measure: wav/<voice>/seed<S>/sid<N>/NNNN.wav and sets.tsv
  asr     (asr-env, GPU)  faster-whisper large-v3 (fp16, beam 5, no VAD, no previous-text conditioning, language per
                          line), three hearings per clip: 0.1, 0.3 and 0.5 s of silence before it and 0.3 s after (the
                          style checks' v_asr.py / v_words3.py): asr/heard_p<pad>.s<i>.tsv
  wer     (asr-env)       English word error of each English-led hearing as the sets' en_wer.py: Whisper's normalizer;
                          English lines (sub + del + ins) / words, English-led mixed lines (sub + del) / English words;
                          the lower of the plain error and the error with apostrophes inside words removed on both sides
  measure (gsv-env, CPU)  per clip: measure.py's acoustic() (LUFS, f0, voicing, HNR, hi band, centroid), tilt.py's
                          voiced-frame tilt and hi band, the whisper set's voicing measures (hr_share ...), a tilt over all
                          sounding frames, spectral flatness of the sounding frames, clipping; for Japanese-led lines the
                          sherpa ReazonSpeech kana recogniser on the whole clip (0.3 s around it) and phrase by phrase
  embed   (gsv-env, GPU)  WavLM x-vectors (measure.py's Embedder) of every item and of the reference clips: emb.npz
"""
import argparse
import csv
import glob
import json
import os
import random
import sys

SC = "/w/job/scripts"
PADS = ("0.1", "0.3", "0.5")
STYLES = ["normal", "soft", "whisper", "loud", "yell"]
REFS = {  # name -> clip: her 4 clean clips (the centroid), the same 4 whispered (whisper's within-style centroid),
    # and each style set's reference clip
    "her_v12_040": "/w/yume/range_proto/refs/v12_040_clean.wav", "her_v12_065": "/w/yume/range_proto/refs/v12_065_clean.wav",
    "her_v12_071": "/w/yume/range_proto/refs/v12_071_clean.wav", "her_yume_07": "/w/yume/range_proto/refs/yume_07_clean.wav",
    "w_v12_040": "/w/yume/range_proto/refs/v12_040_whisper.wav", "w_v12_065": "/w/yume/range_proto/refs/v12_065_whisper.wav",
    "w_v12_071": "/w/yume/range_proto/refs/v12_071_whisper.wav", "w_yume_07": "/w/yume/range_proto/refs/yume_07_whisper.wav",
    "ref_soft": "/w/yume/range_proto/refs/v12_040_clean.wav", "ref_loud": "/w/yume/range_proto/refs_C/C_loud.wav",
    "ref_yell": "/w/yume/range_proto/refs_C/C_yell_inrange.wav",
}


def tsv(p):
    with open(p, encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE))


def write_tsv(p, rows, cols):
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as o:
        o.write("\t".join(cols) + "\n")
        for r in rows:
            o.write("\t".join(str(r.get(c, "")).replace("\t", " ").replace("\n", " ") for c in cols) + "\n")
    os.replace(tmp, p)


# ------------------------------------------------------------------------------------------------------ lines
def cmd_lines(a):
    sys.path.insert(0, SC)
    import check_lang as cl
    from mix_phonemize import MixedPhonemizer
    from kana_text import KanaText
    mp = MixedPhonemizer(); cl._W["mp"] = mp; cl._W["kt"] = KanaText(mp.en.cmu)
    rows = tsv(a.lines)
    for r in rows:
        text, kind = r["text"], r["kind"]
        en_words, ja_units, en_led = cl.line_parts(mp, text)
        r["glang"] = "en" if kind == "en" or (kind == "mixed" and en_led) else "ja"
        r["en_words"] = " ".join(en_words) if r["glang"] == "en" else ""
        r["exp_kana"] = cl.expected_kana(text) if (kind == "mixed" and r["glang"] == "ja") else ""
        r["n_ph"] = sum(len(s) for s in (mp.phonemize(text) or []))
    os.makedirs(f"{a.out}/lines", exist_ok=True)
    cols = list(rows[0].keys())
    write_tsv(f"{a.out}/lines/meta.tsv", rows, cols)
    for sid in range(5):
        sel = [r for r in rows if int(r["sid"]) == sid]
        write_tsv(f"{a.out}/lines/sid{sid}.tsv", sel, cols)
        print("sid", sid, len(sel), "lines", {g: sum(r["glang"] == g for r in sel) for g in ("ja", "en")})
    print("LINES-DONE")


# ------------------------------------------------------------------------------------------------------- sets
def cmd_sets(a):
    """The training clips are the five-style run's own (its ds/metadata.csv `wav|speaker|text`, minus its val_ids.txt:
    each set's held-out lines and the left-out yell clips are not in it), a fixed random sample per style."""
    rng = random.Random(20261124)
    rows = []
    d = a.ds
    val = {l.strip() for l in open(f"{d}/val_ids.txt", encoding="utf-8") if l.strip()}
    by = {s: [] for s in STYLES}
    for l in open(f"{d}/metadata.csv", encoding="utf-8"):
        if l.strip():
            n, spk = l.split("|", 2)[:2]
            n = n if n.endswith(".wav") else n + ".wav"
            if n not in val:
                by[spk].append(n)
    for style in STYLES:
        train = sorted(by[style])
        pick = rng.sample(train, min(a.per_set, len(train)))
        for n in sorted(pick):
            p = os.path.realpath(f"{d}/wavs/{n}")
            if os.path.exists(p):
                rows.append(dict(id=f"set/{style}/{n}", path=p, src="set", cls=style, voice="set", seed="", sid=STYLES.index(style), n=-1))
        print(style, "training clips", len(train), "sampled", len(pick), "found", sum(r["cls"] == style for r in rows))
    for r in tsv(f"{a.out}/lines/meta.tsv"):
        if r["ref"]:
            rows.append(dict(id=f"real/{r['style']}/{int(r['n']):04d}", path=r["ref"], src="real", cls=r["style"], voice="real",
                             seed="", sid=r["sid"], n=r["n"]))
    print("real held-out clips", sum(r["src"] == "real" for r in rows))
    write_tsv(f"{a.out}/sets.tsv", rows, ["id", "path", "src", "cls", "voice", "seed", "sid", "n"])
    print("SETS-DONE")


# ------------------------------------------------------------------------------------------------------ items
def cmd_items(a):
    rows = []
    for p in sorted(glob.glob(f"{a.out}/wav/*/seed*/sid*/[0-9]*.wav")):
        rel = os.path.relpath(p, a.out)
        _, voice, seed, sid, f = rel.split("/")
        rows.append(dict(id=rel, path=p, src="gen", cls=STYLES[int(sid[3:])], voice=voice, seed=seed[4:], sid=sid[3:], n=int(f[:4])))
    if os.path.exists(f"{a.out}/sets.tsv"):
        rows += tsv(f"{a.out}/sets.tsv")
    write_tsv(f"{a.out}/items.tsv", rows, ["id", "path", "src", "cls", "voice", "seed", "sid", "n"])
    print("items", len(rows), {s: sum(r["src"] == s for r in rows) for s in ("gen", "real", "set")})


# -------------------------------------------------------------------------------------------------------- asr
def cmd_asr(a):
    import fcntl
    import numpy as np
    from faster_whisper import WhisperModel, decode_audio
    meta = {int(r["n"]): r for r in tsv(f"{a.out}/lines/meta.tsv")}
    si, sn = (int(v) for v in a.shard.split("/"))
    items = [r for r in tsv(f"{a.out}/items.tsv") if int(r["n"]) >= 0]
    if a.only:
        items = [r for r in items if r["voice"] in a.only.split(",")]
    items = items[si::sn]
    os.makedirs(f"{a.out}/asr", exist_ok=True)
    outs, done = {}, {}
    for p in PADS:
        fn = f"{a.out}/asr/heard_p{p}.s{si}.tsv"
        done[p] = {r["id"] for r in tsv(fn)} if os.path.exists(fn) and os.path.getsize(fn) > 0 else set()
        outs[p] = open(fn, "a", encoding="utf-8")
        if not done[p]:
            outs[p].write("id\tlang\theard\tavg_logprob\n")
    todo = [r for r in items if any(r["id"] not in done[p] for p in PADS)]
    print(f"asr shard {si}/{sn}: {len(items)} clips, {len(todo)} to hear", flush=True)
    if not todo:
        print("ASR-DONE"); return
    model = a.model
    if model.startswith("/workspace"):   # one big read of the volume at a time
        lk = open("/w/locks/volume", "a"); fcntl.flock(lk, fcntl.LOCK_EX)
    m = WhisperModel(model, device="cuda", compute_type="float16")
    if model.startswith("/workspace"):
        fcntl.flock(lk, fcntl.LOCK_UN); lk.close()
    for k, r in enumerate(todo):
        lg = meta[int(r["n"])]["glang"]
        y = decode_audio(r["path"], sampling_rate=16000)
        for p in PADS:
            if r["id"] in done[p]:
                continue
            z = np.concatenate([np.zeros(int(float(p) * 16000), np.float32), y, np.zeros(4800, np.float32)])
            segs, _ = m.transcribe(z, language=lg, beam_size=5, vad_filter=False, condition_on_previous_text=False)
            segs = list(segs)
            txt = "".join(s.text for s in segs).strip().replace("\t", " ").replace("\n", " ")
            lp = float(np.mean([s.avg_logprob for s in segs])) if segs else float("nan")
            outs[p].write(f"{r['id']}\t{lg}\t{txt}\t{lp:.3f}\n"); outs[p].flush()
        if k % 200 == 0:
            print("asr", k, len(todo), flush=True)
    for o in outs.values():
        o.close()
    print("ASR-DONE")


def heard(out):
    """{pad: {id: row}} over every shard."""
    H = {p: {} for p in PADS}
    for p in PADS:
        for fn in sorted(glob.glob(f"{out}/asr/heard_p{p}.s*.tsv")):
            for r in tsv(fn):
                H[p][r["id"]] = r
    return H


# -------------------------------------------------------------------------------------------------------- wer
def cmd_wer(a):
    import re
    sys.path.insert(0, SC)
    from check_lang import edit_ops, english_normalizer
    norm = english_normalizer(None)
    strip = lambda t: re.sub(r"(?<=[A-Za-z])['’](?=[A-Za-z])", "", t)
    meta = {int(r["n"]): r for r in tsv(f"{a.out}/lines/meta.tsv")}
    items = {r["id"]: r for r in tsv(f"{a.out}/items.tsv")}
    H = heard(a.out)
    for p in PADS:
        rows = []
        for fid, h in H[p].items():
            it = items.get(fid)
            if it is None:
                continue
            L = meta[int(it["n"])]
            if L["glang"] != "en":
                continue

            def err(f):
                ref = norm(f(L["en_words"])).split(); hyp = norm(f(h["heard"] or "")).split()
                sd, ins = edit_ops(ref, hyp)
                return (sd + ins) / max(1, len(ref)) if L["kind"] == "en" else sd / max(1, len(ref)), ref, hyp
            e1, ref, hyp = err(lambda t: t)
            e2, _, _ = err(strip)
            rows.append(dict(id=fid, wer=f"{min(e1, e2):.4f}", wer_plain=f"{e1:.4f}", n_ref=len(ref), ref=" ".join(ref), hyp=" ".join(hyp)))
        write_tsv(f"{a.out}/asr/wer_p{p}.tsv", rows, ["id", "wer", "wer_plain", "n_ref", "ref", "hyp"])
        print("wer", p, len(rows))
    print("WER-DONE")


# ---------------------------------------------------------------------------------------------------- measure
_W = {}


def _init_measure(do_sherpa):
    sys.path.insert(0, SC); sys.path.insert(0, f"{SC}/range"); sys.path.insert(0, "/w/range/scripts")
    import measure as M
    import tilt as T
    _W["M"], _W["T"] = M, T
    if do_sherpa:
        import sherpa_phrases as SP
        SP.init(); _W["SP"] = SP


def voicing(x, sr):
    """The whisper set's voicing measures (its score_w.py voicing(), copied): Praat harmonicity (cc, 10 ms, 75 Hz):
    hnr_hi share of rated frames >= 10 dB; hr_share = share of rated frames in runs of 5+ frames (50 ms) at >= 10 dB;
    hr_run the longest such run (s); hr_f0 the median Praat pitch (cc, 75-600 Hz) of those runs (0 if none)."""
    import numpy as np
    import parselmouth
    snd = parselmouth.Sound(x.astype(np.float64), sampling_frequency=sr)
    out = dict(hnr_hi=float("nan"), hr_share=float("nan"), hr_run=float("nan"), hr_f0=0.0)
    try:
        harm = snd.to_harmonicity_cc(time_step=0.01, minimum_pitch=75.0, silence_threshold=0.1, periods_per_window=1.0)
        hall = harm.values[0]; ht = np.asarray(harm.xs()); rated = hall > -200
        hv = hall[rated]
        if len(hv):
            out["hnr_hi"] = float(np.mean(hv >= 10.0))
            hi = hall >= 10.0
            e = np.flatnonzero(np.diff(np.r_[0, hi.astype(np.int8), 0]))
            runs = [(b0, b1) for b0, b1 in zip(e[0::2], e[1::2]) if b1 - b0 >= 5]
            out["hr_share"] = float(sum(b1 - b0 for b0, b1 in runs) / len(hv))
            out["hr_run"] = max([b1 - b0 for b0, b1 in runs], default=0) * 0.01
            if runs:
                pc = snd.to_pitch_cc(time_step=0.01, pitch_floor=75.0, pitch_ceiling=600.0)
                f = np.array([pc.get_value_at_time(tt) for b0, b1 in runs for tt in ht[b0:b1]])
                f = f[np.isfinite(f) & (f > 0)]
                out["hr_f0"] = float(np.median(f)) if len(f) else 0.0
    except Exception:
        pass
    return out


def spectral(x, sr, M):
    """Spectral flatness (geometric over arithmetic mean of the power, 80 Hz-10 kHz) of each sounding STFT frame
    (1024 / 256; frames within 35 dB of the clip's level, as measure.py's active frames): median and 95th percentile
    over the frames; and the tilt over ALL sounding frames (1-4 kHz against 80-1000 Hz, dB), defined for a whisper too."""
    import numpy as np
    import librosa
    lv = M.levels(x, sr); act = lv >= np.percentile(lv, 95) - 35
    S = np.abs(librosa.stft(x.astype(np.float32), n_fft=1024, hop_length=256, center=True)) ** 2
    fr = librosa.fft_frequencies(sr=sr, n_fft=1024)
    t = np.arange(S.shape[1]) * 256 / sr
    idx = np.clip((t / 0.01).astype(int), 0, len(act) - 1)
    P = S[:, act[idx]]
    if P.shape[1] < 3:
        return dict(flat_med=float("nan"), flat_p95=float("nan"), tilt_a=float("nan"))
    band = (fr >= 80) & (fr <= 10000)
    B = P[band] + 1e-12
    fl = np.exp(np.mean(np.log(B), axis=0)) / np.mean(B, axis=0)
    mid = (fr >= 1000) & (fr < 4000); low = (fr >= 80) & (fr < 1000)
    tilt_a = 10 * np.log10((P[mid].sum() + 1e-12) / (P[low].sum() + 1e-12))
    return dict(flat_med=float(np.median(fl)), flat_p95=float(np.percentile(fl, 95)), tilt_a=float(tilt_a))


MCOLS = ["dur", "lufs", "rms_db", "peak_db", "f0_med", "f0_p10", "f0_p90", "voiced", "hnr", "hf_db", "centroid",
         "hf_v", "tilt_v", "hf_unv", "voiced_share", "hnr_hi", "hr_share", "hr_run", "hr_f0", "flat_med", "flat_p95",
         "tilt_a", "clip_n", "sh_whole", "sh_phr", "sh_nphr"]


def _measure_one(job):
    import numpy as np
    import soundfile as sf
    fid, path, do_sh = job
    M, T = _W["M"], _W["T"]
    try:
        x, sr = M.load(path)
        if len(x) < 0.15 * sr:
            return fid, None, "too short"
        d = M.acoustic(x, sr)
        t = T.one(path)
        if t:
            d.update(hf_v=t[1], tilt_v=t[2], hf_unv=t[3], voiced_share=t[4])
        d.update(voicing(x, sr)); d.update(spectral(x, sr, M))
        d["clip_n"] = int((np.abs(x) >= 0.999).sum())
        if do_sh:
            SP = _W["SP"]; rec = SP._W["rec"]
            import librosa
            y = librosa.resample(x, orig_sr=sr, target_sr=16000) if sr != 16000 else x
            pad = np.zeros(int(0.3 * 16000), np.float32)
            s = rec.create_stream(); s.accept_waveform(16000, np.concatenate([pad, y, pad]).astype(np.float32)); rec.decode_stream(s)
            d["sh_whole"] = s.result.text
            k, h = SP.hear(path)
            d["sh_phr"], d["sh_nphr"] = h, k
        return fid, d, ""
    except Exception as e:  # a failed clip is written as failed, never left out silently
        return fid, None, f"{type(e).__name__}: {e}"


def cmd_measure(a):
    from multiprocessing import Pool
    meta = {int(r["n"]): r for r in tsv(f"{a.out}/lines/meta.tsv")}
    items = tsv(f"{a.out}/items.tsv")
    if a.only:
        items = [r for r in items if r["voice"] in a.only.split(",")]
    fn = f"{a.out}/measure.tsv"
    done = {r["id"] for r in tsv(fn)} if os.path.exists(fn) and os.path.getsize(fn) > 0 else set()
    jobs = [(r["id"], r["path"], int(r["n"]) >= 0 and meta[int(r["n"])]["glang"] == "ja") for r in items if r["id"] not in done]
    print(f"measure: {len(items)} clips, {len(jobs)} to measure", flush=True)
    o = open(fn, "a", encoding="utf-8")
    if not done:
        o.write("id\tstatus\t" + "\t".join(MCOLS) + "\n")
    fm = lambda v: f"{v:.4f}" if isinstance(v, float) else ("" if v is None else str(v).replace("\t", " "))
    with Pool(a.jobs, initializer=_init_measure, initargs=(True,)) as pool:
        for k, (fid, d, err) in enumerate(pool.imap_unordered(_measure_one, jobs, chunksize=4)):
            if d is None:
                o.write(f"{fid}\tFAILED {err}" + "\t" * len(MCOLS) + "\n")
            else:
                o.write(f"{fid}\tok\t" + "\t".join(fm(d.get(c)) for c in MCOLS) + "\n")
            o.flush()
            if k % 500 == 0:
                print("measure", k, len(jobs), flush=True)
    o.close()
    print("MEASURE-DONE")


# ------------------------------------------------------------------------------------------------------ embed
def cmd_embed(a):
    import numpy as np
    sys.path.insert(0, "/w/range/scripts")
    import measure as M
    emb = M.Embedder(a.device)
    fn = f"{a.out}/emb.npz"
    have = {}
    if os.path.exists(fn):
        z = np.load(fn); have = {str(i): e for i, e in zip(z["ids"], z["emb"])}
    todo = [(k, v) for k, v in REFS.items() if k not in have]
    todo += [(r["id"], r["path"]) for r in tsv(f"{a.out}/items.tsv") if r["id"] not in have]
    print("embed:", len(have), "done,", len(todo), "to do", flush=True)
    for k, (fid, p) in enumerate(todo):
        x, sr = M.load(p)
        if len(x) < sr // 2:
            x = np.pad(x, (0, sr // 2 - len(x)))
        have[fid] = emb(x, sr)
        if k % 1000 == 0 and k:
            print("embed", k, len(todo), flush=True)
            np.savez(fn + ".tmp.npz", ids=np.array(list(have.keys())), emb=np.stack(list(have.values())))
            os.replace(fn + ".tmp.npz", fn)
    np.savez(fn + ".tmp.npz", ids=np.array(list(have.keys())), emb=np.stack(list(have.values())))
    os.replace(fn + ".tmp.npz", fn)
    print("EMBED-DONE", len(have))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["lines", "sets", "items", "asr", "wer", "measure", "embed"])
    ap.add_argument("--out", default="/w/range_build/styles/eval")
    ap.add_argument("--lines", default="/w/range_build/styles/score/lines.tsv")
    ap.add_argument("--per-set", type=int, default=200)
    ap.add_argument("--ds", default="/w/range_build/styles/ds")
    ap.add_argument("--shard", default="0/1")
    ap.add_argument("--only", default="")
    ap.add_argument("--model", default="/w/models_local/faster-whisper-large-v3")
    ap.add_argument("--jobs", type=int, default=48)
    ap.add_argument("--device", default="cuda")
    a = ap.parse_args()
    globals()["cmd_" + a.cmd](a)


if __name__ == "__main__":
    main()
