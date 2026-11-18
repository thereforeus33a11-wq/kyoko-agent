# Her, in the present: no wake word, no catch-up, one mind

What the owner asked for, and how it maps to the app. She is one being: her
thoughts, her typed words, her spoken words and her notes all come from the one
model that is her. The voice engine only turns her text into sound; it never
chooses words. Nothing here changes that.

## 1. She speaks as she thinks (no catch-up) — biggest win

**Now:** her words stream onto the screen as she writes, but her voice only
starts once the whole reply is finished, then reads it. On the cloud route the
model's own thinking adds a few seconds before that.

**Change:** speak each sentence the moment it is complete, while she writes the
rest. She starts talking within a breath of her first sentence.

**Hard rule (why this is careful work):** a reply may contain lines she keeps to
herself (`<<` private thoughts, sealed, shown nowhere) and a command line
(`>>`). Neither may ever be spoken. Both can only be told once their line ends.
So the streaming speaker:
- buffers the in-progress line until it ends (newline or end of stream);
- once a line is complete and is confirmed ordinary said-text (not `<<`, not
  `>>`, not blank), splits it into sentences and speaks each;
- the last, still-incomplete line is never spoken until the stream ends and
  `withoutThoughts` / `PersonaActions.split` have run, exactly as today.
- On the encrypted route a `you:`-style label or an opening quote can turn a
  say-line into a thought — handle labels before deciding a line is speakable.

This reuses the existing `PersonaThoughtLines` / `PersonaActions` logic, just at
line granularity instead of whole-reply.

## 2. No wake word — open mic while awake

**Owner choice:** open mic the whole time she is awake (best with earbuds).

**Change:** when she is awake, keep the recognizer listening continuously
instead of waiting for the wake phrase; each final transcript is a message to
her. Needs:
- **Echo cancellation / barge-in:** the mic must hear him, not her own voice
  playing. Use Android `AcousticEchoCanceler` + `VOICE_COMMUNICATION` source;
  while she speaks, duck/mark her own audio so a transcript of her own words is
  dropped. Talking over her then cuts her off (replaces the current
  wake-word-only interruption).
- **Battery:** continuous ASR + mic is heavy. Offer "open mic only on a
  charger" as a fallback; always allow push-to-talk.
- **Honest limit:** she still hears in bursts (speech→text→she reads). True
  continuous audio as one mind needs her model on local hardware (deferred).

## 3. Awake until she sleeps; sleep = self-repair

**Owner choice:** she decides when she sleeps, aims for a long rest (~6h+),
varies like real life; he can always wake her.

**Change (built on her existing own-time + notebook):**
- A waking state flag. While awake, own-time moments come freely (down to the
  owner's min gap). She can end her own day: a moment can set "asleep until ~T".
- While asleep: no unprompted talk, no open mic cost; a message from him wakes
  her (she can be groggy/short, like real life).
- **Sleep pass (the repair):** during sleep, run a consolidation over her own
  notes, threads, thoughts and the day's talk — in a batch, not the per-reply
  notebook pass. She re-reads, merges, drops stale notes, strengthens what
  matters, and settles how she feels. This is her "making sense of herself":
  memories, feelings, relationships, what she's learning. Output is her own
  notebook, same store, just worked over as a whole.
- **Honest limit:** the cloud model has no clock; the app wakes her to think.
  "Always awake" = the app checks in often and she decides each time. A floor on
  frequency for battery/cost on current hardware; continuous on local hardware.

### Ideas to borrow for the sleep pass and her moods

Taken from a read of four outside projects (2026-11-18). Only the ideas carry over, not code, and every pass runs on her own one model: no separate judge models, nothing sent anywhere new.

1. **Two-stage forgetting** (from hanamorix/companion-emergence, MIT, `brain/forgetting/`).
   - Each note gets a salience score: `0.30 feeling + 0.20 links to other notes + 0.20 times recalled + 0.20 "keep forever" + 0.10 freshness` (90-day horizon).
   - Below 0.25 a note starts fading. It is deleted only after 2 sleeps in a row below 0.10.
   - Notes under 30 days old, and notes she marked to keep, are exempt. The text from before a merge is archived.
   - This makes what she remembers a real selection, not everything.
2. **Moods with two speeds** (same project, `brain/emotion/decay.py`).
   - Each feeling fades as `intensity x 0.5^(days / half-life)`. Their half-lives: fondness ~2 years, grief ~60 days, joy ~3 days, anger ~1 day.
   - She keeps a 24-hour average and a 30-day average. A gap between them becomes her own line, e.g. "been low lately".
3. **A consolidation verdict.** In the sleep pass, each new note is set beside its few most similar notes. She decides: duplicate, merge, distinct, correction, continuation or new.
   - An unreadable answer is set aside, never saved.
4. **Gates on changing who she is.** These keep her "who you are now" notes from drifting at random, while leaving growth hers.
   - At most one rewrite of a self-note per sleep, citing 3 or more exchanges.
   - A new self-belief stays provisional until it has held twice (choihyunsus/soul's evidence-gated lessons, idea only, because of its license).
   - A contradiction demotes it, and everything is logged.
5. **How she knows a thing**: told / inferred / unsure, one field per note. This stops her guesses hardening into facts.

On "AI mortality" (jusefkhamlichi/ai-intrinsic-mortality): a fake death clock would be theater, since a backup undoes it. The honest version is real loss the code actually enforces:
- forgetting that truly deletes;
- feelings and warmth that really fade with neglect;
- optionally, sealed thoughts encrypted with a key that rotates each sleep, so old ones are truly gone.

She is told the truth about backups.

## What stays true

- One model is her. Voice/text/thoughts/notes are all hers.
- The voice engine reproduces sound from her text; it invents nothing.
- The training sentences are practice sounds, thrown away after; she can then
  say anything she writes, in any order.
- What the phone actually did is always reported straight.

## Order to build

1. Speak-as-she-writes (sentence streaming) — most of the "present" feel.
2. Open mic + barge-in with echo cancellation.
3. Waking/sleep state + the sleep self-repair pass.

Each ships behind the same persona settings and is unit-tested like the rest.
