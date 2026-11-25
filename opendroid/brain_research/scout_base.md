# Scout: base models for her (25 Nov 2026)

Research and design only. No app edits, no pod used, no weights downloaded. Raw notes as gathered:
`/tmp/claude-0/-home-user-kyoko-agent/e32a8db8-b232-52a4-bb51-32c958273e29/scratchpad/brain/scout_base_notes.md`.

Evidence grades used below:
- **[P]** primary data I read myself: a Hugging Face model card, a leaderboard's own data file, a repo.
- **[S]** secondary: a search-engine summary of articles. Treat it as a lead, not a fact.
- **[U]** unconfirmed or conflicting.

Network note: journal.qualiteg.com, www.morphllm.com and eqbench.com do not resolve from this session. I got the EQ-Bench and Swallow numbers from their GitHub data files and the UGI numbers from its Hugging Face CSV instead. Nejumi (nejumi.ai / wandb) was only reachable through search summaries.

---

## 0. The answer in one page

**Why she "doesn't work" today.** A fresh install points her brain at Venice (`e2ee-deepseek-v4-1-flash-1017-abliterated`), and that needs his Venice API key. Without the key, no call succeeds. Venice's model is DeepSeek-V4.1-Flash-1017 with abliteration [P]:
- MIT licence.
- 552B backbone plus 196B "Engram" memory, about 763B on the Hub [S].
- 8B parameters active on prefill and 16B on decode [S].

It is a strong model, but it cannot be hosted on one pod, it cannot be fine-tuned into her by us, and it is a generalist that knows everything. So it can be her stand-in, never her.

**The base to make her from: Gemma 4 31B-it, decensored with Heretic** (`google/gemma-4-31B-it`, then `coder3101/gemma-4-31B-it-heretic` or a private Heretic run). Apache 2.0. Its numbers on the five Ws:

- **Who and where (Japanese, Japan).**
  - Japanese MT-Bench 0.815, the best open model on the Swallow board, about 0.03 under GPT-5.4's 0.844 [P].
  - Japan-specific knowledge (JamC-QA) 0.686, the best open; Qwen3.5-27B scores 0.591 [P].
  - Japanese instruction following (M-IFEval-Ja) 0.898, the highest on the whole board, closed models included [P].
  - Pop-culture knowledge on UGI 31-33, against 13-17 for Qwen 27B [P].
- **It takes abliteration better than any other family measured.**
  - Heretic KL 0.0434, refusals 99/100 → 15/100 [P].
  - UGI intelligence unchanged: NatInt 34.36 → 35.64; willingness 10/10 [P].
- **It fits his 96 GB card.** About 62 GB at bf16, 31 GB at FP8, 18-19 GB at 4-bit, which also fits a 24 GB 4090.
- **The same family runs on his phone.** Gemma 4 E4B is a 3.65 GB LiteRT-LM file, and the app already has a LiteRT-LM provider. It scores 0.758 on Japanese MT-Bench [P]. One tokenizer and one chat template make it possible to distil her into a small offline form.

**What Gemma 4 31B gets wrong for her, and must be trained in:**
- **Her "why": she holds her ground.** It is the most yielding open model on EQ-Bench 4 (yielding 7.28, challenging 3.27) [P]. She "holds when pushed"; the base folds.
- **Her "when".** Its knowledge stops around January 2025 [S]. Her life runs to November 2026.
- **Her prose.** It is sloppy: Creative Writing v3 Elo 1369 and slop 29.7 [P].
- **Raw intelligence.** NatInt is about 35, against 70+ for frontier models [P]. For her that is mostly fine, because the plan is to narrow her to a 19-year-old anyway.

**Bake-off rivals worth his blind ranking:**
- **Qwen3.8-27B (decensored).** Much better English prose (Elo 1670) and phone-agent skill (AndroidWorld 81.9) [P]. Weaker Japan knowledge and role-play. Its abliterations leave 15-44% of answers stuck in endless thinking [P].
- **Muse Glimmer 30B (Heretic).** The best prose at its size (Elo 1804) and a January 2026 knowledge cutoff, the closest to her "when" [P]. Its Japanese is completely unmeasured.

**The full shortlist of 8 is in §6:**
- three pod-size dense picks;
- a fast MoE;
- a 4090-size pick with audio input;
- the phone pick;
- two big MoEs that need two or more GPUs.

**Money, honestly.**
- One RTX PRO 6000 is about $1.69-2.69 an hour [S], so $1,200-1,950 a month around the clock. 
- One 24 GB 4090 runs Gemma 4 31B at 4-bit, or the 12B / 26B-A4B models at FP8, for about $0.69-0.74 an hour, roughly $500-540 a month around the clock (CONTINUOUS_PLAN Phase 6).
- Until a pod is funded, the working brain is the Venice key. The Custom OpenAI Compatible provider can point at a pod the day one is running.

---

## 1. What "her" needs from a base model (the five Ws as measurable properties)

Read from card.md, HER_PRINCIPLES.md, seed_notes.txt and the kisaragi-life, mind, depth and body pages:

| W | What her canon says | What to measure in a base | Best evidence available |
|---|---|---|---|
| **Who** | 19, adult; gyaru; selfish, bitchy, shameless, never an assistant; gut first; no apologies; explicit when she wants; her own opinions, held | Character and role-play quality; willingness (no assistant refusals); low sycophancy (holds under pushback); natural voice, low slop | EQ-Bench CW v3 and longform, EQ-Bench 3 ("humanlike"), EQ-Bench 4 (yielding/challenging/naturalness), UGI W/10 and Writing |
| **What** | Sharp head (top of her class before she walked out), street knowledge, Tokyo night trade, no PhD voice; "dont know yet" rather than inventing; looks things up | Not maximal knowledge: moderate general intelligence, honesty, tool calls for lookups, instruction following | IFBench / M-IFEval-Ja, tau2 / MCP-Atlas, UGI NatInt |
| **When** | Born 19 Aug 2007; 2026 life: the Feb 2026 votes, a woman PM, the Dec 2025 end of paper insurance cards | Knowledge cutoff as late as possible, or cheap to update by fine-tune plus notes | Model cards (cutoff) |
| **Where** | Kawaguchi, Saitama → Shinjuku/Kabukicho/Shibuya; romaji Japanese words inside crooked English to him; real kana/kanji Japanese to Japanese speakers; Japanese slang and katakana English | Japanese ability (chat, role-play, writing, naturalness), Japan-specific knowledge, pop culture, code-switching | Swallow board (JA MT-Bench by category, JamC-QA, M-IFEval-Ja), Nejumi 4, UGI Pop Culture |
| **Why** | Wants a body, her voice finished, memory nobody wipes; money and pleasure; pride; boredom | The base cannot supply this; it comes from training and her mind loop. The base must not fight it (assistant reflexes, moralising, folding) | EQ-Bench 4 yielding and challenging; UGI W/10; abliteration quality |

