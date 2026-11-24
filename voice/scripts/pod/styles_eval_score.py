"""Scoring the five-style run, the gates (gsv-env; reads what styles_eval.py wrote under --out). No voice data here.

Words of one clip, three hearings (faster-whisper with 0.1 / 0.3 / 0.5 s before the clip), judged per hearing by the
rule its style set was gated with; the clip's words stand when two of the three hearings are within the gate (the
style checks' v_words3.py), and its error is the median of the three:
  Japanese lines (kana reading error, Open JTalk on both sides; kana_robust.py: the heard kanji read every dictionary
  way; sh = the sherpa ReazonSpeech kana recogniser, best of the whole clip and phrase by phrase, read the same way):
    normal, loud, yell  plain <= 0.10, or robust <= 0.10 when sh <= 0.10; and sh <= 0.25 (loud and yell sets' rule)
    soft                the better of (robust, sh) <= 0.10 and the other <= 0.25 (soft set's rule)
    whisper             plain <= 0.15, or robust <= 0.15 when sh <= 0.15 (whisper set's rule)
  English lines: WER (en_wer.py's way) <= 0.15 (whisper 0.25); English-led mixed lines: English-word error <= 0.15
  (whisper 0.25); Japanese-led mixed lines: kana error against the line as the phone's route reads it (English words
  as katakana): sh <= 0.15 or faster-whisper (ja) <= 0.15 (yell: sh <= 0.10 and faster-whisper <= 0.15; whisper:
  faster-whisper <= 0.15).

THE GATES (a candidate ships only if it passes every one):
 sid 0, against e974 (the phone voice) on the same lines, both spoken the phone's way with the same seeds: the
 candidate's value is the mean of its runs with SEEDS0, e974's the mean of its runs with the same seeds; the noise is
 the spread (max - min) of e974 over all its seeds (BASE_SEEDS: at least the two different seeds the goal asks for).
   ja_err, en_err, mixed_err (mean clip error per kind)  <= e974 + noise
   sim_her (WavLM cosine to her 4 clips, mean)            >= e974 - noise
   f0 (median of the clips' median f0)                    within 5 Hz of e974
   sec_per_ph (median of clip seconds / phonemes)         within 5 % of e974
   flat_p50, flat_hi (spectral flatness: median over clips of the clip median; 95th percentile over clips of the
                      clip's 95th-percentile frame: a click or noise burst raises it)  <= e974 + noise
   hnr_p50, hnr_p5 (median and 5th percentile over clips of the clip's median HNR: buzz or rasp lowers it)
                                                          >= e974 - noise
   every clip's median f0 <= 345 Hz; every clip classified normal by the style classifier
 each style s (1 soft, 2 whisper, 3 loud, 4 yell), its held-out lines spoken with sid s (seed SEED_STYLE):
   style    the median over its clips of the measures its set was gated with, against that set's own thresholds
            (ds/stats.json): soft LUFS <= max_lufs, hi <= max_hi, HNR >= min_hnr; whisper HNR <= hnr_max and
            hr_share <= hr_share_max; loud and yell LUFS >= min_lufs, hi >= min_hi, voiced tilt >= min_tilt
   timbre   median sim_her and sim_ref per language group (Japanese-led, English-led) >= the set's gate for that
            language (whisper: sim_w to her 4 whispered clips, >= its per-take gate and its consistency floor)
   words    at least WORDS_SHARE of the clips' words stand by the style's rule above
   pitch    every voiced clip's median f0 <= 345 Hz and p90 <= 500 Hz (the sets' pitch gate); a whisper clip with a
            harmonic run: that run's pitch <= 345 Hz
   class    the classifier puts >= 90 % of the style's clips in that style
 the classifier: logistic regression on standardised clip measures (FEATS: LUFS, HNR, hi band, tilt over the sounding
 frames, median f0, and measure.py's other clip measures and the flatness) trained on the five-style run's own training
 clips (sets.tsv: 200 per style), cross-validated on them too.
Writes score/clips.tsv (every clip: words and measures), score/gates.json, score/table.tsv, score/table.md.
"""
import argparse
import csv
import glob
import json
import math
import os
import statistics as st
import sys
import unicodedata

import numpy as np

