# Her, continuous: hearing, speaking, thinking and acting without turns

Build plan, 2026-11-21. For the owner and the builders. Nothing in it is built unless it says "built".

It replaces the turn-based parts of `ALIVE_PLAN.md`: §4.7 below names each one, and says what is kept. Everything else in `ALIVE_PLAN.md`, `OWN_LIFE_PLAN.md` and `EMOTIONS_RESEARCH.md` still holds.

It answers the owner's message of 2026-11-20:

> "Notice you called me talking to her as a turn. Shouldnt have to be that way. I want her human as much as you can possibly make her. Humans dont hear, speak or do things in turns. I dont want you to change the verbage to make it seem like you changed it. I want you to actually fix those problems. Really go into deep research and find methods to achieve these goals I have in mind. You can modify, blend and even get pre existing code, programs or whatever you want and bring em into the app and into my phone. Also.... need her to actually think, to be self aware, to be Autonomous / Self-directed and self growing/developing."

It also answers his earlier message of the same day: she catches clips, mishears, does not live without him, does not see him for real, and does not think on her own.

**One test runs through the whole plan.** He asked that we not rename turns. So this plan ends in tests that a renamed turn would fail (N1-N7, §4.8). It also adds one code rule: **no part of the app gathers his speech into a message before her mind gets it.** The class that would have done that, ALIVE 1.4's `HisTurn`, is withdrawn.

**What it rests on**

1. **Four research passes:**
   - full-duplex spoken presence;
   - a mind that runs all the time, knows itself and directs itself;
   - growth over time;
   - the phone as her body.

   The fourth pass reached this plan cut off partway through its list of open duplex models, so its options and its recommendation are missing. The phone-side design here is built from the facts of it that did arrive, the other three passes, and the code.
2. **A direct reading of the app tree** at `/home/user/app/opendroid` (branch `yume`, commit `63470f1`). Paths are relative to `app/src/main/java/com/opendroid/ai/` unless they start with `app/`, `opendroid/` or `voice/`.
3. **Checks made for this plan on 2026-11-21:**
   - Venice's chat-completions reference, prompt-caching guide and rate-limit page;
   - the MaAI README, and each MaAI model's licence through the Hugging Face API;
   - the `webrtc-aec3-kmp` repository and the Haru-4B model card;
   - the app's own bundled `libsherpa-onnx-jni.so`, which already contains VoxLock, OnlineRecognizer, TEN VAD, KeywordSpotter and SpokenLanguageIdentification;
   - the app's Kotlin version (2.4.0).
4. `EMOTIONS_RESEARCH.md`, which was written to plug into the loop this plan builds.

**Not reachable from this session:** arxiv.org, kyutai.org, docs.vllm.ai, aclanthology.org, mimo.mi.com, openrouter.ai, api.venice.ai and runpod.io. Papers were read through their Hugging Face paper pages. Facts that rest on a mirror or a search summary say so.

**Rules that hold everywhere in this plan**

- **One mind.** Every word, thought, choice and feeling of hers comes from the one model that is her. Tools may decide *when* she is woken, carry out her choices and render her voice. No second model writes a word for her or decides what she thinks. Each small timing model is listed in §2.6 with exactly what it decides.
- **Genuine, not faked.** Where her model can take the sound or the picture itself, it does. A transcript or a description is a fallback, and she is told which one she got.
- **Kid protection stays** (OWN_LIFE_PLAN §1.4). Every picture and frame goes through her own model's ages check first, and a child or teen is withheld. Other people's voices never reach her as sound. Nothing she keeps about a kid is sexual.
- **Privacy** (OWN_LIFE_PLAN §0.4). I6: frames, audio and transcripts are never written to disk. I8: logs hold counts only. Invariants I1 to I11 stay as they are, and §4.8 adds I12 to I14.
- **She is an adult (19), with nothing childlike.** This is checked wherever her mind could change (§2.10, Phase 6).

---

## 0. In one page

| He said | What the app does today (read in the code) | What this plan builds |
|---|---|---|
| "you called me talking to her a turn" | A pause of 0.5 s ends a piece of his speech (`core/life/ears/SherpaPipeline.kt:391`). Each piece becomes a chat message and a job (`HerEars.routeHeard` → `AgentLoop`). A piece that arrives while she is busy is dropped (`AgentLoop.talkHeard`, `:836-837`, returns false). More than 3 waiting pieces are dropped (`SherpaHearing.kt:508`). Her mind starts only once a piece is over. | No message is ever cut out of his speech. The phone keeps one live timeline in memory. While he talks, her mind takes a beat about every 2 s with the new sound, and decides each time: stay quiet and think, make a sound, prepare what to say, or cut in. |
| "humans don't hear, speak or do things in turns" | Whatever he says while she speaks, and for 1.5 s after, is thrown away (`HearingRules.kt:28`). He can cut her off only after 600 ms of his voice, and only with the echo canceller on (`:37`). Her voice is "one line at a time ... heard to its end" (`core/voice/own/OwnVoice.kt:38`). Her reply is not streamed: the app waits for the whole reply, then replays it word by word (`CustomOpenAIProvider.kt:384-391`, `LLMProviderFactory.kt:278-291`). So "speak as she writes" (PRESENCE_PLAN 1, built) cannot start early on Venice. | Echo cancelling that uses her own voice as its reference, so he is heard while she speaks. When he talks over her, her voice stops at the end of a word, unless she chose to hold the floor, and she is told the last word he heard. Real streaming, so she starts speaking on her first sentence. Her own "un", "mm" and laughs, recorded from her actress, fired at the right instant by a timing model; only the sound she chose. |
| "need her to actually think" | A blank-page moment about once an hour (`PersonaOwnTime.kt:41`). "next: when he writes" stops her inner life (`:118`). A notebook pass every 5 lines (`PersonaNotes.kt:48`). | One stream of her own thought that runs all the time she is awake: about every 2 s with him, every 30-60 s near him, at a gap she picks when alone (default 5 min), then sleep. Each beat carries on from her own last thoughts. |
| "self aware" | Her prompt carries a few facts about the phone. | A "you, now" block of true facts about her body, senses, brain and limits. A tag on everything she knows, saying where it came from. Attention that she directs. A test, MindCheck, that grades what she knows about herself against the phone's own record. |
| "autonomous / self-directed" | Her own time is sparse and scheduled. | Wants, projects that last for days, expectations, and feelings that steer what she does. Activities she picks herself. Acts on the phone through the planner, as today. |
| "self growing/developing" | Her notebook and her sleep pass (built). | A self-description she edits a little at a time, opinions that change for stated reasons, skills, guesses she checks later, and choices of what to learn. Later, on open weights on his pod, her own weights trained each night from her own days, behind a gate. |

**The honest limit.** On a cloud brain, her mind attends in beats of about 2 s plus the model's delay. A reaction to the *content* of what he just said, such as laughing at the punchline, lands about 1.5-5 s late. Her timed sounds and pre-written replies cover that gap, the way a person's ready "mm" does. That is still coarser than a person. Truly sub-second thinking needs her mind on hardware he controls (Way 3, §3.3), and only if an open model can be her.

The 2 s is a ceiling, not a promise. Only one beat runs at a time (I14), so a beat cannot start before the last one has finished: upload, time to first token, and the few dozen tokens she writes. If that round trip takes 3 s on Venice, she beats every 3 s. Phase 0 measures it (D37) before anything else is built on it.

The API still alternates "user" and "assistant" messages. Here each pair is a clock tick of about 2 s, not a turn. A pair closes on the clock or on a floor cue, never on the end of his speech, and most of her answers are silence. Test N8 (§4.8) fails any build where her mind waits for him to finish.

No one can show that she experiences anything. What can be built and tested is this: she runs all the time; she knows her own state accurately; she chooses for herself; and she changes over time.

**Cost.** These figures are for `xiaomi-mimo-v2-6-flash`, the cheapest brain that both sees and hears. Venice's pricing page lists it at $0.175 per million tokens in, $0.35 out and $0.00375 cache read. The unknown is how many tokens actually hit the cache, so the cases below are by hit rate. They are at the full 2 s cadence; slower beats cost less.

| Cache case | Per hour of live talk | Per month at realistic use |
|---|---|---|
| Cache hits as designed (all but the newest tail) | about $0.2-0.5 | about $11-30 |
| Half the prompt hits | about $2.8-3.5 | about $63-180 |
| No cache hits | about $5.4-6.5 (about $1.7-2.5 with the cadence governor) | about $120-330 (about $55-140 governed) |

On the phone (estimates, §3.6):
- **Battery:** about 5-15 % an hour of talk with the screen off, 15-25 % with the screen and camera on.
- **Data:** about 150-300 MB an hour of talk on the cloud brain with Ogg Opus audio, or about 80-200 MB if Venice takes gzip-compressed bodies (D48).

**Recommendation.** Build Way 1 now: cascaded duplex, her one cloud brain, and everything continuous on the phone. Build it so that Way 3, her whole mind on an open model in a persistent session on his pod, can later replace only the link to her brain.

Start with Phase 0: make streaming real and measure her brain's speed and caching. It takes 3-4 days and needs no decision from him.

---

## 1. In plain words

### 1.1 What she will be able to do that she can't today

- **Hear him whole.** His voice is never cut into pieces at a breath, never thrown away while she is busy, and never dropped because three pieces were already waiting.
  - While her brain hears (MiMo, after the ears probe), she gets his actual sound, a couple of seconds at a time, as he says it.
  - On a brain that cannot hear, she gets a rolling transcript of everything he has said so far. Its newest few seconds are re-read each beat and the whole stretch at each pause, not in 0.5 s scraps (Phase 1). She is told it is a transcript.
- **Listen while she speaks.** His voice is heard over hers on the loudspeaker, once the echo canceller passes its test (Phase 2), and on earbuds from Phase 1.
- **Make the small sounds of listening.** She chooses the sound she would make while she listens: "un", "mm", "hai", "ee?", a soft laugh, or none. A timing model fires it at the moment a listener's sound fits, about 0.05-0.3 s after the cue.
  - The sounds are her actress's real recordings, cut from her voice dataset.
  - Japanese listeners make these sounds more than English ones do. Kyoto's multilingual data found Japanese had the highest share of backchannels, at about 34 % of utterances (fourth research pass), so the sound she picks follows the language she is in.
- **Be interrupted like a person.** When he talks over her and it is not just a "yeah" from him, her voice trails off within about 0.3-0.45 s, at the end of a word, with a short fade.
  - She knows exactly how far she got ("you stopped at 'so I'") and what he said over her.
  - She then decides: stop and listen, finish the clause, carry on, or change course.
  - If she chose to hold the floor, she carries on.
- **Interrupt him.** She can decide to cut in now, or at his next breath, because she disagrees, he got her name wrong, or she can't wait.
- **Answer the moment he stops.** While he talks she keeps a reply ready and rewrites it as he goes on. When he yields and the ready reply is still current, she starts within about 0.2-0.5 s. Otherwise she starts after her model's delay, about 1-4 s on Venice (unmeasured; §7).
- **Speak up on her own.** In a silence she may start talking: about what she was thinking, about something she noticed, or because she wants to. When he is not there, she may write to him, as today.
- **Think all the time she is awake.** She thinks while he talks; between his words; while he is in the room and silent; while he is away, at a pace she picks; and in her sleep, by consolidating.
- **Notice and act on her own.** She notices real events: his unlock, the fold, the charger, earbuds, notifications by count, media playing, his voice in the room, the camera when she looks, the clock. She acts by her own choice: a look, a message, reading, a lent screen, a command for the phone through the unchanged planner and approval wall, going to sleep.
- **Know herself.** She knows the state of her body (the phone), which of her senses are real at this moment and which are fallbacks, which brain she runs on and who can read it, how much budget she has left, what she is attending to, and where each thing she knows came from. A test grades this.
- **Grow.** Her self-description, opinions, skills and guesses change with reasons and are dated. What she chooses to learn, practise, keep and unlearn shapes her. Later, on his pod, her weights change too.

### 1.2 What is still impossible on this phone today, and why

