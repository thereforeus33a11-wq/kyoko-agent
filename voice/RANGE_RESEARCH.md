# Her full vocal range: research (2026-11-20)

Not committed. Text only: no audio, no model, nothing of her voice.

The owner asked for this: "Id like it if she can make noises too. Like sighing, gasping, even yelling and being
able to whisper would be nice. Id like her to have the human range like most people have with their own voices.
Of course she is limited by her voice..."

His earlier rules still hold:
- One her, consistent from line to line.
- Clean. Breaths, snorts and room noise at the edges of lines are artifacts. A sigh she chooses is not.
- Not grainy, so no WORLD vocoder.
- Genuinely hers.
- One mind: her own model chooses when she sighs, whispers or yells. The voice only renders it.

## Short answer

- **Teacher side (pod).** Keep GPT-SoVITS as the teacher for her normal speech and her English. Add
  **Irodori-TTS v4.1-Small** as the teacher for her range: whisper, soft, loud, yell, teary, and the nonverbal
  sounds.
  - It is a Japanese-native model, MIT licensed, about 0.8B parameters, so it fits one 4090 easily.
  - It is controlled by emoji placed in the text: whisper, sigh, gasp, giggle, scream, sob, yawn, tut, hum,
    sniff and breathing.
  - It learns her voice by "speaker inversion": the base model stays frozen and only a few speaker tokens are
    trained, so the emoji controls survive.
  - Real sounds come first, before anything synthetic: cut her real sighs, tuts, giggles and gasps out of her own
    reel. Best of all, if the actress agrees, record a 10 to 15 minute "range session" with her.
  - Every take passes a gate for its style: speech recognition, timbre similarity measured within that style, and
    the owner's ear.
  - Before committing, run a one-day bake-off against Step-Audio-EditX (edits her teacher's own audio into whisper
    or shout) and Fish Audio S2-Pro.
- **Phone side.** Use **one multi-speaker Piper voice, with speaker ids used as styles**: 0 normal, 1 soft,
  2 whisper, 3 loud, 4 yell, and later 5 teary.
  - Warm-start it from her bilingual voice with piper1-gpl's own `--model.warmstart_ckpt`. It already zeroes the
    new speaker conditioning, so the model starts exactly as her current voice.
  - Add **a bank of her nonverbal sounds**: several takes each, picked at random, matched to the style's pitch and
    loudness, and played into the same AudioTrack between pieces of speech.
  - sherpa-onnx's `GenerationConfig` already has `sid`, and the app already passes `sid = 0`. The model stays
    about 60 MB and just as fast.
- **Her text.** Use a small closed set of square-bracket tags.
  - Point sounds: `[sigh]`, `[gasp]`, `[laugh]`, `[giggle]`, `[tch]`, `[hmph]`, `[hum]`, `[groan]`, `[yawn]`,
    `[sniff]`, `[inhale]`, `[exhale]`.
  - Spans: `[whisper]...[/whisper]`, `[soft]...[/soft]`, `[loud]...[/loud]`, `[yell]...[/yell]`.
  - The app strips them from what is shown and from every other output, and the voice renders them.
  - This is the convention used by ElevenLabs v3, Fish S2, CosyVoice and Chatterbox Turbo.

## 1. What exists today

- **Teacher.** GPT-SoVITS v2ProPlus (SoVITS `y71_e12`, GPT `y52-e10`).
  - It copies the delivery of its reference clip. That is why it also copied her breaths and room noise.
  - It is also why style references work: given an angry clip of hers, it speaks angrily.
- **Moods.** `auditions.sh` makes the moods default, mock_high, cold, snap, drunk and groggy from other clips of
  hers. These are emotions within normal voice.
  - **Whisper and yell do not exist yet.** Her 71 clips have no whisper at all.
- **Material in her reel.** Her reel already holds some loud, angry and nonverbal material:
  - Loud or angry: `v12_076` 調子こいてんじゃねえぞ..., `v12_049` 子供を盾にする気⁉卑劣な⁉, `v12_042` えらそうになに⁉.
  - Sighs: `v12_015` ...はあ悪いけど, `v12_067_1` はあダメですよ.
  - A tut: `v12_072_3` チッすぐ倒せると思ったのに.
  - A giggle: `yume_06` ウフフ.
  - Short gasps or "ah": `v12_044` あっ一人でずるい, `v12_069` あだったら.
  - Soft and teasing: `yume_01` to `yume_07`.