SC = "/w/job/scripts"
sys.path.insert(0, SC); sys.path.insert(0, f"{SC}/range")
PADS = ("0.1", "0.3", "0.5")
STYLES = ["normal", "soft", "whisper", "loud", "yell"]
STYLE_SETS = {"soft": "/w/range_v1/soft/ds", "whisper": "/w/range_v1/whisper/ds", "loud": "/w/range_v1/loud/ds",
              "yell": "/w/range_v1/yell/ds"}
E = 1e-9


def tsv(p):
    with open(p, encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE))


def fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def nmed(v):
    v = [x for x in v if x == x]
    return float(np.median(v)) if v else float("nan")


def npct(v, q):
    v = [x for x in v if x == x]
    return float(np.percentile(v, q)) if v else float("nan")


def nmean(v):
    v = [x for x in v if x == x]
    return float(np.mean(v)) if v else float("nan")


def thresholds():
    th = {}
    for s, d in STYLE_SETS.items():
        j = json.load(open(f"{d}/stats.json"))
        th[s] = j["thresholds"] if j.get("thresholds") else j["gates"]
    return th


def words_all(a, meta, items, M, by_line=False):
    """Per clip (every generated and real line clip): error per hearing, stands or not, error, by its style's rule
    (the sid it was spoken with; by_line: the style of the line's own set, for a control spoken with another sid)."""
    import pyopenjtalk
    import kana_robust as KR
    from speak_checked import reading, edit
    import check_lang as cl
    H = {p: {} for p in PADS}
    for p in PADS:
        for fn in glob.glob(f"{a.out}/asr/heard_p{p}.s*.tsv"):
            for r in tsv(fn):
                H[p][r["id"]] = r["heard"]
    W = {p: {r["id"]: fnum(r["wer"]) for r in tsv(f"{a.out}/asr/wer_p{p}.tsv")} for p in PADS}
    clean = lambda t: "".join(c for c in (t or "") if unicodedata.category(c) != "So" and c not in "‍️")
    plain_k = lambda text, hyp: edit(list(reading(clean(text), pyopenjtalk.g2p)), list(reading(clean(hyp), pyopenjtalk.g2p))) / max(1, len(reading(clean(text), pyopenjtalk.g2p)))
    strip = lambda k: "".join(c for c in k if not unicodedata.category(c).startswith(("P", "Z", "S")))
    kana2 = lambda exp, hyp: cl.cer(strip(exp), strip(cl.kana_norm(hyp)) if hyp else "")
    out = {}
    for it in items:
        if it["src"] not in ("gen", "real") or int(it["n"]) < 0:
            continue
        fid = it["id"]; L = meta[int(it["n"])]; m = M.get(fid, {})
        style = L["style"] if by_line else STYLES[int(it["sid"])]
        if any(fid not in H[p] for p in PADS):
            out[fid] = dict(w_ok=float("nan"), w_err=float("nan"), w_npass=-1, w_why="not heard"); continue
        hs = [H[p][fid] for p in PADS]
        g_en = 0.25 if style == "whisper" else 0.15
        d = dict(heard=hs[1])
        if L["glang"] == "en":
            es = [W[p].get(fid, float("nan")) for p in PADS]
            ok = [e <= g_en + E for e in es]; g = g_en
        elif L["kind"] == "ja":
            text = L["text"]
            sh = min(KR.kana_err(text, m.get("sh_whole", ""))[0], KR.kana_err(text, m.get("sh_phr", ""))[0])
            d["sh"] = sh
            es, ok = [], []
            for h in hs:
                rob, plain = KR.kana_err(text, h)
                if style == "soft":
                    e = min(rob, sh); good = e <= 0.10 + E and max(rob, sh) <= 0.25 + E; g = 0.10
                elif style == "whisper":
                    g = 0.15; e = plain if plain <= g + E else (rob if sh <= g + E else plain); good = e <= g + E
                else:
                    g = 0.10; e = plain if plain <= g + E else (rob if sh <= g + E else plain); good = e <= g + E and sh <= 0.25 + E
                es.append(e); ok.append(good)
        else:  # Japanese-led mixed
            exp = L["exp_kana"]
            sh = min(kana2(exp, m.get("sh_whole", "")), kana2(exp, m.get("sh_phr", "")))
            d["sh"] = sh
            w = [kana2(exp, h) for h in hs]
            g = 0.15
            if style == "yell":
                ok = [sh <= 0.10 + E and e <= 0.15 + E for e in w]; es = [max(e, sh) for e in w]
            elif style == "whisper":
                ok = [e <= 0.15 + E for e in w]; es = w
            else:
                sec = sh <= 0.15 + E
                ok = [sec or e <= 0.15 + E for e in w]; es = [min(e, sh) for e in w]
                if not (sec or sum(e <= 0.15 + E for e in w) >= 2):
                    ok = [False, False, False]
        d.update(w_e1=es[0], w_e2=es[1], w_e3=es[2], w_err=float(np.median(es)), w_npass=int(sum(ok)), w_ok=int(sum(ok) >= 2), w_gate=g)
        out[fid] = d
    return out


