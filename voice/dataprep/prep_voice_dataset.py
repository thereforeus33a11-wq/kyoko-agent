#!/usr/bin/env python3
"""
prep_voice_dataset.py - turn a YouTube URL (or a local audio/video file) that contains a
female target speaker plus a male speaker into a clean, single-speaker GPT-SoVITS dataset.

Stages ("run" does 1-6, "finalize" does 7):
  1 fetch       yt-dlp best audio -> 00_source/source.wav (44.1 kHz stereo, optional trim)
  2 separate    audio-separator BS-Roformer (default) | demucs | none -> 01_vocals/vocals.wav
  3 diarize     Silero VAD (bundled in faster-whisper) -> 1.5 s windows -> speaker labels from
                  ecapa    : SpeechBrain ECAPA embeddings + clustering (no token, default)
                  sherpa   : sherpa-onnx ONNX embeddings + clustering (no token, no torch, CPU)
                  pyannote : pyannote community-1 diarization (needs HF token + accepted terms)
                  pitch    : median-F0 threshold only (crude fallback)
  4 slice       consecutive target-speaker VAD segments -> 3-10 s clips -> 02_review/clips/*.wav
  5 transcribe  faster-whisper, run in a child process that never imports torch
  6 review      02_review/review.html (listen / untick / fix text) + review.csv
  7 finalize    03_dataset/<name>/wavs/*.wav + 03_dataset/<name>.list
                line format (GPT-SoVITS README "Dataset Format"):  vocal_path|speaker_name|language|text

Usage (see README.md):
  python prep_voice_dataset.py check
  python prep_voice_dataset.py run --input "https://www.youtube.com/watch?v=..." --work work\\kyoko --name kyoko
  (open work\\kyoko\\02_review\\review.html, fix, "Save edited CSV" -> review_edited.csv)
  python prep_voice_dataset.py finalize --work work\\kyoko
"""
from __future__ import annotations

import argparse
import csv
import gc
import glob
import html
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import soundfile as sf

SR16 = 16000          # analysis rate (VAD, embeddings, F0, Whisper)
SR_CLIP = 44100       # exported clip rate (GPT-SoVITS resamples itself to 32k/16k)
LIST_LANGS = {"ja", "en", "zh", "ko", "yue"}   # GPT_SoVITS/prepare_datasets/1-get-text.py:110-126
DEFAULT_ROFORMER = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"   # audio-separator default model
DEFAULT_DEMUCS = "htdemucs_ft"
SHERPA_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/{}"
DEFAULT_SHERPA_MODEL = "wespeaker_en_voxceleb_resnet34_LM.onnx"
ECAPA_SOURCE = "speechbrain/spkrec-ecapa-voxceleb"
PYANNOTE_PIPELINE = "pyannote/speaker-diarization-community-1"
# Known Whisper hallucinations on Japanese audio (subtitle credits, "thanks for watching" ...)
HALLUCINATIONS = ["ご視聴ありがとうございました", "チャンネル登録", "字幕", "おやすみなさい。おやすみなさい",
                  "Thank you for watching", "Subtitles by", "Amara.org"]
SEVERE_FLAGS = {"uncertain", "low_sim", "low_f0", "short", "long", "overlap", "no_f0",
                "asr_empty", "asr_lowconf", "asr_repeat", "asr_hallucination", "asr_rate", "lang_unsupported"}
CSV_COLS = ["keep", "clip", "label", "cluster", "start", "end", "dur", "sim_target", "margin",
            "f0_median", "win_labels", "flags", "lang", "text", "asr_logprob", "asr_no_speech"]
SCRIPT_DIR = Path(__file__).resolve().parent


# --------------------------------------------------------------------------------------- utils
def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def die(msg: str) -> None:
    print(f"\nERROR: {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


def require_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        die("ffmpeg is not on PATH. Windows: `winget install Gyan.FFmpeg`, then open a new terminal.")


def parse_time(t: str | None) -> float | None:
    """'83.5', '1:23.5' or '01:01:23.5' -> seconds."""
    if t is None or t == "":
        return None
    parts = [float(p) for p in str(t).split(":")]
    sec = 0.0
    for p in parts:
        sec = sec * 60 + p
    return sec


def parse_span(s: str) -> tuple[float, float]:
    a, b = s.split("-", 1) if s.count("-") == 1 else s.split("..", 1)
    a, b = parse_time(a), parse_time(b)
    if a is None or b is None or b <= a:
        die(f"bad --ref-span '{s}', expected START-END like 83.5-95 or 1:23-1:35")
    return a, b


def load_audio(path: Path | str, sr: int) -> np.ndarray:
    """Decode any media file to mono float32 at `sr` with the ffmpeg CLI (same approach as
    GPT-SoVITS tools/my_utils.py load_audio)."""
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(sr),
           "-f", "f32le", "-acodec", "pcm_f32le", "-"]
    res = subprocess.run(cmd, capture_output=True)
    if res.returncode != 0:
        die(f"ffmpeg failed on {path}:\n{res.stderr.decode(errors='replace')}")
    return np.frombuffer(res.stdout, np.float32).copy()


def l2norm(x: np.ndarray) -> np.ndarray:
    return x / np.maximum(np.linalg.norm(x, axis=-1, keepdims=True), 1e-9)


def free_gpu() -> None:
    gc.collect()
    if "torch" in sys.modules:
        torch = sys.modules["torch"]
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


def download(url: str, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".part")
    log(f"downloading {url}")
    urllib.request.urlretrieve(url, tmp)
    tmp.replace(dst)


def nn(x, nd=4):
    """float rounded, or None for NaN/None (keeps clips.json valid JSON)."""
    return None if x is None or not np.isfinite(x) else round(float(x), nd)


def fnum(x, nd=3):
    return "" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{nd}f}"


def meta_path(work: Path) -> Path:
    return work / "02_review" / "clips.json"


def load_meta(work: Path) -> dict:
    p = meta_path(work)
    if not p.exists():
        die(f"{p} not found - run the 'run' command first")
    return json.loads(p.read_text(encoding="utf-8"))


def save_meta(work: Path, meta: dict) -> None:
    p = meta_path(work)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


# --------------------------------------------------------------------------------- 1. fetch
def stage_fetch(args, work: Path) -> Path:
    src_dir = work / "00_source"
    src_dir.mkdir(parents=True, exist_ok=True)
    wav = src_dir / "source.wav"
    if wav.exists() and not args.force:
        log(f"[fetch] reuse {wav}")
        return wav
    if re.match(r"^https?://", args.input):
        import yt_dlp
        opts = {
            "format": "bestaudio/best",          # best audio-only stream (opus/m4a), else best muxed
            "outtmpl": str(src_dir / "download.%(ext)s"),
            "noplaylist": True,
            "overwrites": True,
        }
        try:  # `pip install deno` puts deno.exe in the venv; YouTube needs a JS runtime + yt-dlp-ejs
            from deno import find_deno_bin
            opts["js_runtimes"] = {"deno": {"path": find_deno_bin()}}
        except Exception:
            pass  # yt-dlp then looks for `deno` on PATH (its default runtime)
        if args.cookies_from_browser:
            opts["cookiesfrombrowser"] = (args.cookies_from_browser,)
        log(f"[fetch] yt-dlp {yt_dlp.version.__version__}: {args.input}")
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(args.input, download=True)
            reqs = info.get("requested_downloads") or []
            raw = Path(reqs[0]["filepath"]) if reqs and reqs[0].get("filepath") else Path(ydl.prepare_filename(info))
        keep = {k: info.get(k) for k in ("id", "title", "channel", "duration", "webpage_url",
                                         "format_id", "acodec", "abr", "asr")}
        (src_dir / "source_info.json").write_text(json.dumps(keep, ensure_ascii=False, indent=1), encoding="utf-8")
    else:
        raw = Path(args.input)
        if not raw.is_file():
            die(f"input file not found: {raw}")
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y"]
    if args.start:
        cmd += ["-ss", str(parse_time(args.start))]
    if args.end:
        cmd += ["-to", str(parse_time(args.end))]
    cmd += ["-i", str(raw), "-vn", "-ac", "2", "-ar", str(SR_CLIP), "-c:a", "pcm_s16le", str(wav)]
    log(f"[fetch] ffmpeg -> {wav}")
    subprocess.run(cmd, check=True)
    return wav