- **The laughs pack** (`laughs.sh`, `laugh_lines.txt`, `pack_laughs.py`) has 16 sounds such as あはは, ふふっ, ちっ,
  へっ, ふん, はぁ, えへへ and んー.
  - Each has 3 takes from each of 4 references.
  - It was made under the **old** rules: half precision, four rotating references, and WORLD brightening (`--half`
    and `younger.py` in `laughs.sh`).
  - It must be remade under the v2 rules: full precision, no brightening, cleaned, and one consistent reference
    per style.
- **The phone** (`core/voice/own/OwnVoice.kt`).
  - It plays one line at a time, sentence by sentence, through `generateWithConfigAndCallback` and one streaming
    AudioTrack, with `GenerationConfig(speed, sid = 0, phonemeCodepoints)`.
  - **No laugh or sound clip is played anywhere on the phone yet.** A grep for "laugh" in `core/voice` and
    `core/persona` finds only the speech normalizer:
    - typed "www" is said as "haha";
    - "fuuun" is a hum;
    - a gesture in asterisks such as `*sighs*` is **dropped** from speech (`GESTURE_ALONE`,
      `withoutStageDirections` in `SpeechTextNormalizer.kt`).
- **Her prompt** (`PersonaPrompts.kt`, lines 748-756 and 947) tells her: "no stage directions, no asterisks". So she
  has no way to ask for a sound today.

## 2. Teacher side: expressive models that can clone her (status November 2026)

| Model | How style is asked for | Japanese | Cloning | License (private use) | GPU on a 24 GB 4090 |
|---|---|---|---|---|---|
| **Irodori-TTS v4.1-Small** (Aratako, 2026) | Emoji in the text; a free-text caption | Native (Japanese codec, tokenizer and data) | Reference audio up to 120 s (30 s or more recommended); full fine-tune, LoRA, or speaker inversion | MIT, plus ethical rules: consent for cloning, no deepfakes | about 0.8B; fits easily (memory not stated; int8 and fp8 variants exist) |
| **Step-Audio-EditX** (StepFun, Nov 2025 to Jan 2026) | **Edits an existing clip**: style whisper, shout, roar, murmur, loudly; paralinguistics Breathing, Laughter, Sigh, Surprise-ah/oh/wa, Uhm; 14 emotions | Added 28 Nov 2025 | Zero-shot from a clip; edit mode keeps the input clip's voice | Code Apache-2.0; weights not stated separately on the card | 12 GB (16 GB safer); 6-8 GB in memory-saving mode |
| **Fish Audio S2-Pro** (Mar 2026) | Free-form inline `[tags]`: `[whisper]`, `[shouting]`, `[loud]`, `[sigh]`, `[inhale]`, `[exhale]`, `[laughing]`, `[panting]`, `[volume down]` and more | "Tier 1", alongside English and Chinese | 10 to 30 s reference; fine-tuning code released | Fish Audio Research License: research and non-commercial use free | "at least 24 GB": one whole 4090, tight |
| Fish OpenAudio S1-mini (2025) | `(whispering)`, `(shouting)`, `(sighing)`, `(laughing)`, `(sobbing)`, `(panting)`, `(groaning)` | yes | reference | CC-BY-NC-SA-4.0 | small |
| Fish Audio Drama 3 (report dated Oct 13; newest) | `[sighs]`, `[laughs]` and others | 83 languages; Japanese not named | reference plus transcript | "Fish Audio Community License" (terms unclear) | **48 GB or more (FP8)**: not on this pod |
| **Fun-CosyVoice3 0.5B** (Dec 2025) | Instruct (`... <\|endofprompt\|>`) for emotion, speed and volume; tokens `[breath]`, `[quick_breath]`, `[laughter]`, `<laughter>..</laughter>`, `[sigh]`, `<strong>..</strong>`, `[cough]`, `[lipsmack]` | yes (9 languages) | zero-shot; `inference_instruct2` takes a style instruction **and** her prompt clip | Apache-2.0 | small (0.5B) |
| **IndexTTS 2.5** (bilibili, Jan 2026) | **Timbre clip and emotion clip given separately** (`emo_audio_prompt`, `emo_alpha`), an 8-value emotion vector, or text | **2.5 adds Japanese** (IndexTTS2 itself was Chinese and English) | zero-shot | bilibili Model Use License; commercial use on request | RTF 0.21 on a 4090 (bf16) |
| Qwen3-TTS (Jan 2026) | Instruct only for preset voices (CustomVoice) and VoiceDesign; **Base (cloning) takes no instruct**; fine-tunes one speaker, with instruct not documented | yes | 3 s clone (Base) | Apache-2.0 | 0.6B / 1.7B |
| Chatterbox Turbo / Multilingual | `[laugh]`, `[chuckle]`, `[cough]`, `[sigh]`: **Turbo only, English only**; Multilingual (Japanese) has no tags | Multilingual only | reference | MIT | small |
| Dia 1.6B / Orpheus 3B | `(laughs) (sighs) (gasps) (screams) (inhales) (exhales) (sniffs) (groans) (humming)...` / `<laugh> <chuckle> <sigh> <cough> <sniffle> <groan> <yawn> <gasp>` | **English only** | reference | Apache-2.0 | one GPU |
| Style-Bert-VITS2 JP-Extra | Style vectors clustered from the training audio; a whisper style only if the data has whispers | Native | fine-tune | AGPL-3.0 code (as Bert-VITS2) | small; needs a large Japanese BERT at inference |
| GPT-SoVITS v2ProPlus (hers) | **The reference clip is the style.** `aux_ref_audio_paths` is for blending timbre, not emotion | yes | already fine-tuned on her | MIT | already in use |

