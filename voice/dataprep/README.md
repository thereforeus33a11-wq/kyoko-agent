# prep_voice_dataset.py: YouTube video to a female-only GPT-SoVITS dataset

One script, four commands:

| command | what it does |
|---|---|
| `check` | prints versions, torch CUDA status, and runs faster-whisper once on the GPU in a child process |
| `run` | download, vocal separation, VAD, speaker clustering, 3-10 s clips, transcription, review page |
| `transcribe` | re-runs only the faster-whisper step, for example on CPU or with another model |
| `finalize` | reads your reviewed CSV and writes `03_dataset/<name>.list` and `03_dataset/<name>/wavs/` |

The `.list` line format is the one in the GPT-SoVITS README ("Dataset Format"): `vocal_path|speaker_name|language|text`, with language `ja` / `en` / `zh` / `ko` / `yue`. This is the format that `GPT_SoVITS/prepare_datasets/1-get-text.py` parses.

Use this only with the speaker's consent. Keep her written OK together with the dataset.

---

## 1. Windows setup (PowerShell, once)

Put the three files `prep_voice_dataset.py`, `requirements-dataprep.txt` and `constraints-dataprep.txt` in one folder, for example `C:\voice`.

```powershell
winget install -e --id Python.Python.3.12
winget install -e --id Gyan.FFmpeg
# close and reopen PowerShell so ffmpeg is on PATH
cd C:\voice
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
python -m pip install --upgrade pip
pip install torch==2.8.0 torchaudio==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cu128
pip install -r requirements-dataprep.txt -c constraints-dataprep.txt
python prep_voice_dataset.py check
```

* Use a separate venv from GPT-SoVITS. GPT-SoVITS pins `numpy<2.0` and `librosa==0.10.2`, but `audio-separator` 0.48.0 needs `numpy>=2`.
* `check` must show a `torch CUDA` line with your RTX card and `faster-whisper test: OK`.
* **CUDA DLLs (faster-whisper):** CTranslate2 4.9.0 needs cuBLAS 12 and cuDNN 9 DLLs. The script first looks for the pip wheels `nvidia-cublas-cu12` and `nvidia-cudnn-cu12`, and otherwise uses `torch\lib` from the cu128 torch build. It does this before importing faster-whisper. If `check` still fails, run the line below and then `check` again:
  ```powershell
  pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"
  ```
  As a last resort, run transcription on the CPU: `--asr-device cpu --compute-type int8`. It is slower but needs no CUDA libraries.
* **Optional: pyannote diarization** needs a Hugging Face token.
  1. Accept the model conditions at https://hf.co/pyannote/speaker-diarization-community-1.
  2. Create a read token at https://hf.co/settings/tokens.
  3. Install the packages and set the token:
     ```powershell
     pip install pyannote.audio==4.1.0 torchcodec==0.7.0 -c constraints-dataprep.txt
     $env:HF_TOKEN = "hf_xxx"
     ```
  The script turns pyannote telemetry off (`PYANNOTE_METRICS_ENABLED=0`) and passes audio as an in-memory waveform, so torchcodec/FFmpeg DLL problems do not matter.

