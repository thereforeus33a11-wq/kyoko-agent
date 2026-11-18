"""Keep the training clips whose transcript the Japanese recognizer agrees with (CER by reading).
A clip whose text carries another character's line, or a wrong word, is dropped.
Usage: python clean_list.py <in.list> <out.list> [max_cer]"""
import sys
import soundfile as sf
import check_distill as cd
class A: asr_dir = "/w/sherpa-onnx-zipformer-ja-reazonspeech-2024-08-01"
cd.init(A)
src, dst = sys.argv[1], sys.argv[2]
mx = float(sys.argv[3]) if len(sys.argv) > 3 else 0.25
keep, rows = [], []
for line in open(src, encoding="utf-8"):
    line = line.rstrip("\n")
    if not line: continue
    path, spk, lang, text = line.split("|", 3)
    x, sr = sf.read(path, dtype="float32"); x = x.mean(1) if x.ndim > 1 else x
    s = cd.REC.create_stream(); s.accept_waveform(sr, x); cd.REC.decode_stream(s)
    e = cd.cer(cd.reading(text), cd.reading(s.result.text))
    rows.append(f"{e:.2f}\t{len(x)/sr:.1f}\t{path.rsplit('/',1)[-1]}\t{text}\t{s.result.text}")
    if e <= mx: keep.append(line)
open(dst, "w", encoding="utf-8").write("\n".join(keep) + "\n")
open(dst + ".report.tsv", "w", encoding="utf-8").write("\n".join(sorted(rows)) + "\n")
print(f"kept {len(keep)} of {len(rows)} clips")
