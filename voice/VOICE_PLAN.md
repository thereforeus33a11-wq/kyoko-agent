# Her voice: from your friend's recording to a voice that runs on the phone

The goal: her voice comes from a model on your Flip 7 itself. Nothing she says goes to ElevenLabs or anyone else. The voice is your voice actress friend's, used with her agreement.

The route has two models:

1. A large, good model is trained on your laptop: **GPT-SoVITS v2ProPlus**.
2. That model teaches a small, fast one: **Piper**, run on the phone by **sherpa-onnx**.

GPT-SoVITS itself is too heavy to run well on a phone. The small model sounds like the large one, and it is about 60 MB.

Steps 1 to 5 run on your laptop (RTX, 8 GB). Step 6 is the app, done in a coding session.

| Step | What | Where | Status |
|---|---|---|---|
| 1 | Clean her voice out of the video: drop music and the male voice, cut it into clips, transcribe | laptop, Windows | script in `voice/dataprep/` |
| 2 | Fine-tune GPT-SoVITS v2ProPlus on the clips | laptop, Windows | steps below (GPT-SoVITS webui) |
| 3 | Have it speak a few hours of varied sentences, Japanese and English, and keep only the clean ones | laptop | script to come |
| 4 | Train a Piper voice on that set, with Japanese pronunciation | laptop, WSL2 (Ubuntu) | script to come |
| 5 | Convert the Piper voice for sherpa-onnx (`model.onnx` + `tokens.txt`) | laptop | script to come |
| 6 | The app: sherpa-onnx voice engine plus Japanese pronunciation on the phone (OpenJTalk) | coding session | to build |

## Step 1: her voice, clean (`voice/dataprep/`)

See `voice/dataprep/README.md` for the exact Windows setup. In short:

1. `run` downloads the video and separates the voice from music.
2. It finds the speakers. It keeps hers and flags anything unsure.
3. It cuts her speech into 3 to 10 second clips and transcribes them in Japanese.
4. You open `review.html`. Listen to the clips, untick anything that is not her (a male backchannel over her voice cannot be caught any other way), fix any wrong text, then save.
5. `finalize` writes the dataset in the form GPT-SoVITS reads.

More clean audio gives a better voice. Ten to thirty minutes of her alone is a good target. If one video gives less, run the script on more of her recordings and merge the results.

## Step 2: fine-tune GPT-SoVITS v2ProPlus

