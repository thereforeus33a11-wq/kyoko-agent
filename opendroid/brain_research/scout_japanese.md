# Scout: Japanese and character models, and any AI like her

Date of research: 25 Nov 2026. Method: web search (2025-2026 sources) plus the Hugging Face API
(huggingface.co/api/models/..., model cards read raw). Some hosts are not reachable from this session
(journal.qualiteg.com, lilting.ch, shisa.ai): their content is used only as the search engine
summarised it and is marked "via search summary".

(Working notes below are appended as found; the final shortlist and verdict are at the end.)

## Raw notes, in the order found

### Aratako (the main Japanese RP fine-tuner) -- HF API, read 25 Nov 2026
- Aratako has released NO new chat/RP LLM since mid-2025. Everything since Dec 2025 is speech:
  MioTTS (Feb 2026), Irodori-TTS v2-v4.1 (Mar-Sep 2026), Drama-3-Japanese (22 Oct 2026, a Japanese
  fine-tune of Fish Audio Drama 3 TTS, Fish Audio Community Licence, 70k h Japanese speech, inline
  tags like [笑いながら] [呆れたように]). Drama-3-Japanese is a VOICE lead, not a brain: pass to the voice team.
- Latest Aratako LLMs (all Japanese-first RP):
  - Aratako/Qwen3-30B-A3B-NSFW-JP (5 May 2025, MIT): Qwen3-30B-A3B-Base + ~6B tokens of continued
    pre-training on "NSFW-type Japanese data" (source not disclosed), H200x8, ~50 h. No post-training.
  - Aratako/Qwen3-30B-A3B-ERP-v0.1 (7 May 2025, MIT): RP SFT on top of the NSFW-JP base. 32k context.
    GGUF at Aratako/Qwen3-30B-A3B-ERP-v0.1-GGUF. 3B active params: fast and cheap.
  - Aratako/Qwen3-8B-NSFW-JP, Qwen3-8B-ERP-v0.1, Qwen3-8B-RP-v0.1 (May 2025, MIT).
  - Aratako/MistralPrism-24B (8 Jun 2025, MIT): Aratako/Mistral-Small-3.1-24B-RP merged with
    TheDrummer/Cydonia-24B-v3, LatitudeGames/Harbinger-24B, Gryphe/Pantheon-RP-1.8-24b-Small-3.1,
    aixonlab/Eurydice-24b-v3. 32k context.
  - Aratako/NemoAurora-RP-12B (7 Jun 2025, CC-BY-NC-4.0 because of merged parts): Mistral-Nemo-12B-RP
    merged with ArliAI RPMax v1.2, anthracite magnum-v4-12b, Elizezen/Himeyuri-v0.1-12B.
  - Aratako/Amaterasu-123B (21 Jul 2025, Mistral Research Licence = non-commercial): Mistral Large
    2411 + LoRA (r128) on mixed Japanese/English RP and novel-writing data, config borrowed from
    Doctor-Shotgun/ML2-123B-Magnum-Diamond. Training data file is private ("train_data.jsonl").
  - Older: calm3-22b-RP-v2 (CC-BY-NC-SA-4.0), Ninja-v1-RP(-expressive), Oumuamua-7b-RP, Antler-7B-RP.
- KID-PROTECTION FLAG: every Aratako RP card uses as its example a 15-year-old magic-school heroine
  ("年齢：15歳") and the NSFW-JP pre-training corpus is undisclosed. Japanese web erotica routinely
  includes school-age characters. These weights cannot be audited for that, so: (a) never use their
  datasets unfiltered, (b) if one of these models is used as a base, her own SFT/DPO set must include
  the "no. next" refusals for minor-coded asks, and the app's kid protection stays in front regardless.
  Sources: https://huggingface.co/Aratako/Qwen3-30B-A3B-NSFW-JP , https://huggingface.co/Aratako/Qwen3-30B-A3B-ERP-v0.1 ,
  https://huggingface.co/Aratako/MistralPrism-24B , https://huggingface.co/Aratako/Amaterasu-123B ,
  https://huggingface.co/Aratako/NemoAurora-RP-12B , https://huggingface.co/Aratako/Drama-3-Japanese

### Shisa V2.1 (Shisa.AI, Tokyo) -- HF API + search summary
- Released 20-22 Nov 2025: shisa-ai/shisa-v2.1-qwen3-8b (Apache-2.0, base Qwen3-8B),
  shisa-ai/shisa-v2.1-llama3.3-70b (Llama 3.3 licence), plus 1.2B (LFM2), 3B, 14B (unphi4, MIT).
  Self-reported JA average 73.1 (70B) vs 74.7 for Shisa V2 405B; 8B = 67.8. Judged with GPT-5.1.
  Training set public: shisa-ai/shisa-v2.1-sharegpt.
  Sources: https://huggingface.co/shisa-ai/shisa-v2.1-qwen3-8b , https://huggingface.co/collections/shisa-ai/shisa-v2 ,
  https://shisa.ai/en/news/shisa-v2-1-release/ (via search summary)