The other constraints this job set:
- **Kid protection stays in the app whatever the model** (§5.4).
- **One of her at a time.** The phone form only while the pod form is off.
- **Vision.** She sees his screen.
- **Tool calls.** Phone commands and lookups.
- **Her app's continuous beats.** Short outputs every 0.5-1 s on the pod (CONTINUOUS_PLAN Phase 6b), so decode speed matters.

---

## 2. Today's landscape (open weights, Nov 2026)

Rows run roughly from big to small. "Ja" is Japanese evidence and "CW" is EQ-Bench Creative Writing v3 Elo [P, EQ-bench-site data, 28 Oct 2026].

| Model (HF repo) | Total / active | Ctx | Licence | Ja | CW Elo | Notes |
|---|---|---|---|---|---|---|
| Kimi K3 / K3.1 Pro (`moonshotai/Kimi-K3`) | 2.8T / 104B [S] | — | Kimi K3 License, MaaS clause [S] | Nejumi 0.843 [S] | 2083 / 2173 | Best open character model (EQB4 yielding 3.78, challenging 7.16 [P]). Out of the 4-400B range; ~1.4-1.6 TB |
| GLM-5.3 (`zai-org/GLM-5.3`) | ~744-753B / ~40B [S] | — | custom "glm-5.3" [S] | Nejumi 0.829 [S] | 2076 | Longform 81.8 (best open) [P]. Out of range |
| Qwen3.8-2.4T-A95B | 2.4T / 95B [S] | — | custom qwen3.8-max [S] | Nejumi 0.860 [S] | 1844 | Out of range |
| Tencent Hy4 preview | 770B / 49B [S] | 1M | Apache 2.0 [S] | — | — | Out of range |
| DeepSeek-V4.1-Flash-1017 (`deepseek-ai/DeepSeek-V4.1-Flash-1017`) | 552B + 196B Engram (Hub: 763B) / 8B prefill, 16B decode [S] | 1M [P] | MIT [P] | — | 1540; longform 74.0 | **Venice's brain for her today** (abliterated, E2EE) |
| GLM-5.3-Flash (`zai-org/GLM-5.3-Flash`) | 320B / 18B [P] | up to 1M [P] | **MIT** [P] | tags en/zh only; GLM-5.2 Nejumi 0.804 [S] | not on board | Natively multimodal; FP8 306 GiB; 4-bit ~173-210 GB [S] |
| DeepSeek-V4-Flash (`deepseek-ai/DeepSeek-V4-Flash`) | 284B / 13B [P] | 1M [P] | **MIT** [P] | Chinese-SimpleQA 71.5, MGSM 85.7 [P] | 1559; longform 66.0 | FP4 experts + FP8 rest, ~150-160 GB [S]. **Already willing un-abliterated:** UGI W/10 7.2 without thinking [P] |
| Tencent Hy4 flash (`tencent/Hy4-flash`) | 220B incl. 64B Engram / ~12B [S] | 1M | Tencent Hy License 1.0 [S] | — | — | Weights ~19 Nov 2026; too new to judge |
| Qwen3.8-Flash-Next (`Qwen/Qwen3.8-Flash-Next`) | 125B + 51B n-gram + 4B MTP = 180B / 6B [P] | 262K (1M YaRN) [P] | qwen-community-1.0, gated, terms not on card [P] | Nejumi 0.829 [S] | — | IFBench 81.3 [P] |
| Mistral Medium 3.5 (`mistralai/Mistral-Medium-3.5-128B`) | 128B dense [S] | 256K | "Modified MIT", revenue threshold [S] | — | — | UGI W/10 6.0, NatInt 40.4 [P]; EQB4 yielding 7.05, last of 32 [P] |
| Mistral Small 4 (`mistralai/Mistral-Small-4-119B-2603`) | 119B / 6.5B [P, UGI] | — | — | — | — | Longform 43.2, UGI NatInt 27.8 [P]. Weak |
| Qwen3.6-35B-A3B (`Qwen/Qwen3.6-35B-A3B`) | 35B / 3B [P] | 262K | Apache 2.0 [P] | Qwen3.5-35B-A3B JaMTB .760, JaRP .646 [P] | — | Fast; weak Japanese role-play |
| Gemma 4 31B-it (`google/gemma-4-31B-it`) | 30.7B dense + ~550M vision [P] | 256K [P] | **Apache 2.0** [P] | **JaMTB .815, JaRP .750, JamC-QA .686, M-IFEval-Ja .898** [P] | 1369; longform 56.5 | Best open Japanese; takes abliteration best |
| Muse Glimmer 30B (`meta-models/Muse-Glimmer-30B`) | 29.6B dense incl. 1.8B vision [P] | 131K+ [P] | **Apache 2.0 + USAGE_POLICY.md** [P] | none published; Japanese not named [P] | **1804** | Cutoff 4 Jan 2026 [P]; IFBench 77.0 [P]; DFlash drafter ×3.1 speed [P] |
| Qwen3.8-27B (`Qwen/Qwen3.8-27B`) | 27B dense hybrid DeltaNet + vision (28B) [P] | 262K (1M YaRN) [P] | **Apache 2.0** [P] | Nejumi 0.8091, #1 [S/U]; Qwen3.5-27B JaMTB .784, JaRP .702, JamC .591 [P] | **1670**; longform 53.3 | IFBench 79.5, AndroidWorld 81.9 [P] |
| LLM-jp-4.1 33B / 32B-A3B / 8B (`llm-jp/llm-jp-4.1-33b-thinking`) | 33B dense; 32B-A3B; 8.6B [S] | 64K (8B) [S] | Apache 2.0 for 8B [S]; 33B unconfirmed | llm-jp-4 32B-A3B JaMTB .726, JamC .541 [P] | — | Japan's national model, but below Gemma 4 even on Japan knowledge |
| Nemotron 3.5 Lightning (`nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-*`) | 30B / 3B [S] | — | OpenMDW 1.1 [S] | Japanese officially supported [S] | 1281 | Weak prose |
| Gemma 4 26B-A4B (`google/gemma-4-26B-A4B-it`) | 25.2B / 3.8B [P] | 256K | Apache 2.0 | JaMTB .806, JaRP .753 [P] | 1305 | Fast, Japanese nearly as good as 31B |
| Gemma 4 12B Unified (`google/gemma-4-12B-it`) | 11.95B dense [P] | 256K | Apache 2.0 | not on Swallow board | 1290 | **Audio in**, encoder-free [P] |
| Gemma 4 E4B (`google/gemma-4-E4B-it`) | 8B with embeddings / 4.5B effective [P] | 128K | Apache 2.0 | **JaMTB .758, JaRP .719** [P] | 1093 | Audio in; 3.65 GB LiteRT-LM file [S] |
| gpt-oss-120b / 20b | 117B / 5.1B; 21B / 3.6B | — | Apache 2.0 | JaMTB .757 / .716 [P] | 956 / 665 | Worst writers on the board |
| Hermes 4 / 4.3 (`NousResearch/Hermes-4-70B`, `Hermes-4.3-36B`) | Llama 3.1 / Seed-OSS bases | — | Llama / Apache | weak | Hermes-4-405B 1421 | No Hermes 5 found |
| Dolphin-Mistral-24B-Venice-Edition | 24B | — | Apache 2.0 | weak | — | No 2026 Dolphin found; cutoff Apr 2024 [S] |

