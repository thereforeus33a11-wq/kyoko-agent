"""Kana reading error that does not punish a recogniser for writing her kana words in kanji.

Why: the words gate reads what a recogniser heard, turns it into kana with Open JTalk and compares it with the
line's kana. A recogniser writes あく as 開く, このへん as この辺, じゅうぶん as 十分; Open JTalk then reads those as
ひらく, このあたり, じっぷん, and a take spoken exactly right scores 0.13-0.19 and fails (seen on every take of such
lines). Here the heard text is also read every way its kanji words can be read by the same dictionary (MeCab N-best
over Open JTalk's own dictionary, up to N parses, each kanji word written out in that parse's reading, then Open
JTalk as before), and the error is the lowest over those readings. The first reading tried is the plain one, so the
result is never higher than measure.py's err and equals it when the heard text has one reading.
The line's own kana is NOT varied: it is what the teacher was asked to say and what Piper will read.

    from kana_robust import kana_err, variants
Caution (seen in the soft set): a kanji written for a MISHEARD sound can have another reading that fits by chance
(見んな spoken as たみな, written 民な; 民 also reads みん). Let the lower error count only when a second recogniser
hears the line right too. Needs gsv-env (pyopenjtalk, the MeCab binding) on the pod.
"""
import glob, os, re, sys, unicodedata

sys.path.insert(0, "/w/job/scripts")
import _mecab, mecab, pyopenjtalk  # noqa: E402
from speak_checked import reading, edit  # noqa: E402

_T = {}
KANJI = re.compile(r"[一-鿿々〆]")
DIC = os.environ.get("OJT_DIC", "/w/range_build/ojt_dic")


def _tagger():
    if "t" not in _T:
        src = glob.glob("/w/gsv-env/lib/python3*/site-packages/pyopenjtalk/open_jtalk_dic_utf_8-1.11")[0]
        os.makedirs(DIC, exist_ok=True)
        for f in os.listdir(src):
            if not os.path.lexists(f"{DIC}/{f}"):
                os.symlink(f"{src}/{f}", f"{DIC}/{f}")
        if not os.path.exists(f"{DIC}/dicrc"):   # MeCab wants one; Open JTalk's copy of the dictionary has none
            open(f"{DIC}/dicrc", "w").write("cost-factor = 800\nbos-feature = BOS/EOS,*,*,*,*,*,*,*,*\neval-size = 8\n"
                                            "unk-eval-size = 4\nconfig-charset = UTF-8\n")
        _T["t"] = _mecab.Tagger(["--rcfile", str(mecab.mecabrc_path), "--dicdir", DIC])
    return _T["t"]


def variants(hyp, n=10):
    """The heard text, then the same text with its kanji words written in each reading of the N best parses."""
    hyp = unicodedata.normalize("NFKC", hyp or "")
    out, seen = [hyp], {hyp}
    if not KANJI.search(hyp):
        return out
    lat = _mecab.Lattice()
    lat.add_request_type(_mecab.MECAB_ALLOCATE_SENTENCE); lat.set_sentence(hyp); lat.add_request_type(_mecab.MECAB_NBEST)
    if not _tagger().parse(lat):
        return out
    for _ in range(n):
        toks = []
        for l in lat.to_string().split("\n"):
            if "\t" not in l:
                continue
            surf, feat = l.split("\t", 1); f = feat.split(",")
            rd = f[7] if len(f) > 7 and f[7] != "*" else None
            toks.append(rd if (rd and KANJI.search(surf)) else surf)
        s = "".join(toks)
        if s not in seen:
            seen.add(s); out.append(s)
        if not lat.next():
            break
    return out


def _clean(t):
    return "".join(c for c in (t or "") if unicodedata.category(c) != "So" and c not in "‍️")


def kana_err(text, hyp, n=10):
    """(lowest error over the readings, plain error): as measure.py text_error for Japanese."""
    r = reading(_clean(text), pyopenjtalk.g2p)
    errs = [edit(list(r), list(reading(v, pyopenjtalk.g2p))) / max(1, len(r)) for v in variants(_clean(hyp), n)]
    return min(errs), errs[0]


if __name__ == "__main__":
    for t, h in [("駅のシャッター、もうすぐあくね。", "駅のシャッターもうすぐ開くね"), ("このへん、昼とは別の街みたい。", "この辺昼とは別の街みたい"),
                 ("ゴジラ、雨の中でもこっち見てる。", "ゴジラ雨の中でもこっち見てる"), ("耳まで赤い。ふふ。", "耳まで赤い")]:
        print(t, "|", h, "->", "%.3f %.3f" % kana_err(t, h), variants(h)[:4])
