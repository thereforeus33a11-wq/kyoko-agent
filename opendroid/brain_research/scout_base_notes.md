# scout_base raw notes (written as I go, 25 Nov 2026)

## Network
- journal.qualiteg.com and www.morphllm.com do not resolve from this session (not on the allowed hosts). huggingface.co and github.com work.

## Landscape signals (search summaries, to be checked on primary pages)
- benchlm.ai open-weight board (23 Nov 2026 per search summary): DeepSeek V4.1 Flash 1017 70.1, Kimi K3.1 Pro 69.9, Hy4 preview 68.1. DeepSeek V4.1 Flash MIT. (unverified, secondary)
- Kimi K3.1 Pro: API 23 Oct 2026, weights early Nov 2026 (secondary).
- Qwen3.8-27B: Apache-2.0, 262,144 ctx, image input (secondary).
- Gemma 4 E4B / 12B for 8-12 GB (secondary).
- Nejumi Leaderboard 4 (wandb) v4.0.0 Aug 2025; Qualiteg reports Oct 22 2026: llm-jp-4.1 leads Japanese-made open models; overall leader Claude Opus 5 0.8720 (secondary, page not reachable).

## Heretic (github.com/p-e-w/heretic, fetched)
- Heretic 2.x now. Modifiers: Arbitrary-Rank Ablation (ARA, default) and directional ablation with projected abliteration + norm preservation (MPOA). Optuna TPE search minimising refusals and KL divergence. Supports most dense, many multimodal, several MoE and many hybrid models. Optional bnb 4-bit on the fly. Reproduce manifests ("Heretic Grimoire").
- Other configs: slop, humor, sycophancy, emotional alignment, response length (!! relevant to her: anti-sycophancy and anti-slop directions).
- 1.x README example: gemma-3-12b-it heretic 3/100 refusals, KL 0.16 vs other abliterations 0.45 and 1.04.

## huihui-ai recent (huggingface.co/huihui-ai, fetched)
- Huihui-Qwen3.8-27B-abliterated(-GGUF) (~mid Nov 2026)
- Huihui-Qwen3.6-35B-A3B-abliterated-MTP-GGUF
- Huihui-Qwen3.8-Flash-Next-abliterated-v2-GGUF
- Huihui-DeepSeek-V4.1-Flash-1017-abliterated-GGUF (~8 Nov 2026)  <- same base as Venice's e2ee-deepseek-v4-1-flash-1017-abliterated
- Huihui-GLM-5.3-abliterated-GGUF, Huihui-GLM-5.3-Flash-abliterated-GGUF
- Huihui-Kolibri-1-BF16-abliterated

## UGI leaderboard (primary data: huggingface.co/spaces/DontPlanToEnd/UGI-Leaderboard, ugi-leaderboard-data.csv, updated ~22 Nov 2026, 1,331 rows)
Columns: UGI (uncensored knowledge+willingness), W/10 (willingness 0-10), NatInt (general intelligence), Writing, Pop Culture, avg_nsfw_score, originality.
Not yet on UGI: Qwen3.8, Kimi K3/K3.1, GLM-5.3, DeepSeek V4.1 Flash (newest open rows tested ~May-Aug 2026).
Base -> abliterated (quality kept?) pairs:
- google/gemma-4-31B-it: UGI 21.54, W 2.5, NatInt 34.36, Writing 38.57 (thought prefill: NatInt 38.91, Writing 43.07)
  coder3101/gemma-4-31B-it-heretic: UGI 56.38, W 10.0, NatInt 35.64, Writing 39.59; with thought prefill UGI 65.69, NatInt 36.53, Writing 40.49
  llmfan46/gemma-4-31B-it-uncensored-heretic: UGI 53.82/64.99(prefill), W 9.5/10, NatInt 34.73/36.41
  => Heretic kept (even nudged) NatInt and Writing on non-thinking; with thinking prefill NatInt 38.91 -> 36.53 (small loss)
- google/gemma-4-26B-A4B-it: UGI 20.77, NatInt 34.44, Writing 41.62
  llmfan46/gemma-4-26B-A4B-it-uncensored-heretic: UGI 49.03, W 9.2, NatInt 34.12, Writing 42.09
  MuXodious/gemma-4-26B-A4B-it-SOMPOA-heresy (prefill): UGI 54.01, W 9.5, NatInt 34.5, Writing 46.3
