"""Gate and pick short vocal noises (round 2 of the sound bank: her own noises), and write them beside round 1.

Every take must pass, in this order (the first failed check is written to select_r2.tsv). The numbers come from
noise_measure.py, the AudioSet tagger (round 1's snd_tag.py), whisper and the ReazonSpeech kana recogniser, and
for clicks noise_clicks.py. GATE below holds each noise's own shape; it was fixed after the pilot and before the
full batch, and is not loosened afterwards.
  clip     no sample at full scale, peak under -0.3 dBFS
  adult    with 60 ms or more of clearly voiced frames: median f0 <= 345 Hz and 90th percentile <= 500 Hz; the
           tagger's child classes <= 0.06 and baby laughter <= 0.05 (her own clips score at most 0.052)
  leak     neither recogniser hears the first word of the line it was cut from (kind L)
  heard    the recognisers hear THIS noise: one of them hears its pattern (HEARD), and they do not hear a word (3
           or more kana that are not the noise's own from one of them, or 2 or more from both); whisper's sign-off
           hallucinations count as nothing heard
  tagger   no cough, sneeze, throat clearing, crying or scream over the breath and laugh classes; the first guess is
           not a body noise or an animal at 0.10 or more ("fart": 0.30, as the tagger hears a short nasal buzz as one;
           a pfft or a click may lead with "burst, pop", "slap, smack" or "snort", and a pfft with a throat clearing
           under 0.25, as AudioSet has no lip-burst or tongue-click class); per noise: a cackle has laughter as its first guess (and over every
           breath / noise class), a haa is a breath out (sigh or breathing >= 0.30, first guess a breath class,
           sigh over gasp), a bark is not an in-breath (no gasp-led first guess at 0.25 or more), pfft / heh /
           click are not speech (speech < 0.5), and the hums, yeahs, hee and hah are not a moan (< 0.3) nor a laugh
           (laughter < 0.25)
  level    it has a level (over -70 LUFS)
  edge     clean onset and offset: the raw take is at least 25 dB under the noise's loud level where the cut
           starts, and the cut is 20 dB under it just before its fade (clicks: their own checks instead)
  shape    the noise's own shape (GATE): length (onset to offset at -45 dB, its breath kept), voicing, pulses,
           pitch contour, mouth (closed: F1 and the low-band share; her speech: F1 median 547 Hz, p75 638, low_db
           +5; her hums from round 1: F1 238-278, low_db +17..+23), burst (attack, core), the laugh's breathy tail;
           a WHISPER has no voice (voiced share <= 0.3, HNR <= 8 dB) and skips the checks that need a voice
  timbre   sim_her (WavLM to her 4 clean clips) at least the noise's floor (SIM_FLOOR; compare within a noise only)
Kept: per noise and style, best first by sim_her + 0.25 x the tagger's score for the noise's class (laughter for
cackle and bark, sigh for haa), a tight cut 0.05 lower; at most 2 takes of one job (3 if fewer than 6 would be kept
otherwise), at most 8 per cell, and a take made twice (two rounds that repeat a job's text, reference and seed give
the same raw audio) only once. A whispered copy made by signal processing (kind W) ranks under every model take.

Writing: <bank>/<noise>/<style>/take_NN.wav (22050 Hz mono PCM 16; round 1's finalize: resampled, trimmed again at
the final rate, peak under -1 dBFS, a take under -45 LUFS raised to -40 LUFS) and <bank>/sounds.json: round 1's
entries are kept as they are; this round's noises are (re)written with round 1's fields plus contour, mouth, burst,
gate and round. Only this round's noise folders are written; round 1's folders are never touched.

Usage (gsv env): python noise_gate.py <build dir> <tags, e.g. "p 1 1b"> <bank dir> [--dry]
  reads <build dir>/{cuts,measure,tag}_<tag>.tsv, asr_<tag>.jsonl, clicks_<tag>.tsv, meta_all.tsv
  --dry: verdicts only (select_r2.tsv and a summary), nothing written to the bank
"""
import csv, hashlib, json, math, os, re, shutil, sys
from collections import defaultdict, Counter
import numpy as np, soundfile as sf, librosa, parselmouth
import pyopenjtalk
sys.path.insert(0, "/w/range/scripts")
from measure import k_loudness