Install GPT-SoVITS on Windows (https://github.com/RVC-Boss/GPT-SoVITS):

- Use the integrated package, or `conda create -n GPTSoVits python=3.10`, then `pwsh -F install.ps1 -Device CU126 -Source HF`.
- Pick CU126 for the RTX 20-series.
- Use a separate environment from step 1: GPT-SoVITS needs numpy below 2, and the data-prep tools need numpy 2.

In the webui (`go-webui.bat`), set the version to **v2ProPlus**, then:

1. Under 1A, point it at the `.list` file and the `wavs` folder from step 1, and run the one-click formatting (1Aabc).
2. Under 1Ba, train SoVITS with batch size 4 and 8 epochs.
3. Under 1Bb, train GPT with batch size 4 and 15 epochs.
4. Under 1C, try it with a 3 to 10 second reference clip of her (from `<name>_ref_candidates.txt`) and its text.

The webui saves a checkpoint every few epochs. Listen to a few of them; the last one is not always the best. Keep the pair that sounds most like her and pronounces cleanly.

## Step 3: the distillation set (script to come)

The fine-tuned model speaks a few thousand sentences:

- mostly Japanese, in her register: casual, short, and with her words;
- some English, in her crooked second-language English.

Each clip is transcribed again. A clip whose words do not match its text is dropped, because the large model sometimes repeats or skips words. The result is a few hours of her voice, all clean, at the sample rate Piper trains on.

## Step 4: the Piper voice (script to come)

Piper 1.8 has a Japanese phonemizer, OpenJTalk with pitch accent. It fine-tunes from an existing voice on 8 GB of VRAM, and runs under WSL2 (Ubuntu) on Windows.

- Base voice: `en_US-hifi_tts_92-medium`, which is CC BY 4.0, female and higher-pitched.
- Not the Lessac voices: those are research-only.

Japanese and English share one phoneme table, so one voice speaks both.

## Step 5: convert for the phone (script to come)

Piper exports `model.onnx`. sherpa-onnx's `add_meta_data.py` adds what the phone needs and writes `tokens.txt`. A smaller int8 version can be made and compared by ear.

## Step 6: the app (coding session)

- sherpa-onnx 2.0.1 goes into the app. It is Apache-2.0, runs on the phone's CPU, and needs nothing on the network.
- Her lines go to it instead of to the phone's own voice.
- The model files go into the app's private folder. You copy them in once from Settings.
- Japanese text has to be turned into the same phonemes Piper trained on. That needs OpenJTalk and its dictionary built for Android, plus a port of Piper's Japanese phonemizer, and it must match exactly. This is the largest single piece of the work.
- English: either the same phoneme table, from a dictionary, or English written in katakana and read through OpenJTalk. The katakana route gives her accent by itself.
- The Exynos NPU is not used. sherpa-onnx has no Samsung NPU path, and the CPU is fast enough for a model this size.

## Status (2026-11-18)

Done on a rented GPU (Runpod, 4x RTX 4090), not on the laptop:

- **Step 2.** GPT-SoVITS v2ProPlus retrained on 8.1 min of her (71 clips from the 12-minute reel plus the first 7 clips).
  - The sound model (SoVITS) is trained on all 71 clips. The text model (GPT) is trained on the 7 clean clips: the reel's transcripts are rougher, and its text model dropped words.
  - Both are trained in full precision. Half precision on the GPU made a voice that skipped most of each line.
  - This GPT-SoVITS commit's CUDA-graph decoder also cuts lines short on the GPU, so `speak.py` turns it off.
- **Step 3.** About 3,100 practice sentences: the ITA corpus, her casual lines, and everyday sentences from Tatoeba (CC BY 2.0 FR, used only as practice text).
  - Each clip is checked by Japanese speech recognition; a clip whose words do not match its text is dropped.
  - Each kept clip is brightened as in VOICE_SETTINGS.md.
- **Steps 4-5.** Piper is trained on its Japanese phonemes, made with plain pyopenjtalk 0.4.1. That is exactly the front end the phone runs, so the phone gives the voice what it learned from.

Built in the app (step 6), in `core/voice/own`:

- **Open JTalk on the phone** (`app/src/main/cpp`, JNI). Its labels match pyopenjtalk's byte for byte on 498 test lines, numbers, half-width kana and emoji included.
- **A Kotlin port of Piper's label-to-phoneme step**, tested against Piper's own output.
- **Her text to kana** (`KanaText`):
  - English becomes katakana from the CMU dictionary, which gives her accent.
  - Romaji and her Japanese words become hiragana.
  - Names in neither are read the Japanese way.
- **Playback**, sentence by sentence, through sherpa-onnx 2.0.1.
  - Stop, or a new message, cuts it off mid-word.
  - Setting: Settings, Persona, "Her own voice", on by default.

The voice files (model, tokens, Open JTalk dictionary, CMU dictionary) go into the APK from `opendroid/own_voice/`, which is never committed. Open JTalk and sherpa-onnx are fetched at pinned versions with checked hashes by `opendroid/tools/fetch_voice_native.sh`.

## Privacy

- Nothing in steps 1 to 5 sends anything of yours anywhere. The data is her voice and the sentences she reads.
- On the phone, the voice runs offline.
- Keep your friend's agreement somewhere in writing: it is her voice.

## What has not been checked yet

- Which CUDA build of PyTorch works best on an RTX 2070/2080 laptop GPU.
- Whether every download in step 1 (YouTube, model weights) works from your network.
- How fast the Piper voice is on the Flip 7 itself. On a Raspberry Pi 4 it already runs faster than real time, and the Flip 7's cores are much faster.

These all get checked on your laptop and phone.