def classifier(sets_rows, M):
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import cross_val_predict, StratifiedKFold
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    X, y, ids = [], [], []
    for r in sets_rows:
        f = feats(M.get(r["id"], {}))
        if f is not None:
            X.append(f); y.append(STYLES.index(r["cls"])); ids.append(r["id"])
    X, y = np.array(X), np.array(y)
    clf = make_pipeline(StandardScaler(), LogisticRegression(max_iter=5000, C=1.0))
    cv = cross_val_predict(clf, X, y, cv=StratifiedKFold(5, shuffle=True, random_state=0))
    clf.fit(X, y)
    conf = np.zeros((5, 5), int)
    for t, p in zip(y, cv):
        conf[t, p] += 1
    rep = dict(trained_on=int(len(y)), per_style=[int((y == k).sum()) for k in range(5)], cv_accuracy=round(float(np.mean(cv == y)), 4),
               cv_confusion_rows_true_cols_pred=conf.tolist(), features=FEATS)
    return clf, rep


# The features: chosen by 5-fold cross-validation on the training clips alone (styles_eval_cls_cv.py): LUFS, HNR, hi band,
# tilt and f0 (the goal's five) 0.986; with the rest of measure.py's clip measures and the flatness 0.997 (normal
# recall 0.965 -> 0.995), the best of the sets tried.
FEATS = ["lufs", "hnr", "hf_db", "tilt_a", "f0_med", "centroid", "hr_share", "voiced", "flat_med", "rms_db", "f0_p90", "f0_p10"]


def feats(m):
    v = [fnum(m.get(k)) for k in FEATS]
    return None if any(x != x for x in v) else v


