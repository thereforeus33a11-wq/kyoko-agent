"""Gate and pick short vocal noises, round 3 of the sound bank (her two laughs, the thin cells, the whispers), and
write the kept takes beside rounds 1 and 2 without changing a file of theirs.

Round 3 closes the gaps an independent check found in round 2's gate (noise_gate.py): a limit on the size and the
end of hah's rise; a closed mouth through the nose for bark_nose, heh, fuun, un, unun, mm, mmm; the fall after the
rise of hee_slide; for the cackle a laugh that is not a giggle and that goes from voice to breath; both edges of every
cut against the raw line; the level (effort) by style; pitch by two trackers. Every take must pass, in this order
(the first failed check is written to select_r3.tsv):
  clip      no sample at full scale, peak under -0.3 dBFS
  adult     pitch by Praat AND by pyin, on each tracker's clearly voiced body frames (voiced to it and HNR >= 6 dB;
            breath noise has no pitch, though Praat reports 400-880 Hz in her real breaths and her whisper set):
            when either has 60 ms or more, its median <= 345 Hz and 90th percentile <= 500 Hz; high for her (the
            check's rule): not (Praat's highest clear point over 400 Hz with pyin's p90 at least 360 Hz) and not both
            p90 over 400 Hz; the low noises (fuun, un, unun, mm, mmm, bark_nose, heh) and the laughs at most 367 Hz
            p90 by both (the highest p90 of her own 4 clips). The tagger's child classes <= 0.06, baby laughter <= 0.05.
  heard     as round 2: one recogniser hears the noise's pattern (HEARD), neither hears a word or another noise;
            plus round 3's patterns (bark_nose: one or two nasal pulses, never a へ; heh: one ふっ / へっ)
  edges     the kana recogniser on the take's first and last 150 ms hears nothing of the line's next word (its
            first kana, or its first two), no word (3+ kana not the noise's own) and, for heh, no second pulse; on
            150 ms of near-silence it writes あれ / え / はい / どう, which is read as nothing
  tagger    round 2's rules; cackle: the first laugh class is not Giggle, Giggle <= 0.7 x the other laugh classes,
            laughter over every noise class and at least 0.6 x the breath classes; bark_nose: not a giggle
            (giggle <= 0.10, not first), not speech, not an in-breath (gasp-led 0.25+ needs voiced >= 0.6; AudioSet has no nose-laugh class)
  level     over -70 LUFS
  edge      against the raw line, at both ends: the raw take 25 dB under the noise's loud level in the 30 ms before the
            cut and in the 30 ms after it, nothing at the loud level - 25 dB within EDGE_GAP s before the noise's
            onset or after its end (-45 dB) in the raw (for a cut from a line: the next word starts at least EDGE_GAP
            s after the noise has died away), and the cut 20 dB under the loud level just before its fade-out
            (processed takes: their own first and last 20 ms 30 dB under the loud level)
  shape     the noise's own shape (GATE): length, voicing, pulses, contour (hah: a rise of 3 to RISE_MAX_HAH st that
            ends at or under 300 Hz; hee_slide: a rise of 2+ st, its peak inside, then a fall of FALL_MIN st+),
            mouth (closed, through the nose: F1 and the low band against her open vowels), burst, the cackle's
            course (voiced chest pulses that break into breath: voicing, HNR fall and breath noise rises from the
            first third to the last), low pitch for bark_nose and the cackle; a WHISPER (her whisper set: pyin
            voiced share p90 0.3, HNR 1.8-4.5 dB) has pyin voiced <= 0.30, median HNR <= 5.0 dB, tonal share
            (hr_share) <= 0.05 and under 60 ms of clear voice by either tracker, and skips the checks that need a voice
  style     effort by style (spectral tilt, 80-1000 Hz against 1000-4000 Hz over the body: higher = darker, less
            effort): a soft take is no brighter than the median of the noise's normal cell in the bank (or of this
            round's normal candidates that pass every other check when the bank has none); a loud take is at least
            LOUD_DB brighter than its reference (the cackle: her normal laughs of round 1)
  natural   a take made by signal processing (kind P): jitter, shimmer and spectral flatness inside her own takes'
            range for the noise (REF_NAT: min - 20 % .. max + 20 % of the reference cells' takes; a whisper: the
            40 takes of her whisper set measured in the calibration); the cackle's wheeze (its last third) as bright
            as her 4 real breaths or her whispers (energy over 4 kHz inside their range +- 20 %), not a hiss
  timbre    sim_her (WavLM to her 4 clean clips) at least the noise's floor (SIM_FLOOR; whispers WHISPER_SIM_FLOOR)
  copy      not the same raw take as one already kept (sha1 of the raw audio), not a near copy of a bank take of the
            same noise (normalised cross-correlation of the final audio >= 0.9)
Kept per cell: best first by sim_her + 0.25 x the tagger's score for the noise's class, a tight cut 0.05 lower, a
processed take 0.5 lower; at most 2 takes of one job (3 if fewer than 6 would be kept), one processed take per
source take, and the cell's takes from earlier rounds count towards its 8.

Writing: <bank>/<noise>/<style>/take_NN.wav, NN after the cell's last take (22050 Hz mono PCM 16, round 2's
finalize); sounds.json: earlier rounds' entries kept as they are, round-3 takes appended with round=3, how each was
made, its gate and numbers; bank["round3"]["gates"] holds the gate text.

Usage (gsv env): python noise_gate_r3.py <build dir> <tags> <bank dir> [--dry] [--calib <calib dir>]
  reads <build dir>/{cuts,measure,extra,tag}_<tag>.tsv, asr_<tag>.jsonl, meta_all.tsv, and <calib dir>/{measure,
  extra}.tsv (the bank's own takes measured with the same code: the style and natural references)
"""
import csv, glob, hashlib, json, math, os, re, sys
from collections import defaultdict, Counter
import numpy as np, soundfile as sf, librosa, parselmouth
import pyopenjtalk
sys.path.insert(0, "/w/range/scripts")
from measure import k_loudness

