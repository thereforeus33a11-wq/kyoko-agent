"""Clean speech with DeepFilterNet 3: the teacher copies its reference's room noise and breaths, so the
reference clip and every take are cleaned. Sample rate is kept (DeepFilterNet works at 48 kHz inside).

Usage (dfn env): python dfn_clean.py [--atten DB] <src.wav> <dst.wav> [<src> <dst> ...]
                 python dfn_clean.py [--atten DB] --dir <src dir> <dst dir> [--shard i/n]
--atten caps how much noise is taken away (in dB); a light touch (about 10) keeps her voice natural.
"""
import glob, os, sys
import soundfile as sf, torch, torchaudio
from df.enhance import enhance, init_df

model, st, _ = init_df()
ATTEN = None

def clean(src, dst):
    x, sr = sf.read(src, dtype="float32")
    if x.ndim > 1:
        x = x.mean(axis=1)
    t = torch.from_numpy(x)[None]
    if sr != st.sr():
        t = torchaudio.functional.resample(t, sr, st.sr())
    y = enhance(model, st, t, atten_lim_db=ATTEN)
    if sr != st.sr():
        y = torchaudio.functional.resample(y, st.sr(), sr)
    sf.write(dst, y[0].numpy(), sr, subtype="PCM_16")

args = sys.argv[1:]
if args and args[0] == "--atten":
    ATTEN = float(args[1]); args = args[2:]
if args and args[0] == "--dir":
    src, dst = args[1], args[2]
    i, n = map(int, (args[4] if len(args) > 4 and args[3] == "--shard" else "0/1").split("/"))
    os.makedirs(dst, exist_ok=True)
    files = sorted(glob.glob(os.path.join(src, "[0-9]*.wav")))[i::n]
    for f in files:
        out = os.path.join(dst, os.path.basename(f))
        if not os.path.exists(out):
            clean(f, out)
    print(f"cleaned {len(files)} takes in {src}")
else:
    for s, d in zip(args[0::2], args[1::2]):
        clean(s, d)
        print("cleaned", d)