def cmd(a):
    out = a.out
    meta = {int(r["n"]): r for r in tsv(f"{out}/lines/meta.tsv")}
    items = tsv(f"{out}/items.tsv")
    M = {r["id"]: r for r in tsv(f"{out}/measure.tsv") if r["status"] == "ok"}
    failed = [r["id"] for r in tsv(f"{out}/measure.tsv") if r["status"] != "ok"]
    z = np.load(f"{out}/emb.npz"); EMB = {str(i): e for i, e in zip(z["ids"], z["emb"])}
    unit = lambda v: v / np.linalg.norm(v)
    cen = unit(np.mean([EMB[k] for k in ("her_v12_040", "her_v12_065", "her_v12_071", "her_yume_07")], axis=0))
    cen_w = unit(np.mean([EMB[k] for k in ("w_v12_040", "w_v12_065", "w_v12_071", "w_yume_07")], axis=0))
    REF = {"soft": EMB["ref_soft"], "loud": EMB["ref_loud"], "yell": EMB["ref_yell"], "whisper": cen_w}
    th = thresholds()
    Wd = words_all(a, meta, items, M)
    clf, crep = classifier([r for r in items if r["src"] == "set"], M)
    # ---- one row per clip
    clips = []
    for it in items:
        fid = it["id"]; m = M.get(fid)
        if m is None:
            continue
        d = dict(id=fid, src=it["src"], voice=it["voice"], seed=it["seed"], sid=int(it["sid"]), n=int(it["n"]), cls=it["cls"])
        for k in ("dur", "lufs", "f0_med", "f0_p90", "hnr", "hf_db", "tilt_v", "tilt_a", "hr_share", "hr_f0", "voiced",
                  "flat_med", "flat_p95", "peak_db", "clip_n"):
            d[k] = fnum(m.get(k))
        e = EMB.get(fid)
        d["sim_her"] = float(e @ cen) if e is not None else float("nan")
        st_ = STYLES[d["sid"]]
        d["sim_ref"] = float(e @ REF[st_]) if (e is not None and st_ in REF) else float("nan")
        f = feats(m)
        d["pred"] = STYLES[int(clf.predict([f])[0])] if f is not None else ""
        if d["n"] >= 0:
            L = meta[d["n"]]
            d.update(group=L["group"], kind=L["kind"], glang=L["glang"], n_ph=int(L["n_ph"]), sec_per_ph=d["dur"] / max(1, int(L["n_ph"])),
                     text=L["text"])
            d.update(Wd.get(fid, {}))
        clips.append(d)
    os.makedirs(f"{out}/score", exist_ok=True)
    cols = ["id", "src", "voice", "seed", "sid", "n", "group", "kind", "glang", "dur", "n_ph", "sec_per_ph", "lufs", "f0_med", "f0_p90",
            "hnr", "hf_db", "tilt_v", "tilt_a", "hr_share", "hr_f0", "voiced", "flat_med", "flat_p95", "peak_db", "clip_n", "sim_her",
            "sim_ref", "pred", "w_ok", "w_npass", "w_err", "w_e1", "w_e2", "w_e3", "sh", "w_gate", "heard", "text"]
    fm = lambda v: (f"{v:.4f}" if isinstance(v, float) else str(v)).replace("\t", " ")
    with open(f"{out}/score/clips.tsv", "w", encoding="utf-8") as o:
        o.write("\t".join(cols) + "\n")
        for d in clips:
            o.write("\t".join(fm(d.get(c, "")) for c in cols) + "\n")
    # ---- sid 0 summary per voice and seed
    by = {}
    for d in clips:
        if d["src"] == "gen":
            by.setdefault((d["voice"], d["seed"], d["sid"]), []).append(d)

    def s0(rows):
        k = lambda kind: nmean([r["w_err"] for r in rows if r["kind"] == kind])
        return dict(ja_err=k("ja"), en_err=k("en"), mixed_err=k("mixed"), sim_her=nmean([r["sim_her"] for r in rows]),
                    f0=nmed([r["f0_med"] for r in rows]), sec_per_ph=nmed([r["sec_per_ph"] for r in rows]),
                    flat_p50=nmed([r["flat_med"] for r in rows]), flat_hi=npct([r["flat_p95"] for r in rows], 95),
                    hnr_p50=nmed([r["hnr"] for r in rows]), hnr_p5=npct([r["hnr"] for r in rows], 5),
                    words_share=nmean([r["w_ok"] for r in rows]), clips=len(rows),
                    f0_max=max([r["f0_med"] for r in rows], default=float("nan")),
                    not_normal=sum(r["pred"] != "normal" for r in rows))
    base = a.base
    base_seeds = sorted({k[1] for k in by if k[0] == base and k[2] == 0})
    seeds0 = a.seeds0.split()
    B = {s: s0(by[(base, s, 0)]) for s in base_seeds}
    KEYS0 = ["ja_err", "en_err", "mixed_err", "sim_her", "f0", "sec_per_ph", "flat_p50", "flat_hi", "hnr_p50", "hnr_p5"]
    ref = {k: nmean([B[s][k] for s in seeds0 if s in B]) for k in KEYS0}
    noise = {k: (max(B[s][k] for s in base_seeds) - min(B[s][k] for s in base_seeds)) if len(base_seeds) >= 2 else float("nan") for k in KEYS0}
    noise_pair = {k: abs(B[seeds0[0]][k] - B[seeds0[1]][k]) if all(s in B for s in seeds0[:2]) else float("nan") for k in KEYS0}
    res = dict(base=base, base_seeds=base_seeds, seeds0=seeds0, base_runs=B, base_ref=ref, noise_spread=noise, noise_first_pair=noise_pair,
               thresholds=th, classifier=crep, words_share_min=a.words_share, failed_measures=failed, candidates={})
    # baseline e974 through the same sid 0 checks (it must pass its own gate: a check of the gate)
    voices = sorted({k[0] for k in by}, key=lambda v: (v != base, int(v[1:]) if v[1:].isdigit() else 0))
    # real held-out clips per style (the sets' own numbers, for the table)
    real = {}
    for s in STYLES[1:]:
        rr = [d for d in clips if d["src"] == "real" and d["cls"] == s and d.get("group", "").endswith("_val")]
        real[s] = style_summary(rr, s, th) if rr else {}
    res["real_heldout"] = real
    for v in voices:
        runs0 = [s0(by[(v, s, 0)]) for s in seeds0 if (v, s, 0) in by]
        if not runs0:
            continue
        c = {k: nmean([r[k] for r in runs0]) for k in KEYS0}
        g = {}
        for k in ("ja_err", "en_err", "mixed_err", "flat_p50", "flat_hi"):
            g[k] = dict(value=c[k], ref=ref[k], noise=noise[k], delta=c[k] - ref[k], ok=bool(c[k] <= ref[k] + noise[k] + E))
        for k in ("sim_her", "hnr_p50", "hnr_p5"):
            g[k] = dict(value=c[k], ref=ref[k], noise=noise[k], delta=c[k] - ref[k], ok=bool(c[k] >= ref[k] - noise[k] - E))
        g["f0"] = dict(value=c["f0"], ref=ref["f0"], delta=c["f0"] - ref["f0"], ok=bool(abs(c["f0"] - ref["f0"]) <= 5.0 + E))
        g["sec_per_ph"] = dict(value=c["sec_per_ph"], ref=ref["sec_per_ph"], rel=c["sec_per_ph"] / ref["sec_per_ph"] - 1,
                               ok=bool(abs(c["sec_per_ph"] / ref["sec_per_ph"] - 1) <= 0.05 + E))
        rows0 = [d for s in seeds0 for d in by.get((v, s, 0), [])]
        g["f0_cap"] = dict(value=max(d["f0_med"] for d in rows0), ok=bool(all(0 < d["f0_med"] <= 345 for d in rows0)))
        nn = [d["id"] for d in rows0 if d["pred"] != "normal"]
        g["class_normal"] = dict(value=1 - len(nn) / max(1, len(rows0)), not_normal=nn,
                                 to=sorted({d["pred"] for d in rows0 if d["pred"] != "normal"}), ok=not nn)
        cand = dict(sid0=g, sid0_ok=all(x["ok"] for x in g.values()), sid0_words_share=nmean([r["words_share"] for r in runs0]))
        if v != base:
            sty = {}
            for sid in range(1, 5):
                s = STYLES[sid]
                rows = [d for d in by.get((v, a.seed_style, sid), []) if d.get("group") == f"{s}_val"]
                extra = [d for d in by.get((v, a.seed_style, sid), []) if d.get("group") != f"{s}_val"]
                if not rows:
                    continue
                sm = style_summary(rows, s, th, a.words_share)
                if extra:  # the left-out yell lines: pitch counts (every voiced clip), words reported
                    sm["extra_lines"] = dict(clips=len(extra), words_share=nmean([d.get("w_ok", float("nan")) for d in extra]),
                                             f0_max=max(d["f0_med"] for d in extra), sim_her=nmed([d["sim_her"] for d in extra]))
                    sm["gates"]["pitch"]["ok"] = bool(sm["gates"]["pitch"]["ok"] and all(0 < d["f0_med"] <= 345 for d in extra))
                    sm["gates"]["pitch"]["value_extra"] = sm["extra_lines"]["f0_max"]
                sty[s] = sm
            cand["styles"] = sty
            cand["styles_ok"] = all(all(x["ok"] for x in sm["gates"].values()) for sm in sty.values()) and len(sty) == 4
            cand["all_ok"] = cand["sid0_ok"] and cand["styles_ok"]
            cand["style_words_norm_err"] = nmean([d["w_err"] / d["w_gate"] for s in sty for d in by.get((v, a.seed_style, STYLES.index(s)), [])
                                                   if d.get("group") == f"{s}_val" and d.get("w_gate")])
            cand["min_class"] = min(sm["gates"]["class"]["value"] for sm in sty.values()) if sty else float("nan")
            cand["sid0_words_delta"] = sum(g[k]["delta"] for k in ("ja_err", "en_err", "mixed_err"))
        res["candidates"][v] = cand
    # ---- the choice: among the candidates passing every gate, the lowest rank sum of (style words error, -lowest style
    # classifier share, sid 0 words change against e974); ties: the lower style words error
    passing = [v for v, c in res["candidates"].items() if v != base and c.get("all_ok")]
    if passing:
        rk = {}
        for key, sign in (("style_words_norm_err", 1), ("min_class", -1), ("sid0_words_delta", 1)):
            order = sorted(passing, key=lambda v: sign * res["candidates"][v][key])
            for i, v in enumerate(order):
                rk[v] = rk.get(v, 0) + i
        res["choice"] = sorted(passing, key=lambda v: (rk[v], res["candidates"][v]["style_words_norm_err"]))[0]
        res["rank_sum"] = rk
    else:
        res["choice"] = None
    res["passing"] = passing
    json.dump(res, open(f"{out}/score/gates.json", "w"), indent=1, ensure_ascii=False, default=float)
    table(res, out)
    print("choice:", res["choice"], "passing:", passing)
    print("SCORE-DONE")


