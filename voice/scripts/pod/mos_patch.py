# With --model.mos_metric none, val_mos is never logged, and Lightning then refuses the
# val_mos ModelCheckpoint at the first validation. Drop that one callback.
import re
p = "/w/piper1-gpl/src/piper/train/__main__.py"
s = open(p, encoding="utf-8").read()
pat = re.compile(r"\n        # Also keep the best-by-perceptual-quality checkpoints\..*?\n        ModelCheckpoint\(\n            monitor=\"val_mos\",.*?\n        \),", re.S)
s2, n = pat.subn("", s)
if n == 0 and 'monitor="val_mos"' in s:
    raise SystemExit("val_mos callback not found in the expected shape")
open(p, "w", encoding="utf-8").write(s2)
print("removed", n, "callback(s); val_mos left:", 'monitor="val_mos"' in s2)