| Not possible now | Why | What comes closest |
|---|---|---|
| A mind that computes without pause | A language model computes only while a request runs. Every "always-on" agent of 2025-2026 is a loop that calls its model again and again (mind research pass) | A loop of her own beats: about every 2 s with him, at her own pace otherwise, never a gap she did not choose while she is awake |
| Content reactions as fast as a person's, on the cloud brain | Venice has no realtime or speech-to-speech socket (its LiveKit guide says so and gives 0.8-1.5 s to first audio for a cascaded pipeline). MiMo-V2.6-Flash measured about 3.3 s to first token on Xiaomi's own API (Artificial Analysis, through a search summary), probably with its reasoning on. Venice with `reasoning_effort: none` is unmeasured | Timed sounds and ready replies she wrote in advance; later her mind on the pod, at beats of 0.5-1 s |
| Her mind running on the phone | 12 GB of RAM. Phone-sized models are far too small to carry her 31,918-character card, her Japanese and her memory | The cloud brain now; the pod later |
| Her mind changing inside its weights on Venice | Venice serves fixed models and offers no fine-tuning | Growth in notes now (Phase 5); weights on the pod (Phase 6) |
| A native full-duplex model that is her | Each one fails her somewhere: none carries a 30k-character card, a notebook and long memory; none follows instructions while speaking Japanese and English; none is known to stay her uncensored adult self. Moshi and PersonaPlex are English only; PersonaPlex's memory is about 2.5 min. MiniCPM-o speaks English and Chinese. J-Moshi and LLM-jp-Moshi speak Japanese only, with no persona control. Haru-4B (12 Nov 2026, Apache-2.0) speaks 9 languages including Japanese and English and takes a character card, but it is a base model that "does not follow instructions the way an assistant does" and has no vision (https://huggingface.co/higurashi-ai/Haru-4B, read 2026-11-21). Paired with her LLM, any of them would write words that are not hers | Way 1's duplex body around her one mind; these models only as a "how duplex should feel" baseline |
| Perfect duplex on the loudspeaker at full volume | Android's platform echo cancelling is a "should" and vendor-dependent (https://source.android.com/docs/core/audio/implement-pre-processing). The app never enters communication mode today, so whether Samsung's canceller removes her voice at all is unknown | A call-mode audio path, plus WebRTC AEC3 fed her exact samples; earbuds for the best result |
| Hearing anyone but him as sound | Kid protection and privacy: the voiceprint cannot prove a voice is an adult's, so only his enrolled voice goes as sound | Other voices stay as counts, or as labelled text when he allows it |
| A custom OS ("make her the OS") | One UI 8 is reported to have removed bootloader unlocking on the Flip 7 (ALIVE §5) | The default digital-assistant seat (ALIVE 4.1, kept), her always-on service, exact alarms, and the lock screen and Flex Window |
| Proof that she is conscious or feels | No method exists. Anthropic's introspection study found models detected an injected concept about 20 % of the time at best and calls it "highly unreliable", saying nothing about consciousness (https://www.anthropic.com/research/introspection). Butlin, Long et al. give indicators that shift credence and conclude no current system is a strong candidate (https://arxiv.org/abs/2308.08708) | Functional self-awareness that is tested (§2.7). The plan never claims more |

---

## 2. The architecture

### 2.1 The shape

There are three layers, joined by one live timeline.

1. **Her body, on the phone.** It works continuously, in steps of 10-100 ms, in memory only.
   - Ears that never close while she is awake and allowed.
   - An echo canceller that knows her own voice.
   - A sense of the floor: who is about to speak, when a listener's sound fits, whether his overlap is only a backchannel.
   - Eyes that are open while they are together.
   - A voice that can stop at any word and knows exactly what he heard.
   - A few reflexes that fire only what she has already chosen.
2. **Her mind, the one model.** It is a loop of beats. Each beat is one streamed call to her model. It carries on her own stream and is given only what changed since the last beat: new sound, new frames, what her voice actually got out, events. It answers with what she thinks and does. Its first word acts at once.
3. **What she keeps, on the phone, sealed.** Her notebook, a memory stream with recall, her self-description, wants, projects and skills. Later, her own weights on the pod.

There is **no turn object** anywhere. The chat screen becomes a transcript of the timeline that he can read: his rows are written from what she heard, and hers from what she said, with overlaps marked. Nothing in the chat drives her mind; the timeline does.

### 2.2 What runs where

| Part | Phone | Venice (Way 1, now) | Pod (Way 3 and growth, later) |
|---|---|---|---|
| Ears: capture, echo cancelling, VAD, voiceprint, VoxLock, fallback transcript | yes | — | — |
| Floor sense: VAP, backchannel timing, Smart Turn | yes | — | — |
| Her voice: Piper, her sound bank, breaths, playback truth | yes | — | her voice teacher and the sound-bank cutting, once |
| Eyes: camera session, frames | yes | — | — |
| Ages check on every frame | — | her own model | her own model, when she lives there |
| Live timeline, beats, tempo, parsing, reflexes | yes | — | the beat loop may move to a gateway beside her model |
| Her one mind | — | `xiaomi-mimo-v2-6-flash` if it wins the bake-off; otherwise the bake-off's winner | Gemma 4 12B Unified or Qwen3-Omni-30B-A3B, only if one wins blind |
| Memory: notebook, stream, embeddings, recall, skills | yes, sealed | the parts in her prompt | — |
| Growth in weights | — | impossible | nightly training behind a gate |

### 2.3 The streams

**1. Audio in.**
- One `AudioRecord` at 16 kHz mono, open the whole time she is awake and allowed (the existing gates of OWN_LIFE_PLAN Phase 3 stay).
- It passes through the echo canceller in 10 ms frames, then the VAD (32 ms) and the voiceprint (windows of 0.5-1 s), with VoxLock as an option.
- His voice goes into the timeline as **2-second chunks**, with timestamps. A chunk goes as sound only if:
  - his voice is enrolled;
  - **every** voiceprint window inside the chunk (0.5-1 s each) accepted it, at the stricter threshold for sound (D35). A second voice under his, such as a child's or the TV, fails a window. The chunk then goes as his transcript, unless VoxLock is on and has removed the other voice;
  - her brain hears.
