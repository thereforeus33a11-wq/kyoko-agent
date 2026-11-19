"""Score her phone voice candidates (and e800 today) on the held-out lines and her_test.txt, against the
teacher, and pick one. Reads check_lang.py's asr_*.tsv and prep.tsv in each candidate's work folder.

Usage: python score_student.py --lines L --teacher T.json --out DIR name=WORKDIR [name=WORKDIR ...]
The first set named e800 is the baseline (today's voice and route). Acceptance, per the plan:
  English held-out WER: median <= teacher median + 0.05 and mean <= 0.15
  Japanese (her_test.txt) kana error: mean <= e800's + 0.01
  pitch: every line p90 <= 500 Hz, median of line medians <= 345 Hz
"""
import argparse
import csv
import glob
import json
import os
import statistics as st


def tsv(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE))


def score(lines, work):
    asr = {int(r["n"]): float(r["err"]) for p in glob.glob(f"{work}/asr_*.tsv") for r in tsv(p)}
    prep = {int(r["n"]): r for r in tsv(f"{work}/prep.tsv")}
    en, mixed, ja, p50, p90 = [], [], [], [], []
    for n, r in lines.items():
        pr = prep.get(n)
        if pr is None:
            continue
        p50.append(float(pr["p50"])); p90.append(float(pr["p90"]))
        if r["split"] == "her_test":
            ja.append(float(pr["kana_err"] or 1.0))
        elif r["kind"] == "en":
            en.append(asr.get(n, 1.0))
        else:
            mixed.append(asr[n] if n in asr else float(pr["kana_err"] or 1.0))

    def m(v, f):
        return round(f(v), 4) if v else None
    return dict(en_wer_median=m(en, st.median), en_wer_mean=m(en, st.mean), mixed_err_mean=m(mixed, st.mean),
                ja_cer_mean=m(ja, st.mean), p50_median=m(p50, st.median), p90_max=m(p90, max), lines=len(p50))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lines", required=True)
    ap.add_argument("--teacher", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("sets", nargs="+")
    a = ap.parse_args()
    lines = {int(r["n"]): r for r in tsv(a.lines)}
    teacher = json.load(open(a.teacher))
    t_med = (teacher.get("en_holdout") or {}).get("err_median") or (teacher.get("en") or {}).get("err_median") or 0.0
    results = {}
    for spec in a.sets:
        name, work = spec.split("=", 1)
        results[name] = score(lines, work)
    base_ja = results.get("e800", {}).get("ja_cer_mean")
    for name, r in results.items():
        if name == "e800":
            r["accepted"] = None
            continue
        checks = {
            "en_median": r["en_wer_median"] is not None and r["en_wer_median"] <= t_med + 0.05,
            "en_mean": r["en_wer_mean"] is not None and r["en_wer_mean"] <= 0.15,
            "ja_cer": base_ja is None or (r["ja_cer_mean"] is not None and r["ja_cer_mean"] <= base_ja + 0.01),
            "pitch_p90": r["p90_max"] is not None and r["p90_max"] <= 500,
            "pitch_median": r["p50_median"] is not None and r["p50_median"] <= 345,
        }
        r["checks"] = checks
        r["accepted"] = all(checks.values())
    passing = [n for n, r in results.items() if r.get("accepted")]
    pool = passing or [n for n in results if n != "e800"]
    choice = min(pool, key=lambda n: (results[n]["en_wer_mean"] or 1) + (results[n]["ja_cer_mean"] or 1)) if pool else None
    out = dict(teacher_en_median=t_med, results=results, choice=choice, choice_passes=bool(passing))
    os.makedirs(a.out, exist_ok=True)
    json.dump(out, open(os.path.join(a.out, "student_scores.json"), "w"), indent=1)
    open(os.path.join(a.out, "choice.txt"), "w").write(f"{choice}\n")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