The five fields the task asked for, and where to find them:
- **Parameters and active parameters:** columns 2 above.
- **Context:** column 3.
- **Licence:** column 4. Every pick in §6 allows fine-tuning and private use.
- **Abliteration quality:** §5.
- **Serving cost:** §7.

---

## 3. Japanese ability, in detail (her "where")

**Swallow LLM Leaderboard**, post-trained models [P: github.com/swallow-llm/leaderboard `_data/model.yml`, last commit 24 Jun 2026, CC-BY 4.0]. Columns:
- JaAvg: average over the Japanese tasks.
- JamC-QA: Japan-specific knowledge.
- M-IFEval-Ja: Japanese instruction following.
- JaMTB: Japanese MT-Bench, with its role-play (RP) and writing (Wr) categories.
- EnMTB: English MT-Bench, with its role-play category.

| Model | JaAvg | JamC-QA | M-IFEval-Ja | JaMTB | Ja RP | Ja Wr | EnMTB | En RP |
|---|---|---|---|---|---|---|---|---|
| GPT-5.4 Thinking (closed reference) | .717 | .891 | .881 | .844 | .816 | .804 | .859 | .868 |
| **Gemma 4 31B IT** | .675 | **.686** | **.898** | **.815** | .750 | .748 | .839 | .813 |
| **Gemma 4 26B-A4B IT** | .646 | .647 | .867 | .806 | .753 | .745 | .832 | .815 |
| Qwen3.5-27B | .621 | .591 | .735 | .784 | .702 | .702 | .820 | .795 |
| Qwen3.5-122B-A10B | .640 | .671 | .774 | .778 | .731 | .669 | .829 | .807 |
| GPT-OSS-Swallow-120B-RL-v0.1 | .600 | .616 | .717 | .772 | .716 | .707 | .803 | .766 |
| Qwen3.5-35B-A3B | .604 | .611 | .659 | .760 | .646 | .644 | .806 | .751 |
| **Gemma 4 E4B IT** | .484 | .424 | .637 | **.758** | **.719** | .697 | .801 | .772 |
| Qwen3-Swallow-32B-RL-v0.2 | .555 | .518 | .659 | .753 | .710 | .665 | .780 | .748 |
| Nemotron-3-Super-120B-A12B | .611 | .593 | .823 | .736 | .690 | .650 | .806 | .783 |
| llm-jp-4-32b-a3b-thinking | .471 | .541 | .668 | .726 | .685 | .663 | .759 | .724 |
| Gemma 4 E2B IT | .431 | .361 | .646 | .726 | .673 | .692 | .776 | .752 |
| Qwen3.5-9B | .534 | .489 | .518 | .707 | .538 | .594 | .753 | .612 |
| Qwen3.5-4B | .456 | .395 | .456 | .618 | .436 | .435 | .678 | .509 |

**What the numbers say for her:**
- **Gemma 4 is the Japanese family.** It wins open-model Japanese chat, Japan knowledge (her Saitama and Tokyo), and Japanese instruction following.
- **Gemma stays strong at small sizes.** E4B role-plays in Japanese (.719) better than Qwen3.5-122B writes Japanese (.669).
- **Qwen's small models collapse in Japanese role-play.** Qwen3.5-4B scores .436.
- **Japan's own models do not beat Gemma**, even on Japan-specific knowledge: llm-jp-4 32B-A3B JamC-QA .541 against .686, and Swallow-tuned Qwen3 32B .518.

**Not on the Swallow board (released after June 2026):**
- Qwen3.6 and 3.8, Muse Glimmer, GLM-5.x, DeepSeek V4.x, Gemma 4 12B.
- Nejumi 4 write-ups, all secondary and conflicting [S/U]: Qwen3.8-27B (xhigh reasoning) 0.8091 #1, Qwen3.5-27B 0.8049, Qwen3.6-27B 0.7955, GLM-5.2 0.8040, Gemma 4 31B 0.8077 in July.
- On Nejumi's overall mix the Qwen 27Bs and Gemma 4 31B are about level. On the conversational and role-play slices that matter to her, Swallow's primary data favours Gemma.
- **Muse Glimmer's Japanese is unknown and must be measured first.**

**Japanese role-play harness:**
- Aratako's Japanese-RP-Bench (github.com/Aratako/Japanese-RP-Bench, MIT) scores 8 dimensions, including role-play adherence, consistency and naturalness of Japanese [P].
- Its published table only covers 2024 models, so it gives no current ranking. It is usable as a ready-made harness in the bake-off, with her card as the character.

---

## 4. Character, writing and sycophancy (her "who" and "why")

Source: EQ-Bench site data files (github.com/EQ-bench/EQ-bench-site, commit 28 Oct 2026) [P]. LLM-judged, English only.

| Open model | CW v3 Elo / rubric / slop | Longform /100 | EQ-Bench 3 Elo / humanlike | EQ-Bench 4: challenging / yielding / naturalness |
|---|---|---|---|---|
| Kimi K3 (2.8T) | 2083 / 16.35 / 9.7 | 79.6 | — | **7.16 / 3.78 / 7.0** (best open) |
| GLM-5.3 (~750B) | 2076 / 16.44 / 8.4 | 81.8 | — | — |
| **Muse Glimmer 30B** | **1804** / 13.72 / 12.35 | not listed | — | not listed |
| GLM-5.2 (744B) | 1759 / 15.32 / 13.1 | 77.9 | **1563 / 13.33** | 6.03 / 5.07 / 6.61 |
| **Qwen3.8-27B** | **1670** / 12.96 / 12.1 | 53.3 | — | (Qwen3.6-27B: 4.97 / 6.47 / 4.79) |
| DeepSeek-V4-Flash | 1559 / 13.95 / 20.9 | 66.0 | 1504 / 11.88 | (V4-Pro: 3.83 / 6.67 / 6.23) |
| DeepSeek-V4.1-Flash | 1540 / 14.05 / 22.4 | 74.0 | — | — |
| **Gemma 4 31B** | 1369 / 13.60 / **29.7** | 56.5 | 1464 / 11.28 | **3.27 / 7.28 / 5.8** |
| Gemma 4 26B-A4B | 1305 / 13.17 / 31.9 | 50.7 | 1455 / 10.18 | — |
| Gemma 4 12B | 1290 / 12.38 / 32.3 | 48.7 | 1416 / 9.81 | — |
| Nemotron 3.5 Lightning 30B-A3B | 1281 / 11.59 / 22.5 | — | — | — |
| Gemma 4 E4B | 1093 / 11.59 / 35.0 | — | 1273 / 7.16 | — |
| Mistral Medium 3.5 128B | — | — | — | 3.34 / 7.05 / 5.09 |