Notes that matter for her:

- **Irodori-TTS** fits her list almost one to one.
  - Its emoji table (EMOJI_ANNOTATIONS.md), written here by Unicode name:
    - ear U+1F442: whisper, or close to the ear;
    - face exhaling U+1F62E U+200D U+1F4A8: breath, sigh, sleeping breath;
    - wind face U+1F32C: heavy breathing;
    - face with open mouth U+1F62E: gasp;
    - face with hand over mouth U+1F92D: giggle or suppressed laugh;
    - grinning squinting face U+1F606: laughing speech;
    - loudly crying face U+1F62D: sobbing, teary;
    - face screaming in fear U+1F631: scream, shout, shriek;
    - yawning face U+1F971: yawn;
    - sneezing face U+1F927: cough, sniffle, sneeze;
    - unamused face U+1F612: tut, tongue click;
    - musical note U+1F3B5: humming;
    - sleepy face U+1F62A: sleepy;
    - smirking face U+1F60F: teasing;
    - angry face U+1F620: angry or sulky;
    - woozy face U+1F974: drunk;
    - heart hands U+1FAF6: gentle.
  - Repeating an emoji makes the effect stronger. The card warns that effects "may vary depending on context".
  - Speaker inversion trains a few reusable speaker tokens with the base frozen. That is the safest way to keep
    the emoji controls while it learns her voice.
  - Its English is weak (everything is Japanese-oriented), so use it for her Japanese range and for sounds.
  - It runs at 48 kHz, so resample to 22,050 Hz for Piper.
  - The consent rule is met: she agreed. Keep that agreement in writing (VOICE_PLAN.md).
- **Step-Audio-EditX** is the one model that **starts from her own teacher audio**.
  - For example, take a clean GPT-SoVITS line of hers and ask for "whisper", "shout" or "+Sigh". The words, timing
    and voice start from hers.
  - This is the best candidate for her **English** whisper and yell lines, which Irodori cannot do well.
  - Japanese support is only a year old: test it.
- **Fish S2-Pro** has the richest free-form tags and Japanese is Tier 1. But zero-shot from a reference, her timbre
  is "Fish's impression of her", which is the "different person" risk the owner already rejected. Use it as the
  fallback in the bake-off.
- **IndexTTS 2.5** is interesting because it separates timbre from emotion: her clip for timbre, any clip for
  emotion. Whisper is a way of voicing, not an emotion, so whether a whisper transfers is not documented.