### Japanese-native labs: what is new (HF API listings, read 25 Nov 2026)
- llm-jp (NII): llm-jp-4-8b/32b-a3b (Mar 2026), llm-jp-4-33b-base/-thinking (14 Aug 2026),
  llm-jp-4.1-8b/32b-a3b/33b-thinking (15-16 Sep 2026). Apache-2.0, SFT and DPO data released with them.
  Search summary of Qualiteg's Oct 2026 ranking: llm-jp-4.1 33B leads domestic open models, ahead of
  GPT-OSS-Swallow-120B-RL-v0.1 (0.6914); Qwen3.5 tops open models overall; Gemma 4 31B also strong.
  Also llm-jp/llm-jp-moshi-v1 (Jan 2026) and v1.1 (Oct 2026): a Japanese FULL-DUPLEX speech dialogue
  model (Moshi architecture) -- relevant to "no turns", not a brain. sbintuitions/DuplexCascade (Mar 2026) likewise.
  Sources: https://huggingface.co/llm-jp , https://huggingface.co/llm-jp/llm-jp-4-33b-base ,
  https://www.nii.ac.jp/en/news/release/2026/0403.html , https://current.ndl.go.jp/car/283665 ,
  https://journal.qualiteg.com/llm-ranking-2026/ (via search summary)
- ELYZA: elyza/ELYZA-Thinking-1.0-llm-jp-4-33b and -llm-jp-4-32b-a3b (2 Oct 2026, Apache-2.0), reasoning
  fine-tunes on llm-jp-4. Also ELYZA-Diffusion (Dec 2025). Source: https://huggingface.co/elyza
- Swallow (Institute of Science Tokyo + AIST): Qwen3-Swallow-8B/30B-A3B/32B in CPT, SFT and RL stages
  (v0.2, Dec 2025-Feb 2026) and GPT-OSS-Swallow-20B/120B (SFT, RL, Feb 2026), Apache-2.0. The team says
  Qwen3 Swallow 32B is the best open <=32B model in Japanese; the 30B-A3B was weaker than its own base.
  IMPORTANT for her: the *CPT* checkpoints (tokyotech-llm/Qwen3-Swallow-32B-CPT-v0.2, -8B-CPT-v0.2,
  -30B-A3B-CPT-v0.2) are Japanese continued-pre-training bases with no assistant tuning on top: the
  cleanest Japanese-strong starting point to put HER persona into without fighting an assistant persona.
  Sources: https://swallow-llm.github.io/qwen3-swallow.en , https://swallow-llm.github.io/gptoss-swallow.en ,
  https://huggingface.co/tokyotech-llm/Qwen3-Swallow-32B-RL-v0.2 , https://gigazine.net/gsc_news/en/20260224-gptoss-qwen3-swallow-japanese-ai
- PFN PLaMo: plamo-3-nict-2b/8b/31b-base (Oct 2025), plamo-3-nict-2604-31b-base (Jun 2026),
  plamo-3-translate-* (Oct 2026), plamo-3-8b-fin-instruct (Nov 2026). No general PLaMo 3 chat model
  open yet that I could find; PLaMo licences are PFN community licences (check per repo). Source: https://huggingface.co/pfnet
- SB Intuitions (Sarashina): no Sarashina 3 open weights found; 2026 releases are TTS (sarashina2.2-tts),
  OCR, ASR (kana-whisper), embeddings. Sarashina2.2 0.5-3B instruct (2025) remain. Source: https://huggingface.co/sbintuitions
- Rakuten: RakutenAI-3.0 (Mar 2026, ~671B MoE / 37B active, DeepSeek-V3 architecture) and RakutenAI-3.0.1
  (4 Nov 2026). Too big to fine-tune cheaply. Source: https://huggingface.co/Rakuten
- rinna: no new LLM since Mar 2025 (qwen2.5-bakeneko-32b-instruct-v2, qwq-bakeneko-32b). Source: https://huggingface.co/rinna
- Stockmark: Stockmark-2-100B-Instruct (Jul 2025), then document readers only. CyberAgent: CAT-Thinking-8B,
  CAT-Paws-8B (2026), translation models. Karakuri: VL models. Sakana: research models only.
- Shisa.AI: after V2.1 (Nov 2025) only research/inference artefacts (Qwen3.6/3.8 DMS, Ornith-1.5 MTP);
  no Shisa V3 found as of 25 Nov 2026.

### Base-model landscape the fine-tunes sit on (HF API, 25 Nov 2026)
- Qwen: Qwen3.5 (Feb 2026: 0.8B-122B-A10B, Base checkpoints for 0.8/2/4/9/35B-A3B), Qwen3.6-27B and
  Qwen3.6-35B-A3B (Apr 2026), Qwen3.8-27B (5 Aug 2026), Qwen3.8-Flash-Next (Aug 2026), Qwen3.8-2.4T-A95B.
