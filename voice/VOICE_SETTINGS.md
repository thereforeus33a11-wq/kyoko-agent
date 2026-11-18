# Her voice: the settings the owner chose

Chosen by ear on 2026-11-18, from the "teasing" test (version 2).

- Model: GPT-SoVITS v2ProPlus, fine-tuned on her 52 s recording
  - SoVITS: `yume_e8_s392.pth` (8 epochs)
  - GPT: `yume-e10.ckpt` (epoch 10)
- Reference clip (sets her delivery): clip 7,
  「こうやってギュッとしてたら全部分かるんだからね」 (8.5 s)
- Delivery: speed 1.08, temperature 1.1, top-k 25
- Brightening after synthesis (`scripts/younger.py`): +1.0 semitone, formants x1.04
  (a young adult woman; the script caps any setting at an adult range)

The owner's description of her voice: an immature young adult with little life
experience, book smart, teasing, confident, mischievous, feisty, dominant.
Not mature or refined, and not a child.

The recording, the clips and every trained model stay out of this public repo.
