"""Round 3 self-check on the bank files: both recognisers heard every round-3 take again as the phone will play it
(22050 Hz, after finalize: <check dir>/measure.tsv for the kana recogniser, asr.jsonl for whisper). The build gate's
hearing rules are applied to what they heard: one of them hears the noise's pattern (HEARD), neither hears it as
another noise (NOT_FIRST), neither hears a word, and the noise's own rules (a hmph or a giggle for heh and bark_nose,
an exhale for haa). A take that fails is moved to <check dir>/removed/, its entry leaves sounds.json, and the cell's
round-3 takes after it are renumbered (earlier rounds' takes are never touched). removals.json lists what went.

Usage (gsv env): python noise_selfcheck_r3.py <bank dir> <check dir> <noise_gate_r3.py> [--dry]
"""
import ast, csv, json, os, re, shutil, sys
import pyopenjtalk

bank, cdir, gate_p = sys.argv[1:4]; DRY = "--dry" in sys.argv
src = open(gate_p, encoding="utf-8").read(); tree = ast.parse(src); V = {}
for n in tree.body:
    if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) and \
            n.targets[0].id in ("OWN", "HEARD", "NOT_FIRST", "HALLU", "PUNCT"):
        V[n.targets[0].id] = eval(compile(ast.Expression(n.value), "gate", "eval"), {"re": re, "__builtins__": {}})
OWN, HEARD, NOT_FIRST, HALLU, PUNCT = V["OWN"], V["HEARD"], V["NOT_FIRST"], V["HALLU"], V["PUNCT"]


def reading(t):
    if not t or any(h in t for h in HALLU): return ""
    t = PUNCT.sub("", t)
    return PUNCT.sub("", pyopenjtalk.g2p(t, kana=True)) if t else ""


key = lambda f: "/".join(f.split("/")[-3:])
kana = {key(r["file"]): r["kana"] for r in csv.DictReader(open(f"{cdir}/measure.tsv", encoding="utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE)}
wh = {}
for l in open(f"{cdir}/asr.jsonl", encoding="utf-8"):
    r = json.loads(l); wh[key(r["file"])] = r["text"]


def verdict(s, w, k):
    wr, kr = reading(w), reading(k)
    foreign = lambda r: sum(ch not in OWN[s] for ch in r)
    if max(foreign(wr), foreign(kr)) >= 3 or min(foreign(wr), foreign(kr)) >= 2: return f"heard a word ({w} | {k})"
    if not any(r and re.search(HEARD[s], r) for r in (wr, kr)): return f"neither recogniser hears it as {s} ({w} | {k})"
    nf = NOT_FIRST.get(s, "")
    if nf and any(r and r[0] in nf for r in (wr, kr)): return f"heard as another noise ({w} | {k})"
    if s == "haa" and wr[:1] == "フ": return f"heard as an exhale ({w})"
    if s == "heh" and any(r and ("ン" in r or len(r.replace("ッ", "")) >= 2) for r in (wr, kr)): return f"heard as a hmph or a giggle ({w} | {k})"
    if s == "bark_nose" and any(re.match(r"^フ+ン+$", r) for r in (wr, kr) if r): return f"heard as a hmph ({w} | {k})"
    if s == "bark_nose" and any(len(r.replace("ッ", "").replace("ン", "")) >= 3 for r in (wr, kr) if r): return f"heard as a giggle ({w} | {k})"
    return ""


j = json.load(open(f"{bank}/sounds.json", encoding="utf-8"))
rem = []
os.makedirs(f"{cdir}/removed", exist_ok=True)
for s, cells in j["sounds"].items():
    for st, takes in cells.items():
        keep = []
        for t in takes:
            if t.get("round") != 3: keep.append(t); continue
            k = t["file"]
            v = verdict(s, wh.get(k, ""), kana.get(k, "")) if s in HEARD else ""
            print(f"{k:32s} whisper {wh.get(k, '?')[:24]:24s} kana {kana.get(k, '?')[:12]:12s} {v or 'ok'}")
            if v:
                rem.append(dict(file=k, why=v, job=t["source"]["job"])); continue
            keep.append(t)
        if len(keep) == len(takes) or DRY: continue
        # renumber this cell's round-3 takes after the earlier rounds' ones
        n_old = sum(1 for t in keep if t.get("round") != 3)
        for r in rem:
            if r["file"].startswith(f"{s}/{st}/") and os.path.exists(f"{bank}/{r['file']}"):
                shutil.move(f"{bank}/{r['file']}", f"{cdir}/removed/{r['file'].replace('/', '__')}")
        for i, t in enumerate([t for t in keep if t.get("round") == 3], n_old + 1):
            new = f"{s}/{st}/take_{i:02d}.wav"
            if t["file"] != new:
                shutil.move(f"{bank}/{t['file']}", f"{bank}/{new}"); t["old_file"] = t["file"]; t["file"] = new
        cells[st] = keep
if not DRY:
    for s in list(j["sounds"]):
        for st in list(j["sounds"][s]):
            if not j["sounds"][s][st]: del j["sounds"][s][st]
        if not j["sounds"][s]: del j["sounds"][s]
    json.dump(j, open(f"{bank}/sounds.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(rem, open(f"{cdir}/removals.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"removed {len(rem)}" + (" (dry)" if DRY else ""))
for r in rem: print("  " + r["file"] + ": " + r["why"])
