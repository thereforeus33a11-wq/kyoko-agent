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