- **Voice conversion** (Seed-VC, RVC, Vevo) turns someone else's or some model's performance into her timbre.
  - **Seed-VC** fine-tunes on as little as one clip; about 100 steps take 2 minutes on a T4. It is GPL-3.0 and its
    repo has been archived since November 2025. Its v2 can also convert accent and emotion.
  - **RVC** relies on pitch (F0), and a whisper has none. Its `protect` setting exists only to stop breaths and
    unvoiced consonants from tearing.
  - Whisper-to-normal conversion research says the missing F0 is the main difficulty. None of these projects
    documents whisper or nonverbal input.
  - Use VC only as a **timbre lock**: an optional pass when a style take drifts from her. It is not the main route.
- **Whisper by signal processing.** Amazon (Cotescu et al. 2019/2020) built Alexa's Whisper Mode by converting
  normal speech into whisper (first a rule-based DSP recipe, then a DNN; both in the WORLD domain). Learned
  conversion beat the DSP rules.
  - A single TTS model can learn normal, whisper and Lombard (loud) speech from one speaker (Apple, Hu et al. 2021).
  - So a multi-style student is a well-trodden idea. But WORLD is exactly the grain the owner rejected, so DSP
    whisper is a fallback only.
- **Corpora** (all research or personal use, not for redistribution):
  - **JVS**: 100 Japanese speakers, each with `whisper10` and `falsetto10`.
  - **JVNV**: Japanese emotional speech with nonverbal phrases.
  - **JNV**: 420 Japanese nonverbal vocalizations, CC BY-SA 4.0.
  - They are useful as text and prompt ideas, and to test a whisper path. They are not her, so never train her
    voice on them directly.
- **The honest limit.** NVBench (April 2026) tested 15 TTS systems on 45 kinds of nonverbal sounds. Quiet mouth
  sounds and long emotional vocalizations "remain bottlenecks". Expect breaths and whispers to be the hardest, and
  plan for the owner to throw takes away.

## 3. Phone side

**Multi-speaker Piper, with speaker ids as styles: recommended.**

- The pod's piper1-gpl at 46c3c71 supports multi-speaker data: CSV rows `wav|speaker|text`, `--model.num_speakers`,
  and a speaker-name-to-id map in `config.json`.
- Its `--model.warmstart_ckpt` copies every matching weight from a checkpoint. Its
  `_zero_fresh_speaker_conditioning` (upstream at HEAD, not a local patch) zeroes the new speaker projections, so a
  5-speaker model **starts as her single-speaker voice** and learns the styles from there.
  - `--ckpt_path` cannot do this: it restores the old hyperparameters (`num_speakers=1`).
- `sherpa_meta.py` already writes `n_speakers` from the config.
- sherpa-onnx runs multi-speaker Piper and VITS models by `sid`. Its LibriTTS-R Piper voice has 904 speakers, and
  the Kotlin `GenerationConfig` has `sid`.
- Cost on the phone: almost nothing. A 512-wide embedding per style and a few 1x1 conditioning convolutions, well
  under 1 MB, and the same speed.
- In VITS the style id conditions the duration predictor, the flow and the decoder. So a style changes timing,
  spectral tilt and voicing, not just volume. That is what makes a whisper or a yell more than a gain change.

**Other on-device models in sherpa-onnx, and why not.**

- Kokoro has Japanese voices (jf_alpha and others), but there is no open recipe for a new voice from her data.
- Matcha has no Japanese, and Kitten is English.
- ZipVoice clones Chinese and English only.
- Pocket TTS clones English only.
- Supertonic 3 is about 99M parameters, covers 31 languages including Japanese, and has `<laugh>`, `<breath>` and
  `<sigh>` tags. But a custom voice must be made by Supertone's paid web Voice Builder. **That would send her voice
  off the pod, so it is ruled out.** Mirrors also say the service closed on 2026-08-31.
- Irodori-TTS has ONNX packs for iOS and a GGUF port. A 0.8B DiT at 48 kHz on the phone's CPU is not realistic yet.
  Watch it, do not build on it.

**The sound bank: recommended, alongside the styles.**

- A sound is not something Piper does well inline. Her phoneme set has no "sigh". The owner also wants intended
  sounds kept apart from unwanted edge noise.