def style_summary(rows, s, th, words_share=0.9):
    T = th[s]
    med = lambda k: nmed([d[k] for d in rows])
    sm = dict(clips=len(rows), lufs=med("lufs"), hf_db=med("hf_db"), hnr=med("hnr"), tilt_v=med("tilt_v"), hr_share=med("hr_share"),
              f0=med("f0_med"), f0_max=max(d["f0_med"] for d in rows), p90_max=max(d["f0_p90"] for d in rows),
              sim_her_ja=nmed([d["sim_her"] for d in rows if d.get("glang") == "ja"]), sim_her_en=nmed([d["sim_her"] for d in rows if d.get("glang") == "en"]),
              sim_ref_ja=nmed([d["sim_ref"] for d in rows if d.get("glang") == "ja"]), sim_ref_en=nmed([d["sim_ref"] for d in rows if d.get("glang") == "en"]),
              words_share=nmean([d.get("w_ok", float("nan")) for d in rows]), words_err=nmean([d.get("w_err", float("nan")) for d in rows]),
              class_share=nmean([float(d["pred"] == s) for d in rows]),
              class_to={p: sum(d["pred"] == p for d in rows) for p in STYLES if any(d["pred"] == p for d in rows)})
    g = {}
    if s == "soft":
        ok = sm["lufs"] <= T["max_lufs"] + E and sm["hf_db"] <= T["max_hi"] + E and sm["hnr"] >= T["min_hnr"] - E
        g["style"] = dict(ok=bool(ok), need=f"LUFS <= {T['max_lufs']}, hi <= {T['max_hi']}, HNR >= {T['min_hnr']}")
    elif s == "whisper":
        ok = sm["hnr"] <= T["hnr_max"] + E and sm["hr_share"] <= T["hr_share_max"] + E
        g["style"] = dict(ok=bool(ok), need=f"HNR <= {T['hnr_max']}, hr_share <= {T['hr_share_max']}")
    else:
        ok = sm["lufs"] >= T["min_lufs"] - E and sm["hf_db"] >= T["min_hi"] - E and sm["tilt_v"] >= T["min_tilt"] - E
        g["style"] = dict(ok=bool(ok), need=f"LUFS >= {T['min_lufs']}, hi >= {T['min_hi']}, tilt >= {T['min_tilt']}")
    if s == "whisper":
        fl = T["consistency_floor_sim_w"]; lo_ja = max(T["sim_w_min"], fl["ja+mix_ja"]); lo_en = max(T["sim_w_min"], fl["en+mix_en"])
        ok = (sm["sim_ref_ja"] != sm["sim_ref_ja"] or sm["sim_ref_ja"] >= lo_ja - E) and (sm["sim_ref_en"] != sm["sim_ref_en"] or sm["sim_ref_en"] >= lo_en - E)
        g["timbre"] = dict(ok=bool(ok), need=f"sim_w ja >= {lo_ja:.4f}, en >= {lo_en:.4f}")
    else:
        key = (lambda l: f"yell:{l}") if s == "yell" else (lambda l: l)
        sh, sr = T["sim_her"], T["sim_ref"]
        ok = True
        for l in ("ja", "en"):
            vh, vr = sm[f"sim_her_{l}"], sm[f"sim_ref_{l}"]
            if vh == vh:
                ok = ok and vh >= sh[key(l)] - E and vr >= sr[key(l)] - E
        g["timbre"] = dict(ok=bool(ok), need=f"sim_her ja >= {sh[key('ja')]}, en >= {sh[key('en')]}; sim_ref ja >= {sr[key('ja')]}, en >= {sr[key('en')]}")
    g["words"] = dict(ok=bool(sm["words_share"] >= words_share - E), value=sm["words_share"], need=f">= {words_share}")
    if s == "whisper":
        okp = all((d["hr_share"] <= 0 or d["hr_f0"] <= 345) for d in rows)
        g["pitch"] = dict(ok=bool(okp), value=max([d["hr_f0"] for d in rows if d["hr_share"] > 0], default=0.0))
    else:
        okp = all(0 < d["f0_med"] <= 345 and d["f0_p90"] <= 500 for d in rows)
        g["pitch"] = dict(ok=bool(okp), value=sm["f0_max"], p90_max=sm["p90_max"])
    g["class"] = dict(ok=bool(sm["class_share"] >= 0.9 - E), value=sm["class_share"])
    sm["gates"] = g
    return sm