B, TAGS, BANK = sys.argv[1], sys.argv[2].split(), sys.argv[3]
DRY = "--dry" in sys.argv
CAL = sys.argv[sys.argv.index("--calib") + 1] if "--calib" in sys.argv else f"{B}/calib"
SR = 22050
ORDER = ["bark_nose", "cackle", "hah", "pfft", "heh", "haa", "hee_slide", "hee", "un", "mm", "fuun", "unun", "mmm", "bark"]
STYLES = ["normal", "soft", "whisper", "loud"]
PUNCT = re.compile(r"[\s、。？！?!〜ー…・,.’'「」『』()（）\-♪~]")
HALLU = ("視聴", "ありがとう", "チャンネル", "おやすみ", "字幕", "エンディング", "次回予告", "おわり", "それではまた", "最後まで")
OWN = {
    "fuun": "フウンム", "un": "ウンム", "unun": "ウンム", "hee": "ヘエェイ", "hee_slide": "ヘエェイ", "hah": "ハァア",
    "pfft": "プッフブゥ", "heh": "ヘッフエ", "bark": "ハッフアヘ", "bark_nose": "フッハンウム", "cackle": "アハッヒィヘエァャギウ",
    "mm": "ンウム", "mmm": "ンウム", "haa": "ハァアフゥ",
}
HEARD = {
    "fuun": r"^フウ*ン+$", "un": r"^ウ?ン$|^ウム$", "unun": r"^ウ?ンウ?ン$", "hee": r"^ヘ[エェイ]*ッ?$",
    "hee_slide": r"^ヘ[エェイ]*ッ?$", "hah": r"^ハ[アァ]*ッ?$", "pfft": r"^[プブ]ッ?(フ?ッ?)$", "heh": r"^[ヘフ]ッ?$",
    "bark": r"^フ?ハッ?(ハッ?)?$", "bark_nose": r"^ン?[フハ]ッ?([フハ]ッ?)?$", "cackle": r"ハ.*ハ.*ハ",
    "mm": r"^ウ?ン+$|^ム+$|^ウム$", "mmm": r"^ウ?ン+$|^ム+$", "haa": r"^[ハア][アァ]*ッ?$",
}
NOT_FIRST = {"hee": "ハアフウ", "hee_slide": "ハアフウ", "hah": "ヘフウ", "un": "フ", "mm": "フ", "mmm": "フ",
             "bark_nose": "ヘエウ"}
SILENCE = {"あれ", "え", "えっ", "はい", "どう", "うん", "あ", "あっ", "ん", "アレ", "エ", "ハイ", "ドウ"}
SIM_FLOOR = {"fuun": 0.45, "un": 0.45, "unun": 0.45, "hee": 0.50, "hee_slide": 0.50, "hah": 0.45, "pfft": 0.30,
             "heh": 0.30, "bark": 0.40, "bark_nose": 0.45, "cackle": 0.50, "mm": 0.45, "mmm": 0.45, "haa": 0.40}