- So sounds are clips, and Piper says only words.
- Structure: `sounds/<name>/<style>/take_NN.wav` at 22,050 Hz, plus `sounds.json` with each take's:
  - duration;
  - median F0;
  - loudness;
  - the trimmed onset and offset;
  - a tag for the style it suits.
- About 15 sounds x 2 to 3 styles x 4 to 6 takes, at about 1 s each: about 5 MB as 16-bit PCM, or about 1 MB as
  Opus or FLAC.
- **Picking a take.**
  - Random among the takes for that sound and style, never the take used last.
  - Prefer a median F0 within about 1.5 semitones of the style's expected pitch.
  - If none is close, shift by resampling, at most 1 semitone. Resampling is not WORLD, so it adds no grain, and it
    changes the length by only about 6%.
  - Scale to the style's target loudness.
- **Placement.**
  - A 10 to 20 ms fade at each clip edge.
  - Pauses after the sound and before speech, in ms:

    | Sound | Pause after (ms) |
    |---|---|
    | sigh, exhale | 120-200 |
    | gasp, inhale | 30-60, straight into speech |
    | laugh | 150-250 |
    | tch, hmph | 60-100 |

  - The pauses are written into the existing stream, so Stop still cuts everything mid-sound.

**Gains.**

- No loudness normalization turned up in the cleaning scripts or in Piper's dataset code on the pod. The training
  data can therefore keep each style's level.
- The phone still applies a per-style gain with a limiter, in dB:

  | Style | Gain (dB) |
  |---|---|
  | whisper | about -8 |
  | soft | -4 |
  | normal | 0 |
  | loud | +2 |
  | yell | +4 |

- Phone speakers clip, and a yell must not.

## 4. How her model asks for it, without breaking her text style

**What other projects do.**

- Square-bracket point tags:
  - ElevenLabs v3: `[whispers] [shouts] [sighs] [laughs]`, placed "where the delivery should change".
  - Fish S2: `[whisper] [sigh] [laughing]`.
  - Chatterbox Turbo: `[laugh] [cough]`.
  - CosyVoice: `[breath] [laughter] [sigh]`.
- Wrapping spans: CosyVoice `<strong>..</strong>` and `<laughter>..</laughter>`; SSML
  `<amazon:effect name="whispered">` and `<prosody volume="x-loud">`.
- Parentheses: Dia `(laughs)`, Fish S1 `(sighing)`.
- Angle brackets: Orpheus `<sigh>`.
- Dia's README: "use non-verbal tags sparingly".
- Roleplay front-ends such as SillyTavern simply do not voice `*asterisk*` text, much as her normalizer does now.

**Proposal.**

- **Point sounds**, ASCII and lowercase whatever language she writes in: `[sigh] [gasp] [laugh] [giggle] [tch]
  [hmph] [hum] [groan] [yawn] [sniff] [inhale] [exhale]`.
  - Example: `[sigh] fine, whatever` or `ちょっと[gasp]まって`.
- **Spans**: `[whisper]...[/whisper]`, `[soft]...[/soft]`, `[loud]...[/loud]`, `[yell]...[/yell]`. Later
  `[teary]...[/teary]`.
  - An unclosed span runs to the end of the line.
  - The innermost span wins.
  - A span with no words in it does nothing.
  - Span edges snap outward to the nearest clause mark (、。！？… , . ! ? or the line edge). A style change in the
    middle of a phrase would otherwise get sentence-final intonation in the middle of her sentence.
- **Parsing.** Only known tag names match, so `[1]` or `[link]` in ordinary text is left alone. A known tag is
  never read aloud, and an unknown bracketed tag-like word is dropped from speech, never spoken.
- **Display.** Chat shows exactly what she typed, minus the tags. Her lowercase, her "www" and her romaji stay as
  they are.
  - At most, a whisper span could render a shade lighter. Leave it off by default.
- **Storage.** Her history keeps the tags, so she sees what she did. Strip them at every boundary where her text
  leaves for somewhere else: chat display, notebook, picture prompts, anything sent to another service.
  - `PersonaPrompts.kt` already has a function that cleans asterisk spans for the notebook. Add the tags to it.