B, TAGS, BANK = sys.argv[1], sys.argv[2].split(), sys.argv[3]
DRY = "--dry" in sys.argv
SR = 22050
ORDER = ["fuun", "un", "unun", "hee", "hah", "hah_snap", "pfft", "heh", "bark", "cackle", "mm", "mmm", "haa", "click"]
STYLES = ["normal", "soft", "whisper", "loud"]
PUNCT = re.compile(r"[\s、。？！?!〜ー…・,.’'「」『』()（）\-♪~]")
HALLU = ("視聴", "ありがとう", "チャンネル", "おやすみ", "字幕", "エンディング", "次回予告", "おわり", "それではまた", "最後まで")
OWN = {  # the kana each noise may be heard as
    "fuun": "フウンム", "un": "ウンム", "unun": "ウンム", "hee": "ヘエェイ", "hah": "ハァア", "hah_snap": "ハァア",
    "pfft": "プッフブゥ", "heh": "ヘッフエ", "bark": "ハッフアヘ", "cackle": "アハッヒィヘエァャギウ",
    "mm": "ンウム", "mmm": "ンウム", "haa": "ハァアフゥ", "click": "チッツクト",
}
# one recogniser must hear the noise's pattern (on the katakana reading, long marks removed)
HEARD = {
    "fuun": r"^フウ*ン+$", "un": r"^ウ?ン$|^ウム$", "unun": r"^ウ?ンウ?ン$", "hee": r"^ヘ[エェイ]*ッ?$",
    "hah": r"^ハ[アァ]*ッ?$", "hah_snap": r"^ハ[アァ]*ッ?$", "pfft": r"^[プブ]ッ?(フ?ッ?)$", "heh": r"^[ヘフ]ッ?$",
    "bark": r"^フ?ハッ?(ハッ?)?$", "cackle": r"ハ.*ハ.*ハ", "mm": r"^ウ?ン+$|^ム+$|^ウム$", "mmm": r"^ウ?ン+$|^ム+$",
    "haa": r"^[ハア][アァ]*ッ?$", "click": r"^$|^[チツクト]ッ?$",
}
NOT_FIRST = {  # neither recogniser may hear the noise as one of these (first kana): another noise
    "hee": "ハアフウ", "hah": "ヘフウ", "hah_snap": "ヘフウ", "haa": "", "un": "フ", "mm": "フ", "mmm": "フ",
}
SIM_FLOOR = {"fuun": 0.45, "un": 0.45, "unun": 0.45, "hee": 0.50, "hah": 0.45, "hah_snap": 0.45, "pfft": 0.30,
             "heh": 0.30, "bark": 0.40, "cackle": 0.50, "mm": 0.45, "mmm": 0.45, "haa": 0.40, "click": None}
