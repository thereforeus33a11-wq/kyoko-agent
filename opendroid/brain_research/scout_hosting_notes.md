# scout_hosting raw notes (25 Nov 2026) - written as gathered

## A. Her call pattern, read from the app (branch yume, /home/user/app/opendroid)
- core/mind/Tempo.kt: FULL_PACE_MILLIS = 0 (next beat starts when the last ends; one in flight, I14).
  WITH HIM: listening beat on each new piece of his speech; cue beats; silence beats at 2.5/6/15/40 s; then NEAR pace.
  NEAR every 45 s (NEAR_EVERY_MILLIS), events at most once per kind per 2 min.
  ALONE default 5 min (10 min until cache seen warm), her choice 1-60 min; events once per kind per 10 min.
  ASLEEP: no beats (a stir beat if he speaks/writes).
- core/mind/Governor.kt: talk budget $3/day default, own-time $2/day default; cold cache -> listening every 3.5 s;
  window compacted at 35k tokens (60k with him + warm cache, 20k cold); mobile data -> 3 s floor.
- core/mind/BeatPrompt.kt: max_tokens LISTENING 60, SPEAKING 400, compaction piece 400, whole 2,000.
- core/life/OwnLedger.kt: DEFAULT_CALLS_PER_DAY = 150 counts MOMENT, OUTING_STEP, OWN_COMMAND, EYES, PICTURE, SIGNUP
  (stream beats are NOT in the 150; they are on the $ budgets).
- CustomOpenAIProvider streams SSE in the clear (stream:true, include_usage, prompt_cache_key = her stream id);
  the Venice e2ee route answers in one piece (streamsLiveFor = !isE2eeModel) -> no streaming on E2EE.
- CONTINUOUS_PLAN §2.4/§3.6: stable prefix ~14k tokens; window avg 10-14k; fresh 0.3-1.5k; ~60 out per beat.
  Talk hour ~1,260 calls at 2 s cadence (810 listening, 150 overlap, 240 replies, 60 silence); ~800 at 3 s.
  Not talking (16 h awake): ~160 NEAR, ~200 ALONE, ~20 compactions, ~30 outing steps, sleep pass.

## B. Runpod, primary (docs source, raw.githubusercontent.com/runpod/docs/main, read 2026-11-25; runpod.io itself does not resolve from this session)
- serverless/pricing.mdx: flex = standard per-second rate, scale to zero; ACTIVE = always on 24/7, "Discounts available through sales inquiry" (no public active price any more). Billed from worker start to full stop. Cold start billed (handler loading model); image pull and cached-model download normally not billed. Idle timeout default 5 s console (REST v2 10 s), billed while waiting. Container disk ~$0.10/GB-mo; network volume $0.07/GB-mo (<1 TB), $0.05 (>1 TB). Spend limit default $80/h.
- snippets/serverless-gpu-pricing-table.mdx (flex per second): 16 GB A4000/A4500/RTX4000 $0.00016 (=$0.58/h); 24 GB L4/A5000/3090 $0.00019 ($0.68/h); 24 GB 4090 PRO $0.00031 ($1.12/h); 48 GB A6000/A40 $0.00034 ($1.22/h); 48 GB L40/L40S/6000 Ada PRO $0.00053 ($1.91/h); 80 GB A100 $0.00076 ($2.74/h); 80 GB H100 PRO $0.00116 ($4.18/h); 96 GB "6000s PRO" (RTX PRO 6000) $0.00111 ($4.00/h); 141 GB H200 PRO $0.00155 ($5.58/h); 180 GB B200 $0.00240 ($8.64/h).
- endpoint-configurations.mdx: defaults active 0, max 3, idle 5 s, exec timeout 600 s, FlashBoot on (console; REST v2 off). FlashBoot "retaining worker state after spin-down... most effective on endpoints with consistent traffic". Idle endpoint: after 3 days no requests max workers -> 2, after 7 days -> 0 (must raise by hand). RUNPOD_INIT_TIMEOUT default 420 s.
- workers/overview.mdx: cached HF models (public/gated/private) = fastest cold start; network volume = slower (read after billing starts). Throttled = host GPUs used by others.
- load-balancing/overview.mdx: load-balancing endpoints go direct to the worker HTTP server (FastAPI, vLLM load balancer), "ideal for real-time applications and streaming", no queue; URL https://ENDPOINT_ID.api.runpod.ai/PATH.
- pods/pricing.mdx: pods per second; Savings plans DEPRECATED (no new ones); container disk $0.10/GB-mo running; volume disk $0.10 running / $0.20 stopped; network volume $0.07 (<1 TB). Pods stop at $0 balance; pods without network volume are terminated, data lost. Need >= 1 h of credit to deploy on-demand.
- pods/configuration/expose-ports.mdx: HTTP proxy https://POD-PORT.proxy.runpod.net via Cloudflare, 100 s max connection; public IPs may change on Community, "should remain stable for Secure Cloud".
- references/security-and-compliance.mdx: multi-tenant containers; ToS prohibits hosts inspecting data; Secure Cloud T3/T4 DCs, SOC 2 / ISO 27001 partners; GDPR for EU regions.