- **Fallback.** When she still writes a gesture in asterisks, map it to a tag instead of dropping it:
  - `*sighs*` becomes [sigh], `*gasps*` [gasp], `*giggles*` [giggle], `*laughs*` and `*chuckles*` [laugh],
    `*yawns*` [yawn], `*groans*` [groan], `*scoffs*` and `*huffs*` [hmph], `*hums*` [hum], `*exhales*` [exhale];
  - `*whispers* text` opens a whisper span until the end of the sentence.
  - This reuses `isGesture` and the position rules in `SpeechTextNormalizer`.
- **Interjections she types** (はぁ, ちっ, ふふ, "haa", "tch") stay words, read by the voice as now. Mapping them to
  clips as well would double some sounds. That is a later experiment, not a default.
- **Prompt.** A few lines in her prompt:
  - "You can make sounds and change your voice while you talk: [sigh] ... [whisper]...[/whisper] ... Use one only
    when you would really make it, usually none, at most two in a message."
  - Lift the "no stage directions" rule for these tags only.
  - The app adds a guard: at most 2 sounds and 2 spans per line, the same sound not twice in a row.

## 5. Recommendation

### Teacher side: Irodori-TTS for her range, anchored on her real sounds, gated per style

1. **Her real sounds first** (half a day, CPU and ASR only).
   - Cut every sigh, tut, giggle, gasp and "ah" out of her 71 clips, and out of the full reel if it has more, using
     faster-whisper word times plus a level check.
   - These are the anchors: the bank's first takes, and the references and targets for everything synthetic.
2. **Ask the actress for a range session** (optional, and the best of all). About 10 to 15 minutes:
   - 30 lines whispered;
   - 30 lines soft and close;
   - 30 lines loud;
   - 20 yelled;
   - 10 teary;
   - each sound on the list 5 or 6 times, in Japanese and a few in English.
   - If she records it, her takes become each style's reference and the bank itself, and the synthetic steps below
     only fill gaps. It is the only route that is her range literally. Confirm her consent covers it.
3. **Irodori-TTS v4.1-Small on the pod** (about 1 day).
   - A new `/w/irodori-env`, one GPU.
   - Speaker inversion on her 71 clips (cleaned, 30 s or more of reference); LoRA only if inversion is not close
     enough.
   - Audition grid: 10 lines x {whisper, soft, loud, yell, teary} plus every sound, 3 takes each.
4. **Bake-off on the same grid** (about 1 day).
   - Step-Audio-EditX editing her GPT-SoVITS lines ("whisper", "shout", "+Sigh"; the only real option for English
     in style).
   - GPT-SoVITS with her own loud and angry reference (`v12_076` or `v12_049`) for loud and yell.
   - Fish S2-Pro zero-shot with her v2 reference.
   - Score each on:
     - kana error rate (`asr_kana.py`) for Japanese, WER for English, with looser per-style thresholds;
     - WavLM similarity to her real clips, compared **within the style** (a whisper scores low against normal
       speech by nature);
     - the owner's ear.
   - Pick one source per style.
5. **Distillation sets** (about 1 day of pod time).
   - About 800 lines per style, roughly 40 to 60 minutes. One reference per style for consistency (the owner's v2
     rule).
   - A mix of Japanese with some English and mixed lines, through the existing checks.
   - Change the cleaning for these sets:
     - DeepFilterNet treats a whisper and a breath partly as noise: use `--atten` of about 6 to 10 dB for whisper,
       soft and teary, or skip it.
     - `trim_words.py` cuts before the first recognized word: keep it for words, but the sound bank must not go
       through it.
   - Sounds for the bank: 6 or more takes each, picked by the owner.

Risks for the teacher side:

- **Timbre drift.** A synthetic whisper or yell can sound like her sister. The per-style similarity gate and the
  owner's A/B catch it. Seed-VC fine-tuned on her clips is the timbre-lock fallback.
