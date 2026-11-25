# Her own brain: the first page (25 Nov 2026)

His ask: "can ya find the perfect model you can modify, alter and retrograde/degrade so it fits the 5 Ws
she is, exactly? ... A custom AI, made from a completely unrestricted, uncensored and abliterated AI.
Maybe there is an AI that is like Yume in someways."

**Status: the research is partly done, and nothing below has had its independent check yet.** Of the
five research parts, three finished (base models, Japanese and character models, methods). The hosting
part stopped half-way, and the part on what the app needs never ran. The checks of each shortlisted model,
the three competing designs and the judging also never ran, because the session's usage ran out. The full
research, with sources, is in [brain_research/](brain_research/). Before any money is spent on training,
the shortlisted models must be checked against their own model cards.

## Why she does not work today

A fresh install points her brain at Venice: `e2ee-deepseek-v4-1-flash-1017-abliterated`, an uncensored
DeepSeek with end-to-end encryption. That needs his Venice API key, typed into Settings > API keys >
"Custom OpenAI Compatible API Key". Without a key, no call succeeds.

That model is about 763B parameters. It cannot be hosted on one pod and cannot be trained into her, so it
can be her stand-in, never her.

## Is there an AI that is already like her?

No. Nobody has released a gyaru or gal-speech language model; the Japanese "AI gal" apps are closed and
sweet. The closest route is a strong bilingual base, made willing in a way that keeps its knowledge, then
trained on her own canon.

## The base the research points to (unchecked)

**Gemma 4 31B-it, made willing with Heretic** (`google/gemma-4-31B-it`, then `coder3101/gemma-4-31B-it-heretic`
or our own Heretic run). Apache 2.0.

Why it fits her:
- **Japanese.** The best open model on the Swallow board for Japanese conversation (Japanese MT-Bench
  0.815), Japan-specific knowledge (0.686) and Japanese instruction following (0.898).
- **It survives being made uncensored.** It loses the least of any family measured (KL 0.0434, intelligence
  unchanged).
- **Size.** It fits his 96 GB card, and at 4-bit a 24 GB card.
- **A phone-sized sister.** Gemma 4 E4B (3.65 GB) runs on his phone through the app's existing LiteRT-LM
  provider, so a small offline form of her is possible from the same family.

What must be trained into it:
- **It folds when pushed**, and she holds her ground. It is the most yielding open model on EQ-Bench 4.
- **Its knowledge stops around January 2025**, and her life runs to November 2026.
- **Its prose is weak.**

Rivals worth a blind test by him:
- **Qwen3.8-27B (decensored):** better English, weaker on Japan, and its uncensored builds often get stuck
  thinking.
- **Muse Glimmer 30B (Heretic):** the best prose at its size, but its Japanese is unmeasured.
- **The fast option for her continuous stream:** Gemma 4 26B-A4B (Heretic), with about 4B parameters active
  per word. Venice already serves an uncensored build of it, so her card can be tried on it today with his
  Venice key.

## Making it her, and narrowing it to her (the five Ws)

Three layers, from [brain_research/scout_method.md](brain_research/scout_method.md):
1. **Put her canon into the weights.** The base, with her card and pages in front of it, teaches the same
   base without them (self-distillation: Prompt Baking, SDFT, Open Character Training's DPO and
   introspection). Weights hold a person far better than a long prompt does.
2. **Narrow her by behaviour, not by deleting knowledge.** This is his "retrograde". Character-LLM's
   "protective experiences" are scenes where she meets things outside her world and honestly does not know
   them. Add training against the lecturing, encyclopedia voice, and three tiers of what she knows taken
   from her canon: what she knows well, what she half knows, and what she does not know. She says "dont
   know" and looks things up the way a person would. Real unlearning methods are shallow, cost general
   ability and come undone; they stay an experiment only.
3. **Keep her opinions.** Train her with pushback data, so that she does not cave to pressure and moves only
   on real reasons (her card's rule, and "Her own mind" in HER_PRINCIPLES.md).

What stays, whatever model: the app's own kid protection. No training data may sexualise minors or make
her childlike, and her own "no. next" wall from her card is kept and tested on every build.

## Money (estimates)

- **Training v1:**
  - a pilot of about 2,000 examples on the fast model, about $10-20;
  - a full run, about $25-55 on the fast 26B-A4B or about $60-150 on the dense 31B, on his 96 GB card.
- **Running her own model** is the real cost:
  - **Always on, one 24 GB card** (4-bit 31B, or the fast model): about $0.72 an hour, about $520 a month.
  - **Always on, one 96 GB card:** about $2 an hour, about $1,450 a month.
  - **Serverless** (pay per second, cheaper when she is quiet): her first word can take from seconds to
    minutes after she has been idle.
  - **The phone-sized sister:** $0, but much weaker.

## What he decides

1. **How much a month her own brain may cost to run.** That decides the size and the hosting.
2. **Whether to start with Venice tonight**, with his key, as her stand-in.
3. **Whether to run the pilot** (about $10-20 of pod time) once the checks have run.