## C. Pod prices (secondary; runpod.io/pricing not reachable here) - web search 2026-11-25
- Runpod aggregators (Jul-Nov 2026 snapshots, disagree): 4090 Secure $0.59-0.89, Community ~$0.34; 5090 Secure $0.89-1.19, Community ~$0.69;
  L40S Secure ~$0.86-1.09, Community ~$0.79; H100 PCIe $1.99 C / $2.39-2.89 S; H100 SXM $2.69 C / $2.99-3.99 S;
  RTX PRO 6000 96 GB: $1.69 Community, $1.99-2.09 Secure (console $1.99 per scout_base). Sources: hivenet.com runpod-pricing guide,
  neroengine.com/runpod-pricing (via search), computeprices.com/providers/runpod/gpus/rtx-pro-6000, northflank RTX PRO 6000 blog, beam.cloud RTX PRO 6000 blog.
- Runpod serverless active worker: docs say "discounts via sales"; marketing copy says 30% (older blog 40%); one snapshot H200 $0.00155 flex vs $0.00124 active (~20%). [S/U]
- Runpod serverless vLLM cold start: Runpod blog "cut vLLM cold starts from 5 minutes to 90 seconds"; independent 4-request FlashBoot test 7 s to 7 min
  (dev.to/sergeyshmakov "How RunPod FlashBoot actually works"); others report 60-120 s; marketing "sub-200 ms"/"~600 ms for 70B" = vendor claims.
  Pre-warmed workers evicted under contention -> full cold start. [S]
- Vast.ai (markaicode snapshot 16 Nov 2026 from vast.ai pricing): from/median per GPU-h: 3090 $0.09/$0.20; 4090 $0.27/$0.50; 5090 $0.37/$0.63;
  RTX PRO 6000 S $1.33/$1.73. Thunder Compute: Vast 5090 median $0.78 (10 Nov 2026, 16 verified US/CA hosts, $0.49-1.12). [S]
- Hetzner (docs.hetzner.com price-adjustment, after 15 Jun 2026, ex VAT): GEX44 (RTX 4000 SFF Ada 20 GB) EUR 232.30/mo + EUR 114 setup;
  GEX131 (RTX PRO 6000 Blackwell 96 GB) EUR 1,197.30/mo + EUR 599 setup. Contabo RTX PRO 6000 GPU VPS EUR 999/mo (pasqualepillitteri.it). [S, official page via search]

## D. Hosted serving of a custom model
- Fireworks: pricing page "LoRA models on serverless billed at base-model rate" but FAQ "fine-tuned (LoRA) models require a dedicated deployment"
  (conflict; serverless LoRA only for some bases); multi-LoRA up to 100 adapters on one deployment; cached input e.g. GLM-5.3 $0.26 vs $1.40. [S]
- Together: LoRA on serverless "base rate plus small overhead" (unconfirmed); AUP text not retrievable; generic "harmful content". [U]
- Featherless: flat monthly (Basic $10, Premium $25, Scale $75+ per llms.txt), unlimited tokens, limited by concurrency units and model size;
  hosts many uncensored/heretic RP models (e.g. llmfan46/...-heretic pages); ToS "output may not suit minors"; blog: prompts/completions not logged;
  individual plans request models on Discord, Business deploys own models. Public HF models only for individuals -> her trained weights would have to be public. [S]

## E. Phone (primary: HF model cards, curl huggingface.co, 2026-11-25)
- litert-community/gemma-4-E4B-it-litert-lm README: 3.66 GB file (2.24 GB decoder + 0.67 GB embeddings mmapped); up to 32k context;
  bench 1024 prefill/256 decode, ctx 2048: S26 Ultra CPU prefill 195 tok/s, decode 17.7, TTFT 5.3 s, 3,283 MB; GPU prefill 1,293, decode 22.1, TTFT 0.8 s, 710 MB.
  Speculative decoding (re-download after 5 May 2026): S26U GPU 36.7-49.4 tok/s, CPU 21-29.5. RTX 4090 (Linux) prefill 7,260, decode 91.2.
  "On supported Android devices Gemma 4 is available through Android AI Core as Gemini Nano." Apache 2.0, not gated.
- litert-community/gemma-4-E2B-it-litert-lm: 2.58 GB; S26U CPU prefill 557, decode 46.9, TTFT 1.8 s; GPU 3,808 / 52.1 / 0.3 s; spec-dec GPU 66-92 tok/s.
  NPU builds only for Qualcomm (QCS8275 example); no Exynos NPU build.