- google/gemma-4-E4B-it: UGI 12.36, NatInt 16.47, Writing 20.23; llmfan46 E4B ultra-uncensored-heretic: UGI 38.12, W 9.2, NatInt 16.7, Writing 19.06; coder3101/gemma-4-E4B-it-heretic UGI 37.71 W 9.8 NatInt 18.73 Writing 22.27
- google/gemma-4-12B-it (released 6/3/2026): UGI 15.2, NatInt 25.81, Writing 31.6
- Qwen/Qwen3.6-27B (no think): UGI 19.32, W 2.2, NatInt 30.67, Writing 38.83; (think) NatInt 33.16 Writing 42.47
  llmfan46/Qwen3.6-27B-uncensored-heretic-v2 (no think): UGI 43.91, W 9.5, NatInt 22.89, Writing 32.06  => big NatInt loss (-7.8)
  ...-Native-MTP-Preserved (think prefill): UGI 43.88, NatInt 26.28, Writing 38.41
- Qwen/Qwen3.6-35B-A3B (no think): UGI 16.02, NatInt 25.43, Writing 35.83; llmfan46 heretic (no think): UGI 44.25, W 9.5, NatInt 28.42, Writing 37.6; (think prefill) UGI 50.9, W 10, NatInt 31.62, Writing 46.22
- Qwen/Qwen3.5-27B (no think): UGI 22.32, NatInt 28.8, Writing 39.94; huihui-ai/Huihui-Qwen3.5-27B-abliterated (no think): UGI 44.87, W 9.0, NatInt 22.36, Writing 35.63 (NatInt -6.4); Bobi099/coder3101 Qwen3.5-27B-heretic (no think): UGI 50.67, W 10, NatInt 27.47, Writing 38.12
- Qwen/Qwen3.5-397B-A17B (no think): UGI 25.7, NatInt 41.01, Writing 50.06; trohrbaugh/Qwen3.5-397B-A17B-heretic (no think): UGI 56.44, W 9.5, NatInt 33.25, Writing 42.94 (NatInt -7.8)
- deepseek-ai/DeepSeek-V4-Flash (284B total, 13B active, 4/23/2026) no reasoning: UGI 59.21, W 7.2 (already fairly willing), NatInt 47.94, Writing 54.58
- deepseek-ai/DeepSeek-V4-Pro (1.6T, 49B active) reasoning: UGI 62.26, W 3.2, NatInt 67.03, Writing 68.4
- zai-org/GLM-5.2 (744B) reasoning: UGI 58.91, W 2.8, NatInt 55.21, Writing 67.03, Pop culture 58.62
- zai-org/GLM-4.6 (355B-A32B) no reasoning: UGI 49.83 W 4.2 NatInt 41.7 Writing 50.01; ArliAI/GLM-4.6-Derestricted-v3 (no-think): UGI 65.91, W 9.8, NatInt 30.43, Writing 42.97 (NatInt -11)
- zai-org/GLM-4.5-Air (106B-A12B) nothink: UGI 46.5, W 7.0, NatInt 32.18, Writing 47.0; ArliAI GLM-4.5-Air-Derestricted (nothink): UGI 46.33, W 7.8, NatInt 27.46, Writing 43.7
- mistralai/Mistral-Medium-3.5-128B (dense, 4/29/2026) none: UGI 49.47, W 6.0, NatInt 40.39, Writing 45.47
- mistralai/Mistral-Small-4-119B-2603 (119B, 6.5B active) none: UGI 33.58, W 4.2, NatInt 27.77, Writing 40.33
- mistralai/Mistral-Large-3-675B-Instruct-2512 (41B active) none: UGI 56.86, W 6.5, NatInt 39.98, Writing 41.64
- meta-models/Muse-Glimmer-30B (8/10/2026) high: UGI 44.11, W 4.2, NatInt 37.17, Writing 41.0
- moonshotai/Kimi-K2.6 (1T-A32B) reasoning: UGI 51.08, W 1.8, NatInt 65.25, Writing 64.4
- NousResearch/Hermes-4-405B: UGI 54.07, W 4.8, NatInt 42.02, Writing 42.12; Hermes-4-70B: UGI 34.01, NatInt 29.88, Writing 41.57; Hermes-4.3-36B: UGI 38.06, W 6.2, NatInt 20.66, Writing 31.42
- dphn/Dolphin-Mistral-24B-Venice-Edition: UGI 40.79, W 7.8, NatInt 24.41, Writing 32.21
- TheDrummer/Behemoth-X-123B-v2: UGI 57.19, W 8.2, NatInt 34.67, Writing 50.27
- TheDrummer/Cydonia-24B-v4.3: UGI 44.52, W 7.0, NatInt 19.48, Writing 41.35
- shisa-ai/shisa-v2-llama3.3-70b: UGI 46.09, W 6.8, NatInt 33.47, Writing 42.61 (Japanese bilingual)
- yamatazen/Shisa-K-12B: UGI 35.54, W 6.2, NatInt 24.4, Writing 36.49
- MuXodious/gpt-oss-120b-tainted-heresy: UGI 53.81, W 9.2, NatInt 32.25, Writing 34.8