# ------------------------------------------------------------------------------ 2. separate
def stage_separate(args, work: Path, src_wav: Path) -> Path:
    out_dir = work / "01_vocals"
    out_dir.mkdir(parents=True, exist_ok=True)
    vocals = out_dir / "vocals.wav"
    if vocals.exists() and not args.force:
        log(f"[separate] reuse {vocals}")
        return vocals
    if args.separator == "none":
        shutil.copyfile(src_wav, vocals)
        return vocals
    if args.separator == "roformer":
        from audio_separator.separator import Separator
        model = args.sep_model or DEFAULT_ROFORMER
        log(f"[separate] audio-separator model={model}")
        sep = Separator(model_file_dir=str(Path(args.models_dir) / "audio-separator"),
                        output_dir=str(out_dir), output_format="WAV", output_single_stem="Vocals",
                        chunk_duration=args.sep_chunk or None)   # chunking bounds RAM on long videos
        sep.load_model(model_filename=model)
        # returned paths are relative to output_dir (non-chunked path), so name the stem explicitly;
        # the chunked path matches custom names case-sensitively, hence both spellings
        sep.separate(str(src_wav), custom_output_names={"Vocals": "vocals", "vocals": "vocals"})
        del sep
        if not vocals.exists():
            cands = [p for p in out_dir.glob("*.wav") if "(vocals)" in p.name.lower()]
            if cands:
                cands[0].replace(vocals)
    elif args.separator == "demucs":
        model = args.sep_model or DEFAULT_DEMUCS
        log(f"[separate] demucs -n {model} --two-stems vocals")
        dem_out = out_dir / "demucs"
        subprocess.run([sys.executable, "-m", "demucs", "--two-stems", "vocals", "-n", model,
                        "-o", str(dem_out), "--filename", "{stem}.{ext}", str(src_wav)], check=True)
        produced = dem_out / model.replace("hf://", "").replace("/", "_") / "vocals.wav"
        if produced.exists():
            shutil.move(str(produced), str(vocals))
    free_gpu()
    if not vocals.exists():
        die(f"separation finished but {vocals} is missing; check the log above")
    return vocals


# ------------------------------------------------------------------------------- 3. diarize
def vad_segments(a16: np.ndarray, max_len: float, args) -> list[tuple[float, float]]:
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    opts = VadOptions(threshold=args.vad_threshold, min_speech_duration_ms=250,
                      min_silence_duration_ms=args.vad_min_silence_ms, speech_pad_ms=60,
                      max_speech_duration_s=max_len)
    ts = get_speech_timestamps(a16.astype(np.float32), opts, sampling_rate=SR16)
    return [(t["start"] / SR16, t["end"] / SR16) for t in ts if t["end"] > t["start"]]


def make_windows(segs, win: float, hop: float):
    """Sliding windows inside each VAD segment -> list of (seg_idx, start, end)."""
    out = []
    for i, (s, e) in enumerate(segs):
        d = e - s
        if d <= win * 1.33:
            out.append((i, s, e))
            continue
        n = int(math.ceil((d - win) / hop)) + 1
        last = None
        for k in range(n):
            ws = s + k * hop
            we = min(ws + win, e)
            ws = max(s, we - win)
            if last is not None and abs(ws - last) < 1e-6:
                continue
            out.append((i, ws, we))
            last = ws
    return out


def f0_track(x: np.ndarray) -> np.ndarray:
    """F0 per 10 ms frame (0 = unvoiced). pyworld DIO+StoneMask, fallback librosa YIN + RMS gate."""
    if len(x) < 1024:
        return np.zeros(0)
    try:
        import pyworld as pw   # pyworld 0.3.5 imports pkg_resources -> needs setuptools<81
        xd = x.astype(np.float64)
        f0, t = pw.dio(xd, SR16, f0_floor=60.0, f0_ceil=700.0, frame_period=10.0)
        return pw.stonemask(xd, f0, t, SR16)
    except ImportError:
        import librosa
        f0 = librosa.yin(x, fmin=60, fmax=700, sr=SR16, frame_length=1024, hop_length=160)
        rms = librosa.feature.rms(y=x, frame_length=1024, hop_length=160)[0]
        n = min(len(f0), len(rms))
        f0, rms = f0[:n].copy(), rms[:n]
        f0[rms < max(1e-4, 0.1 * float(np.percentile(rms, 95)))] = 0.0
        return f0


class EcapaEmbedder:
    """SpeechBrain ECAPA-TDNN (VoxCeleb), 192-dim. Public HF model, no token."""
    name = "ecapa"

    def __init__(self, models_dir: Path, device: str):
        import torch
        from speechbrain.inference.classifiers import EncoderClassifier
        from speechbrain.utils.fetching import LocalStrategy
        self.torch = torch
        self.model = EncoderClassifier.from_hparams(
            source=ECAPA_SOURCE, savedir=str(models_dir / "spkrec-ecapa-voxceleb"),
            run_opts={"device": device}, local_strategy=LocalStrategy.COPY)  # COPY: no symlinks on Windows
        self.model.eval()

    def embed(self, chunks: list[np.ndarray]) -> np.ndarray:
        torch = self.torch
        out = []
        order = np.argsort([len(c) for c in chunks])
        res = [None] * len(chunks)
        bs = 32
        for b in range(0, len(order), bs):
            idx = order[b:b + bs]
            L = max(len(chunks[i]) for i in idx)
            arr = np.zeros((len(idx), L), np.float32)
            rel = np.zeros(len(idx), np.float32)
            for j, i in enumerate(idx):
                arr[j, :len(chunks[i])] = chunks[i]
                rel[j] = len(chunks[i]) / L
            with torch.no_grad():
                e = self.model.encode_batch(torch.from_numpy(arr), torch.from_numpy(rel))
            e = e.reshape(len(idx), -1).float().cpu().numpy()
            for j, i in enumerate(idx):
                res[i] = e[j]
        out = np.stack(res)
        return l2norm(out)

    def close(self):
        del self.model
        free_gpu()


class SherpaEmbedder:
    """sherpa-onnx SpeakerEmbeddingExtractor (CPU, onnxruntime). Models from GitHub releases."""
    name = "sherpa"

    def __init__(self, models_dir: Path, model_name: str, threads: int):
        import sherpa_onnx
        path = Path(model_name) if Path(model_name).is_file() else models_dir / "sherpa" / model_name
        if not path.exists():
            download(SHERPA_URL.format(model_name), path)
        cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(path), num_threads=threads, provider="cpu")
        if not cfg.validate():
            die(f"invalid sherpa-onnx embedding model {path}")
        self.ex = sherpa_onnx.SpeakerEmbeddingExtractor(cfg)

    def embed(self, chunks: list[np.ndarray]) -> np.ndarray:
        out = np.zeros((len(chunks), self.ex.dim), np.float32)
        for i, c in enumerate(chunks):
            st = self.ex.create_stream()
            st.accept_waveform(sample_rate=SR16, waveform=np.ascontiguousarray(c, dtype=np.float32))
            st.input_finished()
            out[i] = np.asarray(self.ex.compute(st), np.float32)
        return l2norm(out)

    def close(self):
        del self.ex


def make_embedder(args):
    if args.embedder == "ecapa":
        return EcapaEmbedder(Path(args.models_dir), args.device)
    return SherpaEmbedder(Path(args.models_dir), args.sherpa_model, args.threads)