Models are downloaded on first use into `C:\voice\models\`:

| model | source |
|---|---|
| BS-Roformer | GitHub releases of `TRvlvr/model_repo` |
| ECAPA | Hugging Face `speechbrain/spkrec-ecapa-voxceleb` |
| Whisper | Hugging Face `Systran/faster-whisper-large-v3` |
| sherpa models | GitHub releases of `k2-fsa/sherpa-onnx` |

## 2. Run

```powershell
python prep_voice_dataset.py run --input "https://www.youtube.com/watch?v=XXXXXXXXXXX" --work work\kyoko --name kyoko --language ja --ref-span 1:23-1:35 4:10-4:18
```

* `--ref-span`: one to three time ranges in the video where **only she** speaks, about 5-15 s each. This is strongly recommended because it decides which cluster is her. Without it, the script picks the cluster with the highest median F0 and warns if that looks male. `--ref her_only.wav` works too.
* A local file works the same way: `--input D:\clips\stream.mkv`.
* `--start 0:45 --end 58:30` trims an intro or outro. Times in the review are always video times.
* If YouTube asks you to sign in or confirm you are not a bot, use `--cookies-from-browser firefox`. Chrome/Edge cookie decryption may fail on Windows; this is UNVERIFIED.
* Everything is resumable. The download (`00_source\source.wav`) and the vocals (`01_vocals\vocals.wav`) are reused. VAD, F0 and embeddings are cached in `02_review\diarize_cache.npz`, so these re-runs take seconds:
  ```powershell
  python prep_voice_dataset.py run --input "<same url>" --work work\kyoko --name kyoko --redo-diarize --target-cluster 0,2
  ```

What `run` does:

1. **fetch**: yt-dlp `bestaudio/best`, then ffmpeg converts to 44.1 kHz stereo WAV. yt-dlp needs the `yt-dlp-ejs` package plus a JS runtime for YouTube. `deno` from pip is passed to yt-dlp automatically.
2. **separate**: `audio-separator` with `model_bs_roformer_ep_317_sdr_12.9755.ckpt` (the library's default), keeping only the Vocals stem. Long files are processed in 600 s chunks (`--sep-chunk`).
   * `--separator demucs` uses `htdemucs_ft` instead.
   * `--separator none` skips this step if there is no music.
3. **diarize**:
   * Silero VAD (bundled in faster-whisper) splits the vocals into speech segments.
   * Each segment is cut into 1.5 s windows (0.75 s hop), and each window gets a speaker embedding.
   * The windows are clustered into `--num-speakers` groups (default 2). Ward linkage is used because average linkage produced one-window "outlier" clusters in tests.
   * The target cluster is picked by `--ref-span`, `--ref`, `--target-cluster`, or highest F0.

   `--diarizer` options:

   | value | embeddings | notes |
   |---|---|---|
   | `ecapa` (default) | SpeechBrain ECAPA | runs on GPU |
   | `sherpa` | sherpa-onnx `wespeaker_en_voxceleb_resnet34_LM.onnx` | CPU only, no torch |
   | `pyannote` | full pyannote community-1 diarization | marks overlapped speech; needs HF token |
   | `pitch` | none | median-F0 threshold `--f0-split 165` only; crude fallback |
4. **slice**: consecutive segments of her voice with pauses of at most 0.6 s become clips of at most 10 s. They are written as mono 16-bit 44.1 kHz WAV. Clips of other speakers and "mixed" clips are exported too (keep=0), so you can rescue mistakes.
5. **transcribe**: faster-whisper `large-v3`, float16 on the GPU, `language=ja`, beam 5, no VAD. It runs in a child process that never imports torch, so separation and ECAPA VRAM are already freed.
   * `--language auto` detects the language per clip, for her English lines.
   * `--initial-prompt "えっと、今日はね、ちょっと話したいことがあるの。"` nudges Whisper toward casual, punctuated Japanese.
6. **review**: writes `02_review\review.html` and `02_review\review.csv`.

## 3. Review (the important part)

Open `work\kyoko\02_review\review.html` in Edge or Chrome.

* Every clip has a player, a **keep** checkbox, its label (`target` / `mixed` / `other (cluster)`), and these columns:
  * `sim`: cosine similarity to her centroid.
  * `margin`: her similarity minus the best other cluster.
  * median `F0`.
  * window code: `T` = her, `o` = other, `X` = overlap.
  * flags, language, and an editable transcript.
* "auto-play next" lets you listen through the list hands-free.
* Filters:
  * `target, not kept`: rescue clips that were flagged by mistake.
  * `mixed`: clips where a speaker change was detected inside the clip.
  * `cluster N`: hear what each cluster is.
* Untick anything with the male voice, laughter over speech, music bleed, or a cut-off word. Fix transcripts. Japanese punctuation `、。？！` helps GPT-SoVITS prosody.
* Press **Save edited CSV** and save it as `work\kyoko\02_review\review_edited.csv`. Edge/Chrome show a save dialog; otherwise the file lands in Downloads and you move it.

You can also edit `review.csv` in Excel (`keep` = 1/0, `text`). Save as "CSV UTF-8". A Shift-JIS (cp932) save is also accepted.

Clips with these flags start unticked:

| flag | meaning |
|---|---|
| `short` / `long` | outside `--min-len 3` / `--max-len 10` s |
| `uncertain` | a window is within `--min-margin 0.05` of another speaker |
| `low_sim` | a window is below her robust similarity floor (median - 3 MAD) |
| `low_f0` | a voiced run of ≥0.25 s far below her pitch range (usually a male "un"/"sou" glued to her line). `--low-f0-hz 0` disables it |
| `overlap` | pyannote found overlapped speech |
| `no_f0` | almost no voiced frames |
| `asr_empty` / `asr_lowconf` / `asr_repeat` / `asr_rate` | transcript empty, low confidence (avg_logprob < -1 or no_speech > 0.6), repetitive (compression > 2.4), or implausible characters per second |
| `asr_hallucination` | known Whisper JA hallucination such as "ご視聴ありがとうございました" |
| `lang_unsupported` | language not in ja/en/zh/ko/yue |

## 4. Finalize

```powershell
python prep_voice_dataset.py finalize --work work\kyoko
```

This uses `review_edited.csv` if it exists, otherwise `review.csv`, or `--csv path`. It writes:

* `work\kyoko\03_dataset\kyoko\wavs\*.wav`, the kept clips.
* `work\kyoko\03_dataset\kyoko.list`: UTF-8 without BOM, `\n` line ends, absolute paths, `|` stripped from text. A BOM would corrupt the first path, because `1-get-text.py` opens the file as `utf8`.
* `work\kyoko\03_dataset\kyoko_ref_candidates.txt`: 3-10 s clips for GPT-SoVITS inference, which rejects references outside 3-10 s (`GPT_SoVITS/inference_webui.py:950`).

Clips with empty text, an unsupported language, or a duration outside 0.6-54 s are skipped with a message. GPT-SoVITS drops those anyway (`GPT_SoVITS/module/data_utils.py:96`).

Then in the GPT-SoVITS WebUI, go to **1-GPT-SoVITS-TTS** → **1A-Dataset formatting**:

* Text labelling file: `...\03_dataset\kyoko.list`
* Audio dataset folder: `...\03_dataset\kyoko\wavs`

For several videos, run each into its own `--work` folder with the same `--name`, finalize each, and concatenate the `.list` files. Clip names contain a running number per work folder, so use a different `--name` suffix per video (for example `kyoko_v1`, `kyoko_v2`). GPT-SoVITS keys features by file basename.

## Notes and limits

* Precision comes before recall: a few seconds of the male voice in a TTS dataset hurt more than losing some of her clips. Expect to rescue some clips from `target, not kept`.
* Backchannels (相槌) spoken **over** her speech cannot be removed by separation or clustering. Only `--diarizer pyannote` (overlap detection) and your ears catch them.
* The VRAM peak is the Roformer separation. If it runs out of memory on the 8 GB card, close other GPU apps, use `--sep-chunk 300`, or use `--separator demucs`.