# the noise's own shape: len (active s), voiced share, pulses, contour (semitones), mouth, burst
GATE = {
    "fuun": dict(len=(0.5, 1.4), voiced_min=0.7, net=(-4.0, 1.5), rise_max=3.0, f1_max=400, low_min=10.0),
    "un": dict(len=(0.15, 0.8), voiced_min=0.7, bursts=(1, 1), net=(None, 2.0), f1_max=420, low_min=8.0),
    "unun": dict(len=(0.4, 1.8), voiced_min=0.6, bursts=(2, 2), net=(None, 2.0), f1_max=420, low_min=8.0),
    "hee": dict(len=(0.4, 1.6), voiced_min=0.6, rise_min=2.0, peak_pos_min=0.2, f1_min=400),
    "hah": dict(len=(0.2, 1.2), voiced_min=0.4, rise_min=3.0, net=(2.0, None), f0_start_max=240, f1_max=700),
    "hah_snap": dict(len=(0.2, 1.2), voiced_min=0.4, rise_min=3.0, net=(2.0, None), f0_start_max=260),
    "pfft": dict(len=(0.08, 0.6), voiced_max=0.35, attack_max=40, core_max=0.15),
    "heh": dict(len=(0.1, 0.6), bursts=(1, 1), attack_max=60, core_max=0.20),
    "bark": dict(len=(0.15, 0.8), voiced_min=0.3, bursts=(1, 3), attack_max=60),
    "cackle": dict(len=(1.0, 3.6), voiced_min=0.4, bursts=(5, None), wheeze=True),
    "mm": dict(len=(0.2, 0.9), voiced_min=0.8, bursts=(1, 1), net=(-4.0, 2.0), f1_max=330, low_min=13.0),
    "mmm": dict(len=(0.7, 2.2), voiced_min=0.8, net=(None, 2.0), f1_max=350, low_min=12.0, f0_med_max=245),
    "haa": dict(len=(0.8, 2.5), voiced_max=0.85, net=(None, 1.0)),
    "click": dict(voiced_max=0.10, width_max=16, dry_min=20, iso_min=15, floor_min=30),
}
GATE_TEXT = {
    "fuun": "heard as ふーん/ふん; 0.5-1.4 s; voiced >= 0.7; flat or slightly falling (net -4..+1.5 st, rise <= 3 st); closed mouth (F1 <= 400 Hz, low band >= +10 dB)",
    "un": "heard as うん/ん; 0.15-0.8 s; one pulse; voiced >= 0.7; no question rise (net <= +2 st); closed or nearly closed (F1 <= 420 Hz, low band >= +8 dB)",
    "unun": "heard as うんうん; 0.4-1.8 s; two pulses; voiced >= 0.6; net <= +2 st; closed or nearly closed (F1 <= 420 Hz, low band >= +8 dB)",
    "hee": "heard as へぇ (never as は/あ/ふ/う); 0.4-1.6 s; voiced >= 0.6; rises at least 2 st, its peak after the first fifth; an e (F1 >= 400 Hz, not a hum)",
    "hah": "heard as はぁ (never as へ/ふ/う); 0.2-1.2 s; voiced >= 0.4; rising (rise >= 3 st, ends >= 2 st over its start); starts low (<= 240 Hz, her speech median 242); mouth not wide open (F1 <= 700 Hz; her laughs' あ 570-706, her speech p90 778)",
    "hah_snap": "heard as はぁ; 0.2-1.2 s; voiced >= 0.4; rising (rise >= 3 st, net >= +2 st); starts at most 260 Hz; asked for loud",
    "pfft": "heard as ぷっ/ぶっ; 0.08-0.6 s; unvoiced (voiced <= 0.35); a burst (attack <= 40 ms, core <= 0.15 s); not speech",
    "heh": "heard as へっ/ふっ (one syllable, never as ふん or へへ by either recogniser); 0.1-0.6 s; one pulse; a burst (attack <= 60 ms, core <= 0.2 s); not speech",
    "bark": "heard as はっ/ははっ/ふはっ; 0.15-0.8 s; 1-3 pulses; voiced >= 0.3; burst onset (attack <= 60 ms); not a gasp (in-breath)",
    "cackle": "heard with 3+ は; 1.0-3.6 s; 5+ pulses; voiced >= 0.4; a breathy tail (last 30 %: voiced share 0.15 lower or 3 dB brighter than before); laughter is the tagger's first guess",
    "mm": "heard as ん/うん; 0.2-0.9 s; one pulse; voiced >= 0.8; net -4..+2 st; closed mouth (F1 <= 330 Hz, low band >= +13 dB)",
    "mmm": "heard as んー/うーん; 0.7-2.2 s; voiced >= 0.8; no question rise (net <= +2 st); closed mouth (F1 <= 350 Hz, low band >= +12 dB); low (median <= 245 Hz, her speech 242)",
    "haa": "heard as はぁ/ああ (whisper not ふぅ); 0.8-2.5 s; breathy (voiced <= 0.85); falls or stays (net <= +1 st); a breath out to the tagger (sigh >= 0.30, first guess a breath)",
    "click": "one dry transient: width <= 16 ms, nothing within 20 dB in the 50 ms after it, isolated by 15 dB over 150 ms, 30 dB over the floor; no voice; no word heard",
}
WHISPER_MAX_VOICED, WHISPER_MAX_HNR = 0.30, 8.0
CHILD_MAX, BABY_LAUGH_MAX = 0.06, 0.05
QUIET_LUFS, QUIET_TO = -45.0, -40.0
WAYS = {
    "B": "Irodori-TTS cloned from her 4 clean clips (emoji style marks)",
    "BS": "Irodori-TTS cloned from her quietest clip v12_040 alone",
    "BN": "Irodori-TTS cloned from her calm clip v12_071 alone",
    "BW": "Irodori-TTS cloned from her 4 clips whispered by whisperize.py",
    "BC": "Irodori-TTS cloned from her 4 clean clips, with a caption describing the delivery",
    "A": "her GPT-SoVITS teacher, one of her clips as reference",
    "AW": "her GPT-SoVITS teacher, a whispered copy of her clip as reference",
    "C": "her GPT-SoVITS teacher, a model take of the noise (+ her clip) as reference",
}
TEACHER = ("A", "AW", "C")
KIND = {"A": "sound alone", "L": "cut from a sound-led line", "K": "one click cut from a take",
        "W": "a kept take whispered by signal processing (whisperize.py)"}


def fnum(v):
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def reading(t):
    if not t or any(h in t for h in HALLU): return ""
    t = PUNCT.sub("", t)
    return PUNCT.sub("", pyopenjtalk.g2p(t, kana=True)) if t else ""