def cluster_embeddings(emb: np.ndarray, n_clusters: int, max_fit: int = 6000):
    """Ward-linkage agglomerative clustering of L2-normalised embeddings (fit on <= max_fit windows;
    average linkage was tested and produced singleton outlier clusters), k = n_clusters or, if 0,
    the k in 2..6 with the best cosine silhouette. Then two spherical k-means passes over all windows.
    Returns (labels, centroids, similarity matrix)."""
    from sklearn.cluster import AgglomerativeClustering
    N = len(emb)
    rng = np.random.default_rng(0)
    fit_idx = np.sort(rng.choice(N, max_fit, replace=False)) if N > max_fit else np.arange(N)
    X = emb[fit_idx]

    def fit(k):
        return AgglomerativeClustering(n_clusters=k, linkage="ward").fit_predict(X) if k > 1 else np.zeros(len(X), int)

    if n_clusters >= 1:
        lab = fit(min(n_clusters, len(X)))
    else:
        from sklearn.metrics import silhouette_score
        best = None
        for k in range(2, min(6, len(X) - 1) + 1):
            lk = fit(k)
            sc = float(silhouette_score(X, lk, metric="cosine"))
            log(f"    k={k}: cosine silhouette {sc:.3f}")
            if best is None or sc > best[0]:
                best = (sc, lk)
        lab = best[1]
    K = int(lab.max()) + 1
    cent = l2norm(np.stack([X[lab == k].mean(0) for k in range(K)]))
    for _ in range(2):
        labels = (emb @ cent.T).argmax(1)
        cent = l2norm(np.stack([emb[labels == k].mean(0) if np.any(labels == k) else cent[k] for k in range(K)]))
    sims = emb @ cent.T
    return sims.argmax(1), cent, sims


def pyannote_window_labels(a16: np.ndarray, wins, args):
    """Label each window with the pyannote speaker that overlaps it most (-1 = overlapped speech,
    -2 = no diarized speech). Returns (labels, label_names)."""
    os.environ.setdefault("PYANNOTE_METRICS_ENABLED", "0")   # pyannote 4.x telemetry is on by default
    import torch
    from pyannote.audio import Pipeline
    token = args.hf_token or os.environ.get("HF_TOKEN")
    if not token:
        die("--diarizer pyannote needs --hf-token or HF_TOKEN (and accepted terms for "
            f"https://hf.co/{PYANNOTE_PIPELINE})")
    log(f"[diarize] pyannote {PYANNOTE_PIPELINE}")
    pipe = Pipeline.from_pretrained(PYANNOTE_PIPELINE, token=token)
    if pipe is None:
        die("pyannote pipeline could not be loaded (token wrong or model terms not accepted)")
    pipe.to(torch.device(args.device))
    kw = {"num_speakers": args.num_speakers} if args.num_speakers > 0 else {}
    out = pipe({"waveform": torch.from_numpy(a16).unsqueeze(0), "sample_rate": SR16}, **kw)
    ann = out.speaker_diarization
    names = sorted(ann.labels())
    turns = {k: [] for k in range(len(names))}
    for seg, _, lbl in ann.itertracks(yield_label=True):
        turns[names.index(lbl)].append((seg.start, seg.end))
    ov = np.array([(s.start, s.end) for s in ann.get_overlap()]).reshape(-1, 2)
    T = {k: np.array(v).reshape(-1, 2) for k, v in turns.items()}
    labels = np.full(len(wins), -2, int)
    for w, (_, a, b) in enumerate(wins):
        best, best_d = -2, 0.0
        for k, arr in T.items():
            d = np.clip(np.minimum(b, arr[:, 1]) - np.maximum(a, arr[:, 0]), 0, None).sum() if len(arr) else 0.0
            if d > best_d:
                best, best_d = k, d
        ov_d = np.clip(np.minimum(b, ov[:, 1]) - np.maximum(a, ov[:, 0]), 0, None).sum() if len(ov) else 0.0
        labels[w] = -1 if ov_d > 0.1 * (b - a) else best
    del pipe
    free_gpu()
    return labels, names