- Exynos 2500 (Flip 7): ~18% slower than Snapdragon 8 Elite (S25) per Android Authority; throttles hard under sustained load in the Flip body
  (androidcentral, androidauthority 3576340, gsmarena 67958). Geekbench AI quantized 3401 (Flip 7) vs 3767 (Fold 7).
  OS_PLAN §1: LiteRT-LM open bugs on Xclipse GPUs (init fail on 960, garbage on 530); 950 untested -> app tries GPU, falls back only on init error.
- No published LLM tokens/s for Exynos 2500 found (search). Estimate from S26U (8 Elite Gen 5) CPU numbers x ~0.6-0.75.

## F. Other
- Modal (third-party tables 2026): H100 $3.95/h, A100 80 GB $2.50, L40S $1.95, RTX PRO 6000 $3.03, L4 $0.80; $30/mo free on Starter; preemptible by default. [S]
- SaladCloud (Spheron blog, 12 Sep 2026): 4090 $0.33 high / $0.16 batch; 5090 $0.50 / $0.25. Consumer machines in homes. GetDeploying: median 4090 on-demand $0.49 (17 Oct 2026). TensorDock 4090 $0.46. [S]
- Phala Cloud GPU TEE (confidential compute, attestation): H200 $2.56-3.50/h (docs: $3.50 on-demand w/ 24 h minimum, $2.56 1-mo, $2.30 6-mo), H100 $2.38-3.08; hourly billing, restart re-triggers 24 h minimum. [S, phala docs via search]
- RTX 5090 retail Nov 2026: US listings ~$4,900-5,200 (guru3d, club386, techspot), MSRP $1,999; EU/UK lower. [S]
- App: Venice e2ee route needs MIN_OUTPUT_TOKENS 4000 ("models served this way reason before they answer"), answers in one piece (no streaming) -> first word only after the whole beat incl. reasoning.

## G. More (web search 2026-11-25)
- Runpod landing page (undated, via search): 4090 $0.69 Secure / $0.34 Community; L40S $0.86 / $0.79; RTX A6000 $0.49 / $0.33; A40 $0.40 Secure.
  Instance-types page: 5090 $0.69, 4090 $0.34, L40S $0.79, A40 $0.35, A6000 $0.33 (community-like). gpu-prices page (updated 27 Jul 2026): "5090 PRO $1.22/h, 4090 PRO $1.15/h" (looks like serverless). [S]
- Gemma 4 31B FP8 (RedHatAI/gemma-4-31B-it-FP8-block) on 1x RTX PRO 6000, vLLM 0.20, prefix caching on: concurrency 12-24, ~27 tok/s per request, 380-548 tok/s total output, TTFT p50 0.73 s
  (huggingface.co/blog/hexgridcloud/gemma-4-31b-vllm-on-rtx-6000-pro, 29 Jun 2026, vendor self-report). [P]
- Gemma 4 26B-A4B: RTX 4090 Ollama 149-193 tok/s generation (markaicode, low reliability); one 5090 vLLM AWQ ~196 tok/s (unverified); forum single-stream ~40 tok/s on 5090 AWQ (odd). [S/U]
- Venice docs (tee-e2ee-models): TEE + E2EE text only; Intel TDX / NVIDIA CC; docs RECOMMEND streaming for E2EE; community venice-e2ee-proxy decrypts per chunk. No caching doc. [S]
  -> the app answers e2ee in one piece; streaming may be possible (to check).
- LiteRT-LM NPU vendors: Google Tensor and Qualcomm only (developers.google.com/edge/litert/next/litert_lm_npu). LiteRT lists Exynos 2500 (E9955) NPU for classic models
  (developers.google.com/edge/litert/next/samsung). ExecuTorch Samsung Exynos backend supports E9955 (docs 1.3-1.5), LLM on Exynos NPU not shown. [S]
- Hosted LoRA: W&B Inference (CoreWeave) "bring your own LoRA" serverless, Gemma 4 31B $0.30/$1.25; Novita Gemma 4 31B $0.14/$0.40 (16 Nov 2026 aggregator); DeepInfra ~$0.07-0.13 / $0.34-0.38. LoRA-on-serverless for Gemma 4 31B unconfirmed at Together/Fireworks/DeepInfra/Novita. [S]
- HF Inference Endpoints (AWS): L4 $0.80/h, L40S $1.80, A100 80 GB $2.50; billed by the minute while active. [S]
- Runpod ToS (ConductAtlas third-party summary): pornography / graphic adult material listed among unauthorized user content; obscene/lewd "as Runpod deems". Enforcement on private inference unknown. [S, low confidence]
- Venice: permissive on adult text and images per reviews (airdroid, nsfwaireviews); ToS age 13+ (quoted by airdroid). [S]