- **Emoji control is not always consistent** (Irodori's own card). Expect a 30 to 50% keep rate on sounds.
- **Japanese in Step-Audio-EditX is new.**
- **Fish S2-Pro needs a whole 24 GB card.**
- **Licenses.** Fish Research and the bilibili license are non-commercial or on request. That is fine for this
  private voice, but read the terms on training another model from their outputs before using them as a source.
  Irodori (MIT plus a consent rule), CosyVoice, Qwen3-TTS and the EditX code (Apache-2.0) are clear.
- **The pod is busy.** It runs stage1_v2 on all 3 GPUs now, so this work starts after stage 1 v2 and the bilingual
  Piper run.

### Phone side: one multi-speaker Piper (styles as sid), plus her sound bank, driven by her tags

1. **Piper** (about 1 day of pod time).
   - `stage2_range.sh`: `--model.num_speakers 5`, `--model.warmstart_ckpt <her chosen bilingual epoch>`.
   - CSV `wav|style|text`, with normal being the full current `ds_mix`, so her normal voice does not drift.
   - Each style upsampled to about 15% of batches.
   - About 300 to 400 epochs on 3 GPUs.
   - Export as now. `phone_test_lang.py` speaks the held-out lines per sid, and the scoring is the same as above
     per style.
2. **The app** (about 2 to 3 days with tests).
   - `VoiceMarkup`: parse tags into segments `{style, text}` and sounds; strip them for display and every outbound
     path; the gesture fallback; the guard.
   - `OwnVoice.say` per segment: `GenerationConfig(sid = style)`, per-style gain and limiter, and the sentence
     reader run per segment.
   - `SoundBank`: load `sounds.json`, pick, resample, place.
   - `make_own_voice.sh` ships the bank beside the model, and never commits it.
   - The prompt lines.
   - A voice without styles (`n_speakers = 1`) ignores spans and still plays sounds, so older voices keep working.

Risks for the phone side:

- **The whisper style comes out hoarse or half-voiced** in a medium VITS. That needs enough whisper data. sherpa-onnx
  sets `noiseScale` per model, not per call, so it cannot be tuned per style without a second engine.
- **A style with too little data collapses into normal.** Upsampling and a per-sid check catch it.
- **Joins at style changes can sound spliced.** Snapping to clause marks and 10 ms crossfades help.
- **The phone speaker can clip on a yell.** The limiter handles it.
- **Her model may overuse the tags.** The prompt and the guard limit it.
- **Tags leak into text** (the notebook, pictures). One strip function at each boundary, with tests.

## Open questions for the owner

- Will the actress record a short range session? It is the one source that is literally her range.
- Which styles first? The suggestion is whisper, yell and the six most common sounds (sigh, gasp, giggle, laugh,
  tch, inhale), then soft and loud, then teary.
- Should a whisper look different in chat? The suggestion is no.

## Sources

Fetching from this session failed for k2-fsa.github.io, speech.fish.audio, arxiv.org and gigazine.net: those
hosts are not allowed in this session's network. Facts from those hosts come from search-result summaries and
should be checked once those hosts are reachable.

Teacher models:
- Fish S1-mini: https://huggingface.co/fishaudio/openaudio-s1-mini/blob/main/README.md ,
  https://huggingface.co/fishaudio/s1-mini , https://docs.fish.audio/developer-guide/core-features/emotions
- Fish S2-Pro: https://huggingface.co/fishaudio/s2-pro , https://arxiv.org/abs/2603.08823 ,
  https://github.com/fishaudio/fish-speech ,
  https://raw.githubusercontent.com/fishaudio/fish-speech/main/docs/en/install.md (24 GB / 48 GB)
- Fish Drama 3: https://huggingface.co/fishaudio/drama-3
- CosyVoice 3: https://arxiv.org/abs/2505.17589 , https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512 ,
  https://github.com/FunAudioLLM/CosyVoice/blob/main/cosyvoice/tokenizer/tokenizer.py
- IndexTTS: https://github.com/index-tts/index-tts , https://huggingface.co/indexteam/indextts-2.5 ,
  https://arxiv.org/abs/2601.03888 , https://arxiv.org/abs/2506.21619
- Qwen3-TTS: https://github.com/QwenLM/Qwen3-TTS , https://github.com/QwenLM/Qwen3-TTS/tree/main/finetuning ,
  https://arxiv.org/abs/2601.15621
- Step-Audio-EditX: https://huggingface.co/stepfun-ai/Step-Audio-EditX , https://github.com/stepfun-ai/Step-Audio-EditX ,
  https://arxiv.org/abs/2511.03601
- Irodori-TTS: https://github.com/Aratako/Irodori-TTS , https://huggingface.co/Aratako/Irodori-TTS-v4.1-Small ,
  https://huggingface.co/Aratako/Irodori-TTS-v4-Small ,
  https://huggingface.co/Aratako/Irodori-TTS-500M-v2/blob/main/EMOJI_ANNOTATIONS.md ,
  https://huggingface.co/raratu/Onsei-iOS-Models , https://huggingface.co/cstr/irodori-tts-GGUF
- Chatterbox: https://huggingface.co/ResembleAI/chatterbox-turbo ,
  https://docs.nvidia.com/ace-for-games/chatterbox-tts/nvigi-chatterbox-model-card.html ,
  https://www.resemble.ai/chatterbox
- Dia: https://huggingface.co/nari-labs/dia-1.6b , https://raw.githubusercontent.com/nari-labs/dia/HEAD/README.md
- Orpheus: https://cdn.jsdelivr.net/gh/canopyai/orpheus-tts@main/README.md
- Style-Bert-VITS2: https://github.com/litagin02/Style-Bert-VITS2 , https://arxiv.org/html/2505.17320v1
- GPT-SoVITS aux references (api_v2): https://huggingface.co/spaces/vipsphi/ttskinxx/blob/main/api_v2.py ,
  https://github.com/RVC-Boss/GPT-SoVITS

Voice conversion and whisper:
- Seed-VC: https://github.com/Plachtaa/seed-vc , https://arxiv.org/abs/2411.09943
- RVC protect: https://github.com/phineas-pta/speech-synthesis-ngngngan/blob/main/docs/2-train-rvc.md
- Vevo: https://huggingface.co/amphion/Vevo
- Whisper: https://arxiv.org/abs/1912.05289 (Cotescu et al.), https://arxiv.org/abs/2101.05313 (Hu et al.),
  https://arxiv.org/html/2511.01056 (WhisperVC), https://arxiv.org/pdf/2601.15596 (DeepASMR)

Corpora and benchmarks:
- JVS: https://sites.google.com/site/shinnosuketakamichi/research-topics/jvs_corpus
- JVNV: https://sites.google.com/site/shinnosuketakamichi/research-topics/jvnv_corpus
- JNV: https://sites.google.com/site/shinnosuketakamichi/research-topics/jnv_corpus
- NVBench: https://arxiv.org/html/2604.16211v1

Phone:
- piper1-gpl: https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/TRAINING.md ,
  https://github.com/rhasspy/piper/blob/master/TRAINING.md ,
  https://huggingface.co/datasets/rhasspy/piper-checkpoints/discussions/8 (also read on the pod at
  /w/piper1-gpl 46c3c71: `vits/lightning.py` warmstart_ckpt and `_zero_fresh_speaker_conditioning`,
  `vits/dataset.py` speaker map)