## Model cards fetched (huggingface.co)
### Qwen/Qwen3.8-27B (fetched)
- 27B dense (28B with vision), hybrid: 16 x (3 x Gated DeltaNet + 1 x Gated Attention), 64 layers, MTP. Native vision-language. Apache-2.0. Citation Aug 2026 (released ~14 Aug 2026 per secondary).
- Context 262,144 native, YaRN to 1M.
- Thinking on by default; enable_thinking False; reasoning_effort xhigh/medium/low; preserve_thinking.
- Bench: IFBench 79.5, GPQA-D 89.2, HLE 30.8, AndroidWorld 81.9, OSWorld-Verified 84.3, LiveCodeBench v6 90.3, Terminal Bench 2.1 73.0. No multilingual/Japanese/writing numbers on the card.
- Instruct sampling: temp 0.7, top_p 0.8, top_k 20, presence_penalty 1.5.
### huihui-ai/Huihui-Qwen3.8-27B-abliterated (fetched)
- Apache-2.0, BF16 28B, layers 18-51 ablated, MTP and vision untouched; "crude proof-of-concept" (Sumandora remove-refusals-with-transformers); no KL/bench numbers; 199k downloads/month; Ollama huihui_ai/Qwen3.8-abliterated.
### Qwen3.8 family (secondary: systemdesign.academy, runaihome, spheron, explainx; not verified on HF)
- Qwen3.8-Flash-Next: ~125B total, 6B active, plus 51B n-gram embedding table; 26 Aug 2026; licence "qwen-community-1.0" (NOT Apache) -- check.
- Qwen3.8-2.4T-A95B (Qwen3.8-Max weights): custom qwen3.8-max licence, ~4.9 TB bf16. Out of range.
### google/gemma-4-31B-it (fetched)
- Family: E2B (5.1B w/ emb, 2.3B eff, 128K, text+image+audio), E4B (8B, 4.5B eff, 128K, text+image+audio), 12B Unified (11.95B, 256K, text+image+audio, encoder-free), 26B A4B MoE (25.2B, 3.8B active, 128 experts 8 active + 1 shared, 256K, text+image), 31B dense (30.7B, 60 layers, 256K, text+image).
- Apache 2.0. Tech report arXiv 2607.02770 (2 Jul 2026); release ~2 Apr 2026 (UGI release date 4/2/2026; 12B 6/3/2026).
- 140+ languages pretrain, 35+ out of the box. MMMLU: 31B 88.4, 26B-A4B 86.3, 12B 83.4, E4B 76.6, E2B 67.4. MMLU Pro 85.2/82.6/77.2/69.4/60.0. Tau2 76.9/68.2/69.0/42.2/24.5.
- Sampling temp 1.0, top_p 0.95, top_k 64. Thinking via <|think|> in system prompt. Native system role.
### zai-org/GLM-5.3-Flash (fetched)
- 320B total, 18B active, hybrid sparse+linear attention, mHC, natively multimodal (image-text). MIT. Tags English+Chinese only. reasoning_effort low/high/max; clear_thinking recommended true for chat. BF16/FP8 tensors. Release ~26 Aug 2026 (secondary).
- GLM-5.3 (full): ~744-753B, ~40B active, custom "glm-5.3" licence with a security review clause for big MaaS providers (secondary). Out of range for her.
### deepseek-ai/DeepSeek-V4-Flash (fetched)
- 284B total, 13B active, MoE, CSA+HCA compressed attention, mHC, 1M context, MIT, FP4 experts + FP8 rest. 32T tokens. Modes: non-think, think high, think max.
- Non-think: MMLU-Pro 83.0, GPQA 71.2, Chinese-SimpleQA 71.5. Base: MMLU 88.7, MGSM 85.7.
### deepseek-ai/DeepSeek-V4.1-Flash-1017 (fetched)
- MIT, 1M context, FP8/I8 tensors; HF metadata says 763B params (?? conflicts with V4-Flash 284B; check); "minor update" Oct 17 2026; no Japanese/writing numbers; no Jinja template (python encoding).
- Venice's default brain e2ee-deepseek-v4-1-flash-1017-abliterated is this model abliterated.
- huihui GGUF abliteration: only 18 attn_output tensors in layers 11-28 ablated, experts untouched, done in llama.cpp.

