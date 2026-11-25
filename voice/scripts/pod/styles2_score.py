"""Rejudging the five-style voice: every style on every gate of GATES.md (gsv-env; reads what styles_eval.py wrote
under --out, and yesterday's sid 0 gates from --s0). No voice data in this file.

Per clip it uses yesterday's code unchanged (styles_eval_score.py): words_all (the per-line words rules, judged by the
line's own style, so her normal voice speaking a style's line is held to that style's rule), the classifier (trained
on yesterday's 1,000 training clips), style_summary (the STYLE, TIMBRE, PITCH and CLASSIFIER gates with the sets'
thresholds). What is new is only the WORDS gate: the style (e1749, its sid) against her shipped voice (e974, sid 0) on
the same lines, per line the mean over the seeds, a paired bootstrap over the lines (90 % interval), pass iff the
style is not shown worse: upper end of D_share >= 0 and lower end of D_err <= 0. Then the settings grid
(styles2_knobs.sh tags), each against the default with the same seeds and lines.
Writes <out>/score2/{gates2.json, table.md, lines_words.tsv, clips2.tsv, knobs.md}.
"""
import argparse
import csv
import json
import os
import sys

import numpy as np

sys.path.insert(0, "/w/job/scripts")
import styles_eval_score as S  # noqa: E402

STYLES = S.STYLES
B_N, B_SEED = 20000, 20261125