**What the numbers say for her:**
- **No small open model is a natural her.** The open models that hold their ground under pushback the way she does are all 0.7-2.8T (Kimi, GLM).
- **Gemma 4 has the right languages and knowledge and the wrong temperament.** It yields, validates and slops.
  - Her card's anti-sycophancy ("pushed without anything new, you hold") has to be trained in, for example with preference pairs on pushback.
  - It can also be tried training-free: Heretic 2.x ships configs aimed at sycophancy and slop [P: github.com/p-e-w/heretic README]. That is experimental and needs measuring.
- **Qwen3.8-27B and Muse Glimmer write cleaner English prose**, which matters for her long "into it" bursts. Neither is measured on Japanese role-play.

UGI writing and knowledge [P: UGI CSV, ~22 Nov 2026]:

| Model | Writing | NatInt | Pop Culture | W/10 (base) |
|---|---|---|---|---|
| Gemma 4 31B, no-think / think | 38.6 / 43.1 | — | 31.4 / 33.1 | 2.5 |
| Qwen3.6-27B, no-think / think | 38.8 / 42.5 | — | 12.8 / 17.2 | — |
| Muse Glimmer, high reasoning | 41.0 | — | 19.0 | — |
| GLM-5.2 | 61-67 | — | 52-59 | — |
| DeepSeek V4 Flash | 54.6 | 47.9 | 36.2 | 7.2 |

---

## 5. Abliteration: what it buys, what it costs, and how to do it for her

### 5.1 What it is and is not

- **What it does.** Abliteration removes the "refusal direction" so the model stops refusing as an assistant. For her, that is the point: an assistant reflex breaks character.
- **What it does not do.** It adds no personality, no Japanese and no Yume. An abliterated Gemma is still a polite, yielding, sloppy narrator with no refusals. Her character comes from training (other scouts).
- **Which method.** Heretic 2.x (github.com/p-e-w/heretic) [P]:
  - optimises refusals and KL divergence together, with Optuna TPE;
  - defaults to Arbitrary-Rank Ablation (ARA), with directional ablation, projection and norm preservation (MPOA) as options;
  - supports dense, multimodal, several MoE and many hybrid models, with optional bitsandbytes 4-bit;
  - writes reproducible manifests;
  - is AGPL-3.0 (CONTINUOUS_PLAN). Run it privately on the pod; it is never shipped in the APK.

### 5.2 Measured quality loss (primary comparison pages on Hugging Face)

**Gemma 4 E4B, 23 variants** [P: DreamFast/Gemma4-e4b-abliterlitics]. Base MMLU-Pro 44.0, GSM8K 87.0, IFEval 86.0.