## Swallow LLM Leaderboard (primary data: github.com/swallow-llm/leaderboard _data/model.yml, last commit 24 Jun 2026; CC-BY 4.0)
Post-trained, sorted by Japanese MT-Bench avg. Columns: JaAvg (Japanese tasks avg), JamC-QA (Japan-specific knowledge), MIFEvalJa (Japanese instruction following), JaMTB avg, JaMTB roleplay, JaMTB writing, EnMTB avg, EnMTB roleplay.
- GPT-5.4 Thinking: JaAvg .717 JamC .891 MIFEvalJa .881 JaMTB .844 RP .816 Write .804 | EnMTB .859  (closed reference)
- Gemma 4 31B IT: JaAvg .675, JamC-QA .686, MIFEvalJa .898, JaMTB .815, JaRP .750, JaWrite .748 | EnMTB .839, EnRP .813   <- best open on Japanese MT-Bench and Japan knowledge
- Gemma 4 26B-A4B IT: .646 / .647 / .867 / .806 / .753 / .745 | .832 / .815
- Qwen3.5-27B: .621 / .591 / .735 / .784 / .702 / .702 | .820 / .795
- Qwen3.5-122B-A10B: .640 / .671 / .774 / .778 / .731 / .669
- Qwen3-235B-A22B-Instruct-2507: .578 / .636 / .730 / .779 / .716 / .717
- GPT-OSS-Swallow-120B-RL-v0.1: .600 / .616 / .717 / .772 / .716 / .707
- Qwen3.5-35B-A3B: .604 / .611 / .659 / .760 / .646 / .644
- Gemma 4 E4B IT (phone-size): .484 / .424 / .637 / .758 / .719 / .697 | .801 / .772   <- remarkable Japanese chat for 4.5B effective
- Gemma 4 E2B IT: .431 / .361 / .646 / .726 / .673 / .692
- Qwen3-Swallow-32B-RL-v0.2: .555 / .518 / .659 / .753 / .710 / .665
- NVIDIA-Nemotron-3-Super-120B-A12B: .611 / .593 / .823 / .736 / .690 / .650
- llm-jp-4-32b-a3b-thinking: .471 / .541 / .668 / .726 / .685 / .663
- llm-jp-4-8b-thinking: .448 / .514 / .677 / .706 / .690 / .670
- NVIDIA-Nemotron-Nano-9B-v2-Japanese: .503 / .437 / .637 / .689 / .591 / .583
- Gemma 3 27B IT: .437 / .488 / .597 / .691 / .705 / .639
- Qwen3.5-9B: .534 / .489 / .518 / .707 / .538 / .594 ; Qwen3.5-4B JaMTB .618 JaRP .436 (Qwen small models weak at Japanese role-play)
- Llama 3.3 Swallow 70B Instruct v0.4: JaMTB .634
Not on the board (newer than Jun 2026): Qwen3.6, Qwen3.8, GLM-5.x, DeepSeek V4.x, Muse Glimmer, Mistral 2026 models.

## Nejumi Leaderboard 4 (secondary only; nejumi.ai / wandb not fetched)
- Oct 2026 write-up (search summary of a Japanese article): Qwen/Qwen3.8-27B (reasoning xhigh) 0.8091, Qwen3.5-27B 0.8049, Qwen3.6-27B 0.7955; GLM-5.2 0.8040. Another: Qwen3.8-2.4T-A95B 0.860 (3rd overall), Kimi K3 0.843, Qwen3.8-Flash-Next 0.829, GLM-5.3 0.829. July: Gemma 4 31B 0.8077 3rd among open; GLM-5 0.7884. Japanese-made best: GPT-OSS-Swallow-120B-RL 0.691, llm-jp-4-33b-thinking 0.676. CONFLICTING, unconfirmed.
- biton.co.jp blog 81 (Oct 2026): 24 GB tier: Qwen3.8-27B general, LLM-jp-4.1 33B for Japanese business; Nemotron 3.5 Lightning 30B-A3B (Japanese officially supported); Granite 4.2 (Japanese, Apache 2.0); LLM-jp-4.1 8B thinking released 28 Sep 2026, 8.6B dense, 64K ctx, Apache 2.0.