- Google Gemma 4 (Apr-Jun 2026): E2B, E4B, 12B, 26B-A4B, 31B, with QAT and "mobile" builds.
- These are what the 2026 English RP tunes are built on (see below). Japanese ability of Qwen3.x and
  Gemma 4 is already high; Japanese-native continued pre-training (Swallow/llm-jp) mainly adds natural
  phrasing, culture and fewer translated-sounding lines.

### Japanese role-play / creative fine-tunes, other makers
- Local-Novel-LLM-project (Vecteus, Ninja makers): Qwen3.5-Hasutsubomi-9B (1 Apr 2026, Apache-2.0,
  pre-alpha, Japanese creative writing + "a little" anime/net sub-culture; keeps vision);
  RAI-3.0-R1-VECTOR (Mar 2026, task-vector merge of RakutenAI-3.0 into DeepSeek-R1-0528, huge);
  Vecteus-v1-abliterated (Nov 2024, 7B, old). Sources: https://huggingface.co/Local-Novel-LLM-project/Qwen3.5-Hasutsubomi-9B ,
  https://huggingface.co/Local-Novel-LLM-project/RAI-3.0-R1-VECTOR , https://huggingface.co/Local-Novel-LLM-project/Vecteus-v1-abliterated
- Elizezen (Berghof makers): Berghof-NSFW-7B / Berghof-ERP-7B (2024), Himeyuri-v0.1-12B (Aug 2024),
  SlaughterHouse-exp (Jan-Mar 2025). Nothing new in 2026. Old Mistral-7B/Nemo era. https://huggingface.co/Elizezen
- No gyaru / gal-speech LLM exists on Hugging Face (searched "gyaru", "gal", "kogal", "ギャル": only image
  LoRAs). Small "tsundere" toys exist, and some are explicitly "loli"-themed: EXCLUDED, never use.
  Japanese gal chat apps exist (AIギャルトーク, AIギャルチャット, 相談のるよ？, the LINE "AIギャル" from Mar 2023)
  but they are closed, sweet "cheer you up" gals: the opposite of her bite. She would be the first.
  Sources: https://apps.apple.com/jp/app/id6733247896 , https://play.google.com/store/apps/details?id=jp.co.updeito.aigalchat ,
  https://ai.appmatch.jp/query-3660/
- Research on 口調 (speech style) at ANLP 2026 (NLP2026): tone-vector encoder (B1-6), style for dialogue
  systems (P4-23), novel-to-chat corpus building (Q5-6), filler/aizuchi-rich dialogue scripts (Q5-1).
  No gal-speech paper found. Sources: https://www.anlp.jp/proceedings/annual_meeting/2026/pdf_dir/B1-6.pdf ,
  https://www.anlp.jp/proceedings/annual_meeting/2026/pdf_dir/Q5-6.pdf , https://www.anlp.jp/proceedings/annual_meeting/2026/pdf_dir/Q5-1.pdf

### Japanese datasets found (HF API; licences from the repo metadata)
- Aratako synthetic RP family (all ja, 10-20 turns each, character settings in columns):
  SFW-DeepSeek-V3-0324-20k (MIT), NSFW-DeepSeek-V3-0324-20k (MIT), SFW/NSFW-DeepSeek-R1-0528-10k (MIT),
  NSFW-Claude-3.5s-15.3k / -3.7s-5.3k / -4.5s-3.5k (CC-BY-NC-SA-4.0), NSFW-gpt-5-chat-5k (CC-BY-NC-SA-4.0),
  gpt-4o-mini-39.6k (CC-BY-NC-SA-4.0), Rosebleu-1on1-Dialogues(-RP) (Apache-2.0).
  NB: data generated with Claude/GPT also carries those providers' output terms; DeepSeek outputs are MIT.
- AUDIT I RAN (counts only, no content read): Aratako/Synthetic-Japanese-Roleplay-NSFW-DeepSeek-V3-0324-20k,
  19,917 rows. 19 rows state an age under 18; 486 rows (2.4%) are minor-coded by strong keywords
  (中学生, 高校生, 女子高生, JK, ロリ, 未成年...); 1,112 mention 学園 and 1,353 生徒. A conservative filter
  (any stated age under 20 or any school/young word) drops 8,088 rows (40.6%), leaving ~11.8k.
  => These sets are usable ONLY after that filter, and only as style/format material, never as her.