cuts, meas, tags, heard, clicks = {}, {}, {}, {}, {}
for tg in TAGS:
    for p, d in ((f"{B}/cuts_{tg}.tsv", cuts), (f"{B}/measure_{tg}.tsv", meas), (f"{B}/tag_{tg}.tsv", tags),
                 (f"{B}/clicks_{tg}.tsv", clicks)):
        if os.path.exists(p):
            for r in csv.DictReader(open(p, encoding="utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE):
                d[os.path.basename(r["file"])] = r
    if os.path.exists(f"{B}/asr_{tg}.jsonl"):
        for l in open(f"{B}/asr_{tg}.jsonl", encoding="utf-8"):
            r = json.loads(l); heard[os.path.basename(r["file"])] = r["text"]
post = {}
for l in open(f"{B}/meta_all.tsv", encoding="utf-8"):
    q = l.rstrip("\n").split("\t")
    if len(q) >= 6 and q[0] != "name": post[q[0]] = q[4]
rows = []
for b, c in cuts.items():
    if c["status"] not in ("ok", "tight", "alone") or b not in meas: continue
    if c["sound"] not in GATE: continue
    if c["sound"] == "click" and c["kind"] != "K": continue  # a click is one transient cut by noise_clicks.py
    r = meas[b]
    m = {k: fnum(v) for k, v in r.items() if k not in ("file", "kana")}
    m.update(file=r["file"], base=b, kana=r["kana"], whisper=heard.get(b),
             tag={k: (v if k == "top" else float(v)) for k, v in tags.get(b, {}).items() if k != "file"},
             click={k: fnum(v) for k, v in clicks.get(b, {}).items() if k != "file"},
             **{k: c[k] for k in ("sound", "style", "kind", "way", "name", "src", "from", "to", "status", "note")})
    rows.append(m)


def fam(m):
    t = m["tag"]; g = lambda *k: max(t.get(x, 0.0) for x in k)
    return dict(laugh=g("Laughter", "Giggle", "Snicker", "Chuckle", "Belly_laugh"),
                breath=g("Breathing", "Sigh", "Gasp", "Pant", "Sniff", "Wheeze", "Snort"),
                noise=g("Throat_clearing", "Sneeze", "Cough", "Hiccup"),
                bad=g("Cough", "Sneeze", "Crying", "Screaming", "Whimper", "Baby_cry", "Hiccup", "Throat_clearing"),
                cry=g("Whimper", "Crying", "Wail"), speech=t.get("Speech", 0.0), moan=t.get("Wail", 0.0),
                sigh=g("Sigh", "Breathing"), gasp=t.get("Gasp", 0.0), snort=t.get("Snort", 0.0))


IGNORE = {"Speech", "Female speech, woman speaking", "Male speech, man speaking", "Narration, monologue",
          "Conversation", "Sound effect", "Inside, small room", "Music", "Speech synthesizer", "Silence"}
LAUGHS = {"Laughter", "Giggle", "Snicker", "Chuckle, chortle", "Belly laugh"}
BREATHS = {"Breathing", "Sigh", "Gasp", "Pant", "Sniff", "Wheeze", "Snort"}
VOICE = {"Groan", "Grunt", "Humming", "Wail, moan", "Whimper", "Whispering", "Singing", "Female singing"}
CLICKY = {"Clicking", "Tick", "Tick-tock", "Finger snapping", "Tap"}
MOUTH = {"Burst, pop", "Slap, smack", "Snort"}  # a lip burst or a tongue click has no class of its own


def lead(m):
    for x in (m["tag"].get("top") or "").split(";"):
        if ":" not in x: continue
        lab, sc = x.rsplit(":", 1)
        if lab not in IGNORE: return lab, float(sc)
    return "", 0.0


def target(m):
    if not m["tag"]: return 0.0
    f = fam(m)
    return {"cackle": f["laugh"], "bark": f["laugh"] + f["snort"], "haa": f["sigh"]}.get(m["sound"], 0.0)


def child(m):
    t = m["tag"]
    if not t: return 0.0
    c = max(t.get(k, 0.0) for k in ("Child_speech", "Baby_laughter", "Baby_cry", "Children_shouting", "Babbling",
                                    "Child_singing", "Children_playing"))
    return max(c, CHILD_MAX + 0.001) if t.get("Baby_laughter", 0.0) > BABY_LAUGH_MAX and c <= CHILD_MAX else c


def tagger(m):
    s = m["sound"]
    if not m["tag"]: return "tagger (not tagged)"
    f = fam(m); lab, sc = lead(m)
    if f["bad"] >= 0.25 and f["bad"] > max(f["laugh"], f["breath"]):
        return f"tagger (cough, sneeze, throat, cry or scream {f['bad']:.2f})"
    ok_first = LAUGHS | BREATHS | VOICE | CLICKY | (MOUTH if s in ("pfft", "click") else set())
    if s == "pfft" and lab == "Throat clearing" and sc < 0.25: ok_first = ok_first | {lab}
    if sc >= (0.30 if lab == "Fart" else 0.10) and lab not in ok_first:
        return f"tagger (first guess: {lab} {sc:.2f})"
    if s == "cackle":
        other = max(f["breath"], f["noise"], f["cry"])
        if f["laugh"] < 0.05 or f["laugh"] < other or lab not in LAUGHS:
            return f"tagger (laughter {f['laugh']:.2f}, first guess {lab})"
    elif s == "haa":
        if f["sigh"] < 0.30 or lab not in BREATHS or m["tag"].get("Sigh", 0) < f["gasp"]:
            return f"tagger (not a breath out: sigh {f['sigh']:.2f}, gasp {f['gasp']:.2f}, first {lab})"
    elif s == "bark":
        if lab == "Gasp" and sc >= 0.25:
            return f"tagger (an in-breath: gasp {sc:.2f})"
    elif s in ("pfft", "heh", "click"):
        if f["speech"] >= 0.5:
            return f"tagger (speech {f['speech']:.2f})"
    if s in ("fuun", "un", "unun", "mm", "mmm", "hee", "hah", "hah_snap", "haa"):
        if f["moan"] >= 0.3: return f"tagger (a moan {f['moan']:.2f})"
        if f["laugh"] >= 0.25: return f"tagger (laughter {f['laugh']:.2f})"
    return ""


def edge(m):
    x, sr = sf.read(m["file"], dtype="float32")
    if x.ndim > 1: x = x.mean(axis=1)
    fr = int(0.01 * sr); n = len(x) // fr
    if n < 12: return ""
    lv = 20 * np.log10(np.sqrt(np.mean(x[:n * fr].reshape(n, fr).astype(np.float64) ** 2, axis=1)) + 1e-9)
    top = np.percentile(lv, 98)
    y, sr2 = sf.read(m["src"], dtype="float32")
    if y.ndim > 1: y = y.mean(axis=1)
    a = int((fnum(m["from"]) or 0.0) * sr2); f0 = y[a:a + int(0.01 * sr2)].astype(np.float64)
    if len(f0) and 20 * np.log10(np.sqrt(np.mean(f0 ** 2)) + 1e-9) > top - 25: return "edge (start)"
    if lv[-8:-6].max() > top - 20: return "edge (end)"
    return ""


def heard_check(m):
    s = m["sound"]; wt = m["whisper"] or ""
    wr, kr = reading(wt), reading(m["kana"])
    if m["kind"] == "L":
        pr = reading(post.get(m["name"], "")); key = pr[:2] if len(pr) >= 2 else pr
        if key and (key in wr or key in kr): return f"leak ({key})"
    foreign = lambda r: sum(ch not in OWN[s] for ch in r)
    if max(foreign(wr), foreign(kr)) >= 3 or min(foreign(wr), foreign(kr)) >= 2:
        return f"heard a word ({wt} | {m['kana']})"
    pat = re.compile(HEARD[s])
    if s == "click":
        if not all(pat.search(r) for r in (wr, kr)): return f"heard ({wt} | {m['kana']})"
    elif not any(r and pat.search(r) for r in (wr, kr)):
        return f"heard ({wt} | {m['kana']})"
    nf = NOT_FIRST.get(s, "")
    if nf and any(r and r[0] in nf for r in (wr, kr)): return f"heard as another noise ({wt} | {m['kana']})"
    if s == "haa" and wr[:1] == "フ": return f"heard as an exhale ({wt})"
    if s == "un" and any(r.count("ン") >= 2 for r in (wr, kr)): return f"heard twice ({wt} | {m['kana']})"
    if s == "heh" and any(r and ("ン" in r or len(r.replace("ッ", "")) >= 2) for r in (wr, kr)):
        return f"heard as a hmph or a giggle ({wt} | {m['kana']})"
    return ""


def shape(m):
    s, g = m["sound"], GATE[m["sound"]]
    wh = m["style"] == "whisper"
    if s == "click":
        c = m["click"] or {}
        if (m["voiced"] or 0) > g["voiced_max"]: return f"shape (voiced {m['voiced']:.2f})"
        if not c or c["width_ms"] > g["width_max"] or c["dry_db"] < g["dry_min"] or c["iso_db"] < g["iso_min"] or c["floor_db"] < g["floor_min"]:
            return f"shape (click {c})"
        return ""
    a = m["active_s"]; lo, hi = g["len"]
    if not (lo <= a <= hi): return f"shape (length {a:.2f})"
    v = m["voiced"] or 0.0
    if wh:
        if v > WHISPER_MAX_VOICED: return f"shape (a whisper with voice: voiced {v:.2f})"
        if m["hnr"] is not None and m["hnr"] > WHISPER_MAX_HNR: return f"shape (a whisper with voice: HNR {m['hnr']:.1f})"
    else:
        if "voiced_min" in g and v < g["voiced_min"]: return f"shape (voiced {v:.2f})"
    if "voiced_max" in g and v > g["voiced_max"]: return f"shape (voiced {v:.2f})"
    if "bursts" in g:
        bl, bh = g["bursts"]; bu = m["bursts"] or 0
        if bu < bl or (bh is not None and bu > bh): return f"shape (pulses {bu:.0f})"
    if "attack_max" in g and (m["attack_ms"] or 0) > g["attack_max"]: return f"shape (attack {m['attack_ms']:.0f} ms)"
    if "core_max" in g and (m["core_s"] or 0) > g["core_max"]: return f"shape (core {m['core_s']:.2f} s)"
    if g.get("wheeze"):
        hv, tv, hh, th = m["head_voiced"], m["tail_voiced"], m["head_hf"], m["tail_hf"]
        ok = (hv is not None and tv is not None and tv <= hv - 0.15) or (hh is not None and th is not None and th >= hh + 3)
        if not ok: return "shape (no breathy tail)"
    if wh: return ""  # the checks below need a voice
    need = lambda k: m.get(k) is not None
    if "net" in g:
        if not need("net_st"): return "shape (no pitch contour)"
        nl, nh = g["net"]
        if (nl is not None and m["net_st"] < nl) or (nh is not None and m["net_st"] > nh): return f"shape (contour net {m['net_st']:+.1f} st)"
    if "rise_max" in g and need("rise_st") and m["rise_st"] > g["rise_max"]: return f"shape (contour rises {m['rise_st']:.1f} st)"
    if "rise_min" in g:
        if not need("rise_st") or m["rise_st"] < g["rise_min"]: return f"shape (contour does not rise: {m.get('rise_st')})"
    if "peak_pos_min" in g and (m["peak_pos"] or 0) < g["peak_pos_min"]: return f"shape (peak at {m['peak_pos']:.2f})"
    if "f0_start_max" in g and need("f0_start") and m["f0_start"] > g["f0_start_max"]: return f"shape (starts high: {m['f0_start']:.0f} Hz)"
    if "f0_med_max" in g and need("f0_med") and m["f0_med"] > g["f0_med_max"]: return f"shape (not low: {m['f0_med']:.0f} Hz)"
    if "f1_max" in g:
        if not need("f1_med") or m["f1_med"] > g["f1_max"]: return f"shape (mouth open: F1 {m.get('f1_med')})"
    if "f1_min" in g and need("f1_med") and m["f1_med"] < g["f1_min"]: return f"shape (a hum, not a vowel: F1 {m['f1_med']:.0f})"
    if "low_min" in g:
        if not need("low_db") or m["low_db"] < g["low_min"]: return f"shape (mouth open: low band {m.get('low_db')})"
    return ""


def check(m):
    s = m["sound"]
    if (m["n_clip"] or 0) > 0 or (m["peak_db"] or 0) > -0.3: return "clip"
    if m["f0_med"] is not None and (m["f0_med"] > 345 or (m["f0_p90"] or 0) > 500):
        return f"adult (f0 {m['f0_med']:.0f}/{m['f0_p90']:.0f})"
    if child(m) > CHILD_MAX: return f"adult (tagger: child class {child(m):.2f})"
    if m["whisper"] is None: return "not heard by whisper"
    h = heard_check(m)
    if h: return h
    t = tagger(m)
    if t: return t
    lu = m["lufs"] if m["lufs"] is not None else m["lufs_rms"]
    if lu is None or lu < -70: return "level"
    if m["kind"] not in ("K", "W"):
        e = edge(m)
        if e: return e
    sh = shape(m)
    if sh: return sh
    fl = SIM_FLOOR[s]
    if fl is not None and (m["sim_her"] is None or m["sim_her"] < fl): return f"timbre ({m['sim_her']})"
    return "pass"


def rank(m):
    return (m["sim_her"] or 0.0) + 0.25 * min(target(m), 0.6) - (0.05 if m["status"] == "tight" else 0) - (1.0 if m["kind"] == "W" else 0)


for m in rows:
    m["verdict"] = check(m)
groups = defaultdict(list)
for m in rows: groups[(m["sound"], m["style"])].append(m)
f3 = lambda v: f"{v:.3f}" if v is not None else ""
with open(f"{B}/select_r2.tsv", "w", encoding="utf-8") as o:
    cols = ["active_s", "voiced", "f0_med", "net_st", "rise_st", "f1_med", "low_db", "attack_ms", "bursts", "sim_her"]
    o.write("sound\tstyle\tfile\tway\tname\tverdict\t" + "\t".join(cols) + "\twhisper\tkana\ttagger\n")
    for k in sorted(groups, key=lambda k: (ORDER.index(k[0]), STYLES.index(k[1]))):
        for m in sorted(groups[k], key=lambda m: (m["verdict"] != "pass", -(m["sim_her"] or 0))):
            o.write("\t".join([m["sound"], m["style"], m["base"], m["way"], m["name"], m["verdict"]] + [f3(m.get(c)) for c in cols]
                              + [m["whisper"] or "", m["kana"], m["tag"].get("top", "")]) + "\n")
for k in sorted(groups, key=lambda k: (ORDER.index(k[0]), STYLES.index(k[1]))):
    c = Counter(m["verdict"].split(" (")[0] for m in groups[k])
    print(f"{k[0]:8s} {k[1]:8s} pass {c.get('pass', 0):3d} of {len(groups[k]):3d} | " + " ".join(f"{v} {n}" for v, n in c.most_common() if v != "pass"))
if DRY:
    sys.exit(0)


def finalize(x, sr, tight=False):
    y = librosa.resample(x.astype(np.float32), orig_sr=sr, target_sr=SR, res_type="soxr_hq") if sr != SR else x.astype(np.float32)
    pk = np.max(np.abs(y)) + 1e-9
    if pk > 10 ** (-1 / 20): y = y * (10 ** (-1 / 20) / pk)
    if tight: return y
    fr = int(0.01 * SR); n = max(1, len(y) // fr)
    lv = 20 * np.log10(np.sqrt(np.mean(y[:n * fr].reshape(n, fr).astype(np.float64) ** 2, axis=1)) + 1e-9)
    act = np.where(lv >= np.percentile(lv, 98) - 45)[0]
    if len(act):
        a = int((act[0] / 100 - 0.15) * SR); b = int(((act[-1] + 1) / 100 + 0.25) * SR)
        if b < len(y) - int(0.03 * SR):
            y = y[:b].copy(); ko = min(len(y) // 2, int(0.06 * SR)); y[-ko:] *= np.linspace(1, 0, ko) ** 2
        if a > int(0.03 * SR):
            y = y[a:].copy(); k = min(len(y) // 2, int(0.015 * SR)); y[:k] *= np.linspace(0, 1, k)
    return y


def final_measure(y):
    fr = int(0.01 * SR); n = max(1, len(y) // fr)
    lv = 20 * np.log10(np.sqrt(np.mean(y[:n * fr].reshape(n, fr).astype(np.float64) ** 2, axis=1)) + 1e-9)
    top = np.percentile(lv, 98); act = np.where(lv >= top - 45)[0]
    on, off = (act[0] / 100, (act[-1] + 1) / 100) if len(act) else (0.0, len(y) / SR)
    a30 = lv >= top - 30
    pt = parselmouth.Sound(y.astype(np.float64), sampling_frequency=SR).to_pitch_ac(time_step=0.01, pitch_floor=75, pitch_ceiling=900)
    f0 = pt.selected_array["frequency"]; idx = np.clip((pt.xs() * 100).astype(int), 0, len(lv) - 1)
    vf = f0[(f0 > 0) & a30[idx]]
    lu = k_loudness(y.astype(np.float64), SR)
    if not np.isfinite(lu): lu = 20 * np.log10(np.sqrt(np.mean(y.astype(np.float64) ** 2)) + 1e-9) - 0.7
    return dict(duration_s=round(len(y) / SR, 3), f0_median_hz=round(float(np.median(vf)), 1) if len(vf) >= 6 else None,
                f0_p90_hz=round(float(np.percentile(vf, 90)), 1) if len(vf) >= 6 else None,
                lufs=round(lu, 1), onset_s=round(on, 3), offset_s=round(off, 3),
                peak_dbfs=round(float(20 * np.log10(np.max(np.abs(y)) + 1e-9)), 1))


def src_hash(m):
    """The raw take's content: rounds that reuse a job's text, reference and seed make the very same take again
    (the seed is the round's seed + 101 x the job index), so a copy is known by its raw audio, not its name."""
    if "hash" not in m:
        h = hashlib.sha1(open(m["src"], "rb").read()).hexdigest()
        m["hash"] = h if m["kind"] != "W" else "W" + h
    return m["hash"]


def pick(ms, per_job):
    kept, n, seen = [], defaultdict(int), set()
    for m in sorted(ms, key=lambda m: -rank(m)):
        if len(kept) >= 8: break
        k = (m["way"], m["name"]); h = src_hash(m)
        if h in seen:
            m["dup"] = True; continue  # the same take made again by another round: kept once
        if n[k] < per_job:
            kept.append(m); n[k] += 1; seen.add(h)
    return kept


r2 = lambda v, d=3: round(v, d) if v is not None else None
jp = os.path.join(BANK, "sounds.json")
bank = json.load(open(jp, encoding="utf-8"))
for s in ORDER: bank["sounds"].pop(s, None)  # this round's noises are rewritten; round 1's entries stay as they are
for s in ORDER:
    d = os.path.join(BANK, s)
    if os.path.isdir(d): shutil.rmtree(d)
gate_json = {s: GATE_TEXT[s] for s in ORDER}
for (s, st) in sorted(groups, key=lambda k: (ORDER.index(k[0]), STYLES.index(k[1]))):
    ok = [m for m in groups[(s, st)] if m["verdict"] == "pass"]
    for m in ok:
        x, sr = sf.read(m["file"], dtype="float32")
        if x.ndim > 1: x = x.mean(axis=1)
        m["y"] = finalize(x, sr, tight=m["kind"] == "K"); m["fm"] = final_measure(m["y"]); m["gain"] = 0.0
        lu = m["fm"]["lufs"]
        if lu is not None and lu < QUIET_LUFS:
            hr = -1.0 - 20 * np.log10(np.max(np.abs(m["y"])) + 1e-9)
            m["gain"] = round(max(0.0, min(QUIET_TO - lu, hr)), 1)
            m["y"] = m["y"] * 10 ** (m["gain"] / 20); m["fm"] = final_measure(m["y"])
        if m["fm"]["f0_median_hz"] is not None and (m["fm"]["f0_median_hz"] > 345 or m["fm"]["f0_p90_hz"] > 500):
            m["verdict"] = "adult in the final file"
    ok = [m for m in ok if m["verdict"] == "pass"]
    kept = pick(ok, 2)
    if len(kept) < 6: kept = pick(ok, 3)
    if not kept: continue
    d = os.path.join(BANK, s, st); os.makedirs(d, exist_ok=True)
    takes = []
    for k, m in enumerate(kept, 1):
        fm = dict(m["fm"]); fm.pop("f0_p90_hz")
        fn = f"take_{k:02d}.wav"
        sf.write(os.path.join(d, fn), m["y"], SR, subtype="PCM_16")
        wt = m["whisper"] or ""
        takes.append(dict(file=f"{s}/{st}/{fn}", style=st, **fm, gain_db=m["gain"],
                          source=dict(type="synthetic", way=m["way"], how=WAYS[m["way"]], job=m["name"], kind=KIND[m["kind"]],
                                      take=os.path.basename(m["src"]), cut_from_s=fnum(m["from"]), cut_to_s=fnum(m["to"]),
                                      deepfilternet_atten_db=6 if m["way"] in TEACHER else None, asked_for=s,
                                      note=m["note"] if m["kind"] in ("K", "W") else ""),
                          sim_her=r2(m["sim_her"]), sim_her_intakes=None, envelope_her_intakes=None,
                          voiced_share=r2(m["voiced"], 2), hnr_db=r2(m["hnr"], 1),
                          heard=(wt if wt and not any(h in wt for h in HALLU) else m["kana"]) or "",
                          tagger=m["tag"].get("top", ""),
                          contour=dict(f0_start_hz=r2(m["f0_start"], 1), f0_end_hz=r2(m["f0_end"], 1), rise_st=r2(m["rise_st"], 2),
                                       fall_st=r2(m["fall_st"], 2), net_st=r2(m["net_st"], 2), slope_st_per_s=r2(m["slope_st_s"], 2),
                                       peak_pos=r2(m["peak_pos"], 2)),
                          mouth=dict(f1_hz=r2(m["f1_med"], 0), f2_hz=r2(m["f2_med"], 0), low_band_db=r2(m["low_db"], 1),
                                     hf_voiced_db=r2(m["hf_v"], 1), hf_db=r2(m["hf_db"], 1)),
                          burst=dict(attack_ms=r2(m["attack_ms"], 0), core_s=r2(m["core_s"], 2), pulses=int(m["bursts"] or 0),
                                     head_voiced=r2(m["head_voiced"], 2), tail_voiced=r2(m["tail_voiced"], 2),
                                     head_hf_db=r2(m["head_hf"], 1), tail_hf_db=r2(m["tail_hf"], 1)),
                          click=({k2: v2 for k2, v2 in m["click"].items()} if m["kind"] == "K" else None),
                          gate=dict(round=2, noise=s, shape=GATE_TEXT[s], passed=["clip", "adult", "leak", "heard", "tagger", "level",
                                    "edge" if m["kind"] not in ("K", "W") else "click", "shape", "timbre"],
                                    sim_floor=SIM_FLOOR[s], whisper=(st == "whisper")),
                          round=2))
    bank["sounds"].setdefault(s, {})[st] = takes
bank.setdefault("round2", {})["gates"] = gate_json
json.dump(bank, open(jp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for s in ORDER:
    for st in STYLES:
        t = bank["sounds"].get(s, {}).get(st)
        if t: print(f"{s:8s} {st:8s} {len(t)} kept")