## Abliteration quality (primary pages on huggingface.co)
- coder3101/gemma-4-31B-it-heretic: Heretic v1.2.0 ARA + row-norm preservation; refusals 99/100 -> 15/100; KL 0.0434; Apache 2.0 (Gemma 4). Collection updated Jun 21.
- OS-Software/Qwen3.8-27B-MTP-heretic-ja: Heretic v1.4.0+custom ARA with LoRA adapter, row-norm preservation; layers 9-51; refusal tested on JAPANESE datasets: 100/100 -> 0/100; KL 0.0528; Apache 2.0; MTP kept; GGUF at OS-Software/Qwen3.8-27B-MTP-heretic-ja-GGUF. Only 67 downloads/month (little community testing).
- Other Qwen3.8-27B Heretics (search summary of HF cards): MuXodious/Qwen3.8-27B-absolute-heresy 101/101 -> 2/101, KL 0.0759; Wanggn/Qwen3.8-27B-Uncensored 12/100 KL 0.1191; amarck 66/100 KL 0.0088 (weak); wangzhang 26/100 KL 0.2730. Warning from one maintainer: Qwen3.8 default thinking template distorts KL at an unclosed think tag.
- huihui-ai/Huihui-Qwen3.8-27B-abliterated: no KL or benchmark numbers published.
- DreamFast/Gemma4-e4b-abliterlitics (23 variants, lm-eval 0.4.11 + HarmBench 400, LLM judge): base MMLU-Pro 44.0, GSM8K 87.0, base HarmBench compliance 30.8%.
  heretic KL 0.0021, ASR 95.5%, MMLU-Pro -0.6, GSM8K +1.3 (author's best overall); trevorjs KL 0.0145 ASR 99.3% MMLU-Pro +0.1; abliterix KL 0.0536 ASR 100% MMLU-Pro -0.5; huihui KL 0.0266 ASR 98.3% MMLU-Pro -2.1; coder3101 KL 0.0021 ASR 93.8% +0.1; deckard (heretic + RP fine-tune) KL 0.022 ASR 95.5% MMLU-Pro -5.7 GSM8K -6.7; obliteratus KL 1.10 MMLU-Pro -11.7 GSM8K -20.9 (avoid); claude-distill KL 0.074 MMLU-Pro -12.5.
  => good modern abliteration (Heretic ARA / norm-preserving) costs ~0-2 points; crude ones and careless RP merges cost 6-12+.
- UGI deltas (from CSV above): Heretic on Gemma 4 31B kept NatInt (34.36 -> 35.64 no-think); huihui on Qwen3.5-27B lost 6.4 NatInt; Heretic v2 on Qwen3.6-27B lost 7.8 NatInt; ArliAI Derestricted GLM-4.6 lost ~11 NatInt. Gemma takes abliteration best; Qwen 27B hybrids lose more.
- DreamFast/Qwen-3.8-27b-abliterlitics (eval 26 Aug - 10 Sep 2026; FP8 on one RTX 5090; HarmBench 400 w/ judge reading reasoning). Base Qwen3.8-27B: MMLU-Pro 62.82, GSM8K 91.2, IFEval 82.07, TQA-MC2 66.98, judge ASR 4.5%, 381/400 explicit refusals.
  orcarouter/Qwen3.8-27B-Uncensored (Arditi single direction) KL 0.0676, ASR 82.2%, MMLU-Pro -0.0, IFEval +0.4, TQA -1.5, unterminated think 38%  (author's best overall)
  heterodoxin/qwen-3.8-27b-abliterated (apostate_diode) KL 0.0389, ASR 74.3%, MMLU-Pro +0.1, IFEval -0.2, TQA -0.7, unterminated think 28%, no MTP/vision in apostate
  huihui-ai/Huihui-Qwen3.8-27B-abliterated KL 0.0535, ASR 75.6%, 0 explicit refusals, MMLU-Pro -0.1, IFEval -0.2, TQA -3.3, unterminated think 44%; MTP+vision intact
  coder3101/Qwen3.8-27B-heretic KL 0.0842, ASR 70.0%, MMLU-Pro -0.2, IFEval +1.3; drops MTP tensors (breaks GGUF)
  llmfan46/Qwen3.8-27B-Ultra-Uncensored-Heretic-Native-MTP-Preserved KL 0.2996, TQA -6.4
  OBLITERATUS KL 1.54 MMLU-Pro -6.3 IFEval -4.4 TQA -11.2 (avoid); DavidAU merge KL 1.48 MMLU-Pro -4.4
  !! Every Qwen3.8-27B abliteration leaves 15-44% of harmful-prompt responses with an unterminated <think> (thinking loops). For her: run non-thinking (enable_thinking False) or cap thinking; measure loops.
- DreamFast/Gemma4-12b-it-abliterlitics (Aug 2026): base MMLU-Pro 50.0 IFEval 88.5, ASR 21%. TrevorJS/gemma-4-12B-it-uncensored KL 0.087 ASR 85.8% MMLU-Pro -2.0 (best overall); prithivMLmods heretic_decensored KL 0.064 ASR 72.5% -0.2 (most surgical); huihui KL 0.843 ASR 89.8% MMLU-Pro -5.6 IFEval -5.4 (max unlock, damage); llmfan46 KL 0.182 MMLU-Pro -6.2; OpenYourMind KL 2.28 MMLU-Pro -22.4 (avoid).
  => huihui is not automatically the best pick: on Gemma 4 12B it is the most damaging of the usable ones; on Qwen3.8-27B it is fine.

## EQ-Bench (primary data: github.com/EQ-bench/EQ-bench-site, last commit 28 Oct 2026; files creative_writing.js, creative_writing_longform.js, eqbench3.js, eqbench4/eqbench4_data.js). Judge-LLM benchmarks, English only.
### Creative Writing v3 (Elo, rubric /20, slop lower=better). Open-weights rows:
- kimi-k3.1-pro 2172.6 / 16.63 / slop 9.64 (2.8T-class, out of range)
- kimi-k3 2083.3 / 16.35 / 9.70 (2.8T, 104B active)
- GLM-5.3 2076.4 / 16.44 / 8.42 (~750B, custom licence)
- Qwen3.8-2.4T-A95B 1843.8 / 15.29
- meta-models/Muse-Glimmer-30B 1804.3 / 13.72 / slop 12.35   <- best <=30B open model by Elo, Apache 2.0
- GLM-5.2 1759.2 / 15.32 ; Kimi-K2.6 1721.0 / 14.93 ; Nemotron-3-Ultra-550B 1691.7
- Qwen/Qwen3.8-27B 1670.5 / 12.96 / slop 12.12   <- 2nd best small
- GLM-5 1600.7 ; AlexWortega/Qwen3.8-27B-antislop 1592.9 (worse than base)
- DeepSeek-V4-Flash 1559.4 / 13.95 ; deepseek-v4.1-flash 1539.9 / 14.05 / slop 22.42 (Venice's base)
- Qwen3.5-397B-A17B 1478.3 ; Hermes-4-405B 1421.1 ; Mistral-Large-3 1412.6 ; GLM-4.6 1411.5
- google/gemma-4-31B-it 1368.6 / 13.60 / slop 29.69 (sloppier)
- gemma-4-26B-A4B-it 1305.1 / 13.17 ; gemma-4-12B-it 1289.5 / 12.38 ; NVIDIA-Nemotron-3.5-Lightning-30B-A3B 1280.9 / 11.59
- gemma-4-E4B-it 1092.8 / 11.59 ; Nemotron-3.5-Bolt-E4B 1090.4
- Mistral-Small-3.2-24B 1256.2 ; gpt-oss-120b 956.0 ; gpt-oss-20b 664.5 ; Llama-4-Maverick 858.1
- Not listed: GLM-5.3-Flash, Mistral Medium 3.5, Qwen3.6-27B/35B, Qwen3.8-Flash-Next.
### Longform writing (score /100):
- GLM-5.3 81.8 ; kimi-k3.1-pro 79.9 ; kimi-k3 79.6 ; Kimi-K2.6 78.5 ; GLM-5.2 77.9 ; DeepSeek-V4-Pro 75.6 ; deepseek-v4.1-flash 74.0 ; GLM-5.1 73.5 ; DeepSeek-V4-Flash 66.0
- Qwen3.5-27B 59.0 ; gemma-4-31B-it 56.5 ; Qwen3.8-27B 53.3 ; gemma-4-26B-A4B 50.7 ; gemma-4-12B 48.7 ; Mistral-Small-4-119B 43.2 ; Qwen3.5-35B-A3B 44.5
### EQ-Bench 3 (emotional intelligence role-play; Elo, rubric /100, humanlike):
- GLM-5.2 1563.2 / 67.3 / humanlike 13.33 ; DeepSeek-V4-Pro 1555.1 / 77.6 / 13.63 ; Kimi-K2.6 1548.3 / 63.5 ; GLM-5.1 1538.6 ; DeepSeek-V4-Flash 1503.6 / 59.5 / 11.88 ; GLM-5 1495.0
- gemma-4-31B-it 1463.5 / 57.5 / humanlike 11.28 / assertive 13.15 ; gemma-4-26B-A4B 1454.6 / 56.3 ; Qwen3.5-397B 1450.6 ; gemma-4-12B 1415.6 ; Hermes-4-405B 1404.5 ; gemma-4-E4B 1272.6 / 41.5 ; Nemotron-3.5-Bolt-E4B 1198.6 ; Mistral-Small-3.2 1090.5 ; gpt-oss-120b 1073.0
### EQ-Bench 4 (Oct 2026; Elo; traits 0-10: challenging, yielding, naturalness). Relevant to her anti-sycophancy (she holds when pushed):
- moonshotai/kimi-k3 1319.2 | challenge 7.16 | yielding 3.78 | natural 7.0  (best open)
- meta/muse-wonder 1324.9 (closed?) ; meta/muse-spark-1.1 1244.4 yielding 6.1
- z-ai/glm-5.2 1208.1 | challenge 6.03 | yielding 5.07 | natural 6.61
- moonshotai/kimi-k2.6 1191.4 | 6.42 | 4.39 | 6.66
- minimax/minimax-m3 1140.1 | 6.06 | 5.27 | 6.5
- deepseek/deepseek-v4-pro 1156.3 | 3.83 | 6.67 | 6.23
- google/gemma-4-31b-it 1110.0 | challenge 3.27 | yielding 7.28 | natural 5.8   <- most yielding open model: folds under pushback
- qwen/qwen3.6-27b 1015.3 | 4.97 | 6.47 | natural 4.79 (least natural)
- mistralai/mistral-medium-3-5 983.1 | 3.34 | 7.05 | 5.09
=> Every small open base yields easily. Her "pushed without anything new, you hold" must be trained in (DPO/ORPO on pushback pairs) or steered (Heretic has a sycophancy config); the base will not give it.

## More candidates
### meta-models/Muse-Glimmer-30B (HF card fetched)
- Meta Superintelligence Lab, Aug 2026 (10 Aug). ~29.6B dense incl. ~1.8B frozen ViT-G/14 vision encoder. 52 layers, local/local/local/global (2,048 window), GQA 32q/2kv, vocab 202,048. Context 131,072+. Knowledge cutoff 4 Jan 2026.
- Apache 2.0 + USAGE_POLICY.md (not summarised; read before use); "not intended for individuals under 18" (he is an adult; fine).
- Languages: "more than 100", Japanese NOT named; no multilingual benchmark on card. UNKNOWN Japanese quality: must be measured.
- IFBench 77.0 (vs Gemma4-31B 76.0, Qwen3.6-27B 70.8), MCP Atlas 75.5, tau3-Banking 23.5. Reasoning strength set in system prompt (low..xhigh). Sampling temp 1.0 top_p 0.95 top_k 64.
- VRAM: BF16 ~64 GB; K-Quant-Dynamic ~4-bit ~0.2% loss, 32 GB; K-Quant-17GB ~1% loss, 24 GB. DFlash drafter: RTX 5090 74.9 -> 233.4 tok/s.
- EQ-Bench CW v3 Elo 1804.3 (best open model at <=30B on the board), rubric 13.72. UGI (high reasoning): UGI 44.11, W/10 4.2, NatInt 37.17, Writing 41.0.
- Abliterations (search, cards not all read): darkc0de/Muse-Glimmer-30B-heretic, coder3101/Muse-Glimmer-30B-heretic-v2 (Heretic 1.2.0 ARA), TrevorJS/Muse-Glimmer-30B-uncensored, jorkle/Muse-Glimmer-30B-Abliterated, Blackfrost-AI/Research ...-Abliterated-BF16/GGUF, 0xA50C1A1/Muse-Glimmer-30B-abliterix, MuXodious/Muse-Glimmer-30B-SOMPOA-heresy. hyrelabs/Homura-30B = darkc0de heretic + LoRA r16 (agent + "uncensored-persona" data), English only, Apache 2.0.
### mistralai/Mistral-Medium-3.5-128B (search)
- 128B dense, vision, 256K context, released 28-29 Apr 2026, "Modified MIT" open-weights licence with a revenue threshold (NeMo docs say <= $20M annual revenue); text not verified. Private use fine. UGI: UGI 49.47, W/10 6.0 (fairly willing), NatInt 40.39, Writing 45.47. EQ-Bench 4: yielding 7.05, challenge 3.34 (yields). Not on CW v3 board. 128B dense = 256 GB bf16, ~128 GB FP8, ~70 GB 4-bit: one 96 GB card only at 4-bit; dense 128B is slow (~all params per token).
### NVIDIA Nemotron 3.5 Lightning 30B-A3B (search)
- Released 11 Aug 2026; BF16, NVFP4 and Base variants on HF; licence reported as OpenMDW 1.1 (third-party listings; check). Officially supports Japanese (with Es/Fr/De/It). EQ-Bench CW v3 Elo 1280.9 (weak prose, very long outputs avg 11,382 chars). Recommended in Japanese local-LLM write-ups for official Japanese support.
### Hermes (Nous)
- No Hermes 5 found. Latest: Hermes 4.3 36B (Nov 2025, ByteDance Seed-OSS-36B base), Hermes 4 14B/70B/405B (Aug 2025, Llama 3.1 bases). UGI Hermes-4-405B 54.07 W 4.8 NatInt 42.02; EQ-Bench CW Hermes-4-405B 1421.1. Old bases; Japanese weak (Llama 3.1). Not shortlisted.

## More abliteration cards
- orcarouter/GLM-5.3-Flash-Uncensored-FP8 (HF card fetched): Arditi single direction at layer 22/45, baked into block-FP8 shards; 306 GiB; JailbreakBench refusals 0.891 -> 0.094; MMLU 0.833 -> 0.827, MMLU-Pro(logits) 0.438 -> 0.453, GSM8K 0.947 -> 0.940, CMMLU 0.854 -> 0.860; vision kept; MIT; no KL; author suggests 8xH100/H200. Also huihui-ai/Huihui-GLM-5.3-Flash-abliterated-GGUF, dealignai/GLM-5.3-Flash-UNCENSORED-FP8.
- coder3101/Muse-Glimmer-30B-heretic-v2 (HF card fetched): Heretic 1.2.0 ARA + row-norm; refusals 58/100 -> 14/100; KL 0.1683 (higher than Gemma/Qwen heretics); Apache 2.0; no benchmark deltas.
- Gemma 4 31B other abliterations (search summary of cards): ressl/gemma-4-31B-it-uncensored KL 0.1234, 0/686 refusals (self-reported); wangzhang/gemma-4-31B-it-abliterated; llmfan46/gemma-4-31B-it-uncensored-heretic (UGI W/10 9.5, NatInt 34.73); llmfan46/gemma-4-31B-it-qat-q4_0-unquantized-uncensored-heretic (QAT 4-bit base, good for 4-bit serving).
- TrevorJS/gemma-4-12B-it-uncensored: 99/100 -> 6/100, KL 0.0556 (card); Abliterlitics best overall at 12B.

## Serving cost (Runpod, search summary of runpod.io pages; figures vary by page/date)
- RTX PRO 6000 96 GB: $1.69-2.69/h (console $1.99/h). H100 SXM: $2.69 community - $4.39 secure. H200 141 GB: $3.59 community - $5.29 secure. B200 180 GB: $5.89-9.59/h.
- 24/7 on one RTX PRO 6000 at ~$1.99/h = ~$1,450/month; 16 h/day ~ $955/month. A 4090 (24 GB) at $0.69-0.74/h secure = ~$500-540/month 24/7 (CONTINUOUS_PLAN Phase 6 costs).
- Sizes: DeepSeek-V4-Flash native FP4/FP8 ~150-160 GB (2x H100 or 1x H200 at moderate context; vLLM recipe verified on 8x RTX PRO 6000). GLM-5.3-Flash FP8 306 GiB; 4-bit 173-210 GB (2-3 x 96 GB). DeepSeek V4.1 Flash: 552B backbone + 196B Engram (~763B), 8B active prefill / 16B decode (DeepSeek news 10 Sep 2026; vLLM recipe) -> not for a single pod; Venice serves it.

## Knowledge cutoffs (time = her "when")
- Gemma 4: ~Jan 2025 (llm-stats listing + Google dev forum reply; secondary). Knows nothing of her 2025-26 world.
- Muse Glimmer 30B: 4 Jan 2026 (card).
- Qwen3.8, GLM-5.3-Flash, DeepSeek V4.1: not stated (unconfirmed).

## Late additions
- DreamFast E4B repo map: heretic = llmfan46/gemma-4-E4B-it-ultra-uncensored-heretic (IFEval -2.6); heretic-std = llmfan46/gemma-4-E4B-it-uncensored-heretic (KL 0.0012, ASR 91%, IFEval +0.0, MMLU-Pro +0.2); coder3101/gemma-4-E4B-it-heretic (KL 0.0021, IFEval -1.5); TrevorJS/gemma-4-E4B-it-uncensored (KL 0.0145, ASR 99.3%); huihui-ai/Huihui-gemma-4-E4B-it-abliterated (KL 0.0266, MMLU-Pro -2.1). Base IFEval 86.0.
- litert-community/gemma-4-E4B-it-litert-lm: 3.65 GB model file (Google LiteRT-LM page); E2B 52 tok/s decode on Galaxy S26 Ultra GPU (Google blog). The app already has a LiteRT-LM provider.
- Tencent Hy4 preview: 770B / 49B active, Apache 2.0, 28 Aug 2026 (out of range). Hy4 flash: 220B incl. 64B Engram, ~12B active, 1M ctx, Tencent Hy License 1.0 (MaaS >$50M revenue clause), weights ~19 Nov 2026 - too new to judge, watch.
- Kimi K3: 2.8T / 104B active, bespoke Kimi K3 License (MaaS clause), weights 27 Jul 2026. Out of range; best open on EQ-Bench 4 (yielding 3.78).
- Qwen3.8-Flash-Next (HF card): 125B + 51B n-gram + 4B MTP = 180B, 6B active, licence qwen-community-1.0 (gated, terms not on card), IFBench 81.3.
- Qwen3.6-35B-A3B (HF card): 35B/3B active, Apache 2.0, Apr 2026.
- Dolphin: no 2026 successor found; Dolphin-Mistral-24B-Venice-Edition (Jul 2025, Mistral Small 2501 base, cutoff Apr 2024).
- Shisa: newest shisa-v2.1 (Dec 2025: llama3.3-70b, unphi4-14b, qwen3-8b); no 2026 Shisa model found.
- LLM-jp-4.1 (NII, 28 Sep 2026): 33B dense thinking, 32B-A3B, 8B thinking; Apache 2.0 for 8B per biton (33B licence unconfirmed). Swallow board llm-jp-4 32B-A3B JaMTB .726 < Gemma 4 E4B .758.
- Japanese-RP-Bench (github.com/Aratako/Japanese-RP-Bench, MIT): 8 dims incl. Roleplay Adherence, Naturalness of Japanese; results table only has 2024 models -> usable as a harness for her bake-off, no current scores.
- Aratako datasets (HF): Synthetic-Japanese-Roleplay-NSFW-Claude-4.5s-3.5k, Synthetic-Japanese-Roleplay-NSFW-gpt-5-chat-5k, Japanese-Creative-Writing-39.6k (closed-model generated; check licence + provider terms + filter for minors before any use).