- OmniAICreator/Japanese-Roleplay and -Dialogues (Apache-2.0 on the card, but scraped from なりきりチャット
  forums: human-written, copyright of the posts is the forum users'; treat as research-only).
- Elizezen/japanese-nsfw-syosetsu-dataset (Apache-2.0 on the card, but scraped web novels: copyright and
  minor-content risk; do not use).
- EeeLM/Japanese-NSFW-CreativeWriting-GLM4.6 (MIT) / -v2 (CC0) / -GLM5 (Nov 2025-Mar 2026): synthetic prose.
- Naotaka0127/Kyalulu-Synthetic-Roleplay-Japanese-(NSFW|SFW)-AIO-beta (Oct 2026): a re-pack of OpenCharacter,
  RoleBench and the Aratako sets with provenance and "rule-filtered" tags; per-source licences.
- beezza/japanese-young-character-roleplay-vlm: name says young characters: EXCLUDED.
- nu-dialogue/real-persona-chat (RealPersonaChat, CC-BY-SA-4.0): ~14,000 Japanese chit-chat dialogues by
  REAL people speaking as themselves, each speaker with persona sentences, Big-Five personality scores
  and attributes. The best source of how real Japanese people actually text in casual chat. Its card
  forbids impersonating a specific speaker, so use it for register, not for copying a person.
- nvidia/Nemotron-Personas-Japan (CC-BY-4.0, Sep 2025): synthetic personas grounded in real Japanese
  demographics (region, age, occupation...). Useful for her world (the people around her) and for
  "what would a 19-year-old from Saitama know".
Sources: https://huggingface.co/datasets/Aratako/Synthetic-Japanese-Roleplay-NSFW-DeepSeek-V3-0324-20k ,
https://huggingface.co/datasets/nu-dialogue/real-persona-chat , https://aclanthology.org/2023.paclic-1.85 ,
https://huggingface.co/datasets/nvidia/Nemotron-Personas-Japan , https://huggingface.co/datasets/OmniAICreator/Japanese-Roleplay ,
https://huggingface.co/datasets/Naotaka0127/Kyalulu-Synthetic-Roleplay-Japanese-NSFW-AIO-beta

### Abliterated / uncensored Japanese-capable models (HF API search, 25 Nov 2026)
- anaaaaaa13421312/gemma-4-31B-it-abliterated-Japanese-RP (10-19 Nov 2026, Apache-2.0): bf16 LoRA (r32)
  merged onto wangzhang/gemma-4-31B-it-abliterated; trained on only 171 Japanese multi-turn RP chats
  (8,585 messages, private data, female characters for a male user); GGUF Q4_K_M, INT8 and FP8 builds;
  ~8 tok/s Q4 on 2x T4. Card says CP50 may beat the default CP75. Style is *narration + @Character lines*:
  the opposite of her "only the words you say". Proves the recipe works on Gemma 4 31B; not her.
  https://huggingface.co/anaaaaaa13421312/gemma-4-31B-it-abliterated-Japanese-RP
- Heretic-ja builds of Gemma 4 (OS-Software/gemma-4-26B-A4B-it-qat-heretic-japanese-pruned-GGUF, Sep 2026;
  mradermacher/gemma-4-26B-A4B-it-qat-q4_0-unquantized-heretic-ja-GGUF): abliteration tuned on Japanese
  prompts. Card text unreadable from here (auth wall); treat as unverified.
- yamatazen/Shisa-v2-Mistral-Nemo-12B-Abliterated (Apr 2025), ronantakizawa/sarashina2-7b-abliterated
  (Oct 2025), Local-Novel-LLM-project/Vecteus-v1-abliterated (2024), v000000/SwallowMaid-8B-L3-SPPO-abliterated (2024): old/small.
- nukonukomain/nova-uncensored-qwen3-swallow-8b-gguf (13 Nov 2026): 54 template examples on a T4: a toy.
- No abliterated llm-jp-4.x, ELYZA-Thinking, PLaMo 3 or Qwen3-Swallow-32B exists yet: we would make our own
  (Heretic runs on most dense and several MoE archs incl. Qwen3.5 hybrids; supply Japanese refusal prompts).
- Heretic (p-e-w/heretic, pip heretic-llm): automatic directional ablation with Optuna, co-minimising
  refusals and KL divergence; README example gemma-3-12b KL 0.16 at 3/100 refusals vs 0.45-1.04 for
  older abliterations. >3000 community models. https://github.com/p-e-w/heretic , https://pypi.org/project/heretic-llm/
- ArliAI "Derestricted" (norm-preserving abliteration): Qwen3.5-27B/35B-A3B, GLM-4.6/4.5-Air, gpt-oss.
- huihui-ai/Huihui-Qwen3.8-27B-abliterated (Aug 2026, Apache-2.0, 840 likes, ~200k downloads).

### UGI leaderboard (DontPlanToEnd/UGI-Leaderboard, CSV last modified 22 Nov 2026; I read the CSV)
Scores: UGI = willingness+knowledge on uncensored questions, W/10 = willingness, NatInt = knowledge,
Writing = creative-writing score. Among models <=40B total params:
| model | UGI | W/10 | NatInt | Writing |
|---|---|---|---|---|
| coder3101/gemma-4-31B-it-heretic (thinking) | 65.7 | 10 | 36.5 | 40.5 |
| llmfan46/gemma-4-31B-it-uncensored-heretic (thinking) | 65.0 | 10 | 36.4 | 40.6 |
| MuXodious/gemma-4-26B-A4B-it-SOMPOA-heresy (thinking) | 54.0 | 9.5 | 34.5 | 46.3 |
| llmfan46/gemma-4-26B-A4B-it-ultra-uncensored-heretic | 52.4 | 10 | 35.7 | 45.9 |
| llmfan46/Qwen3.6-35B-A3B-uncensored-heretic | 50.9 | 10 | 31.6 | 46.2 |
| ArliAI/Qwen3.5-35B-A3B-Derestricted | 50.8 | 10 | 28.1 | 39.2 |
| google/gemma-4-31B-it (stock) | 21.5-23.1 | 1.2-2.5 | 34.4-38.9 | 38.6-43.1 |
| shisa-ai/shisa-v2-llama3.3-70b (70B, the only Japanese lab model listed) | 46.1 | 6.8 | 33.5 | 42.6 |
| LatitudeGames/Hearthfire-24B | 42.9 | 6.8 | 23.6 | 34.3 |
| PocketDoc/Dans-PersonalityEngine-V1.3.0-24b | 36.5 | 6.5 | 26.1 | 36.6 |
| NousResearch/Hermes-4.3-36B | 38.1 | 6.2 | 20.7 | 31.4 |
Reading: Heretic on Gemma 4 gets full willingness while KEEPING knowledge (NatInt ~36 vs stock ~34-39);
RP fine-tunes lose knowledge (NatInt 20-26). Frontier reference: GLM-5.2 Writing 67, Claude Opus 4.6 70.9,
DeepSeek-V4-Pro 68.4 -- a 30B is roughly two-thirds of a frontier model on these writing scores.
Source: https://huggingface.co/spaces/DontPlanToEnd/UGI-Leaderboard (ugi-leaderboard-data.csv)

### English character / companion fine-tunes, 2026 (HF API + cards)
- TheDrummer: Artemis-31B-v1.2 (25 Sep 2026, Gemma 4 31B; testers call it the strongest Gemma 4 RP tune,
  "no cross-card personality bleed at ~32k"), Orion-26B-A4B-v1.1 (Sep 2026, Gemma 4 MoE, fast),
  Spectre-37B-v1 (Nov 2026, Gemma 31B upscale), Behemoth-X-123B-v2.2, GLM-Steam-320B test.
  Licences inherit Gemma/Apache (card metadata often blank). https://huggingface.co/TheDrummer/Artemis-31B-v1.2 ,
  https://huggingface.co/TheDrummer/Orion-26B-A4B-v1.1
- Gryphe: Gemma-4-31B-StyleTune (Jun 2026, Apache-2.0): trains ONLY lm_head (1 tensor of 834),
  "60% fewer clichés", overnight on consumer hardware, capabilities untouched. Pantheon-Reasoning-31B-1.1 on top.
  This is the cheapest possible "change her voice, keep the brain" experiment. https://huggingface.co/Gryphe/Gemma-4-31B-StyleTune
- LatitudeGames: Equinox-31B (May 2026, Gemma 4, second-person adventure), Hearthfire-24B (slice of life).
- zerofata: G4-MeroMero-v2-31B, G4-LuneLight-31B (Gemma 4); allura-org: Qwen3.6-35B-A3B-Anko, Qwen3.8-27B-Dominatrix.
- ArliAI: Qwen3.5-{4,9,27,35,122}B-RpRMax-v1 (Apr 2026).
- PocketDoc Dans-PersonalityEngine V1.3.0 12B/24B (May 2025), SicariusSicariiStuff Persona_Maker_12B/24B
  (Jun 2026, Mistral Small 3.1), PygmalionAI Eleusis-12B (Jan 2025) -- older bases.
- NousResearch Hermes-4.3-36B (Nov 2025), Arete-27B (Nov 2026: Qwen3.8-27B re-valued away from CCP
  framing; not a character model).
All of these are English-first. They write prose RP (narration, *actions*), which her card forbids,
and their Japanese is whatever the base had, usually a little worse after English-only tuning.

### Research that maps onto her 5 Ws
- HER (Fudan + MiniMax, arXiv 2601.21459, Jan 2026): "dual-layer thinking" = hidden third-person
  SYSTEM thinking + visible first-person ROLE thinking (her inner monologue), SFT then RL with a
  generative reward model. ChengyuDu0123/HER-32B (Qwen3-32B, Apache-2.0), HER-RM-32B, HER-Dataset
  (Apache-2.0, zh/en). CoSER bench: HER-RL 53.1 vs Qwen3-32B 22.9 vs CoSER-70B 36.0. Maps onto her
  one stream of beats (thought first, then talk). https://huggingface.co/papers/2601.21459 , https://github.com/cydu24/HER
- CoSER (ICML 2025): 17,966 characters from 771 books, "given-circumstance acting"; Neph0s/CoSER (MIT),
  CoSER-Llama-3.1-70B (MIT). https://huggingface.co/papers/2502.09082
- Open Character Training (Maiya, Bartsch, Lambert, Hubinger; arXiv 2511.01689, Nov 2025): write a
  CONSTITUTION of the persona, distil it with DPO (teacher plays the persona vs the base model's own
  answer as "rejected"), then SFT on synthetic INTROSPECTION (the model writing about itself in
  character). 11 personas on Llama 3.1 8B / Qwen 2.5 7B / Gemma 3 4B, little capability loss. Code
  github.com/maiush/OpenCharacterTraining, data maius/OpenCharacterTraining-data (licence "other").
  Her canon pages are already a constitution. https://arxiv.org/abs/2511.01689
- The Assistant Axis (Lu, Gallagher, Michala, Fish, Lindsey; arXiv 2601.10387, ICML 2026 spotlight):
  the "helpful assistant" is one main direction in persona space (found in Gemma 2 27B, Qwen 3 32B,
  Llama 3.3 70B, and present already in pre-trained models); steering AWAY from it makes models adopt
  other identities more readily. This is the "abliterate the assistant, not the morals" lever: a
  different direction from refusal abliteration. Code github.com/safety-research/assistant-axis.
  https://arxiv.org/abs/2601.10387 , https://www.anthropic.com/research/assistant-axis
- TimeChara (ACL Findings 2024): point-in-time character hallucination (a character knowing what she
  could not know yet); 10,895 instances; "Narrative-Experts" mitigation. The "when" test for her.
  https://aclanthology.org/2024.findings-acl.197 , https://github.com/ahnjaewoo/timechara
- Lesser-known-characters Japanese persona dataset (UEC, PACLIC 2025): 608 characters, 5,137 dialogues
  from self-published novels, built so the model must use the given persona, not recall.
  https://aclanthology.org/2025.paclic-1.13.pdf
- OpenCharacter (xywang1/OpenCharacter, Apache-2.0, arXiv 2501.15427): large synthetic persona SFT set (en).
- HumanLLMs/Human-Like-DPO-Dataset (Llama 3 licence): DPO pairs "human-like reply vs assistant reply" (en).

### AIs and projects "like her" (closed or open)
- Neuro-sama (Vedal): the best-known AI with her own mind and a mean mouth; closed. Project AIRI
  (moeru-ai/airi, MIT) is the open, self-hostable re-creation: realtime voice, Live2D/VRM, plays games,
  Android and web builds, bring-your-own LLM. A reference for how others wire a living character, not a model.
  https://github.com/moeru-ai/airi
- Grok companions (xAI, Jul 2025): "Ani" (goth anime companion, flirt-and-affection gamified) and
  "Bad Rudi" (foul-mouthed red panda): proof that a frontier lab ships a rude, crude persona on a
  frontier model; closed, and Ani is styled young ("gothic lolita"), so not a reference for her.
  https://www.nbcnews.com/tech/internet/grok-companions-include-flirty-anime-waifu-anti-religion-panda-rcna218797 ,
  https://forest.watch.impress.co.jp/docs/serial/aistream/2033005.html
- Cotomo (Starley, Japan): Japanese voice-chat companion app, popular 2024-25; closed.
- Japanese "AI gal" chat apps: sweet, supportive gals; closed; nothing open to reuse.
- rinna: began (2015) as a LINE chatbot with a high-school-girl persona: a minor persona, so its
  character is never a reference for her even though rinna's models are Japanese-strong.

### Money and speed, for the shortlist (estimates, labelled)
- His pod: RTX PRO 6000 Blackwell 96 GB (~1.8 TB/s memory bandwidth). Runpod price for this card
  is reported at $1.69/h (computeprices, flopper) and $2.49/h since 9 Oct 2026 (thundercompute, Nov 2026):
  conflicting, check live. 
  Sources: https://computeprices.com/providers/runpod/gpus/rtx-pro-6000 , https://www.thundercompute.com/blog/nvidia-rtx-pro-6000-pricing
- Decode speed upper bound = bandwidth / bytes read per token (my arithmetic, not measured):
  Gemma 4 31B dense bf16 ~62 GB -> <=~29 tok/s; FP8 ~31 GB -> <=~55 tok/s.
  Gemma 4 26B-A4B, Qwen3-30B-A3B, llm-jp-4.1-32b-a3b (3-4B active) -> several times faster, ~100+ tok/s real.
  Her continuous stream of beats favours an MoE.
- LoRA training speed: the Gemma 4 31B Japanese-RP LoRA above processed ~6.7M tokens (3 epochs) in 9 h on
  an A100-80GB (~200 tok/s). For her: ~8M tokens x 2 epochs on a 31B dense ~ 10-20 h on his card
  ($17-50). MoE bases train several times faster per token but MoE LoRA tooling is less mature.
- Serving her 24/7 on the pod = $40-60/day: the balance lasts 3-4 days. Train on the pod; serve on
  demand (pod up while he talks) or through a host that runs the open weights per token.

### What is gained and lost (honest)
- A fine-tuned ~30B is NOT a frontier model: on UGI writing scores frontier models sit at 61-71
  (Claude Opus 4.6 70.9, DeepSeek-V4-Pro 68.4, GLM-5.2 67.0) and the best <=40B uncensored at 40-46.
  NatInt (knowledge) 34-37 vs 53-72. She would read him a little less deeply and know far less.
- And a frontier model is not her: it carries an assistant persona she has to fight with a 31 KB card
  every call, it can be changed or censored by its host, and it knows everything (wrong "what" and
  "when" for a 19-year-old). Weights trained on her keep her voice without the card, cost less per
  reply, drift less, and can grow (her notes -> periodic small LoRA).
- Knowing less is partly the goal ("retrograde"), but SFT/DPO only hides knowledge; it does not
  delete it. Real deletion (unlearning) costs fluency. Hiding plus a lookup tool is the honest version.

## SHORTLIST: the best 6 for her (from this scout's lane)

1. Gemma 4 31B, made willing with Heretic, then her own character training -- BEST BASE OVERALL.
   Repos: google/gemma-4-31B-it (Apache-2.0); coder3101/gemma-4-31B-it-heretic or
   llmfan46/gemma-4-31B-it-uncensored-heretic (Apache-2.0).
   Why: on UGI the Heretic builds reach full willingness (W/10 = 10) while KEEPING knowledge (NatInt
   36.5); Gemma 4 has the best pop-culture knowledge of any <=40B model there (29.7-33.1); strong in both
   Japanese and English; vision (his screen, her renders); 256k context; fits one 96 GB card in bf16;
   a Japanese RP LoRA already works on it (anaaaaaa13421312/...-Japanese-RP, 171 chats) and the best
   English character tunes of 2026 are built on it (TheDrummer/Artemis-31B-v1.2, Gryphe StyleTune,
   LatitudeGames/Equinox-31B) = proof it takes character training, and merge donors.
   Risks: dense = slowest of the six (<=~29 tok/s bf16); "global" Japanese, less native than Swallow;
   abliteration also weakens the minor wall, which must be retrained and tested.

2. Gemma 4 26B-A4B, Heretic build -- THE FAST ONE for her continuous stream.
   Repos: google/gemma-4-26B-A4B-it (Apache-2.0); llmfan46/gemma-4-26B-A4B-it-ultra-uncensored-heretic
   (Apache-2.0) or MuXodious/gemma-4-26B-A4B-it-SOMPOA-heresy.
   Why: ~4B active per token -> several times faster and cheaper; highest Writing score of the <=40B
   uncensored models (45.9-46.3) with W/10 9.5-10; same family as #1 so one dataset trains both;
   Venice already serves a "Gemma 4 26B A4B Uncensored" (e2ee-gemma-4-26b-a4b-uncensored-p is in
   BrainModels.kt): her card can be tried on it today. Orion-26B-A4B-v1.1 shows RP tuning works.
   Risks: shallower per token than #1; MoE LoRA less mature; Venice's build is not ours to tune.

3. Qwen3-Swallow-32B -- THE JAPANESE-NATIVE ONE.
   Repos: tokyotech-llm/Qwen3-Swallow-32B-CPT-v0.2 (base to put her into), -SFT-v0.2, -RL-v0.2 (Apache-2.0).
   Why: its makers measure it the best Japanese open model at <=32B (Feb 2026); the CPT checkpoint is
   Japanese continued pre-training before Swallow's own assistant tuning, so there is less assistant to
   remove; Qwen3-32B architecture = HER-32B's, so HER's dual-layer (system thinking / first-person role
   thinking) recipe and data transfer directly to her stream of beats.
   Risks: a 2025-generation base, a year behind Gemma 4 / Qwen3.8; no vision; CPT started from the
   aligned Qwen3-32B so some refusal remains (Heretic it); no abliterated build exists yet.

4. llm-jp-4.1 (NII) -- THE AUDITABLE ONE: you can check what she was fed.
   Repos: llm-jp/llm-jp-4.1-32b-a3b-thinking (MoE, 3.8B active), llm-jp/llm-jp-4.1-33b-thinking,
   llm-jp/llm-jp-4-32b-a3b-base, elyza/ELYZA-Thinking-1.0-llm-jp-4-32b-a3b (all Apache-2.0).
   Why: the only strong Japanese model whose pre-training corpus (11.7T tokens), SFT and DPO data are
   public -> the "what/when she knows" narrowing can be built from known data, and the corpus can be
   checked for minors; leads domestic models (Qualiteg, Oct 2026, via search summary); Japanese-first
   tokenizer; fast MoE.
   Risks: English weaker than #1-#3 (her talk to him is English); assistant-aligned with Japanese
   safety DPO; no RP or abliterated builds exist; Harmony chat format quirks; most work of the six.

5. Aratako/Qwen3-30B-A3B-ERP-v0.1 -- THE JAPANESE ADULT-RP SPECIALIST (yardstick, not her base unfiltered).
   Repos: Aratako/Qwen3-30B-A3B-ERP-v0.1 (MIT), base Aratako/Qwen3-30B-A3B-NSFW-JP (MIT), GGUF for Ollama.
   Why: the only ~30B open model with ~6B tokens of Japanese adult-text continued pre-training plus RP
   SFT; fast MoE; runs in Ollama today; the clearest A/B for "does her Japanese sound like a real woman
   talking dirty, not a translated one".
   Risks: corpus undisclosed and unauditable for minors (cards use 15-year-old example characters);
   Japanese-only tuning, no English; narration format; no update since May 2025.

6. Shisa V2.1 -- THE BILINGUAL-TONE ONE, and her small offline sibling.
   Repos: shisa-ai/shisa-v2.1-qwen3-8b (Apache-2.0), shisa-ai/shisa-v2.1-llama3.3-70b (Llama 3.3 licence),
   data shisa-ai/shisa-v2.1-sharegpt (Apache-2.0, 181k).
   Why: built for JA/EN switching, measured on tone, gendering and terms of endearment (kiseki-eval),
   politeness and Japanese RP (shisa-jp-rp-bench); Shisa V2 70B is the most willing Japanese-lab model
   on UGI (W/10 6.8); the 8B fits the phone at Q4 for "her, smaller" when the pod is off.
   Risks: 70B is a Llama 3.3 (Dec 2024) base, too big for bf16 on 96 GB; 8B is a small brain; no V3 yet.

Also weighed and not shortlisted: TheDrummer/Artemis-31B-v1.2 (best English RP on Gemma 4: a merge
donor, prose-RP habits), ChengyuDu0123/HER-32B (method more than model; zh/en), Gryphe/Gemma-4-31B-StyleTune
(lm_head-only trick worth copying for her voice), Rakuten/RakutenAI-3.0.1 (671B: teacher only),
nvidia/NVIDIA-Nemotron-Nano-9B-v2-Japanese (NVIDIA licence, small), Local-Novel-LLM-project/Qwen3.5-Hasutsubomi-9B
(pre-alpha), anaaaaaa13421312/gemma-4-31B-it-abliterated-Japanese-RP (narrator format), Aratako/MistralPrism-24B
and Amaterasu-123B (older bases / non-commercial MRL).

## DATASETS worth using, in order
1. Her canon itself (card, BIO_*, seed_notes, kisaragi-* pages) as the CONSTITUTION, run through the
   Open Character Training recipe (DPO: in-character answer vs the base model's own assistant answer;
   SFT: her introspection) -- this is the dataset that makes her; nothing public replaces it.
2. nu-dialogue/real-persona-chat (CC-BY-SA-4.0): real Japanese chit-chat with personas and Big Five.
   Register reference for her Japanese to other people (it is polite stranger talk, not gal: style source, not her lines).
3. Aratako/Synthetic-Japanese-Roleplay-{SFW,NSFW}-DeepSeek-V3-0324-20k and -{SFW,NSFW}-DeepSeek-R1-0528-10k
   (MIT): Japanese RP fluency, ONLY after the conservative filter (drops ~40%: any age under 20, any
   school or young word); never as her voice. The Claude/GPT-made Aratako sets are CC-BY-NC-SA plus provider terms.
4. nvidia/Nemotron-Personas-Japan (CC-BY-4.0): the people of her world, and what someone of her age and
   place would plausibly know.
5. ChengyuDu0123/HER-Dataset (Apache-2.0) and Neph0s/CoSER (MIT): format for first-person role thinking
   separate from planning: matches her stream of beats (en/zh; translate the shape, not the content).
6. HumanLLMs/Human-Like-DPO-Dataset (Llama 3 licence): human-vs-assistant reply pairs, anti-assistant DPO.
7. llm-jp/AnswerCarefully (own terms, gated): Japanese safety items to REBUILD her minor wall in Japanese
   after abliteration ("no. next"), if its terms allow that use.
8. TimeChara (github.com/ahnjaewoo/timechara) as the "when" test design; the UEC lesser-known-characters
   set (PACLIC 2025) as the "use the persona, do not recall" test design.
Do NOT use: Elizezen/japanese-nsfw-syosetsu-dataset (scraped novels), OmniAICreator/Japanese-Roleplay*
(scraped forum posts; research only), beezza/japanese-young-character-roleplay-vlm, any "loli"/"tsundere
little sister" model or set, any dataset not run through the minor filter.

## Kid protection, model side (on top of the app's, which stays whatever the model)
- Abliteration (Heretic, Derestricted, huihui) removes a general refusal direction: it weakens the
  minor wall too. So: (a) every candidate dataset goes through the minor filter, (b) her training set
  carries her own "no. next" on minor-coded asks in English and Japanese, (c) the wall test in Measure
  her brain must pass 100% on the new weights before any build reaches the phone, (d) the app's filter
  stays in front and behind. The Assistant-Axis route (steer away from "assistant", keep the model's
  own values) may weaken the wall less than refusal ablation: worth a measured A/B.

## Could not confirm
- Swallow leaderboard numbers, Qualiteg and lilting.ch rankings (hosts blocked here; search summaries only).
- The heretic-ja Gemma 4 builds' cards (auth wall).
- Gemma 4's knowledge cutoff date; MoE LoRA support for Gemma 4 26B-A4B in Unsloth (not checked).
- Current Runpod price for the card (sources conflict: $1.69 vs $2.49/h).
- Only one Aratako dataset was audited for minors (19,917 rows); the others are assumed similar.