WHISPER_SIM_FLOOR = 0.35
LOW_NOISES = ("fuun", "un", "unun", "mm", "mmm", "bark_nose", "heh", "cackle", "bark")
RISE_MAX_HAH, FALL_MIN = 8.0, 2.0
EDGE_GAP = 0.12
LOUD_DB = 2.0
LAUGH_MIN = 0.05
NAT_MARGIN = 0.20
# the noise's own shape: len (active s), voiced share, pulses, contour (semitones), mouth, burst
GATE = {
    "fuun": dict(len=(0.5, 1.4), voiced_min=0.7, net=(-4.0, 1.5), rise_max=3.0, f1_max=400, low_min=10.0),
    "un": dict(len=(0.15, 0.8), voiced_min=0.7, bursts=(1, 1), net=(None, 2.0), f1_max=420, low_min=8.0),
    "unun": dict(len=(0.4, 1.8), voiced_min=0.6, bursts=(2, 2), net=(None, 2.0), f1_max=420, low_min=8.0),
    "hee": dict(len=(0.4, 1.6), voiced_min=0.6, rise_min=2.0, peak_pos_min=0.2, f1_min=400),
    "hee_slide": dict(len=(0.4, 1.8), voiced_min=0.6, rise_min=2.0, peak_pos=(0.2, 0.8), fall_min=FALL_MIN, f1_min=400),
    "hah": dict(len=(0.2, 1.2), voiced_min=0.4, rise_min=3.0, rise_max=RISE_MAX_HAH, net=(2.0, None), f0_start_max=240,
                f0_end_max=300, f1_max=650),
    "pfft": dict(len=(0.08, 0.6), voiced_max=0.35, attack_max=40, core_max=0.15),
    "heh": dict(len=(0.1, 0.6), bursts=(1, 1), attack_max=60, core_max=0.20, nose=(450, 8.0)),
    "bark_nose": dict(len=(0.12, 1.1), voiced_min=0.3, bursts=(1, 2), attack_max=40, pulse_max=0.30, f1_max=400,
                      low_min=12.0, f0_med_max=250),
    "cackle": dict(len=(1.0, 3.6), voiced_min=0.4, bursts=(4, None), course=True, f0_med_max=300),
    "mm": dict(len=(0.2, 0.9), voiced_min=0.8, bursts=(1, 1), net=(-4.0, 2.0), f1_max=330, low_min=13.0),
    "mmm": dict(len=(0.7, 2.2), voiced_min=0.8, net=(None, 2.0), f1_max=350, low_min=12.0, f0_med_max=245),
    "haa": dict(len=(0.8, 2.5), voiced_max=0.85, net=(None, 1.0), f1_min_voiced=420),
}
COURSE = dict(v1_min=0.6, v_drop=0.25, hnr_drop=4.0, hf_rise=3.0)
GATE_TEXT = {
    "bark_nose": "heard as ふっ/んふっ/ふふっ/はっ (one or two pulses; never へ, うん or ふん); 0.12-1.1 s (two pulses and their breath); 1-2 pulses, each at most 0.30 s (a laugh pulse, not a held hum); voiced or half-voiced (>= 0.3); abrupt onset (attack <= 40 ms); closed mouth through the nose (F1 <= 400 Hz, low band >= +12 dB; her fuun/mm: F1 246-257, +21 dB; round 2's open-mouth bark: F1 715, +8); low (median <= 250 Hz by both trackers, under round 1's giggles 273-293); the tagger: not a giggle (giggle <= 0.10), not speech, not an in-breath (a gasp-led first guess of 0.25+ only with a voice: voiced >= 0.6, as nobody voices an intake; AudioSet has no class for a laugh through the nose and leads short nasal bursts with gasp)",
    "cackle": "heard with 3+ は; 1.0-3.6 s; 4+ pulses; voiced >= 0.4; LOW: median <= 300 Hz and p90 <= 367 Hz by both trackers; the course of a cackle that breaks into a wheeze: the first third voiced >= 0.6, the last third's voiced share 0.25 lower, its HNR 4 dB lower and its breath noise (energy over 4 kHz) 3 dB higher than the first third's; a laugh to the tagger and not a giggle; loud: at least 2 dB brighter (tilt) than her normal laughs",
    "hah": "heard as はぁ (never as へ/ふ/う); 0.2-1.2 s; voiced >= 0.4; a rise of 3 to 8 semitones (not surprise), ending >= 2 st over its start and at or under 300 Hz; starts <= 240 Hz; mouth barely open (F1 <= 650 Hz)",
    "pfft": "heard as ぷっ/ぶっ; 0.08-0.6 s; unvoiced (voiced <= 0.35); a burst (attack <= 40 ms, core <= 0.15 s); not speech",
    "heh": "heard as へっ/ふっ (one syllable, never ふん or へへ); 0.1-0.6 s; one pulse; a burst (attack <= 60 ms, core <= 0.2 s); not speech; through the nose: with a voice (60 ms+), F1 <= 450 Hz and low band >= +8 dB; without one, heard as ふっ by one recogniser and as は/へ by neither",
    "haa": "heard as はぁ/ああ (whisper not ふぅ); 0.8-2.5 s; breathy (voiced <= 0.85); falls or stays (net <= +1 st); open (with a voice: F1 >= 420 Hz, not a hum); a breath out to the tagger (sigh >= 0.30, first guess a breath)",
    "hee_slide": "heard as へぇ (never as は/あ/ふ/う); 0.4-1.8 s; voiced >= 0.6; rises at least 2 st, its peak inside (0.2-0.8 of the voiced part), then slides down at least 2 st; an e (F1 >= 400 Hz)",
    "hee": "heard as へぇ (never as は/あ/ふ/う); 0.4-1.6 s; rises at least 2 st, its peak after the first fifth; an e (F1 >= 400 Hz) [whisper: no voice, so no contour]",
    "un": "heard as うん/ん; 0.15-0.8 s; one pulse; voiced >= 0.7; no question rise (net <= +2 st); closed (F1 <= 420 Hz, low band >= +8 dB) [whisper: no voice]",
    "mm": "heard as ん/うん; 0.2-0.9 s; one pulse; voiced >= 0.8; net -4..+2 st; closed (F1 <= 330 Hz, low band >= +13 dB) [whisper: no voice]",
    "fuun": "heard as ふーん/ふん; 0.5-1.4 s; voiced >= 0.7; flat or slightly falling; closed (F1 <= 400 Hz, low band >= +10 dB)",
    "unun": "heard as うんうん; 0.4-1.8 s; two pulses; voiced >= 0.6; net <= +2 st; closed (F1 <= 420 Hz, low band >= +8 dB)",
    "mmm": "heard as んー/うーん; 0.7-2.2 s; voiced >= 0.8; net <= +2 st; closed (F1 <= 350 Hz, low band >= +12 dB); low (<= 245 Hz)",
    "bark": "round 2's open-mouth bark: not made in round 3",
}
WHISPER = dict(py_voiced_max=0.30, hnr_max=5.0, hr_share_max=0.05, cv_max_s=0.06)
CHILD_MAX, BABY_LAUGH_MAX = 0.06, 0.05
QUIET_LUFS, QUIET_TO = -45.0, -40.0
WAYS = {
    "B": "Irodori-TTS cloned from her 4 clean clips (emoji style marks)",
    "BS": "Irodori-TTS cloned from her quietest clip v12_040 alone",
    "BN": "Irodori-TTS cloned from her calm clip v12_071 alone",
    "BW": "Irodori-TTS cloned from her 4 clips whispered by whisperize.py (the way her whisper set was made)",
    "BC": "Irodori-TTS cloned from her 4 clean clips, with a caption describing the delivery",
    "BCN": "Irodori-TTS cloned from her calm clip v12_071 alone, with a caption describing the delivery",
    "BL": "Irodori-TTS cloned from round 1's laugh loud takes (her teacher's laughs) + her loud clip v12_065",
    "BY": "Irodori-TTS cloned from two takes of her loud set and two of her yell set",
    "BH": "Irodori-TTS cloned from her calm clip + round 2's kept fuun / mm / un takes (closed mouth)",
    "BWS": "Irodori-TTS cloned from five takes of her whisper set (real whispers)",
    "BSS": "Irodori-TTS cloned from four takes of her soft set",
    "A": "her GPT-SoVITS teacher, one of her clips as reference",
    "AL": "her GPT-SoVITS teacher, a take of her loud set as reference",
    "AWS": "her GPT-SoVITS teacher, a take of her whisper set as reference",
    "C": "her GPT-SoVITS teacher, a take of the noise followed by her clip as reference",
    "X": "her whisper set's own take (Irodori from her whispered clips) of a line that starts with the noise",
    "P": "signal processing of one or more of her takes (see how)",
}
TEACHER = ("A", "AL", "AWS", "C")
KIND = {"A": "sound alone", "L": "cut from a sound-led line", "P": "made by signal processing from her takes"}


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