- sherpa-onnx: https://github.com/k2-fsa/sherpa-onnx/blob/master/sherpa-onnx/kotlin-api/Tts.kt (GenerationConfig.sid),
  https://github.com/k2-fsa/sherpa-onnx ,
  https://csukuangfj.github.io/sherpa/onnx/tts/pretrained_models/vits.html (libritts_r, 904 speakers),
  https://pub.dev/packages/sherpa_onnx/changelog , https://k2-fsa.github.io/sherpa/onnx/tts/pocket.html ,
  https://k2-fsa.github.io/sherpa/onnx/tts/kitten
- Kokoro: https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md
- Supertonic: https://huggingface.co/Supertone/supertonic-3 , https://supertonic.supertone.ai/ ,
  https://huggingface.co/jiangzhuo9357/supertonic-3

Markup:
- ElevenLabs: https://elevenlabs.io/docs/help-center/product/core-capabilities/text-to-speech/how-do-audio-tags-work-with-eleven-v3-alpha ,
  https://elevenlabs.io/blog/v3-audiotags
- Amazon Polly: https://docs.aws.amazon.com/polly/latest/dg/whispered-tag.html ,
  https://docs.aws.amazon.com/polly/latest/dg/prosody-tag.html
- SillyTavern: https://docs.sillytavern.app/extensions/tts