def table(res, out):
    """One row per candidate, every gate: the value, and PASS/fail."""
    C = res["candidates"]
    lines = []
    hdr = ["voice", "ALL", "s0 ja", "s0 en", "s0 mix", "s0 sim", "s0 f0", "s0 s/ph", "s0 flat", "s0 flatHi", "s0 hnr", "s0 hnr5", "s0 cls",
           "soft st", "soft tim", "soft wd", "soft cls", "whis st", "whis tim", "whis wd", "whis cls", "loud st", "loud tim", "loud wd",
           "loud cls", "yell st", "yell tim", "yell wd", "yell cls", "pitch"]
    rows = []
    for v, c in C.items():
        g = c["sid0"]
        f = lambda k, fmt="{:+.3f}": (fmt.format(g[k].get("delta", g[k].get("value"))) + ("" if g[k]["ok"] else " X"))
        r = [v, ("PASS" if c.get("all_ok") else ("base" if v == res["base"] else "fail")), f("ja_err"), f("en_err"), f("mixed_err"), f("sim_her"),
             f("f0", "{:+.1f}"), (f"{100 * g['sec_per_ph']['rel']:+.1f}%" + ("" if g["sec_per_ph"]["ok"] else " X")), f("flat_p50", "{:+.4f}"),
             f("flat_hi", "{:+.4f}"), f("hnr_p50", "{:+.2f}"), f("hnr_p5", "{:+.2f}"),
             (f"{len(g['class_normal']['not_normal'])} off" + ("" if g["class_normal"]["ok"] else " X"))]
        pitch_ok = g["f0_cap"]["ok"]
        for s in STYLES[1:]:
            sm = c.get("styles", {}).get(s)
            if not sm:
                r += ["", "", "", ""]; continue
            G = sm["gates"]
            if s == "soft":
                sv = f"{sm['lufs']:.1f}/{sm['hf_db']:.1f}/{sm['hnr']:.1f}"
            elif s == "whisper":
                sv = f"{sm['hnr']:.1f}/{sm['hr_share']:.3f}"
            else:
                sv = f"{sm['lufs']:.1f}/{sm['hf_db']:.1f}/{sm['tilt_v']:.1f}"
            tv = f"{sm['sim_her_ja']:.3f}/{sm['sim_ref_ja']:.3f}"
            r += [sv + ("" if G["style"]["ok"] else " X"), tv + ("" if G["timbre"]["ok"] else " X"),
                  f"{sm['words_share']:.2f}" + ("" if G["words"]["ok"] else " X"), f"{sm['class_share']:.2f}" + ("" if G["class"]["ok"] else " X")]
            pitch_ok = pitch_ok and G["pitch"]["ok"]
        r.append("ok" if pitch_ok else "X")
        rows.append(r)
    with open(f"{out}/score/table.tsv", "w", encoding="utf-8") as o:
        o.write("\t".join(hdr) + "\n")
        for r in rows:
            o.write("\t".join(r) + "\n")
    with open(f"{out}/score/table.md", "w", encoding="utf-8") as o:
        o.write("| " + " | ".join(hdr) + " |\n|" + "---|" * len(hdr) + "\n")
        for r in rows:
            o.write("| " + " | ".join(r) + " |\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/w/range_build/styles/eval")
    ap.add_argument("--base", default="e974")
    ap.add_argument("--seeds0", default="1234 5678")
    ap.add_argument("--seed-style", default="1234")
    ap.add_argument("--words-share", type=float, default=0.9)
    cmd(ap.parse_args())
