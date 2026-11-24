"""Which features for the style classifier: chosen by cross-validation on the training clips only (sets.tsv).
Then (as a check, not a choice) where e974's sid 0 clips go."""
import sys
sys.path.insert(0, "/w/job/scripts")
import numpy as np
import styles_eval_score as S
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_predict, StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
out = "/w/range_build/styles/eval"
items = S.tsv(f"{out}/items.tsv")
M = {r["id"]: r for r in S.tsv(f"{out}/measure.tsv") if r["status"] == "ok"}
sets = [r for r in items if r["src"] == "set"]
base = [r for r in items if r["voice"] == "e974"]
FS = {"A5": ["lufs", "hnr", "hf_db", "tilt_a", "f0_med"],
      "A+cent": ["lufs", "hnr", "hf_db", "tilt_a", "f0_med", "centroid"],
      "A+voicing": ["lufs", "hnr", "hf_db", "tilt_a", "f0_med", "hr_share", "voiced"],
      "A+cent+voicing": ["lufs", "hnr", "hf_db", "tilt_a", "f0_med", "centroid", "hr_share", "voiced"],
      "A+all": ["lufs", "hnr", "hf_db", "tilt_a", "f0_med", "centroid", "hr_share", "voiced", "flat_med", "rms_db", "f0_p90", "f0_p10"]}
for name, F in FS.items():
    for C in (1.0, 10.0):
        X = []; y = []
        for r in sets:
            v = [S.fnum(M[r["id"]].get(k)) for k in F]
            if all(x == x for x in v): X.append(v); y.append(S.STYLES.index(r["cls"]))
        X, y = np.array(X), np.array(y)
        clf = make_pipeline(StandardScaler(), LogisticRegression(max_iter=5000, C=C))
        cv = cross_val_predict(clf, X, y, cv=StratifiedKFold(5, shuffle=True, random_state=0))
        clf.fit(X, y)
        Xb = np.array([[S.fnum(M[r["id"]].get(k)) for k in F] for r in base])
        pb = clf.predict(Xb)
        print(f"{name:16s} C={C:4.0f} cv_acc {np.mean(cv == y):.4f} normal_recall {np.mean(cv[y == 0] == 0):.3f} | e974 sid0 not normal {int((pb != 0).sum())}/{len(pb)} to {sorted(set(S.STYLES[k] for k in pb if k))}")