def read_tsv(p):
    return list(csv.DictReader(open(p, encoding="utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE)) if os.path.exists(p) else []


cuts, meas, extra, tags, heard = {}, {}, {}, {}, {}
for tg in TAGS:
    for p, d in ((f"{B}/cuts_{tg}.tsv", cuts), (f"{B}/measure_{tg}.tsv", meas), (f"{B}/extra_{tg}.tsv", extra),
                 (f"{B}/tag_{tg}.tsv", tags)):
        for r in read_tsv(p): d[os.path.basename(r["file"])] = r
    if os.path.exists(f"{B}/asr_{tg}.jsonl"):
        for l in open(f"{B}/asr_{tg}.jsonl", encoding="utf-8"):
            r = json.loads(l); heard[os.path.basename(r["file"])] = r["text"]
post = {}
for l in open(f"{B}/meta_all.tsv", encoding="utf-8"):
    q = l.rstrip("\n").split("\t")
    if len(q) >= 6 and q[0] != "name": post[q[0]] = q[4]
# calibration: the bank's own takes measured with the same code (style and natural references)
calm = {r["file"]: r for r in read_tsv(f"{CAL}/measure.tsv")}
calx = {r["file"]: r for r in read_tsv(f"{CAL}/extra.tsv")}
cell_ref = defaultdict(list)
for f, r in calm.items():
    m = re.search(r"/sounds/([^/]+)/([^/]+)/take_", f) or re.search(r"/range_v1/()(soft|loud|yell|whisper)/ds/", f)
    if m:
        x = calx.get(f, {})
        cell_ref[(m.group(1), m.group(2))].append(dict(tilt=fnum(x.get("tilt_db")), jitter=fnum(x.get("jitter_loc")),
                                                        shimmer=fnum(x.get("shimmer_loc")), flat=fnum(x.get("flat")),
                                                        hf=fnum(x.get("hf_body"))))
    elif "/refs/breaths/" in f:
        x = calx.get(f, {})
        cell_ref[("breath", "her")].append(dict(tilt=None, jitter=None, shimmer=None, flat=fnum(x.get("flat")), hf=fnum(x.get("hf_body"))))
STYLE_REF = {"cackle": ("laugh", "normal"), "hee_slide": ("hee", "normal")}  # a noise without a normal cell of its own
REF_NAT = {"cackle": [("laugh", "loud"), ("laugh", "normal")], "bark_nose": [("fuun", "normal"), ("mm", "normal"), ("heh", "normal")],
           "hee_slide": [("hee", "normal"), ("hee", "soft")]}

rows = []
for b, c in cuts.items():
    if c["status"] not in ("ok", "tight", "alone", "proc") or b not in meas or b not in extra: continue
    if c["sound"] not in GATE: continue
    r = meas[b]; x = extra[b]
    m = {k: fnum(v) for k, v in r.items() if k not in ("file", "kana")}
    m.update({k: fnum(v) for k, v in x.items() if k not in ("file", "head_kana", "tail_kana", "kana_after", "pulses")})
    m.update(file=r["file"], base=b, kana=r["kana"], whisper=heard.get(b), head_kana=x.get("head_kana", ""),
             tail_kana=x.get("tail_kana", ""), kana_after=x.get("kana_after", ""), pulses=x.get("pulses", "[]"),
             tag={k: (v if k == "top" else float(v)) for k, v in tags.get(b, {}).items() if k != "file"},
             **{k: c[k] for k in ("sound", "style", "kind", "way", "name", "src", "from", "to", "status", "note")})
    rows.append(m)


def fam(m):
    t = m["tag"]; g = lambda *k: max(t.get(x, 0.0) for x in k)
    return dict(laugh=g("Laughter", "Giggle", "Snicker", "Chuckle", "Belly_laugh"),
                laugh_ng=g("Laughter", "Snicker", "Chuckle", "Belly_laugh"), giggle=t.get("Giggle", 0.0),
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
MOUTH = {"Burst, pop", "Slap, smack", "Snort"}


def tops(m):
    out = []
    for x in (m["tag"].get("top") or "").split(";"):
        if ":" not in x: continue
        lab, sc = x.rsplit(":", 1)
        if lab not in IGNORE: out.append((lab, float(sc)))
    return out


def lead(m):
    t = tops(m)
    return t[0] if t else ("", 0.0)


def target(m):
    if not m["tag"]: return 0.0
    f = fam(m)
    return {"cackle": f["laugh_ng"], "bark_nose": f["laugh_ng"] + f["snort"], "haa": f["sigh"]}.get(m["sound"], 0.0)


def child(m):
    t = m["tag"]
    if not t: return 0.0
    c = max(t.get(k, 0.0) for k in ("Child_speech", "Baby_laughter", "Baby_cry", "Children_shouting", "Babbling",
                                    "Child_singing", "Children_playing"))
    return max(c, CHILD_MAX + 0.001) if t.get("Baby_laughter", 0.0) > BABY_LAUGH_MAX and c <= CHILD_MAX else c


def adult(m):
    """Pitch by both trackers on their clearly voiced frames (voiced to the tracker and HNR >= 6 dB): breath noise
    (her real breaths and her whisper set: HNR -4..+5 dB) has no pitch, though Praat's tracker reports 400-880 Hz in
    it and so made round 2's cap fail whispers and the aspiration between laugh pulses."""
    s = m["sound"]
    for tr in ("pr", "py"):
        if (m.get(f"{tr}_cv_s") or 0) >= 0.06 and m.get(f"{tr}_cv_med") is not None:
            md, p9 = m[f"{tr}_cv_med"], m[f"{tr}_cv_p90"]
            if md > 345 or p9 > 500: return f"adult ({tr} clear voice {md:.0f}/{p9:.0f})"
            if s in LOW_NOISES and p9 > 367: return f"adult (high for her: {tr} p90 {p9:.0f})"
    pp9, yp9, pmx = m.get("pr_cv_p90"), m.get("py_cv_p90"), m.get("pr_cv_max")
    if (pmx or 0) > 400 and (yp9 or 0) >= 360: return f"adult (high for her: peak {pmx:.0f}, pyin p90 {yp9:.0f})"
    if (pp9 or 0) > 400 and (yp9 or 0) > 400: return "adult (high for her: both p90 over 400 Hz)"
    if child(m) > CHILD_MAX: return f"adult (tagger: child class {child(m):.2f})"
    return ""


def heard_check(m):
    s = m["sound"]; wt = m["whisper"] or ""
    wr, kr = reading(wt), reading(m["kana"])
    pr = reading(post.get(m["name"], "")); key = pr[:2] if len(pr) >= 2 else pr
    if m["kind"] == "L" and key and (key in wr or key in kr): return f"leak ({key})"
    foreign = lambda r: sum(ch not in OWN[s] for ch in r)
    if max(foreign(wr), foreign(kr)) >= 3 or min(foreign(wr), foreign(kr)) >= 2:
        return f"heard a word ({wt} | {m['kana']})"
    pat = re.compile(HEARD[s])
    if not any(r and pat.search(r) for r in (wr, kr)): return f"heard ({wt} | {m['kana']})"
    nf = NOT_FIRST.get(s, "")
    if nf and any(r and r[0] in nf for r in (wr, kr)): return f"heard as another noise ({wt} | {m['kana']})"
    if s == "haa" and wr[:1] == "フ": return f"heard as an exhale ({wt})"
    if s == "un" and any(r.count("ン") >= 2 for r in (wr, kr)): return f"heard twice ({wt} | {m['kana']})"
    if s == "heh" and any(r and ("ン" in r or len(r.replace("ッ", "")) >= 2) for r in (wr, kr)):
        return f"heard as a hmph or a giggle ({wt} | {m['kana']})"
    if s == "bark_nose" and any(len(r.replace("ッ", "").replace("ン", "")) >= 3 for r in (wr, kr) if r):
        return f"heard as a giggle ({wt} | {m['kana']})"
    if s == "bark_nose" and any(re.match(r"^フ+ン+$", r) for r in (wr, kr) if r): return f"heard as a hmph ({wt} | {m['kana']})"
    # both ends (the kana recogniser on the first and the last 150 ms): nothing of the next word; on 150 ms of
    # near-silence it writes one of SILENCE, which is not a word of the line
    k1 = pr[:1] if pr and pr[:1] not in OWN[s] else ""
    for end in ("head_kana", "tail_kana"):
        raw_e = (m.get(end) or "").strip("《》 ")
        if raw_e in SILENCE: continue
        er = reading(raw_e)
        if m["kind"] == "L" and ((key and key in er) or (k1 and k1 in er)): return f"edges ({end}: {m.get(end)}: the next word)"
        if s == "heh" and er.replace("ッ", "").count("ヘ") + er.replace("ッ", "").count("フ") >= 2: return f"edges ({end}: {m.get(end)})"
        if foreign(er) >= 3: return f"edges ({end}: {m.get(end)}: a word)"
    return ""


def tagger(m):
    s = m["sound"]
    if not m["tag"]: return "tagger (not tagged)"
    f = fam(m); lab, sc = lead(m)
    if f["bad"] >= 0.25 and f["bad"] > max(f["laugh"], f["breath"]):
        return f"tagger (cough, sneeze, throat, cry or scream {f['bad']:.2f})"
    ok_first = LAUGHS | BREATHS | VOICE | (MOUTH if s == "pfft" else set())
    if s == "pfft" and lab == "Throat clearing" and sc < 0.25: ok_first = ok_first | {lab}
    if sc >= (0.30 if lab == "Fart" else 0.10) and lab not in ok_first:
        return f"tagger (first guess: {lab} {sc:.2f})"
    if s == "cackle":
        laughs = [(l, v) for l, v in tops(m) if l in LAUGHS]
        if not laughs or laughs[0][0] == "Giggle": return f"tagger (giggle first or no laugh: {laughs[:1]})"
        if f["giggle"] > 0.7 * f["laugh_ng"]: return f"tagger (giggle {f['giggle']:.2f} vs laugh {f['laugh_ng']:.2f})"
        if f["laugh"] < LAUGH_MIN or f["laugh"] < max(f["noise"], f["cry"]) or f["laugh"] < 0.6 * f["breath"]:
            return f"tagger (laughter {f['laugh']:.2f}, breath {f['breath']:.2f})"
    elif s == "bark_nose":
        # AudioSet has no class for a laugh through the nose: the pilot's closed-mouth pulses scored laugh + snort
        # 0.00-0.02 and led with gasp / sigh, so the laugh is the shape's job; the tagger only rules out a giggle,
        # speech and an in-breath
        if lab == "Giggle" or f["giggle"] > 0.10: return f"tagger (a giggle: {f['giggle']:.2f})"
        if f["speech"] >= 0.5: return f"tagger (speech {f['speech']:.2f})"
        if lab == "Gasp" and sc >= 0.25 and (m["voiced"] or 0) < 0.6: return f"tagger (an in-breath: gasp {sc:.2f}, voiced {m['voiced']:.2f})"
    elif s == "haa":
        if f["sigh"] < 0.30 or lab not in BREATHS or m["tag"].get("Sigh", 0) < f["gasp"]:
            return f"tagger (not a breath out: sigh {f['sigh']:.2f}, gasp {f['gasp']:.2f}, first {lab})"
    elif s in ("pfft", "heh"):
        if f["speech"] >= 0.5: return f"tagger (speech {f['speech']:.2f})"
    if s in ("fuun", "un", "unun", "mm", "mmm", "hee", "hee_slide", "hah", "haa"):
        if f["moan"] >= 0.3: return f"tagger (a moan {f['moan']:.2f})"
        if f["laugh"] >= 0.25: return f"tagger (laughter {f['laugh']:.2f})"
    return ""


def lvf(x, sr):
    fr = int(0.01 * sr); n = len(x) // fr
    return 20 * np.log10(np.sqrt(np.mean(x[:n * fr].reshape(n, fr).astype(np.float64) ** 2, axis=1)) + 1e-9)


def edge(m):
    x, sr = sf.read(m["file"], dtype="float32")
    if x.ndim > 1: x = x.mean(axis=1)
    lv = lvf(x, sr)
    if len(lv) < 12: return ""
    top = np.percentile(lv, 98)
    if m["kind"] == "P":
        if lv[:2].max() > top - 30: return "edge (processed: start)"
        if lv[-2:].max() > top - 30: return "edge (processed: end)"
        return ""
    if lv[-8:-6].max() > top - 20: return "edge (end of the cut)"
    pre, po = m.get("raw_pre_db"), m.get("raw_post_db")
    if pre is not None and pre > -25: return f"edge (raw before the cut {pre:.0f} dB)"
    if po is not None and po > -25: return f"edge (raw after the cut {po:.0f} dB)"
    ng, pg = m.get("next_gap_s"), m.get("prev_gap_s")
    if ng is not None and ng < EDGE_GAP: return f"edge (next sound {ng * 1000:.0f} ms after the noise)"
    if pg is not None and pg < EDGE_GAP: return f"edge (a sound {pg * 1000:.0f} ms before the noise)"
    return ""


def whisper_ok(m):
    if (m.get("py_voiced") or 0) > WHISPER["py_voiced_max"]: return f"shape (a whisper with voice: pyin voiced {m['py_voiced']:.2f})"
    if m["hnr"] is not None and m["hnr"] > WHISPER["hnr_max"]: return f"shape (a whisper with voice: HNR {m['hnr']:.1f})"
    if (m.get("hr_share") or 0) > WHISPER["hr_share_max"]: return f"shape (a whisper with tonal stretches: {m['hr_share']:.2f})"
    for tr in ("pr", "py"):
        if (m.get(f"{tr}_cv_s") or 0) >= WHISPER["cv_max_s"]: return f"shape (a whisper with clear voice: {tr} {m[f'{tr}_cv_s']:.2f} s)"
    return ""


def low_pitch(m, mx):
    for k in ("pr_cv_med", "py_cv_med", "f0_med"):
        v = m.get(k)
        if v is not None and v > mx: return f"shape (not low: {k} {v:.0f} Hz)"
    if m.get("pr_cv_med") is None and m.get("py_cv_med") is None: return "shape (no clear voice to measure)"
    return ""


def shape(m):
    s, g = m["sound"], GATE[m["sound"]]
    wh = m["style"] == "whisper"
    a = m["active_s"]; lo, hi = g["len"]
    if not (lo <= a <= hi): return f"shape (length {a:.2f})"
    v = m["voiced"] or 0.0
    if wh:
        w = whisper_ok(m)
        if w: return w
    else:
        if "voiced_min" in g and v < g["voiced_min"]: return f"shape (voiced {v:.2f})"
    if "voiced_max" in g and v > g["voiced_max"]: return f"shape (voiced {v:.2f})"
    if "bursts" in g:
        bl, bh = g["bursts"]; bu = m["bursts"] or 0
        if bu < bl or (bh is not None and bu > bh): return f"shape (pulses {bu:.0f})"
    if "attack_max" in g and (m["attack_ms"] or 0) > g["attack_max"]: return f"shape (attack {m['attack_ms']:.0f} ms)"
    if "core_max" in g and (m["core_s"] or 0) > g["core_max"]: return f"shape (core {m['core_s']:.2f} s)"
    if "pulse_max" in g:
        pl = [p["t1"] - p["t0"] for p in json.loads(m["pulses"] or "[]")]
        if not pl or max(pl) > g["pulse_max"]: return f"shape (a held sound, not a laugh pulse: {max(pl) if pl else None})"
    if wh: return ""  # the checks below need a voice
    if g.get("course"):
        c = COURSE; v1, v3, h1, h3, f1, f3 = (m.get(k) for k in ("v1", "v3", "hnr1", "hnr3", "hf1", "hf3"))
        if v1 is None or v1 < c["v1_min"]: return f"shape (no voiced chest pulses first: v1 {v1})"
        if v3 is None or v3 > v1 - c["v_drop"]: return f"shape (no breath at the end: voiced {v1:.2f} -> {v3})"
        if h1 is None or h3 is None or h3 > h1 - c["hnr_drop"]: return f"shape (HNR does not fall: {h1} -> {h3})"
        if f1 is None or f3 is None or f3 < f1 + c["hf_rise"]: return f"shape (breath noise does not rise: {f1} -> {f3})"
        for tr in ("pr_cv_p90", "py_cv_p90"):
            if (m.get(tr) or 0) > 367: return f"shape (squeals: {tr} {m[tr]:.0f})"
    if "f0_med_max" in g:
        lp = low_pitch(m, g["f0_med_max"])
        if lp: return lp
    if s == "heh":
        if (m["voiced_s"] or 0) >= 0.06:
            f1m, lo_db = g["nose"]
            if m["f1_med"] is None or m["f1_med"] > f1m or m["low_db"] is None or m["low_db"] < lo_db:
                return f"shape (open mouth, not through the nose: F1 {m['f1_med']}, low band {m['low_db']})"
        else:
            wr, kr = reading(m["whisper"] or ""), reading(m["kana"])
            if not any(r[:1] == "フ" for r in (wr, kr) if r) or any(r[:1] in "ハヘ" for r in (wr, kr) if r):
                return f"shape (an unvoiced breath not heard as ふっ: {m['whisper']} | {m['kana']})"
    need = lambda k: m.get(k) is not None
    if "net" in g:
        if not need("net_st"): return "shape (no pitch contour)"
        nl, nh = g["net"]
        if (nl is not None and m["net_st"] < nl) or (nh is not None and m["net_st"] > nh): return f"shape (contour net {m['net_st']:+.1f} st)"
    if "rise_max" in g and need("rise_st") and m["rise_st"] > g["rise_max"]: return f"shape (contour rises {m['rise_st']:.1f} st)"
    if "rise_min" in g:
        if not need("rise_st") or m["rise_st"] < g["rise_min"]: return f"shape (contour does not rise: {m.get('rise_st')})"
    if "peak_pos_min" in g and (m["peak_pos"] or 0) < g["peak_pos_min"]: return f"shape (peak at {m['peak_pos']:.2f})"
    if "peak_pos" in g:
        pl, ph = g["peak_pos"]
        if m["peak_pos"] is None or not (pl <= m["peak_pos"] <= ph): return f"shape (peak at {m['peak_pos']})"
    if "fall_min" in g and (m["fall_st"] is None or m["fall_st"] < g["fall_min"]): return f"shape (does not slide down: fall {m['fall_st']})"
    if "f0_start_max" in g and need("f0_start") and m["f0_start"] > g["f0_start_max"]: return f"shape (starts high: {m['f0_start']:.0f} Hz)"
    if "f0_end_max" in g and need("f0_end") and m["f0_end"] > g["f0_end_max"]: return f"shape (ends high: {m['f0_end']:.0f} Hz)"
    if "f1_max" in g:
        if not need("f1_med") or m["f1_med"] > g["f1_max"]: return f"shape (mouth open: F1 {m.get('f1_med')})"
    if "f1_min" in g and need("f1_med") and m["f1_med"] < g["f1_min"]: return f"shape (a hum, not a vowel: F1 {m['f1_med']:.0f})"
    if "f1_min_voiced" in g and (m["voiced_s"] or 0) >= 0.06 and need("f1_med") and m["f1_med"] < g["f1_min_voiced"]:
        return f"shape (closed mouth, a hum: F1 {m['f1_med']:.0f})"
    if "low_min" in g:
        if not need("low_db") or m["low_db"] < g["low_min"]: return f"shape (mouth open: low band {m.get('low_db')})"
    return ""


def med(v):
    v = [x for x in v if x is not None]
    return float(np.median(v)) if v else None


def style_ref(s):
    k = STYLE_REF.get(s, (s, "normal"))
    return med([r["tilt"] for r in cell_ref.get(k, [])])


def style_check(m, cand_ref):
    st, s = m["style"], m["sound"]
    t = m.get("tilt_db")
    if st in ("normal", "whisper") or t is None: return ""
    ref = style_ref(s) if st == "loud" or (s, "normal") in cell_ref else cand_ref.get(s)
    if ref is None: return ""
    if st == "soft" and t < ref: return f"style (soft brighter than normal: tilt {t:.1f} < {ref:.1f})"
    if st == "loud" and t > ref - LOUD_DB: return f"style (loud not brighter: tilt {t:.1f} > {ref - LOUD_DB:.1f})"
    return ""


def natural(m):
    if m["kind"] != "P": return ""
    if m["sound"] == "cackle":  # the wheeze: breath noise as bright as her real breaths or her whispers, not a hiss
        v = [r["hf"] for k in (("", "whisper"), ("breath", "her")) for r in cell_ref.get(k, []) if r.get("hf") is not None]
        if v and m.get("hf3") is not None:
            lo, hi = min(v), max(v); span = hi - lo
            if m["hf3"] > hi + NAT_MARGIN * span or m["hf3"] < lo - NAT_MARGIN * span:
                return f"natural (the wheeze's breath noise {m['hf3']:.1f} dB outside her breaths and whispers {lo:.1f}..{hi:.1f})"
    keys = [("", "whisper")] if m["style"] == "whisper" else REF_NAT.get(m["sound"], [(m["sound"], "normal")])
    refs = [r for k in keys for r in cell_ref.get(k, [])]
    for key, col in (("jitter", "jitter_loc"), ("shimmer", "shimmer_loc"), ("flat", "flat")):
        v = [r[key] for r in refs if r[key] is not None]
        x = m.get(col)
        if not v or x is None: continue
        lo, hi = min(v), max(v); span = max(hi - lo, 1e-6)
        if x < lo - NAT_MARGIN * span or x > hi + NAT_MARGIN * span:
            return f"natural ({key} {x:.3f} outside her {lo:.3f}..{hi:.3f})"
    return ""


def check(m, cand_ref=None, final=False):
    s = m["sound"]
    if (m["n_clip"] or 0) > 0 or (m["peak_db"] or 0) > -0.3: return "clip"
    a = adult(m)
    if a: return a
    if m["whisper"] is None: return "not heard by whisper"
    h = heard_check(m)
    if h: return h
    t = tagger(m)
    if t: return t
    lu = m["lufs"] if m["lufs"] is not None else m["lufs_rms"]
    if lu is None or lu < -70: return "level"
    e = edge(m)
    if e: return e
    sh = shape(m)
    if sh: return sh
    if final:
        stc = style_check(m, cand_ref or {})
        if stc: return stc
    n = natural(m)
    if n: return n
    fl = WHISPER_SIM_FLOOR if m["style"] == "whisper" else SIM_FLOOR[s]
    if fl is not None and (m["sim_her"] is None or m["sim_her"] < fl): return f"timbre ({m['sim_her']})"
    return "pass"


def rank(m):
    return ((m["sim_her"] or 0.0) + 0.25 * min(target(m), 0.6) - (0.05 if m["status"] == "tight" else 0)
            - (0.5 if m["kind"] == "P" else 0))


for m in rows: m["verdict"] = check(m)
# the soft reference of a noise with no normal cell in the bank: this round's passing normal candidates
cand_ref = {}
for s in ORDER:
    t = med([m.get("tilt_db") for m in rows if m["sound"] == s and m["style"] == "normal" and m["verdict"] == "pass"])
    if t is not None: cand_ref[s] = t
for m in rows:
    if m["verdict"] == "pass": m["verdict"] = check(m, cand_ref, final=True)
groups = defaultdict(list)
for m in rows: groups[(m["sound"], m["style"])].append(m)
f3 = lambda v: f"{v:.3f}" if v is not None else ""
okey = lambda k: (ORDER.index(k[0]) if k[0] in ORDER else 99, STYLES.index(k[1]))
with open(f"{B}/select_r3.tsv", "w", encoding="utf-8") as o:
    cols = ["active_s", "voiced", "py_voiced", "f0_med", "pr_cv_med", "py_cv_med", "py_cv_p90", "net_st", "rise_st",
            "fall_st", "peak_pos", "f0_end", "f1_med", "low_db", "hnr", "hr_share", "v1", "v3", "hnr1", "hnr3", "hf1",
            "hf3", "tilt_db", "attack_ms", "bursts", "next_gap_s", "sim_her"]
    o.write("sound\tstyle\tfile\tway\tname\tverdict\t" + "\t".join(cols) + "\twhisper\tkana\thead\ttail\ttagger\n")
    for k in sorted(groups, key=okey):
        for m in sorted(groups[k], key=lambda m: (m["verdict"] != "pass", -(m["sim_her"] or 0))):
            o.write("\t".join([m["sound"], m["style"], m["base"], m["way"], m["name"], m["verdict"]] + [f3(m.get(c)) for c in cols]
                              + [m["whisper"] or "", m["kana"], m["head_kana"], m["tail_kana"], m["tag"].get("top", "")]) + "\n")
for k in sorted(groups, key=okey):
    c = Counter(m["verdict"].split(" (")[0] for m in groups[k])
    print(f"{k[0]:9s} {k[1]:8s} pass {c.get('pass', 0):3d} of {len(groups[k]):3d} | " + " ".join(f"{v} {n}" for v, n in c.most_common() if v != "pass"))
if DRY:
    sys.exit(0)


def finalize(x, sr):
    y = librosa.resample(x.astype(np.float32), orig_sr=sr, target_sr=SR, res_type="soxr_hq") if sr != SR else x.astype(np.float32)
    pk = np.max(np.abs(y)) + 1e-9
    if pk > 10 ** (-1 / 20): y = y * (10 ** (-1 / 20) / pk)
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
    if "hash" not in m:
        p = m["src"].split("|")[0] if m["kind"] == "P" else m["src"]
        m["hash"] = ("P" + hashlib.sha1(open(m["file"], "rb").read()).hexdigest()) if m["kind"] == "P" else \
            hashlib.sha1(open(os.path.realpath(p), "rb").read()).hexdigest()
    return m["hash"]


def ncc(a, b):
    """Highest normalised cross-correlation of two takes at 8 kHz (a near copy: >= 0.9)."""
    from scipy.signal import correlate
    a = librosa.resample(a, orig_sr=SR, target_sr=8000); b = librosa.resample(b, orig_sr=SR, target_sr=8000)
    if len(a) < len(b): a, b = b, a
    cc = correlate(a, b, mode="valid", method="fft")
    e = np.convolve(a ** 2, np.ones(len(b)), mode="valid")
    return float(np.max(cc / (np.sqrt(e * np.sum(b ** 2)) + 1e-12))) if len(cc) else 0.0


jp = os.path.join(BANK, "sounds.json")
bank = json.load(open(jp, encoding="utf-8"))
bank_audio = defaultdict(list)
for s, st in bank["sounds"].items():
    for style, takes in st.items():
        for t in takes:
            x, sr = sf.read(os.path.join(BANK, t["file"]), dtype="float32")
            bank_audio[s].append((t["file"], x if x.ndim == 1 else x.mean(axis=1)))
r2 = lambda v, d=3: round(v, d) if v is not None else None
summary = []
for (s, st) in sorted(groups, key=okey):
    old = bank["sounds"].get(s, {}).get(st, [])
    room = 8 - len(old)
    ok = [m for m in groups[(s, st)] if m["verdict"] == "pass"]
    if room <= 0 or not ok: continue
    for m in ok:
        x, sr = sf.read(m["file"], dtype="float32")
        if x.ndim > 1: x = x.mean(axis=1)
        m["y"] = finalize(x, sr); m["fm"] = final_measure(m["y"]); m["gain"] = 0.0
        lu = m["fm"]["lufs"]
        if lu is not None and lu < QUIET_LUFS:
            hr = -1.0 - 20 * np.log10(np.max(np.abs(m["y"])) + 1e-9)
            m["gain"] = round(max(0.0, min(QUIET_TO - lu, hr)), 1)
            m["y"] = m["y"] * 10 ** (m["gain"] / 20); m["fm"] = final_measure(m["y"])
        if st != "whisper" and m["fm"]["f0_median_hz"] is not None and (m["fm"]["f0_median_hz"] > 345 or m["fm"]["f0_p90_hz"] > 500):
            m["verdict"] = "adult in the final file"
    ok = [m for m in ok if m["verdict"] == "pass"]

    def pick(per_job):
        kept, n, seen = [], defaultdict(int), set()
        for m in sorted(ok, key=lambda m: -rank(m)):
            if len(kept) >= room: break
            # a processed take counts against the job of the take it was made from, and only one is kept per source take
            k = ("P", os.path.basename(m["src"])) if m["kind"] == "P" else (m["way"], m["name"]); h = src_hash(m)
            if h in seen or n[k] >= (1 if m["kind"] == "P" else per_job): continue
            if "copy_of" not in m:
                m["copy_of"] = next((f for f, y in bank_audio[s] if ncc(m["y"], y) >= 0.9), "")
            if m["copy_of"]: continue
            kept.append(m); n[k] += 1; seen.add(h)
        return kept
    kept = pick(2)
    if len(old) + len(kept) < 6: kept = pick(3)
    if not kept: continue
    d = os.path.join(BANK, s, st); os.makedirs(d, exist_ok=True)
    last = max([int(re.search(r"take_(\d+)", t["file"]).group(1)) for t in old] + [0])
    takes = []
    for k, m in enumerate(kept, last + 1):
        fm = dict(m["fm"]); fm.pop("f0_p90_hz")
        fn = f"take_{k:02d}.wav"
        assert not os.path.exists(os.path.join(d, fn)), f"{s}/{st}/{fn} exists"
        sf.write(os.path.join(d, fn), m["y"], SR, subtype="PCM_16")
        wt = m["whisper"] or ""
        takes.append(dict(file=f"{s}/{st}/{fn}", style=st, **fm, gain_db=m["gain"],
                          source=dict(type="synthetic", way=m["way"], how=WAYS.get(m["way"], m["way"]), job=m["name"],
                                      kind=KIND.get(m["kind"], m["kind"]), take=os.path.basename(m["src"].split("|")[0]),
                                      cut_from_s=fnum(m["from"]), cut_to_s=fnum(m["to"]),
                                      deepfilternet_atten_db=6 if m["way"] in TEACHER else None, asked_for=s,
                                      note=m["note"] if m["kind"] == "P" else ""),
                          sim_her=r2(m["sim_her"]), voiced_share=r2(m["voiced"], 2), pyin_voiced_share=r2(m.get("py_voiced"), 2),
                          hnr_db=r2(m["hnr"], 1), heard=(wt if wt and not any(h in wt for h in HALLU) else m["kana"]) or "",
                          heard_kana=m["kana"], heard_whisper=wt, head_kana=m["head_kana"], tail_kana=m["tail_kana"],
                          tagger=m["tag"].get("top", ""),
                          pitch=dict(praat_median_hz=r2(m["f0_med"], 1), praat_p90_hz=r2(m["f0_p90"], 1),
                                     praat_clear_median_hz=r2(m.get("pr_cv_med"), 1), pyin_clear_median_hz=r2(m.get("py_cv_med"), 1),
                                     praat_clear_p90_hz=r2(m.get("pr_cv_p90"), 1), pyin_clear_p90_hz=r2(m.get("py_cv_p90"), 1),
                                     praat_peak_hz=r2(m.get("pr_max"), 1)),
                          contour=dict(f0_start_hz=r2(m["f0_start"], 1), f0_end_hz=r2(m["f0_end"], 1), rise_st=r2(m["rise_st"], 2),
                                       fall_st=r2(m["fall_st"], 2), net_st=r2(m["net_st"], 2), slope_st_per_s=r2(m["slope_st_s"], 2),
                                       peak_pos=r2(m["peak_pos"], 2)),
                          mouth=dict(f1_hz=r2(m["f1_med"], 0), f2_hz=r2(m["f2_med"], 0), low_band_db=r2(m["low_db"], 1),
                                     hf_voiced_db=r2(m["hf_v"], 1), hf_db=r2(m["hf_db"], 1), tilt_db=r2(m.get("tilt_db"), 1)),
                          burst=dict(attack_ms=r2(m["attack_ms"], 0), core_s=r2(m["core_s"], 2), pulses=int(m["bursts"] or 0)),
                          course=dict(voiced=[r2(m.get(k), 2) for k in ("v1", "v2", "v3")], hnr_db=[r2(m.get(k), 1) for k in ("hnr1", "hnr2", "hnr3")],
                                      hf_db=[r2(m.get(k), 1) for k in ("hf1", "hf2", "hf3")], flatness=[r2(m.get(k), 4) for k in ("fl1", "fl2", "fl3")]),
                          quality=dict(jitter_pct=r2(m.get("jitter_loc"), 2), shimmer_pct=r2(m.get("shimmer_loc"), 2), flatness=r2(m.get("flat"), 4),
                                       tonal_share=r2(m.get("hr_share"), 3)),
                          edges=dict(raw_before_db=r2(m.get("raw_pre_db"), 1), raw_after_db=r2(m.get("raw_post_db"), 1),
                                     next_sound_gap_s=r2(m.get("next_gap_s"), 2), prev_sound_gap_s=r2(m.get("prev_gap_s"), 2),
                                     raw_after_heard=m.get("kana_after", "")),
                          gate=dict(round=3, noise=s, shape=GATE_TEXT[s],
                                    passed=["clip", "adult (Praat and pyin)", "heard", "edges heard", "tagger", "level",
                                            "edge (both ends, raw)", "shape", "style", "natural" if m["kind"] == "P" else None, "timbre", "copy"],
                                    sim_floor=WHISPER_SIM_FLOOR if st == "whisper" else SIM_FLOOR[s], whisper=(st == "whisper")),
                          round=3))
        takes[-1]["gate"]["passed"] = [p for p in takes[-1]["gate"]["passed"] if p]
    bank["sounds"].setdefault(s, {}).setdefault(st, []).extend(takes)
    summary.append(f"{s:9s} {st:8s} +{len(takes)} (now {len(bank['sounds'][s][st])})")
bank.setdefault("round3", {})["gates"] = {s: GATE_TEXT[s] for s in ORDER if s in GATE_TEXT}
bank["round3"]["whisper"] = "a whisper: pyin voiced <= 0.30, median HNR <= 5.0 dB, tonal share <= 0.05, under 60 ms of clear voice by either tracker (her whisper set's own numbers)"
json.dump(bank, open(jp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("\n".join(summary))