def boot(a, b, n=B_N, seed=B_SEED):
    """Paired bootstrap over lines of mean(a) - mean(b): (point, lo5, hi95)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(a), (n, len(a)))
    d = a[idx].mean(1) - b[idx].mean(1)
    return float(a.mean() - b.mean()), float(np.percentile(d, 5)), float(np.percentile(d, 95))


def per_line(rows, key):
    """{n: mean over the clips (seeds) of key}, NaN clips left out."""
    acc = {}
    for d in rows:
        v = d.get(key, float("nan"))
        v = float(v) if v not in ("", None) else float("nan")
        if v == v:
            acc.setdefault(d["n"], []).append(v)
    return {n: float(np.mean(v)) for n, v in acc.items()}


def compare(rows_a, rows_b):
    """WORDS comparison of two clip sets on their common lines."""
    sa, sb = per_line(rows_a, "w_ok"), per_line(rows_b, "w_ok")
    ea, eb = per_line(rows_a, "w_err"), per_line(rows_b, "w_err")
    common = sorted(set(sa) & set(sb) & set(ea) & set(eb))
    if not common:
        nan = float("nan")
        return dict(lines=0, share_a=nan, share_b=nan, d_share=nan, d_share_lo=nan, d_share_hi=nan, err_a=nan, err_b=nan, d_err=nan,
                    d_err_lo=nan, d_err_hi=nan, ok=False)
    A, B = [sa[n] for n in common], [sb[n] for n in common]
    EA, EB = [ea[n] for n in common], [eb[n] for n in common]
    ds, ds_lo, ds_hi = boot(A, B)
    de, de_lo, de_hi = boot(EA, EB)
    return dict(lines=len(common), share_a=float(np.mean(A)), share_b=float(np.mean(B)), d_share=ds, d_share_lo=ds_lo, d_share_hi=ds_hi,
                err_a=float(np.mean(EA)), err_b=float(np.mean(EB)), d_err=de, d_err_lo=de_lo, d_err_hi=de_hi,
                ok=bool(ds_hi >= 0 and de_lo <= 0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/w/range_build/styles2/eval")
    ap.add_argument("--s0", default="/w/range_build/styles2/eval_s0/score/gates.json")
    ap.add_argument("--cand", default="e1749"); ap.add_argument("--base", default="e974")
    ap.add_argument("--seeds", default="2101 2202 2303 2404")
    ap.add_argument("--knob-seeds", default="2101 2202"); ap.add_argument("--confirm-seeds", default="2303 2404")
    a = ap.parse_args()
    out, seeds = a.out, a.seeds.split()
    meta = {int(r["n"]): r for r in S.tsv(f"{out}/lines/meta.tsv")}
    items = S.tsv(f"{out}/items.tsv")
    mrows = S.tsv(f"{out}/measure.tsv")
    M = {r["id"]: r for r in mrows if r["status"] == "ok"}
    failed = [r["id"] for r in mrows if r["status"] != "ok"]
    z = np.load(f"{out}/emb.npz"); EMB = {str(i): e for i, e in zip(z["ids"], z["emb"])}
    unit = lambda v: v / np.linalg.norm(v)
    cen = unit(np.mean([EMB[k] for k in ("her_v12_040", "her_v12_065", "her_v12_071", "her_yume_07")], axis=0))
    cen_w = unit(np.mean([EMB[k] for k in ("w_v12_040", "w_v12_065", "w_v12_071", "w_yume_07")], axis=0))
    REF = {"soft": EMB["ref_soft"], "loud": EMB["ref_loud"], "yell": EMB["ref_yell"], "whisper": cen_w}
    th = S.thresholds()
    Wd = S.words_all(a, meta, items, M, by_line=True)
    clf, crep = S.classifier([r for r in items if r["src"] == "set"], M)
    clips = []
    for it in items:
        fid = it["id"]; m = M.get(fid)
        if m is None or it["src"] == "set":
            continue
        d = dict(id=fid, src=it["src"], voice=it["voice"], seed=it["seed"], sid=int(it["sid"]), n=int(it["n"]), cls=it["cls"])
        for k in ("dur", "lufs", "f0_med", "f0_p90", "hnr", "hf_db", "tilt_v", "tilt_a", "hr_share", "hr_f0", "voiced", "flat_med",
                  "flat_p95", "peak_db", "clip_n"):
            d[k] = S.fnum(m.get(k))
        e = EMB.get(fid); st_ = STYLES[d["sid"]]
        d["sim_her"] = float(e @ cen) if e is not None else float("nan")
        d["sim_ref"] = float(e @ REF[st_]) if (e is not None and st_ in REF) else float("nan")
        f = S.feats(m)
        d["pred"] = STYLES[int(clf.predict([f])[0])] if f is not None else ""
        L = meta[d["n"]]
        d.update(group=L["group"], kind=L["kind"], glang=L["glang"], n_ph=int(L["n_ph"]), text=L["text"], line_style=L["style"])
        d.update(Wd.get(fid, {}))
        clips.append(d)
    os.makedirs(f"{out}/score2", exist_ok=True)
    cols = ["id", "src", "voice", "seed", "sid", "n", "group", "kind", "glang", "line_style", "dur", "lufs", "f0_med", "f0_p90", "hnr",
            "hf_db", "tilt_v", "tilt_a", "hr_share", "hr_f0", "voiced", "flat_med", "flat_p95", "sim_her", "sim_ref", "pred", "w_ok",
            "w_npass", "w_err", "w_e1", "w_e2", "w_e3", "sh", "w_gate", "heard", "text"]
    fm = lambda v: (f"{v:.4f}" if isinstance(v, float) else str(v)).replace("\t", " ")
    with open(f"{out}/score2/clips2.tsv", "w", encoding="utf-8") as o:
        o.write("\t".join(cols) + "\n")
        for d in clips:
            o.write("\t".join(fm(d.get(c, "")) for c in cols) + "\n")

    def sel(voice, sid, groups, sds=seeds):
        return [d for d in clips if d["src"] == "gen" and d["voice"] == voice and d["sid"] == sid and d["group"] in groups and d["seed"] in sds]

    res = dict(cand=a.cand, base=a.base, seeds=seeds, classifier=crep, failed_measures=failed, bootstrap=dict(resamples=B_N, seed=B_SEED), styles={})
    # sid 0: yesterday's gates, run by yesterday's code on the sid 0 gate set
    if os.path.exists(a.s0):
        g0 = json.load(open(a.s0))
        c0 = g0["candidates"].get(a.cand, {})
        res["sid0"] = dict(ok=c0.get("sid0_ok"), gates=c0.get("sid0"), words_share=c0.get("sid0_words_share"), base_runs=g0.get("base_runs"),
                           base_ref=g0.get("base_ref"), noise=g0.get("noise_spread"), seeds0=g0.get("seeds0"), base_seeds=g0.get("base_seeds"),
                           e974_words_share=(g0["candidates"].get(a.base) or {}).get("sid0_words_share"))
    line_rows = []
    for sid in range(1, 5):
        s = STYLES[sid]
        G = {f"{s}_new", f"{s}_val"}
        ra, rb, rc = sel(a.cand, sid, G), sel(a.base, 0, G), sel(a.cand, 0, G)
        extra = [d for d in clips if d["src"] == "gen" and d["voice"] == a.cand and d["sid"] == sid and d["group"].endswith("_excluded")
                 and d["seed"] in seeds]
        sm = S.style_summary(ra, s, th)
        sm["gates"].pop("words")   # yesterday's 0.90 bar: replaced by the comparison below (GATES.md)
        if extra:
            sm["extra_lines"] = dict(clips=len(extra), f0_max=max(d["f0_med"] for d in extra), sim_her=S.nmed([d["sim_her"] for d in extra]),
                                     words_share=S.nmean([d.get("w_ok", float("nan")) for d in extra]))
            sm["gates"]["pitch"]["ok"] = bool(sm["gates"]["pitch"]["ok"] and all(0 < d["f0_med"] <= 345 for d in extra))
            sm["gates"]["pitch"]["value_extra"] = sm["extra_lines"]["f0_max"]
        w = compare(ra, rb)
        sm["gates"]["words"] = dict(ok=w["ok"], **w)
        sm["all_ok"] = all(g["ok"] for g in sm["gates"].values())
        sm["words_vs_e1749_sid0"] = compare(ra, rc)
        sm["e1749_sid0_vs_e974"] = compare(rc, rb)
        for part in ("new", "val"):
            gp = {f"{s}_{part}"}
            sm[f"words_{part}_only"] = compare(sel(a.cand, sid, gp), sel(a.base, 0, gp))
            smp = S.style_summary(sel(a.cand, sid, gp), s, th)
            sm[f"gates_{part}_only"] = {k: dict(ok=v["ok"], value=v.get("value")) for k, v in smp["gates"].items() if k != "words"}
            sm[f"class_{part}_only"] = smp["class_share"]
        per_seed = {}
        for sd in seeds:
            q = S.style_summary(sel(a.cand, sid, G, [sd]), s, th)
            per_seed[sd] = dict(class_share=q["class_share"], words_share=q["words_share"], style_ok=q["gates"]["style"]["ok"],
                                timbre_ok=q["gates"]["timbre"]["ok"], pitch_ok=q["gates"]["pitch"]["ok"],
                                e974_words_share=S.nmean([d["w_ok"] for d in sel(a.base, 0, G, [sd]) if "w_ok" in d]))
        sm["per_seed"] = per_seed
        # the A/A noise: e974's share seed against seed, and half against half
        b_seed = [per_seed[sd]["e974_words_share"] for sd in seeds]
        sm["e974_noise"] = dict(per_seed=b_seed, spread=float(max(b_seed) - min(b_seed)),
                                half_vs_half=compare(sel(a.base, 0, G, seeds[:2]), sel(a.base, 0, G, seeds[2:])))
        sm["sid0_lines_classed"] = {v: {p: sum(d["pred"] == p for d in sel(v, 0, G)) for p in STYLES} for v in (a.base, a.cand)}
        res["styles"][s] = sm
        sa, sb, sc = per_line(ra, "w_ok"), per_line(rb, "w_ok"), per_line(rc, "w_ok")
        ea, eb, ec = per_line(ra, "w_err"), per_line(rb, "w_err"), per_line(rc, "w_err")
        for n in sorted(set(sa) | set(sb)):
            line_rows.append(dict(style=s, n=n, group=meta[n]["group"], kind=meta[n]["kind"], share_style=sa.get(n, ""), share_e974=sb.get(n, ""),
                                  share_e1749_sid0=sc.get(n, ""), err_style=ea.get(n, ""), err_e974=eb.get(n, ""), err_e1749_sid0=ec.get(n, ""),
                                  text=meta[n]["text"]))
    # every voiced output under the 345 Hz cap (whisper: its harmonic runs)
    caps = {}
    for d in clips:
        if d["src"] != "gen":
            continue
        key = f"{d['voice']}/sid{d['sid']}"
        v = d["hr_f0"] if d["sid"] == 2 else d["f0_med"]
        if v == v and (d["sid"] != 2 or d["hr_share"] > 0):
            caps[key] = max(caps.get(key, 0.0), v)
    res["f0_max_per_voice_sid"] = caps
    res["f0_over_345"] = sorted(d["id"] for d in clips if d["src"] == "gen" and (
        (d["sid"] != 2 and d["f0_med"] > 345) or (d["sid"] == 2 and d["hr_share"] > 0 and d["hr_f0"] > 345)))
    # the settings grid against the default (same lines, same seeds)
    knobs = {}
    kt = f"{out}/knobs.tsv"
    if os.path.exists(kt):
        ks, cs = a.knob_seeds.split(), a.confirm_seeds.split()
        for r in S.tsv(kt):
            tag = r["tag"]; v = f"{a.cand}{tag}"
            kr = dict(setting=dict(noise_scale=float(r["noise_scale"]), noise_scale_w=float(r["noise_scale_w"]), length_scale=float(r["length_scale"])), styles={})
            for sid in range(1, 5):
                s = STYLES[sid]
                rk, rd = sel(v, sid, {f"{s}_new"}, ks), sel(a.cand, sid, {f"{s}_new"}, ks)
                if not rk:
                    continue
                qk, qd = S.style_summary(rk, s, th), S.style_summary(rd, s, th)
                w = compare(rk, rd)
                gk = {k: g["ok"] for k, g in qk["gates"].items() if k != "words"}
                qual = bool(w["d_share_lo"] > 0 and gk["style"] and gk["timbre"] and gk["pitch"] and qk["class_share"] >= qd["class_share"] - 0.05)
                e = dict(words=w, gates=gk, class_share=qk["class_share"], class_default=qd["class_share"], lufs=qk["lufs"], hnr=qk["hnr"],
                         hf_db=qk["hf_db"], tilt_v=qk["tilt_v"], hr_share=qk["hr_share"], sim_her_ja=qk["sim_her_ja"], sim_ref_ja=qk["sim_ref_ja"],
                         sim_her_ja_default=qd["sim_her_ja"], f0=qk["f0"], f0_max=qk["f0_max"], vs_e974=compare(rk, sel(a.base, 0, {f"{s}_new"}, ks)),
                         qualifies=qual, sec=S.nmean([d["dur"] for d in rk]), sec_default=S.nmean([d["dur"] for d in rd]))
                rkc = sel(v, sid, {f"{s}_val"}, cs)
                if rkc:
                    rdc = sel(a.cand, sid, {f"{s}_val"}, cs)
                    qc = S.style_summary(rkc, s, th)
                    wc = compare(rkc, rdc)
                    e["confirm"] = dict(words=wc, gates={k: g["ok"] for k, g in qc["gates"].items() if k != "words"}, class_share=qc["class_share"],
                                        class_default=S.style_summary(rdc, s, th)["class_share"])
                    e["confirmed"] = bool(qual and wc["d_share_lo"] > 0 and all(e["confirm"]["gates"][k] for k in ("style", "timbre", "pitch"))
                                          and e["confirm"]["class_share"] >= e["confirm"]["class_default"] - 0.05)
                kr["styles"][s] = e
            knobs[tag] = kr
    res["knobs"] = knobs
    json.dump(res, open(f"{out}/score2/gates2.json", "w"), indent=1, ensure_ascii=False, default=float)
    with open(f"{out}/score2/lines_words.tsv", "w", encoding="utf-8") as o:
        c = list(line_rows[0].keys()) if line_rows else []
        o.write("\t".join(c) + "\n")
        for r in line_rows:
            o.write("\t".join(fm(r[k]) for k in c) + "\n")
    tables(res, out)
    print("STYLES2-SCORE-DONE")


def tables(res, out):
    L = []
    s0 = res.get("sid0")
    if s0:
        L.append(f"## sid 0 (yesterday's gates, e974 seeds {' '.join(s0['base_seeds'])}, candidate seeds {' '.join(s0['seeds0'])}): "
                 f"{'PASS' if s0['ok'] else 'FAIL'}\n")
        L.append("| gate | e1749 | e974 | noise | delta | ok |\n|---|---|---|---|---|---|")
        for k, g in (s0["gates"] or {}).items():
            if k in ("f0_cap", "class_normal"):
                L.append(f"| {k} | {g['value']:.3f} | | | | {'ok' if g['ok'] else 'FAIL'} |"); continue
            delta = g.get("delta", g.get("rel"))
            L.append(f"| {k} | {g['value']:.4f} | {g['ref']:.4f} | {g.get('noise', float('nan')):.4f} | {delta:+.4f} | {'ok' if g['ok'] else 'FAIL'} |")
        L.append(f"\nwords share (info): e1749 {s0['words_share']:.3f}, e974 {s0['e974_words_share']}\n")
    L.append("## Styles (e1749 with the style's sid; all four seeds pooled; new + held-out lines)\n")
    L.append("| style | lines | clips | STYLE | TIMBRE ja/en (her, ref) | PITCH max f0 | CLASS | WORDS share style / e974 (D, 90 % CI) | "
             "WORDS err style / e974 (D, 90 % CI) | ALL |\n|---|---|---|---|---|---|---|---|---|---|")
    for s, sm in res["styles"].items():
        G = sm["gates"]; w = G["words"]
        if s == "soft":
            sv = f"LUFS {sm['lufs']:.1f}, hi {sm['hf_db']:.1f}, HNR {sm['hnr']:.1f} ({G['style']['need']})"
        elif s == "whisper":
            sv = f"HNR {sm['hnr']:.2f}, hr_share {sm['hr_share']:.3f} ({G['style']['need']})"
        else:
            sv = f"LUFS {sm['lufs']:.1f}, hi {sm['hf_db']:.1f}, tilt {sm['tilt_v']:.1f} ({G['style']['need']})"
        tv = (f"ja {sm['sim_her_ja']:.3f}/{sm['sim_ref_ja']:.3f}, en {sm['sim_her_en']:.3f}/{sm['sim_ref_en']:.3f} ({G['timbre']['need']})")
        pv = f"{G['pitch']['value']:.0f} Hz" + (f" (left-out lines {G['pitch']['value_extra']:.0f})" if "value_extra" in G["pitch"] else "")
        ok = lambda k: "" if G[k]["ok"] else " FAIL"
        L.append(f"| {s} | {w['lines']} | {sm['clips']} | {sv}{ok('style')} | {tv}{ok('timbre')} | {pv}{ok('pitch')} | {sm['class_share']:.3f}{ok('class')} | "
                 f"{w['share_a']:.3f} / {w['share_b']:.3f} ({w['d_share']:+.3f}, {w['d_share_lo']:+.3f}..{w['d_share_hi']:+.3f}){ok('words')} | "
                 f"{w['err_a']:.3f} / {w['err_b']:.3f} ({w['d_err']:+.3f}, {w['d_err_lo']:+.3f}..{w['d_err_hi']:+.3f}) | {'PASS' if sm['all_ok'] else 'FAIL'} |")
    L.append("\n### Words, beside the gate (not deciding)\n")
    L.append("| style | new only: style / e974 (D, CI) | held-out only: style / e974 (D, CI) | style vs e1749 sid 0 (D, CI) | e1749 sid 0 vs e974 (D, CI) | "
             "e974 share per seed (spread) | e974 half vs half (D, CI) |\n|---|---|---|---|---|---|---|")
    f = lambda w: f"{w['share_a']:.3f} / {w['share_b']:.3f} ({w['d_share']:+.3f}, {w['d_share_lo']:+.3f}..{w['d_share_hi']:+.3f})"
    for s, sm in res["styles"].items():
        nz = sm["e974_noise"]
        L.append(f"| {s} | {f(sm['words_new_only'])} | {f(sm['words_val_only'])} | {f(sm['words_vs_e1749_sid0'])} | {f(sm['e1749_sid0_vs_e974'])} | "
                 f"{' '.join(f'{x:.3f}' for x in nz['per_seed'])} ({nz['spread']:.3f}) | {f(nz['half_vs_half'])} |")
    L.append("\n### Per seed (style clips) and the other gates on each part\n")
    L.append("| style | class per seed | words per seed (style / e974) | new only: style timbre pitch class | held-out only: style timbre pitch class |\n|---|---|---|---|---|")
    for s, sm in res["styles"].items():
        ps = sm["per_seed"]
        part = lambda p: " ".join(("ok" if sm[f"gates_{p}_only"][k]["ok"] else "FAIL") for k in ("style", "timbre", "pitch", "class")) + f" ({sm[f'class_{p}_only']:.3f})"
        cls_ = " ".join("%.3f" % v["class_share"] for v in ps.values())
        wds_ = " ".join("%.2f/%.2f" % (v["words_share"], v["e974_words_share"]) for v in ps.values())
        L.append(f"| {s} | {cls_} | {wds_} | {part('new')} | {part('val')} |")
    L.append("\n### Where the style lines spoken with sid 0 are classed (info)\n")
    for s, sm in res["styles"].items():
        L.append(f"- {s}: " + "; ".join(f"{v}: " + ", ".join(f"{p} {c}" for p, c in cc.items() if c) for v, cc in sm["sid0_lines_classed"].items()))
    L.append(f"\nf0 max per voice and sid (whisper: harmonic runs): " + ", ".join(f"{k} {v:.0f}" for k, v in sorted(res["f0_max_per_voice_sid"].items())))
    L.append(f"clips over 345 Hz: {len(res['f0_over_345'])} {res['f0_over_345'][:10]}")
    open(f"{out}/score2/table.md", "w", encoding="utf-8").write("\n".join(L) + "\n")
    K = ["| setting (ns, nsw, ls) | style | words share knob / default (D, 90 % CI) | vs e974 (D) | err D | style timbre pitch | class knob / default | "
         "sim_her ja knob / default | sec knob / default | qualifies | confirmed on held-out |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for tag, kr in res["knobs"].items():
        st_ = kr["setting"]
        for s, e in kr["styles"].items():
            w = e["words"]
            conf = ""
            if "confirm" in e:
                wc = e["confirm"]["words"]
                conf = f"{'YES' if e.get('confirmed') else 'no'} ({wc['share_a']:.3f}/{wc['share_b']:.3f}, {wc['d_share_lo']:+.3f}..{wc['d_share_hi']:+.3f})"
            K.append(f"| {tag} ({st_['noise_scale']}, {st_['noise_scale_w']}, {st_['length_scale']}) | {s} | {w['share_a']:.3f} / {w['share_b']:.3f} "
                     f"({w['d_share']:+.3f}, {w['d_share_lo']:+.3f}..{w['d_share_hi']:+.3f}) | {e['vs_e974']['d_share']:+.3f} | {w['d_err']:+.3f} | "
                     f"{' '.join('ok' if e['gates'][k] else 'FAIL' for k in ('style', 'timbre', 'pitch'))} | {e['class_share']:.3f} / {e['class_default']:.3f} | "
                     f"{e['sim_her_ja']:.3f} / {e['sim_her_ja_default']:.3f} | {e['sec']:.2f} / {e['sec_default']:.2f} | {'YES' if e['qualifies'] else 'no'} | {conf} |")
    open(f"{out}/score2/knobs.md", "w", encoding="utf-8").write("\n".join(K) + "\n")


if __name__ == "__main__":
    main()
