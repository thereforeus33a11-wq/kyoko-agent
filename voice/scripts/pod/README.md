# Her voice on a rented GPU (Runpod), as it was run on 2026-11-18

Nothing of her voice is in this folder: the scripts only. Her clips, the trained models and
the practice audio stay off the repository.

Order on the pod (4x RTX 4090; image runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404):

1. `setup.sh`: GPT-SoVITS (commit 6d51ffc), Piper 1.8 (piper1-gpl 46c3c71), the Japanese
   recogniser, the Piper base voice (hifi_tts_92, CC BY 4.0).
   - Then, in the Piper env, swap `pyopenjtalk-plus` for plain `pyopenjtalk==0.4.1`. That is
     exactly what the phone runs, so the voice is trained on the labels the phone makes.
   - Then apply `ddp_patch.py` (Piper 1.8 cannot train on several GPUs without it) and
     `mos_patch.py` (drops the val_mos checkpoint callback, which breaks training once the
     MOS predictor is off).
2. `exps.sh` / `exp.sh`: training experiments (full precision only; see VOICE_PLAN.md).
3. `stage1c.sh`: the chosen pair, the owner's test file, about 3,100 practice lines on 8
   readers, checked by `check_distill.py` and brightened.
4. `stage2.sh`: the Piper voice, 800 epochs on 4 GPUs (bf16, DDP).
5. `stage3.sh`: ONNX export, sherpa-onnx metadata and tokens (`sherpa_meta.py`), int8
   copy, and a test that speaks lines the phone's way (`phone_test.py`).

Files move to and from the pod only through the Runpod API's exec call (`podio.py`), which
reads the API key from a local file and never prints it.

Two traps worth knowing:
- GPT-SoVITS at this commit: on GPU, its CUDA-graph decoder cuts lines short. `speak.py` turns
  it off.
- Half-precision training made a voice that skipped most words. Train in full precision.

Added after the phone voice was finished:
- `morning.sh`: after training, exports her phone voice on the pod, fetches it, scores 25 new lines
  (`her_test.txt`) with `asr_kana.py` (Japanese ASR, kana error rate, 0.3 s of silence padded on
  each side so the recognizer does not miss a first phrase), and packs it with
  `opendroid/tools/make_own_voice.sh`.
- `laughs.sh`, `laugh_lines.txt`, `pack_laughs.py`: her laughs and small sounds from the teacher
  voice, three takes per line from four references, packed one file per sound with pitch per take.
- `make_ab.py`, `ab_speak.py`: English A/B. A sends English words through katakana as the phone
  does; B splices English IPA (from CMU ARPAbet) between her Japanese phonemes, since her phone
  voice was warm-started from an English voice and still has those phoneme ids.
- `podio.py` waits out the API's rate limit with a growing backoff, and uses a precomputed
  `<file>.sha256` for files too big to hash within one exec call.

## Her English on the phone (bilingual Piper), prepared 2026-11-19

One voice, fine-tuned from e800, that reads English as English (IPA) and Japanese as before.
Nothing here is voice data: the lines are text, the clips and models stay on the pod and off the repo.

The shared English table, read the same way by training and (to come) by the phone:
- `en_ipa_table.json`: ARPAbet to IPA in espeak en-us style (stress mark before the vowel, AH0 ə / AH1 ʌ,
  ER0 ɚ / ER1 ɜː, IY0 i / IY1 iː, no flapping), weak forms of function words, overrides (her contractions
  without apostrophes, chat words), her romaji words (`ja_words`), letter names, numbers, suffix rules,
  and the rules for cutting a line into sentences and segments and joining them. Pinned to the CMU
  dictionary by sha256. `opendroid/tools/make_own_voice.sh` ships it in the voice assets.
- `en_phonemize.py` (English words), `mix_phonemize.py` (whole lines: Latin runs to English, kana and
  kanji and her romaji to Piper's JapanesePhonemizer; a pure Japanese sentence goes to Open JTalk whole,
  so her Japanese stays byte-identical to e800's training), `kana_text.py` (today's katakana route, for
  the A/B and the kana check).
- `tests/`: `python -m unittest discover -s tests` (CMUDICT and PIPER_SRC set). `tests/make_golden.py`
  writes `tests/fixtures/golden_mixed.tsv`, 615 texts with their codepoints, for the phone's Kotlin port.

Her lines (`lang_lines/`, built by `build_lang_lines.py` into `lang_lines/out/`): about 2,670 English and
660 mixed lines in her register (school English, street English learned in Japan, Japanese-flavoured
English, questions and replies, numbers; Japanese tails and Japanese-led lines). `tatoeba.tsv` comes from
Tatoeba (https://tatoeba.org, CC BY 2.0 FR) via `tatoeba_pick.py`. The text column is what the phone's
normalizer hands the voice; `speak_lang.txt` is the teacher's input (numbers spelled, her romaji in kana).
60 lines are held out (never trained) for scoring.

On the pod, after `setup.sh` (and the pyopenjtalk 0.4.1 swap):
1. `setup_lang.sh`: faster-whisper large-v3 in `/w/asr-env`, WavLM-SV, both on `/workspace/models`;
   `mixed_patch.py` on Piper (mixed phonemizer at the phonemize step, fixed validation list, a kept
   checkpoint every N epochs, a learning-rate restart for the resumed run); parity and unit tests.
2. `MODE=pilot stage1_lang.sh`: the 60 held-out lines with her GPT e10 and with the pretrained GPT, both on
   her SoVITS; WER, pitch, timbre; `pilot/choice.txt`, `pilot_her.wav`, `pilot_base.wav`.
3. `MODE=full stage1_lang.sh`: two takes per line, `check_lang.py` asr / prep / sim / pick into
   `out/lang/ds_lang` (best take, brightened like her Japanese, pitch caps, English not above her
   Japanese by more than 1.5 semitones).
4. `make_ds_mix.py`: 1,500 Japanese replay lines (checked byte-identical to Piper's phonemes) plus the
   English and mixed set, into `out/ds_mix`.
5. `DRY=1 stage2_lang.sh`, then `stage2_lang.sh`: resume e800's run (`--ckpt_path`) to epoch 1100.
6. `score_lang.sh`: export epochs 900/1000/1100, speak the held-out lines and her_test.txt the phone's
   way (`phone_test_lang.py`), score against the teacher and e800 (`score_student.py`), pick, A/B wav,
   chosen voice in `/workspace/phone_lang` with `.sha256` files for `podio.py down`.