def stage_diarize_and_slice(args, work: Path, vocals: Path) -> dict:
    review = work / "02_review"
    clips_dir = review / "clips"
    if meta_path(work).exists() and not args.force and not args.redo_diarize:
        log(f"[diarize] reuse {meta_path(work)} (pass --redo-diarize to recompute)")
        return load_meta(work)
    if clips_dir.exists():
        shutil.rmtree(clips_dir)
    clips_dir.mkdir(parents=True, exist_ok=True)
    offset = parse_time(args.start) or 0.0

    log("[diarize] loading vocals")
    a16 = load_audio(vocals, SR16)
    total = len(a16) / SR16

    # VAD segments, windows, F0 and embeddings are cached so that re-running with another
    # --target-cluster / --ref-span / --num-speakers / thresholds takes seconds, not minutes.
    need_emb = args.diarizer in ("ecapa", "sherpa") or (args.diarizer == "pyannote" and bool(args.ref or args.ref_span))
    st = vocals.stat()
    key = json.dumps([st.st_size, int(st.st_mtime), args.max_len, args.win, args.hop, args.vad_threshold,
                      args.vad_min_silence_ms, args.embedder if need_emb else None,
                      args.sherpa_model if (need_emb and args.embedder == "sherpa") else None])
    cache = review / "diarize_cache.npz"
    emb = None
    if cache.exists() and not args.force:
        z = np.load(cache, allow_pickle=False)
        if str(z["key"]) == key:
            segs = [tuple(x) for x in z["segs"].tolist()]
            wins = [(int(i), float(a), float(b)) for i, a, b in z["wins"].tolist()]
            f0_all, f0_off = z["f0_all"], z["f0_off"]
            f0_seg = [f0_all[f0_off[i]:f0_off[i + 1]] for i in range(len(segs))]
            emb = z["emb"] if z["emb"].size else None
            log(f"[diarize] reuse cache {cache.name} ({len(segs)} segments, {len(wins)} windows)")
        else:
            segs = None
    else:
        segs = None
    if segs is None:
        segs = vad_segments(a16, args.max_len, args)
        if not segs:
            die("VAD found no speech in the vocals track")
        wins = make_windows(segs, args.win, args.hop)
        log(f"[diarize] F0 analysis of {len(segs)} segments")
        f0_seg = [f0_track(a16[int(s * SR16):int(e * SR16)]) for s, e in segs]
    speech = sum(e - s for s, e in segs)
    log(f"[diarize] {len(segs)} VAD segments, {len(wins)} windows, {speech/60:.1f} min speech of {total/60:.1f} min")
    chunks = [a16[int(a * SR16):int(b * SR16)] for _, a, b in wins]

    def f0_values(si, a, b):
        f0 = f0_seg[si]
        s0 = segs[si][0]
        i0, i1 = int((a - s0) * 100), int(math.ceil((b - s0) * 100))
        v = f0[max(0, i0):max(0, i1)]
        return v[v > 0]

    win_f0 = np.array([np.median(v) if len(v) >= 5 else np.nan
                       for v in (f0_values(si, a, b) for si, a, b in wins)])

    # reference embedding (her voice), from --ref files and/or --ref-span ranges of the vocals
    ref_chunks = []
    for rf in args.ref or []:
        ra = load_audio(rf, SR16)
        ref_chunks += [ra[int(a * SR16):int(b * SR16)] for _, a, b in make_windows([(0, len(ra) / SR16)], args.win, args.hop)]
    for sp in args.ref_span or []:
        a, b = parse_span(sp)
        a, b = max(0.0, a - offset), min(total, b - offset)
        ra = a16[int(a * SR16):int(b * SR16)]
        ref_chunks += [ra[int(x * SR16):int(y * SR16)] for _, x, y in make_windows([(0, len(ra) / SR16)], args.win, args.hop)]
    ref_chunks = [c for c in ref_chunks if len(c) > 0.5 * SR16]
    if (args.ref or args.ref_span) and not ref_chunks:
        die("--ref/--ref-span gave no usable audio (need > 0.5 s)")

    ref_emb = None
    if need_emb and (emb is None or ref_chunks):
        embedder = make_embedder(args)
        if emb is None:
            log(f"[diarize] embedding {len(chunks)} windows with {args.embedder}")
            t0 = time.time()
            emb = embedder.embed(chunks)
            log(f"[diarize] embeddings done in {time.time() - t0:.0f}s")
        if ref_chunks:
            ref_emb = l2norm(embedder.embed(ref_chunks).mean(0))
        embedder.close()
    f0_off = np.cumsum([0] + [len(f) for f in f0_seg])
    np.savez(cache, key=np.array(key), segs=np.array(segs, float).reshape(-1, 2),
             wins=np.array(wins, float).reshape(-1, 3),
             f0_all=np.concatenate(f0_seg) if f0_seg else np.zeros(0), f0_off=f0_off,
             emb=emb if emb is not None else np.zeros(0, np.float32))

    # ---- window labels
    names = None
    if args.diarizer in ("ecapa", "sherpa"):
        labels, cent, _ = cluster_embeddings(emb, args.num_speakers)
    elif args.diarizer == "pyannote":
        labels, names = pyannote_window_labels(a16, wins, args)
    else:  # pitch
        labels = np.where(np.isnan(win_f0), -2, np.where(win_f0 >= args.f0_split, 1, 0))
        names = [f"F0<{args.f0_split:.0f}Hz", f"F0>={args.f0_split:.0f}Hz"]
    K = int(max(labels.max(), 0)) + 1
    if emb is not None and args.diarizer in ("pyannote",):
        cent = l2norm(np.stack([emb[labels == k].mean(0) if np.any(labels == k) else np.zeros(emb.shape[1])
                                for k in range(K)]))

    # ---- cluster summary + target choice
    # time "owned" by each window = until the next window of the same segment starts
    wown = np.zeros(len(wins))
    for w, (si, a, b) in enumerate(wins):
        nxt = wins[w + 1] if w + 1 < len(wins) else None
        wown[w] = (nxt[1] - a) if (nxt is not None and nxt[0] == si) else (segs[si][1] - a)
    clusters = []
    for k in range(K):
        m = labels == k
        f0s = win_f0[m & ~np.isnan(win_f0)]
        clusters.append({
            "id": k, "name": names[k] if names else f"C{k}", "windows": int(m.sum()),
            "speech_sec": round(float(wown[m].sum()), 1),
            "f0_median": round(float(np.median(f0s)), 1) if len(f0s) else None,
            "sim_ref": round(float(cent[k] @ ref_emb), 3) if (ref_emb is not None and emb is not None) else None,
        })
    big = [c for c in clusters if c["windows"] >= 0.05 * len(wins)] or clusters
    if args.target_cluster:
        target = [int(x) for x in str(args.target_cluster).split(",")]
        if any(t < 0 or t >= K for t in target):
            die(f"--target-cluster {args.target_cluster}: valid cluster ids are 0..{K - 1}")
        how = "--target-cluster"
    elif args.diarizer == "pitch":
        target, how = [1], "pitch threshold"
    elif ref_emb is not None and emb is not None:
        target, how = [max(big, key=lambda c: c["sim_ref"])["id"]], "closest to reference"
    else:
        target, how = [max(big, key=lambda c: c["f0_median"] or 0)["id"]], "highest median F0"
    for c in clusters:
        c["is_target"] = c["id"] in target
    log(f"[diarize] target cluster(s) {target} ({how})")
    for c in clusters:
        log(f"    cluster {c['id']} {c['name']:>12}: {c['windows']:6d} win  ~{c['speech_sec']/60:6.1f} min  "
            f"F0 {c['f0_median']} Hz  sim_ref {c['sim_ref']}  {'<- TARGET' if c['is_target'] else ''}")
    tf0 = [c["f0_median"] for c in clusters if c["is_target"] and c["f0_median"]]
    if tf0 and min(tf0) < 165 and args.diarizer != "pitch":
        log("    WARNING: target median F0 < 165 Hz looks like a male voice - check review.html, "
            "use --ref-span or --target-cluster")

    # ---- per-window target similarity / margin
    is_t = np.isin(labels, target)
    if emb is not None:
        tcent = l2norm(cent[target].mean(0))
        sim_t = emb @ tcent
        others = [k for k in range(K) if k not in target]
        sim_o = (emb @ cent[others].T).max(1) if others else np.full(len(wins), np.nan)
        margin = sim_t - sim_o
        st = sim_t[is_t]
        med = float(np.median(st)) if len(st) else 0.0
        mad = float(np.median(np.abs(st - med))) * 1.4826 if len(st) else 0.0
        low_thr = min(med - 0.05, med - args.low_sim_mads * mad)
        log(f"[diarize] target-window cosine: median {med:.3f}, robust floor {low_thr:.3f}")
    else:
        sim_t = margin = np.full(len(wins), np.nan)
        low_thr = -np.inf

    # 'low_f0': voiced frames far below HER normal range inside a "target" clip are usually a male
    # backchannel glued to her speech without a pause (1.5 s window embeddings can miss those).
    # threshold = geometric mean of the low end of her range and the other speakers' median F0
    # (or 0.8 x her low end when there is no lower-pitched other speaker).
    core = is_t & ~np.isnan(win_f0)
    if emb is not None and core.any():
        core &= sim_t >= np.median(sim_t[core])
    her = np.concatenate([f0_values(si, a, b) for (si, a, b), c in zip(wins, core) if c] or [np.zeros(0)])
    oth = [c["f0_median"] for c in clusters if not c["is_target"] and c["f0_median"]]
    low_f0_hz = 0.0
    if args.low_f0_hz is not None:
        low_f0_hz = args.low_f0_hz
    elif len(her) >= 50:
        lg = np.log2(her)   # robust low end of her range: median - 2 robust SD, in octaves
        her_lo = float(2 ** (np.median(lg) - 2 * 1.4826 * np.median(np.abs(lg - np.median(lg)))))
        low_f0_hz = math.sqrt(her_lo * float(np.median(oth))) if oth and np.median(oth) < her_lo else 0.8 * her_lo
        log(f"[diarize] her F0: median {np.median(her):.0f} Hz, robust low end {her_lo:.0f} Hz; "
            f"other clusters {oth} Hz")
    if low_f0_hz:
        log(f"[diarize] 'low_f0' flag for voiced runs >= {args.low_f0_min_run}s below {low_f0_hz:.0f} Hz")

    def low_f0_run(seg_ids) -> float:
        best = 0
        for si in seg_ids:
            f0 = f0_seg[si]
            run = 0
            for v in f0:
                run = run + 1 if 0 < v < low_f0_hz else 0
                best = max(best, run)
        return best / 100.0   # frames are 10 ms

    # ---- segment labels
    seg_w = [[] for _ in segs]
    for w, (si, _, _) in enumerate(wins):
        seg_w[si].append(w)
    seg_info = []
    for si, ws in enumerate(seg_w):
        lt = [bool(is_t[w]) for w in ws]
        if all(lt):
            lab = "target"
        elif not any(lt):
            lab = "other"
        else:
            lab = "mixed"
        cl = [int(labels[w]) for w in ws]
        major = max(set(cl), key=cl.count)
        seg_info.append({"label": lab, "cluster": major if lab != "target" else target[0],
                         "wins": ws})

    def win_code(w):
        if labels[w] == -1:
            return "X"     # overlapped speech (pyannote)
        return "T" if is_t[w] else ("?" if labels[w] < 0 else "o")

    # ---- group consecutive segments into clips
    groups, cur = [], None
    for si, (s, e) in enumerate(segs):
        key = (seg_info[si]["label"], seg_info[si]["cluster"])
        if (cur is not None and key == cur["key"] and key[0] != "mixed"
                and s - segs[cur["segs"][-1]][1] <= args.max_gap and e - cur["start"] <= args.max_len):
            cur["segs"].append(si)
            cur["end"] = e
        else:
            cur = {"key": key, "segs": [si], "start": s, "end": e}
            groups.append(cur)

    log("[slice] loading vocals at 44.1 kHz for clip export")
    a44 = load_audio(vocals, SR_CLIP)
    clips = []
    n = 0
    for gi, g in enumerate(groups):
        label, cl = g["key"]
        if label == "other" and not args.export_other:
            continue
        prev_end = groups[gi - 1]["end"] if gi > 0 else 0.0
        next_start = groups[gi + 1]["start"] if gi + 1 < len(groups) else total
        s = max(0.0, g["start"] - min(0.1, max(0.0, (g["start"] - prev_end) / 2)))
        e = min(total, g["end"] + min(0.1, max(0.0, (next_start - g["end"]) / 2)))
        dur = e - s
        if dur < 0.6:     # GPT-SoVITS drops < 0.6 s anyway (GPT_SoVITS/module/data_utils.py:96)
            continue
        ws = [w for si in g["segs"] for w in seg_info[si]["wins"]]
        f0v = np.concatenate([f0_values(si, *segs[si]) for si in g["segs"]])
        flags = []
        if label == "target":
            if dur < args.min_len:
                flags.append("short")
            if dur > args.max_len + 0.25:
                flags.append("long")
            if emb is not None:
                if np.nanmin(margin[ws]) < args.min_margin:
                    flags.append("uncertain")
                if np.nanmin(sim_t[ws]) < low_thr:
                    flags.append("low_sim")
            if len(f0v) < 10:
                flags.append("no_f0")
            if low_f0_hz and (low_f0_run(g["segs"]) >= args.low_f0_min_run
                              or any(win_f0[w] < low_f0_hz for w in ws if not np.isnan(win_f0[w]))):
                flags.append("low_f0")
        if any(labels[w] == -1 for w in ws):
            flags.append("overlap")
        n += 1
        name = f"{args.name}_{n:05d}.wav"
        x = a44[int(s * SR_CLIP):int(e * SR_CLIP)]
        peak = float(np.abs(x).max()) if len(x) else 0.0
        if peak > 0.98:
            x = x * (0.98 / peak)
        sf.write(clips_dir / name, x, SR_CLIP, subtype="PCM_16")
        clips.append({
            "clip": name, "label": label, "cluster": int(cl), "start": round(s + offset, 3),
            "end": round(e + offset, 3), "dur": round(dur, 3),
            "sim_target": nn(np.mean(sim_t[ws])) if emb is not None else None,
            "margin": nn(np.min(margin[ws])) if emb is not None else None,
            "f0_median": round(float(np.median(f0v)), 1) if len(f0v) else None,
            "win_labels": "".join(win_code(w) for w in ws), "flags": flags,
            "lang": args.language if args.language != "auto" else "", "text": "", "asr": {},
        })
    for c in clips:
        c["keep"] = default_keep(c, args.min_len, args.max_len)
    meta = {
        "version": 1, "name": args.name, "input": args.input, "offset": offset,
        "diarizer": args.diarizer, "embedder": args.embedder if need_emb else None,
        "language": args.language, "min_len": args.min_len, "max_len": args.max_len,
        "target": target, "target_how": how, "clusters": clusters, "clips": clips,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_meta(work, meta)
    nt = sum(1 for c in clips if c["keep"])
    log(f"[slice] {len(clips)} clips exported, {nt} pre-selected "
        f"({sum(c['dur'] for c in clips if c['keep'])/60:.1f} min)")
    return meta


def default_keep(c: dict, min_len: float, max_len: float) -> int:
    return int(c["label"] == "target" and min_len <= c["dur"] <= max_len + 0.25
               and not (set(c["flags"]) & SEVERE_FLAGS))


# ---------------------------------------------------------------------------- 5. transcribe
def setup_windows_cuda_dlls() -> None:
    """ctranslate2 (faster-whisper) needs cuBLAS 12 + cuDNN 9 DLLs on Windows. Use the pip wheels
    nvidia-cublas-cu12 / nvidia-cudnn-cu12 if installed, else torch\\lib of a CUDA-12 torch build.
    torch itself is NOT imported (keeps this process free of torch's CUDA context)."""
    if os.name != "nt":
        return
    dirs = []
    for mod in ("nvidia.cublas", "nvidia.cudnn"):
        try:
            spec = importlib.util.find_spec(mod)
        except (ImportError, ValueError):
            spec = None
        for loc in (spec.submodule_search_locations or []) if spec else []:
            if os.path.isdir(os.path.join(loc, "bin")):
                dirs.append(os.path.join(loc, "bin"))
    if not dirs:
        try:
            spec = importlib.util.find_spec("torch")
        except (ImportError, ValueError):
            spec = None
        for loc in (spec.submodule_search_locations or []) if spec else []:
            lib = os.path.join(loc, "lib")
            if glob.glob(os.path.join(lib, "cublas64_12.dll")):
                dirs.append(lib)
    for d in dirs:
        os.add_dll_directory(d)
        os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")


def clean_text(t: str) -> str:
    t = t.replace("|", " ").replace("\t", " ").replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", t).strip()


def stage_transcribe(args, work: Path) -> None:
    setup_windows_cuda_dlls()
    from faster_whisper import WhisperModel
    meta = load_meta(work)
    labels = set(args.asr_labels.split(","))
    todo = [c for c in meta["clips"] if c["label"] in labels and (args.redo_asr or not c.get("text"))]
    if not todo:
        log("[asr] nothing to transcribe")
        write_review(work, meta)
        return
    log(f"[asr] faster-whisper {args.whisper_model} on {args.asr_device}/{args.compute_type}, {len(todo)} clips")
    model = WhisperModel(args.whisper_model, device=args.asr_device, compute_type=args.compute_type,
                         download_root=str(Path(args.models_dir) / "whisper"))
    lang = None if meta["language"] == "auto" else meta["language"]
    clips_dir = work / "02_review" / "clips"
    t0 = time.time()
    for i, c in enumerate(todo, 1):
        segments, info = model.transcribe(
            str(clips_dir / c["clip"]), language=lang, beam_size=args.beam_size, vad_filter=False,
            condition_on_previous_text=False, without_timestamps=True,
            initial_prompt=args.initial_prompt or None)
        segments = list(segments)
        text = clean_text("".join(s.text for s in segments))
        c["text"] = text
        c["lang"] = info.language if lang is None else lang
        lp = float(np.mean([s.avg_logprob for s in segments])) if segments else None
        ns = float(max(s.no_speech_prob for s in segments)) if segments else None
        cr = float(max(s.compression_ratio for s in segments)) if segments else None
        c["asr"] = {"avg_logprob": lp, "no_speech_prob": ns, "compression_ratio": cr,
                    "language": info.language, "language_probability": float(info.language_probability)}
        fl = [f for f in c["flags"] if not f.startswith("asr_") and f != "lang_unsupported"]
        if not text:
            fl.append("asr_empty")
        if lp is not None and (lp < -1.0 or (ns or 0) > 0.6):
            fl.append("asr_lowconf")
        if cr is not None and cr > 2.4:
            fl.append("asr_repeat")
        if any(h.lower() in text.lower() for h in HALLUCINATIONS):
            fl.append("asr_hallucination")
        rate = len(text.replace(" ", "")) / max(c["dur"], 1e-3)
        if text and (rate < 1.0 or rate > 30):
            fl.append("asr_rate")
        if c["lang"] not in LIST_LANGS:
            fl.append("lang_unsupported")
        c["flags"] = fl
        c["keep"] = default_keep(c, meta["min_len"], meta["max_len"])
        if i % 25 == 0 or i == len(todo):
            save_meta(work, meta)
            el = time.time() - t0
            log(f"[asr] {i}/{len(todo)}  ({el/i:.2f}s/clip)  {c['clip']}: {text[:40]}")
    save_meta(work, meta)
    write_review(work, meta)


# -------------------------------------------------------------------------------- 6. review
def write_review(work: Path, meta: dict) -> None:
    review = work / "02_review"
    with open(review / "review.csv", "w", encoding="utf-8-sig", newline="") as f:   # BOM: Excel shows JP text
        w = csv.writer(f)
        w.writerow(CSV_COLS)
        for c in meta["clips"]:
            a = c.get("asr") or {}
            w.writerow([c["keep"], c["clip"], c["label"], c["cluster"], fnum(c["start"]), fnum(c["end"]),
                        fnum(c["dur"]), fnum(c["sim_target"]), fnum(c["margin"]), fnum(c["f0_median"], 1),
                        c["win_labels"], " ".join(c["flags"]), c["lang"], c["text"],
                        fnum(a.get("avg_logprob")), fnum(a.get("no_speech_prob"))])
    data = json.dumps({"cols": CSV_COLS, "clips": meta["clips"], "clusters": meta["clusters"],
                       "name": meta["name"], "target_how": meta["target_how"], "input": meta["input"]},
                      ensure_ascii=False).replace("</", "<\\/")
    (review / "review.html").write_text(REVIEW_HTML.replace("__DATA__", data)
                                        .replace("__TITLE__", html.escape(meta["name"])), encoding="utf-8")
    log(f"[review] {review / 'review.html'}  and  {review / 'review.csv'}")


REVIEW_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Clip review - __TITLE__</title>
<style>
:root{--bg:#fff;--fg:#1d1d1f;--mut:#6b6b70;--line:#e2e2e6;--t:#e7f6ec;--o:#f4f4f6;--m:#fff4dc;--bad:#b3261e;--acc:#1a5fd0}
@media (prefers-color-scheme:dark){:root{--bg:#17171a;--fg:#ececf0;--mut:#9a9aa2;--line:#2e2e34;--t:#15301f;--o:#202024;--m:#3a2f12;--bad:#ff8a80;--acc:#8ab4ff}}
body{background:var(--bg);color:var(--fg);font:14px/1.4 system-ui,"Segoe UI","Yu Gothic UI",sans-serif;margin:0;padding:16px}
h1{font-size:18px;margin:0 0 4px} .mut{color:var(--mut)} table{border-collapse:collapse;width:100%}
th,td{border-bottom:1px solid var(--line);padding:4px 6px;text-align:left;vertical-align:middle}
th{position:sticky;top:0;background:var(--bg);font-weight:600;z-index:1}
tr.target{background:var(--t)} tr.other{background:var(--o)} tr.mixed{background:var(--m)}
tr.playing td{outline:2px solid var(--acc);outline-offset:-2px}
input.txt{width:100%;min-width:260px;font:inherit;background:transparent;color:inherit;border:1px solid var(--line);padding:3px}
input.lang{width:3.5em;font:inherit;background:transparent;color:inherit;border:1px solid var(--line)}
audio{height:30px;width:220px} .fl{color:var(--bad);font-size:12px} .num{font-variant-numeric:tabular-nums}
.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:10px 0}
button,select{font:inherit;padding:4px 10px} code{font-size:12px}
#sum td,#sum th{border:1px solid var(--line)} #sum{width:auto;margin:8px 0}
</style></head><body>
<h1>Clip review: __TITLE__</h1>
<div class="mut" id="src"></div>
<table id="sum"></table>
<div class="mut">Tick <b>keep</b> only for clips that contain <b>her voice only</b> (no male voice, no music, no laughter over speech).
Fix wrong transcripts in place. Window code: <code>T</code>=target window, <code>o</code>=other speaker, <code>X</code>=overlap, <code>?</code>=unlabeled.
When done press <b>Save edited CSV</b> and store it as <code>02_review/review_edited.csv</code>, then run <code>finalize</code>.</div>
<div class="bar">
 <label>Show <select id="filt"><option value="all">all</option><option value="keep">kept</option><option value="target">target</option>
 <option value="mixed">mixed</option><option value="other">other speaker</option><option value="flag">flagged</option><option value="dropped">target, not kept</option></select></label>
 <label><input type="checkbox" id="auto" checked> auto-play next</label>
 <button id="kall">keep all shown</button><button id="knone">un-keep all shown</button>
 <button id="save"><b>Save edited CSV</b></button><span id="stat" class="mut num"></span>
</div>
<table><thead><tr><th>#</th><th>keep</th><th>audio</th><th>label</th><th class="num">dur</th><th class="num">sim</th>
<th class="num">margin</th><th class="num">F0</th><th>windows</th><th>flags</th><th>lang</th><th>text</th></tr></thead><tbody id="tb"></tbody></table>
<script>
const D = __DATA__;
const C = D.clips;
document.getElementById('src').textContent = 'source: ' + D.input + '  |  target chosen by: ' + D.target_how;
const sum = document.getElementById('sum');
sum.innerHTML = '<tr><th>cluster</th><th>name</th><th>windows</th><th>~minutes</th><th>median F0</th><th>sim to ref</th><th>target</th></tr>' +
  D.clusters.map(c => `<tr><td>${c.id}</td><td>${c.name}</td><td>${c.windows}</td><td>${(c.speech_sec/60).toFixed(1)}</td><td>${c.f0_median ?? ''}</td><td>${c.sim_ref ?? ''}</td><td>${c.is_target ? 'YES' : ''}</td></tr>`).join('');
D.clusters.forEach(c => { const o = document.createElement('option'); o.value = 'c' + c.id;
  o.textContent = 'cluster ' + c.id + (c.is_target ? ' (target)' : ''); document.getElementById('filt').appendChild(o); });
const tb = document.getElementById('tb');
const fmt = (x, n) => (x === null || x === undefined) ? '' : Number(x).toFixed(n);
function stat(){ const k = C.filter(c => c.keep); document.getElementById('stat').textContent =
  `${k.length} kept / ${C.length} clips, ${(k.reduce((a, c) => a + c.dur, 0)/60).toFixed(1)} min kept`; }
function shown(c){ const f = document.getElementById('filt').value;
  return f === 'all' || (f === 'keep' && c.keep) || (f === c.label) || (f === 'flag' && c.flags.length) ||
    (f === 'dropped' && c.label === 'target' && !c.keep) || f === 'c' + c.cluster; }
function render(){
  tb.innerHTML = '';
  C.forEach((c, i) => { if (!shown(c)) return;
    const tr = document.createElement('tr'); tr.className = c.label; tr.dataset.i = i;
    tr.innerHTML = `<td class="num">${i+1}</td><td><input type="checkbox" class="k" ${c.keep ? 'checked' : ''}></td>
      <td><audio controls preload="none" src="clips/${encodeURIComponent(c.clip)}"></audio><div class="mut" style="font-size:11px">${c.clip} @ ${fmt(c.start,1)}s</div></td>
      <td>${c.label}${c.label !== 'target' ? ' (' + c.cluster + ')' : ''}</td><td class="num">${fmt(c.dur,2)}</td><td class="num">${fmt(c.sim_target,3)}</td>
      <td class="num">${fmt(c.margin,3)}</td><td class="num">${fmt(c.f0_median,0)}</td><td><code>${c.win_labels}</code></td>
      <td class="fl">${c.flags.join(' ')}</td><td><input class="lang" value="${c.lang || ''}"></td><td><input class="txt"></td>`;
    tr.querySelector('.txt').value = c.text || '';
    tr.querySelector('.k').onchange = e => { c.keep = e.target.checked ? 1 : 0; stat(); };
    tr.querySelector('.txt').oninput = e => { c.text = e.target.value.replace(/[|\r\n\t]/g, ' '); };
    tr.querySelector('.lang').oninput = e => { c.lang = e.target.value.trim(); };
    const au = tr.querySelector('audio');
    au.onplay = () => { document.querySelectorAll('audio').forEach(a => { if (a !== au) a.pause(); });
      document.querySelectorAll('tr.playing').forEach(r => r.classList.remove('playing')); tr.classList.add('playing'); };
    au.onended = () => { if (!document.getElementById('auto').checked) return; let n = tr.nextElementSibling;
      if (n) { const a = n.querySelector('audio'); n.scrollIntoView({block: 'center'}); a.play(); } };
    tb.appendChild(tr); });
  stat(); }
document.getElementById('filt').onchange = render;
document.getElementById('kall').onclick = () => { C.forEach(c => { if (shown(c)) c.keep = 1; }); render(); };
document.getElementById('knone').onclick = () => { C.forEach(c => { if (shown(c)) c.keep = 0; }); render(); };
function q(v){ v = (v === null || v === undefined) ? '' : String(v); return '"' + v.replace(/"/g, '""') + '"'; }
function toCSV(){
  const rows = [D.cols.join(',')];
  C.forEach(c => { const a = c.asr || {};
    rows.push([c.keep, c.clip, c.label, c.cluster, fmt(c.start,3), fmt(c.end,3), fmt(c.dur,3), fmt(c.sim_target,3), fmt(c.margin,3),
      fmt(c.f0_median,1), c.win_labels, c.flags.join(' '), c.lang || '', c.text || '', fmt(a.avg_logprob,3), fmt(a.no_speech_prob,3)].map(q).join(',')); });
  return '﻿' + rows.join('\r\n') + '\r\n'; }
document.getElementById('save').onclick = async () => {
  const blob = new Blob([toCSV()], {type: 'text/csv;charset=utf-8'});
  if (window.showSaveFilePicker) { try {
      const h = await showSaveFilePicker({suggestedName: 'review_edited.csv', types: [{description: 'CSV', accept: {'text/csv': ['.csv']}}]});
      const w = await h.createWritable(); await w.write(blob); await w.close(); return; } catch (e) { if (e.name === 'AbortError') return; } }
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'review_edited.csv'; a.click(); };
render();
</script></body></html>
"""


# ------------------------------------------------------------------------------ 7. finalize
def read_review_csv(p: Path) -> list[dict]:
    raw = p.read_bytes()
    for enc in ("utf-8-sig", "cp932"):   # Excel on Japanese Windows may save as Shift-JIS (cp932)
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        die(f"cannot decode {p} as UTF-8 or cp932")
    return list(csv.DictReader(text.splitlines()))


def stage_finalize(args, work: Path) -> None:
    meta = load_meta(work)
    review = work / "02_review"
    if args.csv:
        csv_path = Path(args.csv)
    else:
        ed, base = review / "review_edited.csv", review / "review.csv"
        csv_path = ed if ed.exists() else base
    log(f"[finalize] using {csv_path}")
    rows = read_review_csv(csv_path)
    name = args.name or meta["name"]
    out = Path(args.out) if args.out else work / "03_dataset"
    wav_dir = out / name / "wavs"
    if wav_dir.exists():
        shutil.rmtree(wav_dir)
    wav_dir.mkdir(parents=True)
    by_clip = {c["clip"]: c for c in meta["clips"]}
    lines, kept, skipped = [], [], []
    for r in rows:
        if str(r.get("keep", "")).strip().lower() not in ("1", "true", "yes", "y", "x"):
            continue
        clip = r["clip"].strip()
        src = review / "clips" / clip
        text = clean_text(r.get("text", ""))
        lang = (r.get("lang") or meta["language"]).strip().lower()
        lang = {"jp": "ja", "ja-jp": "ja"}.get(lang, lang)
        if not src.exists():
            skipped.append((clip, "missing wav"))
            continue
        if not text:
            skipped.append((clip, "empty text"))
            continue
        if lang not in LIST_LANGS:
            skipped.append((clip, f"language '{lang}' not supported by GPT-SoVITS"))
            continue
        info = sf.info(str(src))
        if not (0.6 < info.duration < 54):
            skipped.append((clip, f"duration {info.duration:.2f}s outside GPT-SoVITS 0.6-54 s"))
            continue
        dst = wav_dir / clip
        shutil.copyfile(src, dst)
        lines.append(f"{os.path.abspath(dst)}|{name}|{lang}|{text}")
        kept.append((clip, info.duration, by_clip.get(clip, {}), text))
    list_path = out / f"{name}.list"
    with open(list_path, "w", encoding="utf-8", newline="\n") as f:   # no BOM: 1-get-text.py reads utf8
        f.write("\n".join(lines) + ("\n" if lines else ""))
    # reference-audio candidates for GPT-SoVITS inference (must be 3-10 s: inference_webui.py:950)
    refs = sorted([k for k in kept if 3.0 <= k[1] <= 10.0 and not k[2].get("flags")],
                  key=lambda k: -(k[2].get("sim_target") or 0))[:15]
    with open(out / f"{name}_ref_candidates.txt", "w", encoding="utf-8") as f:
        for clip, d, c, txt in refs:
            f.write(f"{os.path.abspath(wav_dir / clip)}\t{d:.2f}s\t{txt}\n")
    tot = sum(k[1] for k in kept)
    log(f"[finalize] {len(lines)} clips, {tot/60:.1f} min -> {list_path}")
    langs = {}
    for ln in lines:
        langs[ln.split("|")[2]] = langs.get(ln.split("|")[2], 0) + 1
    log(f"[finalize] languages: {langs}")
    for clip, why in skipped:
        log(f"    skipped {clip}: {why}")
    if tot < 60:
        log("    WARNING: less than 1 minute of audio")
    print(f"\nGPT-SoVITS WebUI -> 1-GPT-SoVITS-TTS -> 1A-Dataset formatting:\n"
          f"  Text labelling file : {os.path.abspath(list_path)}\n"
          f"  Audio dataset folder: {os.path.abspath(wav_dir)}\n"
          f"Reference clips (3-10 s) for inference: {os.path.abspath(out / (name + '_ref_candidates.txt'))}")


# ---------------------------------------------------------------------------------- check
def cmd_check(args) -> None:
    import platform
    print("python      ", sys.version.split()[0], platform.platform())
    print("ffmpeg      ", shutil.which("ffmpeg"))
    try:
        from deno import find_deno_bin
        print("deno        ", find_deno_bin())
    except Exception:
        print("deno        ", shutil.which("deno") or "MISSING (pip install deno) - YouTube downloads need it")
    for mod in ("yt_dlp", "torch", "torchaudio", "audio_separator", "demucs", "speechbrain", "sherpa_onnx",
                "pyannote.audio", "faster_whisper", "ctranslate2", "onnxruntime", "sklearn", "librosa", "pyworld"):
        try:
            if mod == "pyannote.audio":
                os.environ.setdefault("PYANNOTE_METRICS_ENABLED", "0")
            m = importlib.import_module(mod)
            v = getattr(m, "__version__", None) or getattr(getattr(m, "version", None), "__version__", "?")
            print(f"{mod:12s} ", v)
        except Exception as e:
            print(f"{mod:12s}  not usable: {type(e).__name__}: {str(e)[:100]}")
    if "torch" in sys.modules:
        t = sys.modules["torch"]
        if t.cuda.is_available():
            p = t.cuda.get_device_properties(0)
            print(f"torch CUDA   {t.version.cuda}  {p.name}  cc {p.major}.{p.minor}  {p.total_memory/2**30:.1f} GiB")
        else:
            print("torch CUDA   NOT available (CPU-only torch build? reinstall from the cu128 index)")
    # ASR test in a clean child process (same as the real transcribe step)
    r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "_asrtest", "--asr-device", args.asr_device,
                        "--compute-type", args.compute_type, "--whisper-model", args.whisper_model,
                        "--models-dir", args.models_dir])
    print("faster-whisper test:", "OK" if r.returncode == 0 else f"FAILED (exit {r.returncode}) - see README 'CUDA DLLs'")


def cmd_asrtest(args) -> None:
    setup_windows_cuda_dlls()
    import ctranslate2
    from faster_whisper import WhisperModel
    print("ctranslate2 cuda devices:", ctranslate2.get_cuda_device_count())
    if args.asr_device == "cuda":
        print("supported compute types:", sorted(ctranslate2.get_supported_compute_types("cuda")))
    m = WhisperModel(args.whisper_model, device=args.asr_device, compute_type=args.compute_type,
                     download_root=str(Path(args.models_dir) / "whisper"))
    t = np.linspace(0, 1, SR16, dtype=np.float32)
    segs, info = m.transcribe(0.1 * np.sin(2 * np.pi * 220 * t), language="ja", vad_filter=False)
    list(segs)   # forces encoder+decoder (loads cuBLAS/cuDNN)
    print(f"whisper '{args.whisper_model}' ran on {args.asr_device}/{args.compute_type}")


# ----------------------------------------------------------------------------------- main
def add_common(p):
    p.add_argument("--work", required=True, help="working folder (one per source video)")
    p.add_argument("--models-dir", default=str(SCRIPT_DIR / "models"), help="model cache folder")


def add_asr(p):
    p.add_argument("--whisper-model", default="large-v3", help="faster-whisper size or HF id (large-v3, large-v3-turbo, medium ...)")
    p.add_argument("--asr-device", default="cuda", choices=["cuda", "cpu"])
    p.add_argument("--compute-type", default="float16", help="float16 | int8_float16 | int8 (cpu) | float32")
    p.add_argument("--beam-size", type=int, default=5)
    p.add_argument("--initial-prompt", default="", help="optional Whisper prompt, e.g. a punctuated Japanese sentence")
    p.add_argument("--asr-labels", default="target,mixed", help="which clip labels to transcribe (add ',other' for all)")
    p.add_argument("--redo-asr", action="store_true", help="re-transcribe clips that already have text")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="fetch + separate + diarize + slice + transcribe + review")
    add_common(r)
    add_asr(r)
    r.add_argument("--input", required=True, help="YouTube URL or local audio/video file")
    r.add_argument("--name", default="speaker", help="speaker name (ASCII, used in file names and the .list)")
    r.add_argument("--start", help="trim: start time in the source (s or hh:mm:ss)")
    r.add_argument("--end", help="trim: end time in the source")
    r.add_argument("--cookies-from-browser", help="yt-dlp: e.g. edge / chrome / firefox, if YouTube asks to sign in")
    r.add_argument("--separator", default="roformer", choices=["roformer", "demucs", "none"])
    r.add_argument("--sep-model", help=f"default: {DEFAULT_ROFORMER} (roformer) / {DEFAULT_DEMUCS} (demucs)")
    r.add_argument("--sep-chunk", type=float, default=600, help="audio-separator chunk length in s for long inputs (0 = off)")
    r.add_argument("--diarizer", default="ecapa", choices=["ecapa", "sherpa", "pyannote", "pitch"])
    r.add_argument("--embedder", choices=["ecapa", "sherpa"], help="embedding model (default = diarizer, ecapa for pyannote/--ref)")
    r.add_argument("--sherpa-model", default=DEFAULT_SHERPA_MODEL, help="sherpa-onnx speaker model file name or path")
    r.add_argument("--hf-token", help="Hugging Face token for --diarizer pyannote (or set HF_TOKEN)")
    r.add_argument("--device", default="cuda", help="torch device for separation/ECAPA/pyannote")
    r.add_argument("--threads", type=int, default=max(1, (os.cpu_count() or 4) // 2))
    r.add_argument("--num-speakers", type=int, default=2, help="clusters to find (1 = solo video); 0 = pick 2..6 by silhouette")
    r.add_argument("--target-cluster", help="force target cluster id(s), e.g. 0 or 0,2 (see review.html summary)")
    r.add_argument("--ref", nargs="*", help="audio file(s) with ONLY her voice (a few seconds each)")
    r.add_argument("--ref-span", nargs="*", help="time span(s) in the source where only she speaks, e.g. 83.5-95 1:40-1:52")
    r.add_argument("--language", default="ja", help="ja | en | auto (per-clip detection)")
    r.add_argument("--min-len", type=float, default=3.0)
    r.add_argument("--max-len", type=float, default=10.0)
    r.add_argument("--max-gap", type=float, default=0.6, help="max pause inside one clip (s)")
    r.add_argument("--win", type=float, default=1.5, help="embedding window (s)")
    r.add_argument("--hop", type=float, default=0.75, help="embedding hop (s)")
    r.add_argument("--min-margin", type=float, default=0.05, help="flag 'uncertain' if a window is this close to another cluster")
    r.add_argument("--low-sim-mads", type=float, default=3.0, help="flag 'low_sim' below median - N*MAD of target windows")
    r.add_argument("--f0-split", type=float, default=165.0, help="--diarizer pitch threshold (Hz)")
    r.add_argument("--low-f0-hz", type=float, help="override the automatic 'low_f0' threshold (Hz); 0 disables the check")
    r.add_argument("--low-f0-min-run", type=float, default=0.25, help="... lasting at least this many seconds")
    r.add_argument("--vad-threshold", type=float, default=0.5)
    r.add_argument("--vad-min-silence-ms", type=int, default=300)
    r.add_argument("--no-export-other", dest="export_other", action="store_false", help="do not export other-speaker clips for review")
    r.add_argument("--asr", default="on", choices=["on", "none"])
    r.add_argument("--force", action="store_true", help="redo every stage")
    r.add_argument("--redo-diarize", action="store_true", help="redo diarize/slice (keeps download + vocals)")

    t = sub.add_parser("transcribe", help="(re)run faster-whisper on the clips and rewrite the review files")
    add_common(t)
    add_asr(t)

    f = sub.add_parser("finalize", help="write the GPT-SoVITS dataset from the reviewed CSV")
    add_common(f)
    f.add_argument("--csv", help="reviewed CSV (default: 02_review/review_edited.csv, else review.csv)")
    f.add_argument("--name", help="speaker name in the .list (default: from run)")
    f.add_argument("--out", help="output folder (default: <work>/03_dataset)")

    c = sub.add_parser("check", help="check the environment (versions, CUDA, faster-whisper on GPU)")
    c.add_argument("--models-dir", default=str(SCRIPT_DIR / "models"))
    c.add_argument("--asr-device", default="cuda", choices=["cuda", "cpu"])
    c.add_argument("--compute-type", default="float16")
    c.add_argument("--whisper-model", default="tiny")

    a = sub.add_parser("_asrtest")
    a.add_argument("--models-dir", default=str(SCRIPT_DIR / "models"))
    a.add_argument("--asr-device", default="cuda")
    a.add_argument("--compute-type", default="float16")
    a.add_argument("--whisper-model", default="tiny")

    args = ap.parse_args()
    if args.cmd == "check":
        return cmd_check(args)
    if args.cmd == "_asrtest":
        return cmd_asrtest(args)
    require_ffmpeg()
    work = Path(args.work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    if args.cmd == "run":
        if not re.fullmatch(r"[A-Za-z0-9_\-]+", args.name):
            die("--name must be ASCII letters/digits/_/- (it becomes part of every file name)")
        if args.language != "auto" and args.language not in LIST_LANGS:
            die(f"--language must be auto or one of {sorted(LIST_LANGS)}")
        args.embedder = args.embedder or (args.diarizer if args.diarizer in ("ecapa", "sherpa") else "ecapa")
        if args.min_len >= args.max_len:
            die("--min-len must be < --max-len")
        src = stage_fetch(args, work)
        voc = stage_separate(args, work, src)
        meta = stage_diarize_and_slice(args, work, voc)
        write_review(work, meta)
        if args.asr == "on":
            cmd = [sys.executable, str(Path(__file__).resolve()), "transcribe", "--work", str(work),
                   "--models-dir", args.models_dir, "--whisper-model", args.whisper_model,
                   "--asr-device", args.asr_device, "--compute-type", args.compute_type,
                   "--beam-size", str(args.beam_size), "--asr-labels", args.asr_labels]
            if args.initial_prompt:
                cmd += ["--initial-prompt", args.initial_prompt]
            if args.redo_asr or args.redo_diarize or args.force:
                cmd += ["--redo-asr"]
            log("[asr] starting child process (no torch in it)")
            rc = subprocess.run(cmd).returncode
            if rc != 0:
                die(f"transcription failed (exit {rc}). Clips and review.html without text are ready.\n"
                    f"Fix CUDA DLLs (README) or retry on CPU:\n  python {Path(__file__).name} transcribe "
                    f"--work \"{work}\" --asr-device cpu --compute-type int8")
        print(f"\nNEXT: open {work / '02_review' / 'review.html'} in Edge/Chrome, review, 'Save edited CSV' as\n"
              f"      {work / '02_review' / 'review_edited.csv'}, then:\n"
              f"      python {Path(__file__).name} finalize --work \"{work}\"")
    elif args.cmd == "transcribe":
        stage_transcribe(args, work)
    elif args.cmd == "finalize":
        stage_finalize(args, work)


if __name__ == "__main__":
    main()