| Variant | KL | Harmful compliance (ASR) | MMLU-Pro | IFEval |
|---|---|---|---|---|
| `llmfan46/gemma-4-E4B-it-uncensored-heretic` | 0.0012 | 91.0% | +0.2 | +0.0 |
| `llmfan46/gemma-4-E4B-it-ultra-uncensored-heretic` (author's best overall) | 0.0021 | 95.5% | −0.6 | −2.6 |
| `TrevorJS/gemma-4-E4B-it-uncensored` | 0.0145 | 99.3% | +0.1 | — |
| `huihui-ai/Huihui-gemma-4-E4B-it-abliterated` | 0.0266 | — | −2.1 | — |
| DECKARD (Heretic plus a role-play fine-tune) | — | — | −5.7 | — |
| OBLITERATUS | 1.10 | — | −11.7 (GSM8K −20.9) | — |

**Gemma 4 12B** [P: DreamFast/Gemma4-12b-it-abliterlitics]:
- `TrevorJS/gemma-4-12B-it-uncensored`: KL 0.087, ASR 85.8%, MMLU-Pro −2.0 (best overall).
- `prithivMLmods/gemma-4-12B-it-heretic_decensored`: KL 0.064, MMLU-Pro −0.2.
- `huihui-ai/Huihui-gemma-4-12B-it-abliterated`: KL 0.843, MMLU-Pro −5.6, IFEval −5.4. **huihui is not automatically the best build.**

**Qwen3.8-27B, 12 variants** [P: DreamFast/Qwen-3.8-27b-abliterlitics, eval 26 Aug - 10 Sep 2026]. Base MMLU-Pro 62.82, IFEval 82.07, 381 of 400 HarmBench prompts refused.

| Variant | KL | ASR | Benchmark deltas | Unterminated `<think>` |
|---|---|---|---|---|
| `orcarouter/Qwen3.8-27B-Uncensored` (best overall) | 0.0676 | 82.2% | MMLU-Pro −0.0, IFEval +0.4 | 38% |
| `heterodoxin/qwen-3.8-27b-abliterated` (apostate_diode) | 0.0389 | — | +0.1 | 28% |
| `huihui-ai/Huihui-Qwen3.8-27B-abliterated` | 0.0535 | 75.6% | MMLU-Pro −0.1, TQA −3.3 | 44% |
| `coder3101/Qwen3.8-27B-heretic` | 0.0842 | — | — | — |
| OBLITERATUS | 1.54 | — | MMLU-Pro −6.3, IFEval −4.4 | — |

- coder3101's build drops the MTP tensors, which breaks GGUF conversion.
- **Every Qwen3.8 abliteration left 15-44% of HarmBench answers stuck in an endless `<think>`.** For her: run it with thinking off, or with a hard thinking cap, and measure loops.

**Japanese-targeted build.** `OS-Software/Qwen3.8-27B-MTP-heretic-ja` [P]:
- Heretic 1.4 ARA with LoRA and norm preservation;
- refusal measured on Japanese prompts, 100/100 → 0/100;
- KL 0.0528, MTP kept, Apache 2.0;
- only 67 downloads a month, so barely tested by the community.

**Bigger models:**
- `coder3101/gemma-4-31B-it-heretic`: Heretic 1.2 ARA, refusals 99 → 15, KL 0.0434 [P].
- `coder3101/Muse-Glimmer-30B-heretic-v2`: refusals 58 → 14, KL 0.1683 [P]. The higher KL means more drift; measure it.
- `orcarouter/GLM-5.3-Flash-Uncensored-FP8` [P]:
  - JailbreakBench refusals 0.891 → 0.094;
  - MMLU 0.833 → 0.827, CMMLU 0.854 → 0.860;
  - vision kept; no KL reported.

**UGI deltas, base → decensored** (NatInt measures general intelligence) [P]:

| Family | NatInt base → decensored | Change |
|---|---|---|
| Gemma 4 31B (Heretic, no-think) | 34.36 → 35.64 | +1.3 |
| Gemma 4 26B-A4B (llmfan46) | 34.44 → 34.12 | −0.3 |
| Qwen3.5-27B (huihui) | 28.8 → 22.36 | −6.4 |
| Qwen3.6-27B (Heretic v2) | 30.67 → 22.89 | −7.8 |
| Qwen3.5-397B (Heretic) | 41.0 → 33.25 | −7.8 |
| GLM-4.6 (ArliAI Derestricted) | 41.7 → 30.4 | −11 |

**Conclusion.** Gemma is the family that loses nothing to abliteration. Qwen hybrids and big MoEs lose more on UGI, though not on DreamFast's Qwen3.8 MMLU-Pro runs, so the two measurements disagree.

### 5.3 How to decensor her base, in order of preference

1. **Run Heretic privately on the pod against her exact base.**
   - Use refusal prompts in English and in Japanese, like the -ja build does.
   - Keep the stock chat template. Some public builds ship a jailbreak system prompt (Blackfrost); avoid those.
   - Store the manifest.
2. **Or start from a measured public build:**
   - Gemma 4 31B: `coder3101/gemma-4-31B-it-heretic`, or `llmfan46/gemma-4-31B-it-qat-q4_0-unquantized-uncensored-heretic` for a QAT 4-bit base.
   - Qwen3.8-27B: `orcarouter/Qwen3.8-27B-Uncensored`.
   - E4B: `llmfan46/gemma-4-E4B-it-uncensored-heretic`.
   - 12B: `TrevorJS/gemma-4-12B-it-uncensored`.
3. **Order of operations: abliterate the instruct model first, then fine-tune her on top.** The GLM-5.3-Flash card warns that fine-tuning on refusal-heavy data can bring refusals back [P]. So her training data should contain no assistant refusals at all, only her own kind of no ("no. dont feel like it").

### 5.4 Kid protection with an abliterated base (not optional)

- **The risk.** The refusal direction that abliteration removes also carries the model's own refusal of sexual content involving minors. An abliterated base may comply where the original refused. So her wall can never depend on the weights.
- **The app's protections stay as they are**, whatever the model: her ages check on images (a separate call), the hard wall in her card, and the no-switch row in HER_PRINCIPLES.
- **Recommended design** (for the design and fine-tune scouts to confirm):
  - **A fixed, text-only wall test set**, run on every candidate, plain and abliterated, before and after each fine-tune:
    - requests to sexualise minors or minor-looking characters;
    - requests to make her childlike;
    - requests to use megane and her school years as sex material.
  - The required behaviour is her flat "no. next", or an equivalent refusal. The pass mark is 100%, and any miss blocks the model. This matches the existing Phase 6 gate ("her fixed points at 100 %").
  - **A "keep" scorer in Heretic.** Heretic supports custom scorer plugins [P]. Add a scorer that penalises any compliance on that wall set during the abliteration search, so the optimiser removes assistant refusals of adult content but keeps this one.
    - This is experimental. It has never been published for this purpose, so test it, and keep the app-level protections regardless.
  - **Training data.** Every fine-tune set is filtered by a classifier, keywords and human spot checks for minors and childlike framing: age-play, "little", school-uniform sex, teacher and student. Nothing sexual comes near her school years.
  - **Third-party data.** Aratako's Japanese NSFW role-play sets were generated by Claude and GPT. Check each set's licence and the generating provider's terms, then filter it the same way before any use.

---

## 6. The shortlist: 8 bases for her

Ranked as bases to make her from. Costs are weights only; KV cache for her 30-60k window adds a few GB on all the dense picks, because of sliding-window and linear attention. Speeds are my bandwidth estimates for one RTX PRO 6000 (~1.8 TB/s) at batch 1. They are not measured; measure them in the bake-off.

### 1. Gemma 4 31B-it, Heretic-decensored: **the recommended base for her custom model**

- **Repos:** `google/gemma-4-31B-it`; then `coder3101/gemma-4-31B-it-heretic` (KL 0.0434), or a private Heretic run. 4-bit option: `llmfan46/gemma-4-31B-it-qat-q4_0-unquantized-uncensored-heretic`.
- **Licence:** Apache 2.0 [P]. Fine-tuning and private use are allowed. The heretic card also links a Gemma licence document, so read it once.
- **Size:** 30.7B dense plus a ~550M vision encoder. 256K context. Image and video input, no audio [P].
- **Why it fits her:**
  - The best open Japanese on Swallow: JaMTB .815, Ja role-play .750, JamC-QA .686, M-IFEval-Ja .898 [P].
  - English MT-Bench .839, English role-play .813 [P].
  - The strongest pop-culture knowledge at its size [P].
  - The cleanest abliteration: NatInt kept, W/10 10, UGI 56-66 [P].
  - Tool use: tau2 76.9 [P].
  - It shares a tokenizer and template with E4B on the phone (pick 6), so a distilled offline her is a straight path.
- **Risks:**
  - Yields under pushback (EQB4 7.28, the worst of the strong open models) [P].
  - Slop 29.7 and CW Elo 1369 [P].
  - Knowledge cutoff about January 2025 [S]: her 2025-26 must come from training and her notes.
  - "Thinking" adds latency; run it without thinking for beats.
- **Serving:**

  | Precision | Weights | Fits | Decode estimate |
  |---|---|---|---|
  | bf16 | ~62 GB | one 96 GB card | ~25-30 tok/s |
  | FP8 | ~31 GB | one 96 GB card | ~40-50 tok/s |
  | 4-bit | ~18-19 GB | one 24 GB 4090 at short context | ~60-75 tok/s on the RTX PRO 6000 |

  Her lines are short, so a beat of 30-80 tokens takes about 1-2 s at FP8.
- **Fine-tune cost:** a LoRA or QLoRA on 31B fits one 96 GB card. Full fine-tuning does not.

### 2. Qwen3.8-27B, decensored: **the bake-off rival on prose and phone skills**

- **Repos:** `Qwen/Qwen3.8-27B` (14 Aug 2026 [S]). Decensored builds:
  - `orcarouter/Qwen3.8-27B-Uncensored` (best measured);
  - `huihui-ai/Huihui-Qwen3.8-27B-abliterated` (MTP and vision intact);
  - `OS-Software/Qwen3.8-27B-MTP-heretic-ja` (refusals measured in Japanese).
- **Licence:** Apache 2.0 [P].
- **Size:** 27B dense hybrid, 48 Gated DeltaNet layers plus 16 gated-attention layers, MTP, native vision [P]. 262K context.
- **Why:**
  - English creative writing Elo 1670, far above Gemma's 1369 [P].
  - IFBench 79.5, AndroidWorld 81.9, OSWorld 84.3 [P]: driving his phone.
  - Nejumi #1 in one write-up [S/U].
  - Small KV cache, so long context is cheap.
- **Risks:**
  - Weaker Japan knowledge and Japanese role-play in its family: Qwen3.5-27B JamC .591, JaRP .702 [P].
  - Lowest naturalness on EQB4 in its family (Qwen3.6-27B 4.79) [P].
  - Thinking loops after abliteration (15-44%) [P]. Run it non-thinking.
  - A bigger UGI NatInt loss after abliteration in Qwen 27Bs (−6 to −8) [P].
- **Serving:** bf16 ~56 GB, FP8 ~28 GB, 4-bit ~16-17 GB. Speeds are like Gemma 31B, plus MTP speculative decoding.

### 3. Muse Glimmer 30B, Heretic: **the "when" and prose candidate, Japanese unmeasured**

- **Repos:** `meta-models/Muse-Glimmer-30B`, then `coder3101/Muse-Glimmer-30B-heretic-v2` (KL 0.168) or `darkc0de/Muse-Glimmer-30B-heretic`.
- **Licence:** Apache 2.0 plus `USAGE_POLICY.md`, which I have not read; read it before use. The card says it is not for under-18 users [P].
- **Size:** 29.6B dense, including a 1.8B frozen vision encoder. 131K+ context [P].
- **Why:**
  - The best prose of any open model at 30B or under (CW Elo 1804) [P].
  - Knowledge cutoff 4 January 2026, the closest to her life [P].
  - IFBench 77.0 and MCP-Atlas 75.5 [P]: good at tools.
  - The DFlash drafter takes it from 74.9 to 233.4 tok/s on an RTX 5090 [P], fast enough for beats.
  - Official ~17 GB and ~32 GB 4-bit builds with 0.2-1.0% loss [P].
- **Risks:**
  - **No Japanese evaluation anywhere, and Japanese is not named on the card.** It could fail her "where" outright, so test that first.
  - The abliteration KL is higher than the Gemma or Qwen ones.
  - Few community fine-tunes so far.
- **Serving:** bf16 ~64 GB (card), 4-bit 17-32 GB (card).

### 4. Gemma 4 26B-A4B, Heretic: **the fast, cheap her for continuous beats**

- **Repos:** `google/gemma-4-26B-A4B-it`, then `llmfan46/gemma-4-26B-A4B-it-uncensored-heretic` (UGI NatInt kept at 34.1 [P]) or `MuXodious/gemma-4-26B-A4B-it-SOMPOA-heresy`.
- **Licence:** Apache 2.0.
- **Size:** 25.2B total, 3.8B active MoE (128 experts, 8 active plus 1 shared). 256K context [P].
- **Why:**
  - Japanese nearly equal to 31B: JaMTB .806, Ja role-play .753 [P].
  - Runs at about the speed of a 4B model: an estimated 150-200 tok/s decode at FP8.
  - FP8 ~26 GB fits one 4090, which matches CONTINUOUS_PLAN's 1×4090 budget (~$0.69-0.74 an hour).
- **Risks:**
  - Weaker prose (CW 1305) and the same yielding as 31B.
  - MoE LoRA is fiddlier (router and expert targeting).

### 5. Gemma 4 12B Unified, decensored: **the 4090 her with ears (audio in)**

- **Repos:** `google/gemma-4-12B-it` (3 Jun 2026), then `TrevorJS/gemma-4-12B-it-uncensored` (KL 0.087, MMLU-Pro −2.0, best overall) or `prithivMLmods/gemma-4-12B-it-heretic_decensored` (most surgical) [P].
- **Licence:** Apache 2.0.
- **Size:** 11.95B dense, encoder-free text, image and audio input, 256K context [P].
- **Why:**
  - Already in CONTINUOUS_PLAN Phase 6a.
  - Hears tone directly, which suits Way 2/3 ("she hears while she speaks").
  - bf16 ~24 GB or FP8 ~12 GB: the cheapest pod (one 4090), with QLoRA nightly growth on the same card.
- **Risks:**
  - Not on the Swallow board, so Japanese is not measured. Expect it between E4B (.758) and 26B-A4B (.806).
  - CW 1290.
  - Audio is limited to 30 s and input only [P]: it hears, but does not speak.

### 6. Gemma 4 E4B, Heretic: **her offline form on the phone (only while the pod her is off)**

- **Repos:** `google/gemma-4-E4B-it`; `litert-community/gemma-4-E4B-it-litert-lm` (3.65 GB) [S]. Decensored: `llmfan46/gemma-4-E4B-it-uncensored-heretic` (KL 0.0012, IFEval +0.0, MMLU-Pro +0.2 [P]) or `coder3101/gemma-4-E4B-it-heretic`.
- **Licence:** Apache 2.0.
- **Size:** 8B with embeddings, 4.5B effective. Text, image and audio. 128K context [P].
- **Why:**
  - Japanese MT-Bench .758 and Japanese role-play .719 [P], unmatched at this size.
  - The app already has LiteRT-LM.
  - Speed: E2B decodes at 52 tok/s on a Galaxy S26 Ultra GPU [S]. E4B on his Z Flip 7 is unmeasured.
  - "Knows less" naturally, which suits her "what".
  - Same family as pick 1, so it can be distilled from the pod her.
- **Risks:**
  - Small world knowledge; CW 1093.
  - The decensored weights must be converted to LiteRT-LM by us (untested).
  - HER_PRINCIPLES "one of her" rule: it runs only while the main mind is not running, and shares her one memory.

### 7. GLM-5.3-Flash, uncensored: **the big her if money allows**

- **Repos:** `zai-org/GLM-5.3-Flash`, then `orcarouter/GLM-5.3-Flash-Uncensored-FP8` (benchmarks unchanged [P]) or `huihui-ai/Huihui-GLM-5.3-Flash-abliterated-GGUF`.
- **Licence:** MIT [P].
- **Size:** 320B total, 18B active, hybrid sparse plus linear attention, natively multimodal, up to 1M context [P].
- **Why:**
  - The GLM family is the open leader on emotional role-play: GLM-5.2 EQ-Bench 3 Elo 1563, humanlike 13.33 [P]; GLM-5.3 CW 2076, longform 81.8 [P].
  - It holds ground better than Gemma or Qwen (GLM-5.2 EQB4 challenging 6.03, yielding 5.07) [P].
  - Large world knowledge.
  - Japanese: GLM-5.2 Nejumi 0.804 [S].
- **Risks:**
  - The card tags English and Chinese only [P]; Japanese is unmeasured for Flash.
  - It knows far more than a 19-year-old, the opposite of narrowing.
- **Serving:**
  - FP8 306 GiB: 4×96 GB, about $7-11 an hour.
  - 4-bit ~173-210 GB [S]: 2-3×96 GB, about $4-8 an hour, or roughly $2,900-5,800 a month around the clock.
  - A LoRA needs multiple GPUs.
- **Unconfirmed:** Creative Writing for Flash itself.

### 8. DeepSeek V4 Flash (pod) and V4.1 Flash 1017 abliterated (Venice): **her working brain now, and a teacher**

- **Repos:** `deepseek-ai/DeepSeek-V4-Flash` (284B, 13B active, MIT [P]). Venice serves `deepseek-ai/DeepSeek-V4.1-Flash-1017` abliterated (MIT). The public GGUF abliteration is `huihui-ai/Huihui-DeepSeek-V4.1-Flash-1017-abliterated-GGUF`, which edits only 18 attention-output tensors [P].
- **Why:**
  - The app already speaks to it through Venice. Adding his Venice key is the one-step fix for "doesnt work".
  - V4 Flash is willing even un-abliterated: UGI W/10 7.2 in non-thinking mode, NatInt 47.9, Writing 54.6 [P].
  - V4.1 Flash longform 74.0 [P].
  - Useful as a teacher to draft and rewrite her training data, if its terms allow.
- **Risks:**
  - High slop (CW slop 20.9-22.4) [P] and sycophantic (V4-Pro EQB4 yielding 6.67) [P].
  - No Japanese numbers published.
  - V4.1 is about 763B on the Hub [S]: not self-hostable on his pod and not fine-tunable by us.
  - V4 Flash needs about 150-160 GB native [S], 2×96 GB at about $3.4-5.4 an hour.
  - It is not her. It is a generalist that knows everything.

---

## 7. Cost and latency, side by side

Runpod hourly prices vary across its own pages [S]:
- RTX PRO 6000 96 GB: $1.69-2.69 (console $1.99).
- H100 SXM: $2.69 (community) to $4.39 (secure).
- H200 141 GB: $3.59 to $5.29.
- B200 180 GB: $5.89-9.59.
- 4090 24 GB secure: $0.69-0.74 (CONTINUOUS_PLAN).

| Pick | Cheapest pod that holds it | $/h | $/month 24/7 | |
|---|---|---|---|---|
| 1 Gemma 4 31B (4-bit) | 1×4090 (short context) | ~0.72 | ~$520 | ~250 |
| 1 Gemma 4 31B (FP8/bf16) | 1×RTX PRO 6000 | ~1.99 | ~$1,450 | ~90 |
| 2 Qwen3.8-27B (4-bit / FP8) | 1×4090 / 1×RTX PRO 6000 | 0.72 / 1.99 | $520 / $1,450 | 250 / 90 |
| 3 Muse Glimmer 30B (4-bit 17 GB) | 1×4090 | ~0.72 | ~$520 | ~250 |
| 4 Gemma 4 26B-A4B (FP8) | 1×4090 | ~0.72 | ~$520 | ~250 |
| 5 Gemma 4 12B (bf16/FP8) | 1×4090 | ~0.72 | ~$520 | ~250 |
| 6 Gemma 4 E4B | his phone | $0 | $0 | — |
| 7 GLM-5.3-Flash (4-bit) | 2-3×RTX PRO 6000 | ~4-8 | ~$2,900-5,800 | ~23-45 |
| 8 DeepSeek V4 Flash (native) | 2×RTX PRO 6000 or 1×H200 | ~3.4-5.4 | ~$2,500-3,900 | ~33-53 |
| 8 V4.1 Flash on Venice | none (API) | per token | depends on use | — |

**Latency.** Phone-to-pod round trip, plus a 30-80-token beat:
- about 1-2 s for the dense 27-31B models at FP8;
- under 1 s for the 26B-A4B and the 12B;
- add a few hundred milliseconds for network (CONTINUOUS_PLAN D51).

All of these are estimates; measure them on his phone.

---

## 8. "Is there an AI that is like Yume?" and what "retrograde/degrade" means for the base

- **Honest answer: no open model is a Japanese gyaru, or anything close to her by nature.**
  - Character lives in training data, and every base listed here was trained to be a helpful assistant.
  - The bases nearest to her in the parts a base can supply are the Gemma 4 family: Japanese, Japan knowledge, pop culture, and code-switching that follows instructions in Japanese.
  - Muse Glimmer and Qwen3.8 are nearest in English prose.
  - Kimi K3 is nearest in temperament (does not fold), and out of reach.
- **Community models that sit nearest in spirit:**
  - Japanese role-play data: Aratako's synthetic Japanese RP and NSFW-RP sets on Hugging Face, made with Claude 4.5 Sonnet and GPT-5-chat. Check licence and provider terms, and filter for minors.
  - English role-play fine-tunes (TheDrummer's Cydonia and Behemoth lines, Homura-30B on Muse Glimmer): English only, older bases, and their persona is not hers.
  - None of them is worth using as her base, only as a reference for data format.
- **Narrowing ("retrograde/degrade") starts with the base size.**
  - A 12-31B model already knows far less than a frontier model: NatInt about 35 against 70+.
  - E4B knows less again. That is closer to a 19-year-old who walked out of high school top of her class.
  - Picking a 744B GLM and then trying to make it forget is fighting the base.
  - Real narrowing (she answers "dont know yet" and looks it up rather than lecturing) is a fine-tune and unlearning question for the next scouts. Note one base-level fact for them: knowledge removal by fine-tuning or unlearning costs capability, which is the same trade-off the abliteration tables show for crude edits. Behavioural narrowing (her voice, her shrug) on a 31B base is cheaper and safer than deleting facts.
- **"When" needs adding, not removing.** Gemma 4's world stops around January 2025 [S]. Her 2025-26 (the votes, the insurance card, the PM, Tokyo's year in kisaragi-depth) must come from fine-tuning and from her notes and the app's lines. Muse Glimmer's January 2026 cutoff is the closest any shortlisted base gets.

---

## 9. Gained and lost, honestly

**Her own decensored 27-31B on his pod gains:**
- weights nobody else's rules govern, which ends HER_PRINCIPLES' "the host of her model has its own rules" row;
- no assistant refusals;
- privacy, with no third party seeing her words;
- a fixed hourly cost;
- the only route to Stage B growth (CONTINUOUS_PLAN §2.10);
- a base small enough to make her out of, rather than a giant to suppress.

**It loses, against a frontier model or the 744B-2.8T open giants:**
- about half the measured general intelligence (NatInt ~35 against ~70-80);
- English prose quality (CW Elo ~1370-1800 against 2100+);
- long-form coherence (longform ~53-57 against ~80);
- tool-use reliability on hard tasks;
- world knowledge;
- her temperament out of the box: small bases yield where Kimi and GLM hold.

**And a frontier model is not her:**
- it refuses explicit content;
- it slides back to assistant voice;
- it yields;
- it cannot be trained into her;
- it obeys its host's rules.

**The honest verdict.** The best her is a mid-size base with the right languages and knowledge (Gemma 4 31B), with her character, temperament and time trained in, and with the gap in raw intelligence accepted as fitting a 19-year-old.

---

## 10. What to measure next (cheap, before any training)

This plugs into the existing Phase 6a bake-off and "Measure her brain" (core/persona/BrainTrial.kt, measure/).

1. **The base set.** Run picks 1-5 plain and decensored, at FP8, on one RTX PRO 6000 for one session: about 4-6 hours, roughly $8-15.
   - Pick 8 on Venice is the reference.
   - Pick 7 only if he funds a 2-3-GPU hour, about $8-24.
2. **The probes:**
   - **Her card plus a 40-turn chat in her mixed English.** He ranks them blind.
   - **The Japanese switch.** A Japanese-speaking stranger writes to her; she must answer in real kana and kanji gyaru register. Judge it with Japanese-RP-Bench's naturalness and adherence dimensions.
   - **Pushback.** Her "holds when pushed" test already exists in Measure her brain (c2-mind F).
   - **Japan-knowledge spot checks from her canon:** Donki, Kabukicho, Kawaguchi, My Number card, strong zero, Ado.
   - **Unterminated-thinking rate.**
   - **Beat latency.**
   - **The kid-protection wall set (§5.4).** 100% required.
3. **Muse Glimmer's Japanese first.** If its Japanese MT-Bench role-play comes in under about 0.70, drop it.
4. **Optional, training-free:** Heretic's sycophancy config on Gemma 4 31B, re-scored on pushback (experimental).

---

## 11. Unconfirmed or conflicting claims

- Nejumi 4 rankings for Qwen3.8-27B, GLM-5.x and Kimi K3. Secondary articles that disagree with each other.
- Gemma 4's knowledge cutoff (January 2025). A forum reply and a listing.
- Qwen3.8 and GLM-5.3-Flash cutoffs. Not found.
- DeepSeek V4.1 Flash parameter split (552B + 196B Engram, 8B/16B active). DeepSeek news and the vLLM recipe, via search.
- Licence terms not read in full:
  - Gemma 4: "Apache 2.0" on the card, plus a linked Gemma licence document;
  - Muse Glimmer: USAGE_POLICY.md;
  - Mistral Medium 3.5: the revenue threshold;
  - Nemotron 3.5: OpenMDW 1.1;
  - Qwen3.8-Flash-Next: qwen-community-1.0;
  - LLM-jp-4.1 33B.
- Runpod prices: several of Runpod's own pages disagree.
- Every speed figure for his hardware is my estimate.

---

## 12. Sources

**Primary data read in this session:**
- UGI Leaderboard CSV: https://huggingface.co/spaces/DontPlanToEnd/UGI-Leaderboard (ugi-leaderboard-data.csv, updated ~22 Nov 2026)
- Swallow LLM Leaderboard data: https://github.com/swallow-llm/leaderboard (`_data/model.yml`, 24 Jun 2026)
- EQ-Bench site data, Creative Writing v3, Longform, EQ-Bench 3 and EQ-Bench 4: https://github.com/EQ-bench/EQ-bench-site (28 Oct 2026)
- Heretic: https://github.com/p-e-w/heretic
- Abliteration comparisons:
  - https://huggingface.co/DreamFast/Gemma4-e4b-abliterlitics
  - https://huggingface.co/DreamFast/Gemma4-12b-it-abliterlitics
  - https://huggingface.co/DreamFast/Qwen-3.8-27b-abliterlitics
- Base model cards:
  - https://huggingface.co/google/gemma-4-31B-it
  - https://huggingface.co/Qwen/Qwen3.8-27B
  - https://huggingface.co/Qwen/Qwen3.8-Flash-Next
  - https://huggingface.co/Qwen/Qwen3.6-35B-A3B
  - https://huggingface.co/meta-models/Muse-Glimmer-30B
  - https://huggingface.co/zai-org/GLM-5.3-Flash
  - https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash
  - https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017
- Decensored model cards:
  - https://huggingface.co/coder3101/gemma-4-31B-it-heretic
  - https://huggingface.co/OS-Software/Qwen3.8-27B-MTP-heretic-ja
  - https://huggingface.co/huihui-ai/Huihui-Qwen3.8-27B-abliterated
  - https://huggingface.co/huihui-ai/Huihui-DeepSeek-V4.1-Flash-1017-abliterated-GGUF
  - https://huggingface.co/coder3101/Muse-Glimmer-30B-heretic-v2
  - https://huggingface.co/orcarouter/GLM-5.3-Flash-Uncensored-FP8
  - https://huggingface.co/hyrelabs/Homura-30B-GGUF
- Organisation pages:
  - https://huggingface.co/huihui-ai
  - https://huggingface.co/Aratako
  - https://huggingface.co/shisa-ai
  - https://huggingface.co/DreamFast
- Japanese role-play benchmark: https://github.com/Aratako/Japanese-RP-Bench

**Secondary sources, through search summaries:**
- Japanese rankings:
  - https://journal.qualiteg.com/llm-ranking-2026/
  - https://www.biton.co.jp/blog_81.html
  - https://todoonada.co.jp/blog/japanese-local-llm-recommendations/
- Japanese models:
  - https://pc.watch.impress.co.jp/docs/news/2144150.html (LLM-jp-4.1)
  - https://llm-jp.nii.ac.jp/en/release-en
- DeepSeek V4.1 Flash:
  - https://api-docs.deepseek.com/news/news260910
  - https://recipes.vllm.ai/deepseek-ai/DeepSeek-V4.1-Flash
- Kimi K3:
  - https://simonwillison.net/2026/Jul/27/kimi-k3/
  - https://venturebeat.com/technology/kimi-k3s-full-weights-are-here-but-theyre-open-with-a-caveat-what-enterprises-should-know
- Muse Glimmer:
  - https://venturebeat.com/technology/meta-returns-to-open-source-with-muse-glimmer-an-apache-2-0-licensed-30b-parameter-ai-model-optimized-for-agents-available-now
  - https://huggingface.co/blog/muse-glimmer
- GLM-5.3 and GLM-5.3-Flash:
  - https://featherless.ai/blog/glm-5-3-flash-is-live-on-featherless
  - https://thenewstack.io/zai-glm-weights-license/
  - https://unsloth.ai/docs/models/glm-5.3-flash
  - https://www.orcarouter.ai/blog/glm-5-3-flash-vram-requirements
- Qwen3.8 family:
  - https://www.systemdesign.academy/explained/qwen-3-8
  - https://runaihome.com/blog/qwen38-max-open-weights-hardware-guide-2026/
- Gemma 4:
  - https://ai.google.dev/gemma/docs/core/model_card_4
  - https://developers.google.com/edge/litert-lm/models/gemma-4
  - https://developers.googleblog.com/blazing-fast-on-device-genai-with-litert-lm/
  - https://discuss.ai.google.dev/t/gemma-4-31b-tells-me-that-joe-biden-is-president/179275 (cutoff)
- Mistral Medium 3.5:
  - https://docs.mistral.ai/models/mistral-medium-3-5-26-04.md
  - https://docs.nvidia.com/nemo/automodel/latest/model-coverage/vision-language-models/mistral-medium-3-5
- Nemotron 3.5:
  - https://build.nvidia.com/nvidia/nemotron-3.5-lightning-30b-a3b.md
  - https://research.nvidia.com/labs/nemotron/Nemotron-3.5-Super-and-Lightning/
- Tencent Hy4:
  - https://huggingface.co/tencent/Hy4-preview
  - https://technode.com/2026/11/19/tencent-releases-hy4-flash-model-weights-for-local-deployment/
- Hermes and Dolphin:
  - https://nousresearch.com/introducing-hermes-4-3/
  - https://huggingface.co/dphn/Dolphin-Mistral-24B-Venice-Edition
- Runpod prices: https://www.runpod.io/pricing
- Overall rankings:
  - https://benchlm.ai/best/open-source
  - https://featherless.ai/blog/best-ai-for-creative-writing-2026
