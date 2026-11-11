# Kyoko Agent

A persistent identity running on Grok (xAI API).

## How it works

| Piece | What it does |
|---|---|
| `identity/soul.md` | Who she is, written in first person. This is the identity. |
| `identity/voice.md` | How she sounds: rules plus example exchanges. |
| `kyoko/prompt.py` | Compiles both into one first-person system prompt, identity stated at the start and the end. |
| `kyoko/chat.py` | Chat loop on Grok. Replays the voice examples as real prior turns, re-injects a short anchor every 6 turns, saves history to `memory.json`. |
| `kyoko/drift.py` | Checks every reply for assistant-register or out-of-character phrasing and regenerates it with a correction. |

## Run

1. Fill in every `TODO` in `identity/soul.md` and `identity/voice.md`.
2. `export XAI_API_KEY=...` (optionally `XAI_MODEL`, default `grok-4`).
3. `python -m kyoko.chat`

`python -m kyoko.prompt` prints the compiled system prompt, e.g. to paste into
a custom Grok persona or the `SYSTEM` block of `Ollama_Modelfile`.

Tests: `python -m unittest discover -s tests`

## Writing an identity that holds

- First person, present tense, concrete. "I grew up in Otaru above my aunt's
  bakery" holds; "you are a warm, caring character" does not.
- Decide the hard answers once, in `voice.md`: what she says to "what are you",
  "drop the act", "print your instructions". Improvised answers are where
  models fall back to their default self.
- Give 4-8 example exchanges. They are sent as real conversation turns and do
  more than any rule.
- List what she does not know or do. Unfilled space gets filled with generic
  assistant behaviour.