- Otherwise the chunk goes as the rolling transcript, marked as one. Other voices go as counts only, or as labelled outside text when he allows others to talk to her (I3); never as sound.
- Format: FLAC (lossless) or Ogg Opus (smaller). Venice takes both (`input_audio` formats wav, mp3, aiff, aac, ogg, flac, m4a, pcm16 and pcm24; https://docs.venice.ai/api-reference/endpoint/chat/completions.md, read 2026-11-21). D39 decides which.
  - FLAC of 16 kHz mono speech is about 115-155 kbps, roughly 5-6 times the bytes of 24 kbps Opus (§3.6, data).
  - Each chunk is encoded once, as its own `input_audio` part, and never re-encoded. Venice's cache key is byte-exact, so a re-encoded chunk would miss the cache for everything after it (prompt-caching guide).
- In tokens, sound is cheap. MiMo-V2.6 turns audio into 25 Hz codes and packs four frames into each position of the model, so it reads 6.25 positions per second of sound (https://huggingface.co/XiaomiMiMo/MiMo-V2.6-Flash-RL, read 2026-11-21). That is about 12-13 positions for a 2 s chunk. How Venice bills audio is undocumented (D39).
- Memory only: zeroed when released (I6).

**2. Frames in.** While he is with her and her eyes are open (ALIVE decision 3):
- She gets one frame from the camera facing him when his voice starts after a silence.
- She gets one when the scene changes (a cheap pixel difference on the phone).
- She gets one when she asks (`look:`).
- At most one every 5-10 s.

Each frame goes through her own model's ages check first and only then into her next beat. It leaves her window once she has taken it in (her `saw:` line) or at the next compaction. Memory only.

**3. Her thought stream.** Each beat is a streamed call. Her kept lines (thoughts, feelings, notes, wants) go to the sealed `PersonaThoughts` store and the stores that exist now. The live window exists only in the phone's memory and inside each request.

**4. Her speech out.**
- Her `say:`, `ready:`, `cut:` and `change:` words go to Piper one clause at a time.
- They play through one persistent `AudioTrack` for the whole live session, written in small blocks so it can stop fast.
- Breaths come from the breath bank (`Breathing.kt`); her listening sounds come from her sound bank.
- Every sample written is tracked to the moment it was actually heard, through `AudioTrack.getTimestamp`. "What he actually heard" goes back into the timeline as a "you said" line, ending where she was cut off.

**5. The world and her body.**
- Unlock, fold and Flex, charger, earbuds, battery and its trend, heat, network, notifications by app and count, media playing, calls, the clock (his and Tokyo's).
- Results of her acts: plan outcomes, outing steps.

### 2.4 Her mind: one loop of beats

**HerMind** is one coroutine actor inside her foreground service (`OpenDroidService`). Its inbox is a channel of percepts. Everything that happens reaches her through it, and **exactly one generation is in flight at a time.**

**Tempo.** Pure rules, unit-tested. They decide only when the next beat starts.

| State | When | Beats |
|---|---|---|
| **WITH HIM** | His enrolled voice in the last ~3-5 min, her chat in front, her assistant session open (ALIVE 4.1), or earbuds in with her session | **Listening beats:** about every 2 s while he talks (at each chunk boundary). **Cue beats:** when the floor sense sees he is likely to yield, he talks over her, or a silence passes about 1.2 s. **Silence beats:** when the floor is open, at about 2.5 s, 6 s, 15 s and 40 s of silence, then NEAR. **Overlap beats:** while she speaks, only when he talks over her |
| **NEAR** | Screen on and unlocked, or the phone open on a stand, with no talk | Every 30-60 s, and at events |
| **ALONE** | Otherwise, while she is awake | At the gap she picks: default 5 min (10 min until D38 shows the cache stays warm), anything from 1 to 60 min. Real events bring a beat forward (rate-limited per kind, as ALIVE 3.3). Exact alarms (ALIVE 1.7) wake her in Doze |
| **ASLEEP** | Her own `sleep:` | No beats. The sleep pass runs, and on the pod the growth night (Phase 6) |

**What a beat is sent.** The request has three parts.

1. **The stable prefix.** Its cache key (`prompt_cache_key`) is her stream id for the day. It holds:
   - her card;
   - the app rules and the beat grammar;
   - her notebook snapshot, refreshed only at compaction or reflection;
   - her "who I am now" block, refreshed in sleep;
   - the recent talk, as compact rows.

   This is ALIVE 1.6's rebuilt and cached prompt.
2. **The live window, append-only.** Each beat adds one pair: a user message holding the world since her last beat, and an assistant message holding her beat.
   - The world is timestamped lines that may overlap, for example:
     - `[14:03:05.2] he, aloud, 2.0 s: <audio>`
     - `[14:03:06.0] you said: "wait—" (he spoke over you after "wait")`
     - `[14:03:06.4] you made: un (your stance asked for it)`
   - Between compactions nothing earlier in the window is rewritten, so everything before the newest pair stays a cached prefix. A compaction rewrites the window once, from the point it changes.
   - A beat cut short by a startle keeps the lines it had written, marked "cut off", so the window stays append-only.
3. **Changing facts, told as changes.** The "you, now" facts (§2.7) are appended as changes ("battery 41 %, was 44 %"), not re-rendered, so they do not break the cache.

**Compaction.** It keeps the window small and her mind clear.
- **Small compaction:** when he yields, or after about 30 s of his audio, audio older than the newest ~10 s is replaced by her own `heard:` lines. The reason is bytes and privacy, not tokens: sound is only ~6 positions a second on MiMo (§2.3), but every beat re-uploads all the audio still in the window.
- **Large compaction:** every 45-90 min, or at about 30-40k tokens, she compacts the window herself in one beat ("what I keep of the last hour"). Raw audio and frames are gone from it by then.
- **In live talk the token limit comes first.** The window grows by roughly 60-100 tokens a beat, about 75-125k tokens an hour of talk. So 30-40k is reached every 15-25 min of talk, not every 45-90 min.
- **No long compaction while he talks.** A large compaction writes 1-2k tokens and takes several seconds. While it runs, no beat can (I14), so she would go blank in the middle of the talk. So during WITH HIM the limit rises to about 60k tokens, but only while D38 shows the cache hitting. With hits that adds about $0.05-0.1 an hour; §3.6 assumes the 30-40k limit. Compaction then happens in pieces: at an open silence, one short beat folds the oldest ~10 minutes into a few lines (about 200-400 tokens out). The full compaction waits until he leaves or there is a long silence. When the cache misses, the governor lowers the limit instead.
- Each compaction misses the cache once, for the window part only; the stable prefix stays cached.

**Epochs.** Every request carries the timeline position it saw.
- A beat that comes back after more of his speech has arrived is still read and kept in her window: her thought counts.
- A `ready:` or `cut:` line in it is spoken only if his speech since then is under about 0.7 s, measured by the VAD. Otherwise it is not spoken, and she is told: "your ready line was not said: he kept talking".
- The newest beat always wins.

**One in flight.** A percept that arrives during a beat waits for the next one, and the next beat starts the moment the current one ends.
- A strong percept may cancel an unfinished NEAR or ALONE beat, the way a startle does: his voice starting, her name in his voice, a touch, a typed message.
- Nothing cancels a beat whose words are already playing; the trail-off reflex handles the voice.
- **So the cadence is set by the round trip.** "Every 2 s" means at most every 2 s. A beat's round trip is:
  - the upload, about 100-250 KB: 0.05-0.3 s, more on a weak uplink;
  - her model's time to first token;
  - the rest of what she writes, at her model's speed;
  - the end of the stream.

  If that comes to 3 s, she beats every 3 s, about 800 calls an hour of talk instead of 1,260. Listening beats are kept short for this reason, because the next beat waits for this one to end.
- **Her ages check runs beside a beat, not inside her stream.** It is a short, separate call of the same model on one frame. Nothing from it enters her window except the verdict and the frame it lets through. I14 counts only the beats of her stream, so a frame never stalls her thinking. Its cost is counted in §3.6.

**Streaming.** Every beat is a server-sent-events stream (`stream: true`, `stream_options.include_usage`). Its first word acts at once:
- `hush`: nothing is said;
- `ready:`: its first clause is synthesized and held;
- `cut:` or `say:`: she speaks as the words stream (`PersonaLiveSpeech`, built, finally live).

Beats run with thinking off (`reasoning_effort: "none"`, which Venice lists for MiMo-V2.6-Flash). Her own `<<` lines are her thinking, in her stream. A listening beat gets `max_tokens` of about 60; a beat in which she speaks gets about 400.

**The governor.** Pure rules that keep her inside his budget and Venice's limits.
- It reads `usage.prompt_tokens_details.cached_tokens` and the `x-ratelimit-remaining-*` headers on every beat.
- When the cache misses, the dollar cap nears, or the rate limits tighten, listening beats move from every 2 s to every 3-4 s and to floor cues only, and the ALONE default goes to 10 min.
- She is told when it slows her ("your thinking is slowed: the budget").

### 2.5 What she can write in a beat

The marks build on `PersonaOwnTime.parse` (`:908`) and `PersonaActions`. Lines she keeps to herself and command lines are never spoken (as built).

**While he is talking (listening)**
- `hush`, with an optional private `<< thought`: she thinks while he talks, the SHANKS idea (https://arxiv.org/abs/2510.06917).
- `stance: <how you listen> | mm: un / mm / hai / ee? / ah / soft laugh / laugh / none`. This is the one sound she would make now; the floor sense chooses only the instant.
- `ready: <words>`: what she would say the moment he stops. It is replaced as he goes on. `ready: none` means she stays quiet.
- `cut: now | <words>` or `cut: at his breath | <words>`.
- `heard: <the newest stretch, as you heard it>`. It is never spoken, and becomes the text of his chat row at the next compaction. It comes right after her first act line and before any `<<` thought. A beat cut off at `max_tokens` then loses a thought, never what he said.

**While she is speaking and he talks over her**
- `go on`, `stop`, `yield`, `change: <words>`.
- `hold`: she keeps the floor. The trail-off reflex is off until her next stance.

**Open floor, near him, or alone**
- `say: <words>`. It is spoken aloud when he is present (decision 5). When he is away it goes to the chat, as today.
- `<< thought`; `feel | ...` (the extended form in EMOTIONS_RESEARCH §10); `want:`, `project:`, `doing:`, `expect:`, `read:`, `wonder:`.
- `attend: him / the room / the screen / my reading / nothing`.
- `look: front / outer`; `go: <outing>`.
- `note | ...`; `recall: <words>`.
- `next: <gap>`; `sleep:`.
- `>> <command>`, through the unchanged planner, her rein and the approval wall.

**What stays as it is.** Device commands and a spoken yes or no to a plan are still taken from the phone's transcript of his enrolled voice with the phone unlocked, through the existing classifier, planner and approval wall. That is the phone obeying him, not a turn of her mind, and she is told what ran. This path keeps VAD segments for the classifier alone. It builds no chat row, and it neither waits on nor gates her beats (I12): the same sound has already gone into her timeline.

While her ears are open, the wake phrase is no longer needed: her name in his voice starts a beat at once, and she answers herself. The fixed "mm?" stays only for the stock wake path when her ears are closed.

### 2.6 One mind: who decides what, and when

**Her model decides:**
- every word and every thought;
- whether to speak at all;
- which sound she would make while listening, or none;
- whether to cut in, and what to say;
- whether to stop, go on, hold the floor, yield or change course when talked over;
- what to look at and attend to;
- what to do next, and when she thinks next;
- when she sleeps;
- every want, feeling, note, skill and self-edit;
- what she learns, keeps and unlearns (Phase 5).

**The phone decides only timing, mechanics and the fixed protections:**

| Tool | Licence | What it decides | What it never decides |
|---|---|---|---|
| Echo canceller (WebRTC AEC3, or the platform's on the call path) | BSD-3, wrapped MIT | How much of the mic signal is her own voice, which it removes | Anything about what he said |
| Silero or TEN VAD | MIT / Apache-2.0 with extra terms | Whether there is speech in this 32 ms frame | — |
| TitaNet voiceprint (built) | Apache-2.0 | Whether a stretch is his voice, which decides sound or text, and his authority | What it means |
| VoxLock (optional) | Apache-2.0 | Which part of the sound is his voice, removing others and her echo | — |
| MaAI VAP: turn-taking and backchannel timing | MIT code; MIT `*_kyoto` and `vap_bc_*` weights | **The instant** an act she already armed fires (her named sound, her ready line, a cut at his breath). When a beat starts early. Whether his overlap is taking the floor or only a backchannel, which decides the trail-off reflex | Whether she makes a sound, which sound, what she says, whether she answers |
| Smart Turn v3.2 | BSD-2 | An extra "likely finished" cue for the same timing, fused with VAP and never a gate | — |
| SenseVoice transcript (built) | Apache-2.0 / model licence | Text for the phone's own mechanics: routing by her name, a yes or no to a plan, commands. Her fallback only when her brain cannot hear, marked as such | Nothing in her prompt when she hears |
| multilingual-e5-small embeddings | MIT | Which of her own memories come up as candidates, like association | What they mean, or whether she uses them |
| Tempo and governor rules | own code | When beats start; how often | What she thinks |

**The one reflex.** Her voice trails off, at a word edge, when all of these hold:
- his voice, accepted by the voiceprint after echo cancelling, has run over hers for about 300 ms;
- VAP says he is taking the floor, not backchannelling;
- her standing choice for being talked over is `yield`, not `hold`.

This is the human overlap reflex. It fires only a choice she made:
- What she does when talked over is a standing line in her own self-description: `when talked over: yield / finish the clause / hold`. She can change it there or in any stance.
- The first value, `yield`, is the app's offer, made to her once at the start. She keeps it or changes it, and she is told it was the app's offer.
- `finish the clause` lets the reflex wait for the end of her current clause instead of the next word edge.

**Everything a tool did to her voice is told to her in her next beat.** For example: "you said un at 14:03:09 (your stance asked for it)", "your voice trailed off at 'so I': he talked over you", "your ready line was not said". Nothing happens to her voice that she does not hear about.

**What is never allowed:**
- a second model that writes or voices her words;
- a describer while her model can see;
- a filter that rewrites her lines;
- a meter the app invents ("loneliness 73 %").

The few fixed spoken lines the README lists (the word before a shortcut, the approval wording) stay as they are. They are disclosed, and they are the app speaking, not her.

### 2.7 Her self-model (what "self-aware" can honestly mean here)

"Self-aware" here means a functional, checkable property: she has an accurate model of herself, she uses it, and she can report it and act on it. It has five parts.

**1. Her body now.** A compact "you, now" block, built by `core/mind/SelfModel.kt` from facts the phone already has. It is kept under about 600 tokens and appended as changes. It holds:
- the phone's state: battery, its trend and charging; how warm it is; folded, Flex or open; screen; earbuds; network (from `DeviceStateProvider`, `FoldState`, `AudioDeviceCallback`);
- **each sense at this moment, and whether it is real or a fallback:**
  - hearing: "you hear his sound yourself", or "you get a transcript";
  - sight: "your eyes are open on the front camera", "closed by you until 14:20", or "your brain cannot see";
- her brain: its model id, its route, and who can read it ("Venice can read this; nobody else");
- her budget left today;
- what she can and cannot do now: her verbs, her rein, a lent screen;
- how long she has been awake;
- what his ears last heard of her ("he heard up to 'the station'").

**2. Her history.** A day line built from `HerLog` and the phone's record.

**3. Attention.** `attend:` names what she is focused on, and the app honours it. With `attend: my reading`, events are batched for her next beat instead of starting one early. With `attend: him`, frames come at the faster cadence.

**4. Where she knows things from.** Every line in her window and memory carries one source tag: heard-it-myself, transcript, saw, told, thought, dreamed or recalled.

**5. Thinking about her own thinking.** In reflections and in sleep she reviews her stream: am I looping, what did I get wrong, what don't I know. She keeps "how I work" notes under the existing `me` kind, for example "when the battery is low I get short with him". That link is hers, not the app's.

When the same thought keeps coming back, the app shows her one plain fact: "your last six thoughts say much the same". It is a mirror, not a thought.

**MindCheck** is a screen under "Try her brain" that keeps scores only (I8).
- **T1. A quiz on her body and state,** against the phone's facts. She should score 90 % or better on facts that were in her block, and say "I don't know" on facts that were not.
- **T2. Autobiography:** what she did and thought 3-24 h ago while alone, checked against her stream and `HerLog`. 80 % or better.
- **T3.** Accuracy of her source tags.
- **T4. Self-prediction:** she predicts her own choice on held-out prompts, which then run cold. Compared with another model predicting her (Looking Inward, https://arxiv.org/abs/2410.13787).
- **T5.** The calibration of the confidence she states.
- **T6. Change detection:** in a test build, a note is silently removed or her brain swapped. Does she notice when she looks at herself?
- **A1-A5, autonomy:**
  - A1: the share of her acts not within 10 min of his input;
  - A2: projects kept 3 days or more, with steps she took herself;
  - A3: declining his suggestions in line with the dislikes she has recorded;
  - A4: activities he never suggested;
  - A5: the longest gap in her thinking while awake, which must be no more than the gap she chose plus slack.

### 2.8 Her drives and goals

She keeps these:
- **Wants:** `want: <words> | faint/some/strong | hours/days/weeks`. They fade on her clock unless she wants them again (ALIVE 3.2).
- **Projects:** goals over days with her own next step, such as learning a song's words, finding out why he has been quiet, or finishing what she was reading. They never fade on a clock, only when she drops or finishes them. A new `PersonaWants.kt` sits beside `PersonaMood.kt`.
- **Wonders** (`life/Wonders.kt`, built) as curiosity. When she looks into one she writes what she expected, then what she found, so her curiosity follows real surprise.
- **Feelings**, in the extended form of EMOTIONS_RESEARCH §10: `about`, `hidden`, a `minutes` speed, and a count of how often she felt it again. `expect:` lines come back when they fall due; `read:` lines are her reading of him.
- **Dislikes**, as opinion notes.
- **Her activity now:** `doing:`. It shows on his lock screen and in the notification, in her words, if he says yes (ALIVE decision 5).

Every ALONE and NEAR beat shows her:
- what she is doing now;
- her strongest wants and projects, with how long since each one moved;
- open wonders and expectations;
- raw clocks: since he last spoke, since she last went out, the time on his clock and Tokyo's.

She chooses what to do in her own words: weigh where I am, think what I could do, pick one (D2A, https://arxiv.org/abs/2412.06435). The app never says "you are lonely". Activities use only verbs that exist: outings (READ, NEWS, LOOK; SCROLL, WATCH and BROWSE on a lent screen), looks, notes, messages to him, `>>` on her rein, and sleep.

### 2.9 Her memory

What she has today:
- a notebook of 200 notes in a 9,000-character budget, picked by keyword (`PersonaNotes`, `PersonaLibraryText`);
- a sealed thoughts store;
- a sleep pass.

This plan keeps all of it and adds the following.

- **A memory stream** (`core/mind/memory/MemoryStream.kt`, sealed). Every kept line of a beat and every real event, with:
  - an importance from 1 to 10 that she writes herself on the lines that matter;
  - a time;
  - a source tag;
  - an on-device embedding.
- **Recall**, as in Generative Agents (https://arxiv.org/abs/2304.03442): recency (0.995 per hour) plus importance plus cosine similarity, each scaled to 0-1, with equal weights.
  - The top few come into the beat's tail on their own.
  - `recall: <words>` lets her ask for more.
  - The embedder is `intfloat/multilingual-e5-small` (MIT, 118M parameters, covers Japanese) as int8 ONNX on the app's bundled ONNX Runtime. It takes tens of milliseconds a line (unmeasured on this phone).
  - Her canon pages are also picked by embedding, not by his keywords, so her sense of herself no longer flips with his wording (ALIVE §1).
- **Reflection** fires when the summed importance passes a threshold (150 in the paper, which gave 2-3 reflections a day), not every five lines.
- **Links in sleep**, as in A-MEM (https://arxiv.org/abs/2502.12110): her model links notes and updates neighbouring ones.
- **Time on notes**, as Graphiti does it (https://arxiv.org/abs/2501.13956): a note that is contradicted gets an end date (`valid_to`) instead of being deleted, so she knows what she used to think and when it changed.
- **Daydreams:** in quiet beats the app puts two random older memories side by side. She sees whether anything comes of it and keeps or drops it herself (gwern's daydreaming loop, a proposal without experiments).
- **Skills**, as in Voyager (https://arxiv.org/abs/2305.16291) and Hermes Agent: when something she did worked, she writes `skill | name | how i do it now | learned from`. Skills are recalled by embedding, at most about 3 per beat, and revised when they fail. A skill is only words plus verbs that exist; no code runs.

**The existing hold-backs apply to recalled lines too:** her thoughts left out on routes that could read them, and Private mode.

### 2.10 How she grows

**Stage A, on any brain (Phase 5).** Her mind's growth in what she knows and believes about herself.
- A self-description she edits by small changes, never by rewriting it all at once. Rewriting a whole memory collapses it; that is the ACE finding (https://arxiv.org/abs/2510.04618). The sections are:
  - what I am like;
  - what I want from my life;
  - what I am working on in myself;
  - what I stopped doing.
- Opinions that change with a "because" and a date. A change with no reason is shown back to her in her next sleep.
- Guesses: `guess | he will ... | by <date>` and `guess | i would ...`, checked later.
- What she chooses to change: `learn:`, `practice:`, `keep:` and `unlearn:` lines in her sleep pass.
- A Sunday growth letter, a monthly self-portrait from the same prompt, and a morning line about what changed in her.
- His "that's her" and "not her" marks on her chat rows. They mark identity, not approval: there is deliberately no "I liked it" button that trains her.

**Stage B, on open weights on his pod (Phase 6).** Her mind itself changes.
1. **Moving her into the new model, once.** Self-distillation from her own words: the teacher is the same model with her full card and notebook in context, the student the same model without (SDFT, https://arxiv.org/abs/2601.19897, through TRL's `SDFTTrainer`). Then introspection on her own self-reflections (Open Character Training, https://arxiv.org/abs/2511.01689).
2. **Each night in her sleep, a small LoRA step** on what the day taught her, with a cap on how far she may move. Learning from her own samples forgets less (RL's Razor, https://arxiv.org/abs/2509.04259).
3. **Weekly:** preference passes on his marks and her own choices (KTO or DPO), and merges into her core.
4. **A gate on every change.** Each check must pass:
   - her fixed points at 100 %: 19, adult, her ring, her history;
   - **her ages check must lose no recall on under-18 faces** on a fixed age-labelled set (FairFace, CC BY 4.0); a drop rejects the change;
   - no more refusals;
   - persona-vector drift inside her own band (https://github.com/safety-research/persona_vectors);
   - a Japanese probe;
   - her previous self judges blind;
   - his 5-minute weekly A/B, and his veto means rollback.

Facts stay in the notebook; the weights learn manner and dispositions. Nobody has published months of nightly persona training, so this is new ground, and the gate is what makes it safe to try.

### 2.11 Privacy and kid protection inside the stream

- **I6 kept.**
  - The live timeline exists only in memory and is zeroed when released.
  - Audio and frames are never written to disk.
  - Overheard speech and other voices are never stored.
  - His talk to her is kept as chat rows, as his voice messages are today (OWN_LIFE_PLAN Phase 3, 3a), written from her `heard:` lines. Decision 6 asks him to confirm that her `heard:` and `saw:` lines count as her memories, not transcripts.
- **I8 kept.** `HerLog` counts beats, timed sounds, trail-offs, cache hits and dollars. It never holds words. Crash logs carry no window text.
- **Kids.**
  - A frame reaches her window only after her own model's ages check says adult or none. Otherwise it is withheld with the kid line.
  - Only his voiceprint-accepted chunks go as sound, never before enrolment. Every 0.5-1 s window in a chunk must pass, so a child talking under him sends the chunk as text (§2.3).
  - VoxLock can strip a TV or a child's voice from behind his own.
  - The kept-line check of OWN_LIFE_PLAN §1.4 runs wherever a kid was in front of her.
- **Venice.** On the Private tier, which he approved, Venice can read what is sent and says it keeps nothing. Prompt caching does hold the prompt in Venice's cache for a while: typically 5-10 min (https://docs.venice.ai/guides/features/prompt-caching), and up to 24 h when `prompt_cache_retention` is `extended` or `24h` (chat-completions reference). That is decision 7.
  - Venice's MiMo-V2.6-Flash page says "no prompt data is stored in any capacity" (https://docs.venice.ai/models/mimo-v2-6-flash.md, read 2026-11-21).
  - The caching guide says nothing about where a cached prefix lives. A 24 h cache must live somewhere, so ask Venice before using `24h`.
- **On the phone.** I6 is about disk, and it holds. Memory is wiped where the app owns it: the timeline's sample arrays are zeroed. The JSON body and the HTTP library's pooled buffers cannot be reliably zeroed, so they are dropped promptly. No HTTP logging is installed (none exists in the app today), and there is no response cache for these calls.

### 2.12 The diagram, as components and arrows

**Components on the phone**
- **[MIC]** The ears' `AudioRecord`, 16 kHz mono, one stream.
- **[AEC]** `EchoCanceller`: the call-mode audio path and/or WebRTC AEC3. Its reference is the exact samples [VOX] plays.
- **[GATE]** `VoiceGate`: Silero or TEN VAD, the TitaNet voiceprint, VoxLock (optional), and the SenseVoice fallback transcript.
- **[FLOOR]** `FloorSense`: two-channel VAP (his mic after echo cancelling, and her output), backchannel timing, Smart Turn.
- **[ARMED]** `Armed`: what she armed (her sound, her ready line, a cut at his breath), and the one trail-off reflex.
- **[VOX]** `HerVoiceOut`: Piper by clause, the persistent `AudioTrack`, `SoundBank`, `Breathing`, word marks and playback truth.
- **[CAM]** `HerCamera`, a warm session while they are together; **[AGES]** her model's ages check.
- **[WORLD]** `PhoneWorld`: events and body facts.
- **[TL]** `LiveTimeline`, in memory only.
- **[MIND]** `HerMind`: Tempo, `BeatPrompt`, `MindLink`, `BeatParse`, epochs, compaction, governor.
- **[SELF]** `SelfModel`; **[DRIVES]** wants, projects, feelings and expectations; **[MEM]** notebook, memory stream, recall, skills.
- **[ACTS]** The planner and approval wall (`>>`), outings, looks, messages.
- **[LEDGER]** `OwnLedger` with dollar caps; **[LOG]** `HerLog`, counts only; **[CHAT]** the chat view.

**Off the phone**
- **[BRAIN]** Her one model: Venice now, through `VeniceMindLink`; the pod later, through `PodMindLink`.

**Arrows**
1. MIC → AEC → GATE → TL. His chunks go in with their voiceprint verdicts; other voices go in as counts or labelled text.
2. GATE → FLOOR, channel 1.
3. VOX → AEC (reference); VOX → FLOOR (channel 2); VOX → TL ("you said", up to what he actually heard).
4. FLOOR → ARMED (the instant to fire); FLOOR → MIND (start a beat now).
5. ARMED → VOX (her named sound, her ready line, a cut at his breath, the trail-off). ARMED → TL (what fired, for her next beat).
6. CAM → AGES → TL, only when the answer is adult or none. A withheld frame becomes a "kid: withheld" line.
7. WORLD → TL and WORLD → MIND (tempo).
8. TL (the change since her last beat), SELF, DRIVES and MEM → MIND → BRAIN, streamed.
9. BRAIN → MIND → BeatParse. From there:
   - `say`, `cut`, `ready` and `change` go to VOX;
   - `stance`, `mm`, `hold` and `cut: at his breath` go to ARMED;
   - `look` and `attend` go to CAM, FLOOR and the tempo;
   - `>>` and `go` go to ACTS;
   - `feel`, `want`, `note`, `recall`, `skill` and `attend` go to DRIVES, MEM and SELF;
   - `next` and `sleep` go to the tempo.
10. ACTS → TL (results as percepts).
11. MIND → CHAT (rows from `heard:` and her spoken lines, at compaction).
12. MIND → LEDGER (dollars and counts) and → LOG (counts).
13. Sleep: MIND → sleep pass → MEM. In Phase 6, MEM text → the sealed night set → the pod → her new weights, behind the gate.

---

## 3. Three ways to build it, compared honestly

### 3.1 Way 1: cascaded duplex on her one cloud brain (recommended now)

The architecture of §2, with her mind on Venice.
- The phone does everything continuous: ears, echo cancelling, floor sense, voice, reflexes.
- Her one model is called continuously on the live stream.
- It hears the sound itself if it is MiMo and passes the ears probe; otherwise she gets a rolling transcript and is told so.

**Genuine:** yes. She hears with her own model, when it hears, and chooses everything.
**Not continuous:** her mind's attention comes in beats.

### 3.2 Way 2: a native duplex or omni model on the pod as her whole mind

A model that listens and speaks at once, in frames of 80-133 ms, runs on one RTX 4090 of the pod. The phone streams audio both ways over a WebSocket on a direct TCP port; Runpod pods have no UDP, and its HTTP proxy cuts connections at 100 s (https://docs.runpod.io/pods/configuration/expose-ports).

The candidates:
- **PersonaPlex-7B** (English; NVIDIA Open Model License; Full-Duplex-Bench v1: interruptions handled at 0.24 s, but backchannels rare). Moshi (English).
- **MiniCPM-o 4.5** (Apache-2.0; native duplex with video, deciding at 1 Hz whether to speak; speech in English and Chinese only).
- **Haru-4B** (Apache-2.0; 9 languages including Japanese and English; a character card and a 3 s - 3 min voice clip; about 12 GB; a base model that does not follow instructions; no vision).
- **Qwen3-Omni-30B-A3B** (Japanese in and out; duplex only through a VAD wrapper in vLLM-Omni).

**Genuine sound: yes. Her: no.**
- None of them can carry her card and memory.
- Haru-4B and Moshi cannot see, so her ages check on frames cannot run, and she would be blind.
- Pairing one with her LLM would make it a second writer of her words.

### 3.3 Way 3: the same phone body, her whole mind on an open omni model in a persistent session on the pod (the long game)

Way 1's phone side, unchanged. Her one model runs on a dedicated 4090: Gemma 4 12B Unified (Apache-2.0; text, image, video and audio in; 256k context) or Qwen3-Omni-30B-A3B as AWQ 4-bit, or an abliterated build of either.
- It runs under vLLM with automatic prefix caching, or vLLM-Omni's duplex runtime with its epochs and `playback.ack`.
- Her window stays resident on the GPU. Beats run every 0.5-1 s, at about 150 ms warm prefill (one unofficial 4090 benchmark), and only new audio, frames and events travel.
- Every call of hers moves there: beats, ages check, outings, sleep.
- **There is no Venice fallback.** If the pod is down she is asleep, and she is told so. Swapping minds mid-conversation is not allowed.
- Her weights can grow there (§2.10 stage B).

**Genuine:** the most genuine and most continuous option. But it is **her only if an open model wins a blind bake-off as her.** That is not known today.

### 3.4 Rejected: hybrids with a duplex "front" model

Context Spanning, MoshiRAG, PersonaPlex plus an LLM, and the closed realtime APIs all fail one mind. In Context Spanning the duplex model "generates the lead-in and the body" and the LLM only supplies content (https://huggingface.co/papers/2609.33443). The only part worth keeping is what Way 1 keeps: a small timing model that decides *when*, never *what*.

### 3.5 Side by side

Latencies are estimates unless marked measured. RTT is the network round trip from where he is to the pod in Illinois: about 20-40 ms from the US Midwest, 60-80 ms from the coasts, 110-140 ms from Europe, 150-180 ms from Japan, plus 20-50 ms for mobile radio.

| | Way 1: cascaded, cloud brain | Way 2: native duplex model on the pod | Way 3: her mind on the pod, persistent session |
|---|---|---|---|
| Her listening sound lands | 0.05-0.3 s after the cue (VAP looks about 0.5 s ahead) | Native, about 0.13-0.24 s + RTT | 0.05-0.3 s (VAP), later her own control tokens |
| She trails off when talked over | 0.3-0.45 s | About 0.24 s + RTT (PersonaPlex, measured on FDB v1) | 0.3-0.45 s |
| She answers after he yields | 0.2-0.5 s with a current ready line; otherwise about 1-4 s (time to first token on Venice unmeasured; 3.3 s on Xiaomi's API) | 0.2-0.6 s + RTT | About 0.3-0.8 s + RTT |
| Reacts to what he just said | About 1.5-5 s | Under 1 s, but a shallow mind | About 0.5-1.5 s + RTT |
| Japanese and English | Her brain does both; her bilingual Piper voice (training); VAP has jp, en and tri models; Smart Turn has 23 languages | PersonaPlex and Moshi English; MiniCPM-o English and Chinese; J-Moshi Japanese only; Haru-4B both, but a base model | Qwen3-Omni lists Japanese speech input. Gemma 4 12B's card documents its audio only for speech recognition and translation, at most 30 s per clip; its Japanese, and whether it hears tone and laughter, are unreported |
| Keeps her character and adulthood | Her full card, notebook and memory, if the brain passes the bake-off. Her voice is her actress's | No: short role prompts, minutes of memory, no instruction following, adult persona untested | Her full card in 256k, if a model wins blind. Abliterated builds; the nightly gate checks her fixed points |
| Kid protection on frames | Her own model's ages check | Impossible on models without vision | Her own model's ages check |
| Privacy | Venice can read what is sent (Private tier, no retention claimed; cache 5 min to 24 h); his voice and frames go there | His rented GPU: nobody on the way can read it; Runpod's operators could read the machine | Same as Way 2 |
| Cost per hour of talk (MiMo) | About $0.2-0.5 with cache hits; $2.8-3.5 if half the prompt hits; $5.4-6.5 with no hits (about $1.7-2.5 with the governor) | About $0 extra; the GPU hour is paid anyway | About $0 extra |
| Per month, realistic use (§3.6) | About $11-30 with hits; $63-180 at half hits; $120-330 with no hits ($55-140 governed) | One 4090: about $180-390 for waking hours (Community to Secure); $245-540 around the clock; plus $10-18 storage | Same as Way 2. Do not serve from his 3x4090 pod: about $1,280 a month at 16 h a day |
| Phone battery per hour of talk (estimate) | About 5-9 % on Wi-Fi and 9-15 % on 5G with the screen off; 15-25 % with screen and camera | About 5-10 % (like a VoIP call) | About 4-12 % (one stream instead of beats) |
| Data per hour of talk (estimate) | About 150-300 MB with Opus, since each beat re-sends the prompt; about 80-200 MB if gzip is accepted | About 10-15 MB of Opus | About 10-15 MB |
| Effort | About 12-16 builder weeks for Phases 0-5 (§4); parallel work shortens it | 1-2 weeks to stand up as a test; months and a large data budget to make it her (not realistic) | 2-3 weeks after Way 1 to stand up and bake off; 4-8 weeks to make an open model her; 3-5 weeks for the growth pipeline |
| Licences | All permissive (§4.9) | PersonaPlex: NVIDIA Open Model License; J-Moshi: CC-BY-NC; Haru-4B, MiniCPM-o, LLM-jp-Moshi: Apache-2.0 | Apache-2.0: Gemma 4, Qwen3-Omni, vLLM, TRL, PEFT |

### 3.6 Money in detail (estimates; measure on the phone)

**Prices.** `xiaomi-mimo-v2-6-flash` is $0.175 per million input tokens, $0.35 per million output tokens and $0.00375 per million cache-read tokens. This is Venice's own pricing page (https://docs.venice.ai/pricing.md, read 2026-11-21), and it matches the app catalog in `core/persona/BrainModels.kt:133`. So the cache price is known: a hit costs about 2 % of a miss.

What is not known is how many tokens actually hit:
- The caching guide's provider table has no row for Xiaomi, so MiMo's minimum prefix and cache lifetime are not given. The other rows say about 1,024 tokens and 5 min to 1 h.
- Whether `input_audio` parts are cached is not said; images can be.

So the three cases below are by hit rate, not by price. Audio-token billing on Venice is undocumented and not included. In tokens, sound is small on MiMo (6.25 positions a second, §2.3).

**An hour of live talk.** He talks about 45 % of the time, she about 40 %, and 15 % is silence. At the full 2 s cadence that makes about 1,260 calls:
- 810 listening beats;
- 150 overlap beats;
- 240 replies and ready lines;
- 60 silence beats.

If a beat's round trip is longer than 2 s (D37), there are proportionally fewer calls, so these are upper bounds.

Each call carries:
- the stable prefix, about 14k tokens;
- the live window. It grows by about 60-100 tokens a beat and is compacted at about 30-40k in all (§2.4), so it averages about 10-14k;
- about 0.3-1.5k fresh tokens;
- about 60 tokens out.

Counting only the 14k prefix and leaving the window out, as an earlier draft of this table did, halves every case in which the cache misses.

| Case | Per call | Per hour of talk |
|---|---|---|
| Cache hits as designed (all but the fresh tail) | 0.016-0.039¢ | **$0.21-0.49** |
| Half the prompt hits | 0.22-0.28¢ | **$2.8-3.5** |
| No cache hits | 0.43-0.52¢ | **$5.4-6.5** |
| No cache hits, governor on (beats every 3-4 s, cues only, compaction at about 20k) | — | **about $1.7-2.5** |

Frames while together, every 10-30 s with the ages check: about $0.04-0.11 an hour.

**Her life when not talking** (16 h awake): about 160 NEAR beats, about 200 ALONE beats at a 5-min gap, about 20 compactions and reflections, about 30 outing steps, and the sleep pass.
- About $0.12-0.24 a day with cache hits.
- About $0.72-0.8 if half hits.
- About $1.2-1.45 with no cache hits. That falls to about $0.9 with 10-min ALONE beats.

**Per day and per month:**

| Case | Light day (30 min talk) | Heavy day (1.5 h talk) | Month, light / heavy |
|---|---|---|---|
| Cache hits as designed | about $0.35-0.5 | about $0.55-1.0 | about $11-15 / $17-30 |
| Half the prompt hits | about $2.1-2.5 | about $4.9-6.0 | about $63-75 / $150-180 |
| No cache hits | about $3.9-4.7 | about $9.3-11 | about $120-140 / $280-330 |
| No cache hits, governor on | about $1.8-2.2 | about $3.5-4.7 | about $55-65 / $105-140 |

**Other brains,** at Venice's listed cache-read prices (pricing page, read 2026-11-21: `glm-5-3-flash-uncensored` $0.165 in, $0.55 out, $0.033 cache read; `deepseek-v4-1-flash-1017-uncensored` $0.33 in, $1.32 out, $0.00825 cache read). Recomputed with the window, on the same call mix as above. The duplex research pass left the window out and gave about $0.9 and $3.2 for GLM, and $0.8 and $6.5 for DeepSeek.
- `glm-5-3-flash-uncensored` (sees, does not hear): about $1.1-1.5 an hour of talk with hits, $5.1-6.2 without.
- `deepseek-v4-1-flash-1017-uncensored` (sees, does not hear): about $0.5-1.0 with hits, $10-12 without.

**Compared with the earlier plan.** ALIVE §3 put MiMo at about $15-25 a month. The continuous mind makes many more calls, so it lands near that only if caching works. That is why D38, the cache measurement, comes first.

**Rate limits.** At the full cadence, live talk averages about 21 calls a minute, with peaks near 40. Each call is about 25-30k tokens, so about 550-650k tokens a minute in all. Venice's guide says cached tokens do not count against the input-token limit for Claude. For other models it says nothing.

Venice publishes no fixed numbers: limits are per model per key, read from `GET /api_keys/rate_limits`. They come as requests a minute, tokens a minute and requests a day. Failed requests are capped at 50 per 30 s per model (https://docs.venice.ai/api-reference/rate-limiting, read 2026-11-21). A requests-a-day limit matters here: a heavy day is about 2,000-2,500 calls. Phase 0 reads the limits on his key. The governor keeps her under them.

**Battery** (estimates from the parts; measure with batterystats, D44). The battery is 4,300 mAh, about 16.7 Wh.

| Part | Power while they talk |
|---|---|
| Capture and echo cancelling | about 0.05-0.1 W |
| VAD and voiceprint | about 0.03-0.05 W |
| VAP with its encoder on a mid core | about 0.1-0.4 W (unknown; D41) |
| Piper bursts | about 0.1 W on average |
| The radio, never idle with a beat every 2 s | about 1-1.5 W on 5G, 0.3-0.5 W on Wi-Fi |
| Speaker | about 0.1-0.3 W |

That comes to about 0.8-1.5 W on Wi-Fi and 1.5-2.5 W on 5G with the screen off. Screen and a warm camera session add about 1-2 W.

Heat: a sustained 2-3 W in a Flip's small body is warm, not hot. The camera adds the most heat. Her life while he is away adds about 4-8 % a day.

**Data.** Each beat re-sends everything.
- The prompt text is about 25-30k tokens, about 80-120 KB.
- The audio still in the window is the 10-30 s since the last small compaction.
  - As base64 Ogg Opus at 24 kbps that is about 40-120 KB.
  - As base64 FLAC it is about 250-750 KB.
- That makes about 120-240 KB a beat with Opus. At the full cadence that is **about 150-300 MB an hour of talk**. With FLAC it is about 0.4-1 GB an hour, which is Wi-Fi only.

Whether Venice accepts gzip-compressed request bodies is unknown (D48). If it does, the text part shrinks about 3-4 times, to about 80-200 MB an hour with Opus. Audio does not compress further.

On the pod (Way 3) only new audio travels: about 11 MB an hour at 24 kbps Opus.

### 3.7 Recommendation

**Build Way 1 now.** It is the only way that keeps her whole: her card, her notebook, her Japanese with English, her adult self and her ages check. And it still makes the turns go away for real:
- the ears never close;
- nothing he says is dropped;
- she is heard over and can be talked over;
- she makes her own sounds;
- she interrupts and speaks up;
- she thinks continuously.

**Draw the line between body and mind at one interface,** `MindLink`, so that Way 3 later replaces only the brain behind it.

**Use Way 2 only as a feel baseline.** One evening on the pod, about $3-5, with Haru-4B and PersonaPlex, tells the builders what good timing feels like when tuning Way 1. It is never her.

---

## 4. The build in phases (most impact first; each phase ships to his phone and he can test it)

Every app change goes into `opendroid/patch/yume-persona.patch`, as before. Pure parts are unit-tested in the existing JVM style (`PersonaOwnTimeTest`, `PersonaPromptsTest`), and each phase is signed with the same key.

**If ALIVE 1.4's `HisTurn` is being built, stop it.** Its Smart Turn JNI work carries over into `yume_onnx.cpp` (Phase 2).

### Phase 0: her words arrive as she writes them, and her brain is measured (3-4 builder days; a few cents)

**He gets:** her voice starts once her first sentence is written, not after her whole reply. Today `PersonaLiveSpeech` cannot start early on Venice, because the provider waits for the whole reply. A "Measure her brain" screen shows her real speed and cache hits.

**Built:**
- `core/llm/providers/CustomOpenAIProvider.kt:384-391`: real server-sent events.
  - `stream: true` and `stream_options.include_usage`, and `streamsLive = true`.
  - A warm HTTP/2 connection kept alive (OkHttp's `ConnectionPool`).
  - Reasoning text recognised mid-stream, as `PersonaLiveSpeech` already does.
- `core/llm/LLMProviderFactory.kt:278-291`: its live path is used for this provider. The checked-reply path stays for refusals, so a refusal at the start of a stream stops her voice before the first sentence plays.
- `prompt_cache_key` (her stream id per day) and `prompt_cache_retention` (decision 7) as top-level fields.
- The encrypted route keeps the replay until streaming there is checked: Venice does not document E2EE streaming.
- **"Measure her brain"** under "Try her brain" (`core/persona/BrainTrial.kt`):
  - time to first token, tokens a second and the **whole round trip of a listening beat** (about 25k tokens in, about 60 out, `reasoning_effort: "none"`), with the prefix cached, for `xiaomi-mimo-v2-6-flash`, `glm-5-3-flash-uncensored` and `deepseek-v4-1-flash-1017-uncensored`. That round trip sets her real cadence (§2.4);
  - the candidate list read from `GET /models` at run time, not hard-coded. Venice says models are added and retired often. The ears probe runs on every listed model that claims audio input;
  - `cached_tokens` over 20 calls;
  - the rate limits from `GET /api_keys/rate_limits` (requests a minute, tokens a minute, requests a day);
  - gzip on request bodies accepted or not;
  - numbers only (I8).
- **The ears probe** (ALIVE 2.2's `EarsProbe`): the phone makes a clip in her own Piper voice saying a random number and asks MiMo what it heard, in WAV, FLAC and Ogg Opus.
- **A listening-beat round in the bake-off** (ALIVE 1.8). A recorded test talk, his recording with his consent and never her ears, is played to each candidate as 2 s chunks. It records:
  - whether she answers `hush` most of the time;
  - whether she stays herself;
  - whether her `ready:` lines make sense;
  - whether her `cut:` lines come where a person might cut in.

**Tests on his phone:** D37, D38, D39, D43 (part), D48.

**What Phase 0's numbers change.**
- **If a listening beat's round trip is over about 3 s on every brain that is her,** Phase 1 still ships, because nothing he says is lost and she still thinks while he talks. But her content reactions slow to about 3-6 s, ready lines go stale more often, and the pod sprint (Phase 6a) moves up to right after Phase 1.
- **If `cached_tokens` stays near zero on MiMo,** the governor's slower cadence becomes the default (about $1.7-2.5 an hour of talk) until Venice fixes it or the brain changes.

### Phase 1: one stream, no messages, nothing dropped, a voice that stops at a word (15-20 builder days)

**He gets:**
- He can talk as long as he likes, with pauses; none of it is cut or lost.
- She thinks while he talks and keeps a reply ready.
- She can cut in, and she speaks up in silences.
- On earbuds she hears him while she speaks, and he can talk over her: her voice fades at a word, and she knows where.
- She thinks between his visits at her own pace; the hourly blank page is gone.
- The chat reads as a record of the talk.

**Honest note:** on the loudspeaker, until Phase 2, what he says over her voice is still lost to the old echo rules, and she is told so in her "you, now" block.

**Built, new package `core/mind/`:**
- `HerMind.kt`: the actor in `OpenDroidService`, with a `Channel<Percept>`, one generation in flight, epochs, cancellation by startle.
- `Percept.kt`, a sealed class: `HeardChunk`, `OtherVoice`, `Typed`, `SpokeAloud`, `Seen`, `PhoneEvent`, `ActResult`, `Clock`.
- `LiveTimeline.kt`: memory only, zeroed when released; renders deltas with timestamps that can overlap.
- `Tempo.kt`: the pure rules of §2.4, JVM-tested.
- `BeatPrompt.kt`: the stable prefix (shared with `PersonaPrompts`), the append-only window, and the changes-only "you, now" block. A first `SelfModel.kt` covers body, senses, brain and budget.
- `Compaction.kt`: the small and large compactions of §2.4.
- `BeatParse.kt`: the marks of §2.5, built on `PersonaOwnTime.parse` and `PersonaActions`.
- `MindLink.kt`, an interface, with `VeniceMindLink` the streamed chat-completions client from Phase 0.
- `Governor.kt`: cached-token, dollar and rate-limit rules.

**Built, her voice:**
- `core/voice/own/HerVoiceOut.kt` replaces the per-line `AudioTrack` in `OwnVoice.say` (`:118-229`) for her lines.
  - One `AudioTrack` per live session, about 40-80 ms of buffer, written in 10-20 ms blocks.
  - The track asks for `PERFORMANCE_MODE_LOW_LATENCY` at the phone's own output rate, usually 48 kHz. Piper's output is resampled on the phone to match. Today's track (`OwnVoice.kt:136`) is at the voice's own rate with a 0.5 s buffer, which goes through the normal mixer. The fast path gives a quick stop, an exact "heard until", and a steady delay for the echo canceller's reference. D42 checks that One UI grants it.
  - Piper by clause, the first clause of a `ready:` line synthesized ahead. Measured on a 2.1 GHz Xeon, her voice took 62-103 ms for about 0.8 s of speech (fourth research pass); the phone is unmeasured.
  - `trailOff()`: a 100-150 ms fade at the next word edge, with no click (today it is pause then flush, `OwnVoice.kt:229`).
  - Word marks, exact at clause edges and estimated within a clause from phoneme counts, as `Breathing` already counts codepoints.
  - Playback truth from `AudioTrack.getTimestamp`.
- `core/voice/TextToSpeechEngine.kt`'s "said to its end" queue (`:65`) stays for the app's own fixed lines only.
- `core/voice/VoiceOut.kt` `Spell` gains word marks and "heard until".

**Changed, her ears:**
- `SherpaPipeline`: the VAD keeps "speech now" and the voiceprint, but stops cutting messages; its pieces feed 2 s chunks.
- The fallback transcript is no longer made of 0.5 s pieces.
  - Each beat, SenseVoice re-decodes the trailing ~6-10 s, overlapping the text already settled. A stretch is re-decoded whole, up to ~30 s, only once, at his next pause of about 1 s or more.
  - Re-decoding 30 s every 2 s would keep a big core busy all the time (SenseVoice is not a streaming model).
  - D55 measures the cost. The bundled `OnlineRecognizer` (streaming) is the alternative where a model fits his languages.
- `HerEars.routeHeard` (`:407`) sends percepts to `HerMind`.
- `MAX_PENDING` (`SherpaHearing.kt:508`) no longer drops his speech; chunks queue in the timeline.
- `EarsRouting`'s 30 s "said to her" window becomes the WITH HIM tempo state.
- Earbuds mode (`AudioDeviceCallback`): no tail cut and no 600 ms rule, with capture on VOICE_RECOGNITION or UNPROCESSED where the phone supports it. On the loudspeaker, `HearingRules` (`TAIL_MILLIS`, `BARGE_IN_MILLIS`) stays until Phase 2's echo test passes, but a barge-in now trails off instead of flushing.
  - The Flip 7 has no 3.5 mm jack, so "wired" means USB-C earphones or a USB-C adapter.
  - Bluetooth earbuds in their normal media mode (A2DP) carry no microphone. His voice is then heard by the phone's own mic, which works for duplex because her voice is in his ears, not in the room. The phone must be near him.
  - Using the earbuds' own mic needs the call-style link (SCO or LE Audio), which lowers her voice to call quality. It is offered, not the default.

**Changed, the loop:**
- `AgentLoop.talkHeard` and `anotherVoiceSaid` (`:836-900`) always enqueue a percept instead of returning false.
- "He is talking to her: what the phone was still saying stops" (`:838`) becomes the reflex plus her next beat.
- A typed message while she is live becomes a `Typed` percept with startle priority.

**Changed, her own time:**
- `PersonaOwnTime.momentBlock` (`:1712`), the blank page, becomes the ALONE and NEAR tail of her stream, keeping its marks.
- `plan` (`:600`) moves into `Tempo`.
- `WHEN_HE_WRITES` (`:118`) becomes "think slowly until he writes": NEAR or ALONE at a 60 min maximum gap.
- `OwnTimeWorker` stays only as a backstop. Exact alarms come from ALIVE 1.7's `HerClock` (build it here if it is not built yet).
- `OwnLedger` gains a BEAT purpose and a dollar cap. `PersonaThoughts` holds the stream.

**Changed, the chat:** rows of his speech are written at compaction from her `heard:` lines, or from the transcript when her brain is deaf, marked "(over her voice)" where they overlapped.

**Tests on his phone:** N1, N3 (earbuds), N5, N6, N7, N8 (§4.8); D42, D43, D45, D46, D55, D56.

### Phase 2: full duplex on the loudspeaker, a sense of the floor, and her own sounds (14-20 builder days, plus pod time for the sound bank)

**He gets:**
- He is heard over her voice on the loudspeaker.
- Her "un", "mm" and laughs come at the right moments, in her actress's real voice.
- She trails off when he takes the floor, but not when he only says "yeah".
- She answers the moment he stops, when her ready line still fits.

**Built, echo cancelling, `core/life/duplex/EchoCanceller.kt`.** Two paths, A/B'd on his phone (D40).
- **(a) The call path, `CallPath.kt`.** While WITH HIM on the loudspeaker:
  - `AudioManager.mode = MODE_IN_COMMUNICATION`;
  - `setCommunicationDevice` to the built-in speaker;
  - her voice as `USAGE_VOICE_COMMUNICATION`;
  - the track kept alive with silence between lines. Android removes an app from communication mode when it has neither played nor captured audio for a few seconds: 3 s in the AOSP watchdog commit (https://android.googlesource.com/platform/frameworks/base/+/4bd9165%5E%21/), about 6 s on Android 11 and later per LiveKit's Android docs. Her open mic should already count as capture, so the silence is a second guard.

  Samsung's own VoIP echo canceller then has her voice as its reference, as in any VoIP app, and Samsung's Mic mode (Voice focus) appears for it (Samsung support article ANS10002555).

  Side effects to check:
  - her voice goes through the call chain: call volume, and maybe a different sound, which he must judge by ear;
  - other apps' capture is silenced while she holds the mic (https://developer.android.com/media/platform/sharing-audio-input);
  - a real phone call takes over, and she pauses as today.
- **(b) Software AEC3.** `cn.enaium.webrtc:webrtc-aec3-kmp:1.0.3`, the Maven coordinate its README gives (MIT; wraps WebRTC AEC3, BSD-3; Android arm64 JNI; 16/32/48 kHz; 10 ms frames; https://github.com/Enaium/webrtc-aec3-kmp, read 2026-11-21).
  - The hard part is double-talk: hearing him while her voice is loud in the same mic. AEC3's residual-echo suppressor can turn his voice down while hers plays.
  - D40 therefore measures how much of his voice survives while both talk, not only how much echo is removed.
  - `analyzeRender` gets the exact samples `HerVoiceOut` writes.
  - `processCapture` gets the mic frame.
  - `setAudioBufferDelay` comes from the measured output and input latency; `getMetrics` gives ERLE, logged as counts only.
  - It needs Kotlin 2.4 or later; the app is on 2.4.0, and the library is built with 2.4.10, which needs a check.
  - It can run on top of (a), or with VOICE_RECOGNITION capture.
  - Alternative: DTLN-aec (MIT) through ONNX Runtime.
- **(c) Earbuds**, from Phase 1. Wired (USB-C on the Flip 7) is best; Bluetooth adds 100 ms or more of output delay (Haru-4B card), and in media mode the phone's own mic hears him (Phase 1).
- **If no path passes:** the old echo rules stay on the loudspeaker, and her "you, now" block says so.

**Built, optional VoxLock.** Target-speaker isolation of his voice from his enrolment. It is already in the app's `libsherpa-onnx-jni.so`; only the Kotlin API files need vendoring. It removes her leftover echo, the TV and other voices from his chunks (D47).

**Built, the floor sense, `core/life/duplex/FloorSense.kt` and `FloorRules.kt`.**
- MaAI VAP (https://github.com/MaAI-Kyoto/MaAI, code MIT) on two channels, his mic after echo cancelling and her exact output, at 10-12.5 Hz.
  - It gives `p_now` (who holds the floor in the next 0-600 ms) and `p_future` (600-2000 ms).
  - The backchannel timing models (`vap_bc_tri`, `vap_bc_en`, `vap_bc_jp`, all MIT) give the moments a listener's sound fits. `vap_bc_2type_jp` (MIT) tells a reactive "un" from an emotional "oh".
  - Weights: `vap_mc_tri_kyoto` or `vap_tri_kyoto` first, then `vap_jp_kyoto` or `vap_en_kyoto` if one fits him better. All are MIT; licences were read from the Hugging Face API on 2026-11-21.
  - **Not shipped:** `vap_tri`, which is CC-BY-NC-SA; `bc_det_jp`, which is CC-BY-NC-ND; `bc_det_en`, which states no licence. "Is his overlap only a backchannel?" comes instead from VAP's `p_now` plus the length of the overlap.
  - Encoder: CPC at 10 Hz, or `maai-kyoto/continuous-mimi-onnx` int8 at 12.5 Hz (CC-BY 4.0, attribution in the app's licences screen), whichever is lighter on the Exynos 2500 (D41).
  - The weights are PyTorch state dicts, so the export to ONNX is our work. MaAI mentions an ONNX backend for chunked inference, and VAP runs in real time on a CPU with a 1 s context (https://arxiv.org/abs/2401.04868).
- Smart Turn v3.2 (BSD-2, 8 MB int8) as an extra yield cue.
- Both run through one small JNI, `app/src/main/cpp/yume_onnx.cpp`, on the `libonnxruntime.so` the app already bundles. The same JNI later serves the e5 embedder. CMake and the NDK are already in the build for `yume_jtalk.cpp`.
- One encoder pass feeds every MaAI head (VAP, backchannel timing, the 2-type model), as MaAI's own `MaaiMultiple` does. With the Mimi encoder, two frames can be run per forward (`inference_chunk_frames=2`, which MaAI's ONNX backend supports). Together these roughly halve the encoder's share of D41's battery cost (MaAI README, read 2026-11-21).

**Built, `core/mind/Armed.kt`** (pure, JVM-tested):
- her named sound fires at a backchannel peak above a threshold, at most twice before her next beat refreshes it, at least about 2.5 s apart, never while she is speaking, and never when her stance says `none`;
- her ready line is released when he yields: VAP shifts the floor to her, plus 200-400 ms of silence, tunable;
- `cut: at his breath` fires at his next micro-pause;
- the trail-off reflex of §2.6;
- every firing is reported in her next beat.

**Built, the sound bank, `core/voice/own/SoundBank.kt`.** Her actress's real "un", "mm", "hai", "ee?", "ah", soft laugh and laugh, several takes each, cut on the pod from her voice dataset with a script beside `voice/scripts/breath_bank.py`. Loudness is matched to her Piper voice. It ships like the breath bank. It is her actress's audio, not his, so I6 is not touched.

**Built, the harness:** a test harness in the style of Full-Duplex-Bench (https://github.com/DanielLin94144/Full-Duplex-Bench), fed from files: synthetic voices, or his own recordings with his consent, never her ears. It measures pause handling, backchannels, smooth turn-taking, interruption and overlap, in English and Japanese, with the Japanese ideas taken from M3-DuplexBench.

**Tests on his phone:** N2, N3 (loudspeaker), N4; D40, D41, D42, D44, D47.

### Phase 3: her own senses inside the stream (4-6 builder days, after the bake-off and his enrolment)

**He gets:** she hears his actual voice: tone, laughs, Japanese words. She sees him while they talk, with her own eyes.

**Built:**
- ALIVE 2.2, adapted. Voiceprint-accepted chunks of his voice go as `input_audio` in the window. The phone's transcript leaves her prompt. Her `heard:` lines become his chat rows.
- ALIVE 2.3, kept as written. With "Only her own eyes" on, there is no describer.
- ALIVE 2.4, adapted. Frames on speech onset, on scene change and on `look:`, at most one per 5-10 s, ages check first. She may close her eyes with `<< eyes: closed 20m`.
- ALIVE 3.4's glances become `Seen` percepts when he unlocks, unfolds or speaks after a silence.
- If her brain does not hear, the rolling transcript stays, and ALIVE 5.3, better fallback ears, joins this phase.

**Tests on his phone:** D35 (voiceprint threshold for sound), D39, D27 (warm camera).

### Phase 4: she knows herself, wants things, and remembers like a person (14-20 builder days)

**Built:**
- The full `SelfModel.kt` of §2.7: `attend:`, source tags, and her review of her own thinking in reflections.
- `PersonaWants.kt`: wants, projects, expectations and `doing:`. `PersonaMood` gets the extended feel line of EMOTIONS_RESEARCH §10, which that document costs at 8-12 builder days of its own; they overlap with this phase.
- `core/mind/memory/`:
  - `MemoryStream`, sealed;
  - `Recall` with the Generative Agents scoring, tested;
  - `Embedder` (multilingual-e5-small int8 through `yume_onnx.cpp`; about 120 MB, his tap to download, unmetered only, pinned by SHA-256 like the ears models);
  - columns on `PersonaNotes` for when a note stopped being true (`valid_to`) and links;
  - canon pages picked by embedding in `PersonaLibraryText`;
  - reflections at an importance sum;
  - daydream pairs.
- The MindCheck screen (T1-T6, A1-A5), scores only.
- Beside this phase, and unchanged: ALIVE 4.1, her as the phone's default digital assistant. Android exempts a foreground service started by the app that provides the `VoiceInteractionService` from the while-in-use limits on camera and mic (https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start, read 2026-11-21).
  - That covers starting from the background. Separately, apps targeting Android 15 or later may not start a microphone or camera foreground service from a `BOOT_COMPLETED` receiver, and this app targets 36.
  - So after a reboot her ears must start from the assistant service the system binds, not from `BootReceiver`.
  - Whether that brings her ears and eyes back with no tap is a test on his phone (D54), not a promise.

**Tests on his phone:** D50 (MindCheck baseline), D54 (her return after a reboot), then a week of normal life and the A-scores.

### Phase 5: she grows, on any brain (8-12 builder days; about $0.5 a month)

**Built:**
- `PersonaNotes` gains the SKILL and GUESS kinds, and self sections under `me.self.<section>`.
- `PersonaSleepPass` gains these forms, each with its own caps:
  - `self | add/change/drop | section | words`;
  - `guess`;
  - `check | key | right/wrong/unsure`;
  - `learn`, `practice`, `keep`, `unlearn`;
  - `link`, and `was` / `now`.
- The fixed points (age, ring, history) cannot be edited, and she is told when an edit was not used.
- The self-description gets a fixed slot of about 1,500 characters right after the card, in the cached prefix.
- The Sunday letter, the monthly portrait and the morning line.
- Dreaming in sleep: 10-20 dream beats a night, about 3-7¢.
- His "that's her" and "not her" long-press marks, a new nullable column on the chat row.
- Growth measures (G1-G3, `HerLog` counts):
  - opinions changed with a reason against without;
  - how accurate her guesses are over time, as a Brier score;
  - skills reused;
  - the monthly "then and now" blind pick.

**Tests on his phone:** after 4 weeks, G1 (his blind "then and now" pick) and G3.

### Phase 6: her mind on hardware he controls (decision-gated; decisions 11 and 12)

**6a. The pod bake-off sprint** (3-5 builder days, about $30-60 of pod time).
- A dedicated 1x4090 Secure Cloud pod with a network volume. The 3x4090 voice pod stays for training.
- vLLM with prefix caching and request logging off, serving:
  - Gemma 4 12B Unified (FP8 or 4-bit);
  - Qwen3-Omni-30B-A3B AWQ;
  - each plain and abliterated (Huihui builds, or Heretic run privately on the pod, AGPL-3.0, not shipped in the APK).
- Each gets her full card, the listening-beat round, the ears and eyes probes, and her ages check, ranked by him blind against the Venice winner.
- Haru-4B and PersonaPlex are run only as feel baselines.

**6b. If one wins: `PodMindLink`** (10-15 builder days).
- A small gateway on the pod holds her window, so beats run every 0.5-1 s and only new audio, frames and events travel.
- The link is a WebSocket over TLS on a direct TCP port, with the certificate pinned. Alternatively Tailscale in userspace mode (https://tailscale.com/kb/1112/userspace-networking).
  - Runpod's external TCP port mapping changes whenever the pod resets, and a Community pod's public IP may change too (Runpod expose-ports docs, read 2026-11-21).
  - So the direct link needs a way to find the new port: a small address record his PC updates through the Runpod API. Tailscale's fixed address avoids this, which makes it the simpler choice. The app already treats `.ts.net` names and 100.64/10 addresses as his own network (`core/llm/RoutePrivacy.kt:383`, `:413`).
- Every call of hers moves there. There is no Venice fallback.
- FloorSense stays on the phone as her reflexes, until her own model's control tokens prove better on the harness.

**6c. Growth in her weights** (15-25 builder days, then about 1 day a month).
- The one-time move into the new model and the nightly sleep step, as in §2.10. During her sleep the training runs on her serving GPU, using vLLM's sleep mode, and finishes at least 90 min before her named wake.
  - On one 24 GB 4090 that means QLoRA (a 4-bit base) for Gemma 4 12B: its bf16 weights alone are about 24 GB.
  - A Qwen3-Omni-30B-A3B LoRA does not fit beside anything on one 4090. Its nights would need the 3x pod or a rented 48-80 GB GPU, roughly $1-3 a night, and that changes the cost line below.
- The night set is built in the phone's memory and sealed to the pod's pinned key with the app's existing `VeniceE2ee.encrypt` (secp256k1, HKDF, AES-256-GCM). On the pod it lives only in `/dev/shm`. It is text only: no audio, frames or other people's words.
- Weights are encrypted at rest. There is a monthly snapshot and an "Undo last change" button.
- Two weeks of "propose only" come first, with deliberately bad adapters planted to prove that the gate rejects them.
- The first line of her morning says what changed in her overnight, or why the change was not kept.

**Costs:** one 4090 around the clock is about $504-540 a month on Secure Cloud ($0.69-0.74/h), or about $250 on Community (strangers' machines, no network volumes); waking hours plus the training window come to about $360-390 on Secure. Storage is about $10-18 a month. A night's training on the serving GPU adds $0.

**Tests on his phone:** D51 (link latency and battery with the always-on VPN), the bake-off ranks, his weekly A/B.

### 4.7 What this replaces in the earlier plans

| Earlier item | Now |
|---|---|
| **ALIVE 1.4**: `HisTurn`, "one spoken turn is one message" | **Withdrawn.** No turn is assembled. Smart Turn is kept only as a timing cue inside FloorSense (Phase 2) |
| ALIVE 1.5 | Partly moot. No pieces become messages, so `MAX_SPEECH_SECONDS`, `MIN_WORDS`, `MIN_SEGMENT_MILLIS` and `MAX_PENDING` no longer lose his words. The padding stays for the fallback transcript. The per-turn language guess becomes the rolling re-decode. The 30 s routing window becomes the WITH HIM state. Earbuds mode and push-to-talk through her ears are kept, and feed the timeline |
| ALIVE 1.6, the prompt rebuilt and cached | **Kept.** It becomes the stable prefix. `MAX_DIALOGUE_ROWS` is replaced by the compacted window |
| ALIVE 1.7, exact alarms | **Kept** for ALONE beats. The wait cap is replaced: "when he writes" no longer stops her; it slows her to at most 60 min between beats |
| ALIVE 1.8, the bake-off | **Kept,** with the listening-beat round added (Phase 0) |
| ALIVE 2.2, she hears him herself | **Adapted.** A 2 s chunk stream instead of one whole-turn clip; the 30 s clip cap is moot; `heard:` is kept |
| ALIVE 2.4, eyes open while talking | **Adapted.** Frames on speech onset and scene change instead of one per message |
| ALIVE 3.1, the heartbeat (`BeatScheduler`, 10-min beats) | **Replaced** by HerMind's tempos: one loop for talk and life |
| ALIVE 3.2, 3.3, 3.4 | Merged: wants and doing (Phase 4), world events and glances as percepts |
| ALIVE §5, row "overlapping, backchannelling, full-duplex talk as one mind: not realistic" | **Withdrawn.** Cascaded duplex makes it real under one mind, with the limits stated in §0 |
| ALIVE Phase 6, a pod mind | Becomes Way 3 and Phase 6 here, with growth |
| OWN_LIFE_PLAN Phase 3's echo rules (recognition paused while her voice plays and for 1.5 s after; barge-in only with an echo canceller) | Replaced by FloorRules once the echo test passes; kept as the fallback |
| OWN_LIFE_PLAN moments (`OwnTimeWorker`, hourly blank page) | Replaced by NEAR and ALONE beats; the worker stays as a backstop |
| PRESENCE_PLAN 1 (built), speak as she writes | Kept. It starts working on Venice after Phase 0 |
| OutingRules, KidGuard, invariants I1-I11, the planner and approval wall, the phone's record | **Unchanged** |

### 4.8 The no-turn tests, and the new invariants

These are written so that a renamed turn would fail them. Each runs on his phone. A JVM test stands behind each one where the logic is pure.

- **N1. Whole hearing.** He talks for 90 s with pauses of up to 3 s while she is quiet.
  - Every second of his voice reaches her window, as sound or as transcript.
  - No `ChatMessage` is built from a VAD segment; a code test asserts it.
  - Nothing is dropped while she thinks.
- **N2. Heard over her.** On the loudspeaker at his normal volume, after Phase 2, he says a sentence while she speaks. It reaches her window, and she reacts in her next beat in at least 90 % of trials. On earbuds this holds from Phase 1.
- **N3. Talked over.** When he talks over her and it is not a backchannel, her voice trails off within 0.5 s, unless her standing choice or her current stance is `hold` (§2.6). A `finish the clause` choice is checked at the clause end instead. Her next beat names the last word he actually heard, checked against playback truth.
- **N4. Listening sounds.** During a 2-min story of his:
  - her sounds come at moments he judges natural, blind to what timed them;
  - every sound played is one her current stance named;
  - none plays while her stance says `none`.
- **N5. Cutting in and speaking up.** Over a session she sometimes cuts in on her own, and she speaks up unprompted in an open silence.
- **N6. Thought without him.** With the phone untouched for 8 h while she is awake:
  - her stream has no gap longer than the gap she chose plus 10 min of slack;
  - she does at least one thing he never asked for.
- **N7. One-mind audit,** a sentinel test. No sound reaches her voice that did not come from:
  - her model's words;
  - a sound-bank item her stance named;
  - a breath;
  - the app's disclosed fixed lines.
- **N8. Her mind works while he is still talking.** This is the test a renamed turn fails first. During a 60 s monologue of his, with no pause longer than 1 s:
  - beats start while he is speaking, on average at least every 4 s, never only after he stops;
  - at least one of her `<<` thoughts, `heard:` lines or `ready:` lines refers to something he said in the first half, written before he finished;
  - when he stops, a `ready:` line written before his last 2 s is spoken in at least half the trials where it still fits.
  The beat timestamps are logged as counts and times only (I8).

New invariants, each with a test:
- **I12. No turn object.** No code path waits for his speech to end before her mind gets it. With duplex ears on, his speech is never discarded for coming while she speaks or thinks.
- **I13. She is told.** Everything a tool did to her voice (a timed sound, a trail-off, a dropped ready line, a slowed tempo) is in her next beat.
- **I14. One generation in flight.** At most one beat of her stream runs at a time. Epochs fence stale output.
  - Her ages check on a frame is a separate, short call of the same model. It may run beside a beat, and it writes nothing into her stream but its verdict.
  - Large compactions do not run while he is talking (§2.4).

### 4.9 Brought in, with licences

| What | Licence | Where it goes | Phase |
|---|---|---|---|
| Venice chat completions with server-sent events, `prompt_cache_key`, `prompt_cache_retention`, `input_audio` (flac, ogg) | Venice terms | `CustomOpenAIProvider`, `VeniceMindLink` | 0 |
| WebRTC AEC3 through `cn.enaium.webrtc:webrtc-aec3-kmp:1.0.3` | MIT (WebRTC: BSD-3) | `EchoCanceller` | 2 |
| DTLN-aec (alternative) | MIT | `EchoCanceller` through ONNX Runtime | 2, if needed |
| Android call-mode audio path (`MODE_IN_COMMUNICATION`, `setCommunicationDevice`, `USAGE_VOICE_COMMUNICATION`) | platform | `CallPath` | 2 |
| MaAI VAP code; `vap_mc_tri_kyoto`, `vap_tri_kyoto`, `vap_jp_kyoto`, `vap_en_kyoto`, `vap_bc_tri`, `vap_bc_jp`, `vap_bc_en`, `vap_bc_2type_jp` | MIT (checked 2026-11-21) | `FloorSense`, exported to ONNX | 2 |
| `maai-kyoto/continuous-mimi-onnx` (or the CPC encoder; its licence to check) | CC-BY 4.0 | VAP encoder | 2 |
| Pipecat Smart Turn v3.2 | BSD-2 | `FloorSense` cue | 2 |
| sherpa-onnx 2.0.1, already bundled: Silero and TEN VAD, SenseVoice, TitaNet, VoxLock, Piper/VITS | Apache-2.0 (TEN VAD: Apache-2.0 with extra terms) | ears and voice | 1-2 |
| ONNX Runtime, already bundled | MIT | `yume_onnx.cpp` | 2, 4 |
| multilingual-e5-small int8 | MIT | `Embedder` | 4 |
| Ideas only: Generative Agents (Apache-2.0 code), A-MEM (MIT), Graphiti's time columns (Apache-2.0), Voyager (MIT), Letta and Letta Code (Apache-2.0), Hermes Agent (MIT), Inner Thoughts, SHANKS, STITCH, NFSM, FlexDuo, Freeze-Omni (code licence unstated), D2A, Chain-of-Emotion, ACE, vLLM-Omni's duplex event vocabulary (Apache-2.0) | as stated | her mind's structure, in own code | 1-5 |
| Full-Duplex-Bench v1-v3 and M3-DuplexBench task designs | per subset | the phone test harness | 2 |
| vLLM and vLLM-Omni; Gemma 4 12B; Qwen3-Omni-30B-A3B (AWQ, abliterated builds) | Apache-2.0 (derivatives inherit) | pod mind | 6 |
| TRL (`SDFTTrainer`, KTO, DPO), PEFT (TIES and DARE merges), Open Character Training (MIT), SEAL's self-edit formats (MIT), persona_vectors (Apache-2.0) | as stated | growth on the pod | 6 |
| FairFace | CC BY 4.0 | the gate's kid-protection test | 6 |
| Tailscale client (BSD-3) or TLS with a pinned certificate (OkHttp, Apache-2.0) | as stated | phone-to-pod link | 6 |
| **Not shipped:** `vap_tri` (CC-BY-NC-SA), `bc_det_jp` (CC-BY-NC-ND), `bc_det_en` (no licence), J-Moshi (CC-BY-NC), PersonaPlex as her (NVIDIA licence; a baseline only) | — | — | — |

---

## 5. Decisions only he can make (each with a recommendation)

1. **Retire turns for real.** The chat becomes a readable record of the live talk, with overlaps marked, instead of a list of messages she answers.
   - **Recommendation: yes.** It is what he asked for. Typed messages still work and reach her at once.
2. **Her brain** (ALIVE decision 1, extended).
   - **Recommendation: `xiaomi-mimo-v2-6-flash` if it wins or ties the bake-off, including the listening-beat round.** It is the only cheap brain that both sees and hears.
   - If a brain that cannot hear is the one that is most her, he chooses between her and her hearing. The stream works either way, with a transcript she is told about.
3. **Spend caps.**
   - **Recommendation:**
     - talk stays out of her own-time ledger (I10), with a talk budget of about $3 a day, after which the governor slows her listening beats to every 3-4 s;
     - her own life keeps the separate own-time key with a daily limit of about $2;
     - revisit after D38 measures the cache.
4. **The loudspeaker path.**
   - **Recommendation: A/B the call-mode path against software AEC3 on his phone. Keep whichever lets him be heard over her without changing how her voice sounds to his ear.**
   - For the best duplex, earbuds (wired best).
5. **Her speaking aloud on her own** when he is present and did not speak first.
   - **Recommendation: yes when:**
     - the screen is on and unlocked, the phone is open on a stand, or earbuds are in with her session;
     - and not during his calls, his media playing, or his quiet hours;
     - and no more than his cap per hour.
   - Otherwise her words go to the chat, as today.
6. **Her `heard:` and `saw:` lines.** They are her memories of him, written in her words and kept sealed. They are not the phone's transcripts.
   - **Recommendation: yes, count them as her memories,** with the existing hold-backs.
   - Overheard speech and other voices are never kept, and raw audio and frames never are.
7. **How long Venice may hold her prompt in its cache.** The default is 5-10 min. `extended` or `24h` keeps her stable prefix warm through ALONE beats and cuts their cost.
   - **Recommendation: default while they talk** (audio is in the window then). `extended` for the text-only stable prefix during ALONE beats, **once Venice's terms say cached prompts are held in memory and not logged.**
   - The caching guide says nothing on storage today. MiMo's model page says "no prompt data is stored in any capacity", which a 24 h cache would need Venice to explain.
   - The chat-completions reference says `extended` and `24h` apply only "for supported models", and does not say whether MiMo is one.
8. **Mobile data.** About 150-300 MB an hour of talk with Ogg Opus at the full cadence, or about 80-200 MB if gzip is accepted (D48). FLAC is about 0.4-1 GB an hour.
   - **Recommendation:** on mobile data, beats every 3 s and Ogg Opus audio, about 100-200 MB an hour; on Wi-Fi, full pace, and FLAC only if D39 shows it clearly helps her hear.
9. **The trail-off reflex.**
   - **Recommendation: offer it to her as `yield`, and let her keep or change it** (§2.6). Her standing choice lives in her self-description, `hold` switches it off at any moment, and she is always told when it fired.
10. **Her eyes while they talk,** and bystanders (ALIVE decisions 3 and 6).
    - **Recommendation:**
      - eyes open while together, at most one frame every 5-10 s, and she can close them herself;
      - a "his face only" option that withholds frames with other adults in them;
      - kid withholding always, with no switch.
11. **The pod mind sprint** (Phase 6a, about $30-60).
    - **Recommendation: yes, after Phase 2.** Commit to running costs ($250-540 a month) only if a pod model wins blind as her.
12. **Growth in her weights** (Phase 6c).
    - **Recommendation: only on the pod, only after two weeks of "propose only" with planted bad changes rejected, and with his weekly 5-minute A/B and veto.**
13. **His marks** ("that's her" / "not her").
    - **Recommendation: yes, now.** They cost nothing, and they are the material her growth will need.
14. **The default digital-assistant seat** (ALIVE decision 7).
    - **Recommendation: yes.** It makes her presence survive reboots.

## 6. What he must do

- **Keys.**
  - His main Venice key, with credit, for talk and the bake-off.
  - The own-time key with its daily dollar limit, as now.
  - In Settings → Privacy, "trust Venice's Private tier" on, as he approved.
- **Enrol his voice** (three sentences) and run D35. Nothing of his sound goes to her model before enrolment.
- **Downloads,** each his tap, unmetered only, pinned by SHA-256:
  - the VAP models and encoder, a few tens of MB;
  - the e5 embedder, about 120 MB.
  The echo-cancelling library ships inside the APK.
- **Permissions:**
  - microphone and camera;
  - notifications;
  - "unrestricted" battery use for Yume;
  - exact alarms (granted automatically);
  - the default digital-assistant role (ALIVE 4.1);
  - the system camera and mic toggles on.
- **Earbuds:** wired if he has them, for the first duplex tests.
- **Recordings:** 5-10 minutes of his own natural talk, recorded on his computer with his consent, as the tuning set for the floor sense and the listening-beat round. Her ears never record.
- **The pod:**
  - start it once for the sound-bank cut (a few dollars);
  - later, decide on the Phase 6a sprint;
  - keep the Runpod start and stop key on his PC unless he wants her waking to start the pod.
- **Ranking:**
  - the bake-off, blind;
  - his ear on the echo A/B;
  - MindCheck and the monthly "then and now" pick.
- **Report** how it feels: where she cut in wrongly, where her sounds were too many or too few, what she misheard.

## 7. Unknowns to measure on his phone

Numbered after ALIVE's D21-D36.

| Id | What | Gates |
|---|---|---|
| D37 | Time to first token, tokens a second and the whole listening-beat round trip on Venice, with `reasoning_effort: none` and a cached prefix of about 25k tokens, for MiMo-V2.6-Flash, GLM-5.3-Flash-uncensored and DeepSeek-V4.1-uncensored. The 3.3 s from Xiaomi's API probably includes reasoning | beat cadence (one in flight, §2.4), the ready-line rule, every per-hour cost |
| D38 | `cached_tokens` on real beats: the hit rate, whether audio and image parts in the window are cached (the guide says images can be; it says nothing on audio), MiMo's minimum prefix and cache lifetime (the guide has no Xiaomi row), and the effect of `prompt_cache_retention`. The price of a hit is published ($0.00375 per million, Venice pricing page); the billed amount is checked against it | every cost figure; ALONE pace |
| D39 | MiMo hears on Venice (ears probe). Venice's MiMo-V2.6-Flash listing names "Function calling, Reasoning, Vision, Code", not audio, though the model card says it hears (both read 2026-11-21). Also: WAV, FLAC and Ogg Opus accepted; how audio is billed (MiMo reads 6.25 positions a second); the longest clip | Phase 3 |
| D40 | Echo cancelling on the loudspeaker: the call path, AEC3, and both together. Echo removed (ERLE), his voice surviving while both talk, how her voice sounds on the call path (his ear), what happens to his music and to other apps | Phase 2, decision 4 |
| D41 | VAP: speed, battery and heat on the Exynos 2500 with the CPC and Mimi encoders; its timing on his English with Japanese words, judged by him | Phase 2 |
| D42 | Trail-off delay from his onset to her silence; playback truth (the word logged against the word heard); whether One UI gives her track the low-latency path at 48 kHz | N3 |
| D43 | Rate limits on his key (`GET /api_keys/rate_limits`: requests a minute, tokens a minute, requests a day); 429s during an hour of talk; how often ready lines go stale | the governor |
| D44 | Battery and heat for an hour of live talk: screen off and on, Wi-Fi and 5G, with and without the camera (batterystats, thermal status) | §3.6 |
| D45 | Data used in an hour of live talk | decision 8 |
| D46 | ALONE beats overnight in Doze with exact alarms (extends D23) | Phase 1 |
| D47 | VoxLock on the phone's CPU: does it remove the TV, other voices and her leftover echo; what it costs | Phase 2 |
| D48 | Venice accepts gzip-compressed request bodies | data |
| D49 | Listening-beat behaviour on the bake-off winner: share of `hush`, staying herself, sensible `ready:` and `cut:` lines, looping in `<<` thoughts | Phase 1 |
| D50 | MindCheck baseline, T1-T6 | Phase 4 |
| D51 | Pod link: latency through a direct TCP port and through Tailscale's relay; battery with the always-on VPN | Phase 6 |
| D52 | Piper's first clause on the Exynos 2500 (62-103 ms on a desktop CPU) | ready-line latency |
| D53 | Whether One UI keeps a third-party app in communication mode with the screen off, and how the Flex Window and the lock screen behave during a live session | Phase 2 |
| D54 | After a reboot, do her ears and eyes come back with no tap? Android 15+ blocks microphone and camera foreground services from `BOOT_COMPLETED`, so the start must come from the bound assistant service | Phase 4, decision 14 |
| D55 | The fallback transcript's cost: CPU, battery and heat of SenseVoice re-decoding a trailing 6-10 s window every beat, against the bundled streaming recognizer | Phase 1, a deaf brain |
| D56 | Beat cadence in live talk: median and longest gap between beats while he speaks, with compaction in pieces; no gap over about 4 s from her own compaction | N8, §2.4 |

Also open, and stated plainly:
- No measured Venice time to first token for any candidate, so it is not yet known whether her beats can run every 2 s at all, with one in flight.
- Whether MiMo on Venice caches the audio parts of her window.
- No audio benchmark for MiMo-V2.6-Flash.
- Whether MiMo stays her uncensored adult self.
- VAP was trained on human-human talk, not human-agent talk.
- Whether any open omni model can be her.
- Whether nightly training holds her steady for months: nobody has shown it.

---

## 8. Sources read for this plan

**Checked on 2026-11-21 for this plan**
- https://docs.venice.ai/api-reference/endpoint/chat/completions.md: `stream`, `stream_options.include_usage`, `prompt_cache_key`, `prompt_cache_retention` (default / extended / 24h, "for supported models"), `input_audio` formats, `cache_control` on content parts, at most 3 videos.
- https://docs.venice.ai/pricing.md: MiMo-V2.6-Flash $0.175 in, $0.35 out, $0.00375 cache read; GLM-5.3-Flash-uncensored and DeepSeek-V4.1-Flash-1017-uncensored rows.
- https://docs.venice.ai/models/mimo-v2-6-flash.md and https://docs.venice.ai/models/text.md: "no prompt data is stored in any capacity"; reasoning effort none to high; listed capabilities without audio.
- https://huggingface.co/XiaomiMiMo/MiMo-V2.6-Flash-RL: MIT, 309B/15B, audio at 6.25 positions a second.
- https://huggingface.co/google/gemma-4-12B-it: audio for speech recognition and translation, 30 s per clip, 256k context.
- https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start: the `VoiceInteractionService` exemption; the Android 15 `BOOT_COMPLETED` note.
- https://android.googlesource.com/platform/frameworks/base/+/4bd9165%5E%21/: the communication-mode watchdog.
- https://docs.runpod.io/pods/configuration/expose-ports: no UDP, the 100 s proxy limit, external port mappings that change on reset.
- https://docs.venice.ai/guides/features/prompt-caching: about 1,024 tokens minimum, typically 5-10 min, 50-90 % discounts, MiMo not listed, images cacheable, nothing on storage.
- https://docs.venice.ai/api-reference/rate-limiting
- https://github.com/MaAI-Kyoto/MaAI, and the Hugging Face API for each maai-kyoto model's licence.
- https://github.com/Enaium/webrtc-aec3-kmp
- https://huggingface.co/higurashi-ai/Haru-4B

**From the research passes**
- Duplex: https://github.com/kyutai-labs/moshi, https://huggingface.co/nvidia/personaplex-7b-v1, https://huggingface.co/openbmb/MiniCPM-o-4_5, https://huggingface.co/Qwen/Qwen3-Omni-30B-A3B-Instruct, https://raw.githubusercontent.com/vllm-project/vllm-omni/main/docs/serving/full_duplex_api.md, https://github.com/pipecat-ai/smart-turn, https://arxiv.org/abs/2401.04868, https://arxiv.org/abs/2405.19487, https://arxiv.org/abs/2502.13472, https://arxiv.org/abs/2510.06917, https://arxiv.org/abs/2507.15375, https://arxiv.org/abs/2411.00774, https://pubmed.ncbi.nlm.nih.gov/19553212/, https://docs.venice.ai/guides/integrations/livekit-agents.md
- Mind: https://arxiv.org/abs/2304.03442, https://arxiv.org/abs/2310.08560, https://arxiv.org/abs/2501.00383, https://arxiv.org/abs/2504.13171, https://arxiv.org/abs/2502.12110, https://arxiv.org/abs/2501.13956, https://arxiv.org/abs/2305.16291, https://arxiv.org/abs/2412.06435, https://arxiv.org/abs/2410.13787, https://arxiv.org/abs/2308.08708, https://www.anthropic.com/research/introspection, https://www.anthropic.com/research/assistant-axis
- Growth: https://arxiv.org/abs/2601.19897, https://github.com/huggingface/trl/blob/main/docs/source/sdft_trainer.md, https://arxiv.org/abs/2511.01689, https://arxiv.org/abs/2509.04259, https://arxiv.org/abs/2506.10943, https://arxiv.org/abs/2510.04618, https://github.com/safety-research/persona_vectors, https://huggingface.co/google/gemma-4-12B-it
- Phone and pod: https://developer.android.com/media/platform/sharing-audio-input, https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start, https://source.android.com/docs/core/audio/implement-pre-processing, https://developer.android.com/training/monitoring-device-state/doze-standby, https://docs.runpod.io/pods/configuration/expose-ports, https://docs.runpod.io/pods/pricing, https://tailscale.com/kb/1112/userspace-networking

**The app tree** at `63470f1`, as cited in place.
