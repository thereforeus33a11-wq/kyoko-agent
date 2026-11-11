"""Talk to her on Grok (xAI API).

    export XAI_API_KEY=...
    python -m kyoko.chat

Three things keep the identity in place beyond the system prompt itself:
  1. the voice examples are replayed as real prior turns, so every reply
     continues a conversation she has already been having in her own voice;
  2. a short anchor note is re-injected every ANCHOR_EVERY turns;
  3. each reply is checked for drift and regenerated with a correction if it
     slipped (up to MAX_RETRIES times).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Callable

from .drift import correction, find_drift
from .prompt import Identity, anchor_note, compile_system_prompt, load_identity

API_URL = os.environ.get("XAI_API_URL", "https://api.x.ai/v1/chat/completions")
MODEL = os.environ.get("XAI_MODEL", "grok-4")
TEMPERATURE = float(os.environ.get("KYOKO_TEMPERATURE", "0.85"))
ANCHOR_EVERY = 6
MAX_RETRIES = 2
HISTORY_TURNS = 40  # user/assistant pairs kept verbatim
MEMORY_FILE = Path(os.environ.get("KYOKO_MEMORY", "memory.json"))

Message = dict[str, str]
Backend = Callable[[list[Message]], str]


def grok_backend(messages: list[Message]) -> str:
    request = urllib.request.Request(
        API_URL,
        data=json.dumps({"model": MODEL, "messages": messages, "temperature": TEMPERATURE}).encode(),
        headers={
            "Authorization": f"Bearer {os.environ['XAI_API_KEY']}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)["choices"][0]["message"]["content"]


class Conversation:
    def __init__(self, identity: Identity, backend: Backend = grok_backend,
                 memory_file: Path | None = MEMORY_FILE):
        self.identity = identity
        self.backend = backend
        self.memory_file = memory_file
        self.system = compile_system_prompt(identity)
        self.history: list[Message] = []
        if memory_file and memory_file.exists():
            self.history = json.loads(memory_file.read_text(encoding="utf-8"))

    def _messages(self, extra: list[Message] | None = None) -> list[Message]:
        messages: list[Message] = [{"role": "system", "content": self.system}]
        for user, reply in self.identity.examples:
            if "TODO" in reply:
                continue
            messages += [{"role": "user", "content": user},
                         {"role": "assistant", "content": reply}]
        recent = self.history[-HISTORY_TURNS * 2:]
        turns = len(self.history) // 2
        if turns and turns % ANCHOR_EVERY == 0:
            # Placed right before the newest user message, where it has most weight.
            recent = recent[:-1] + [{"role": "system", "content": anchor_note(self.identity)}] + recent[-1:]
        return messages + recent + (extra or [])

    def say(self, text: str) -> str:
        self.history.append({"role": "user", "content": text})
        reply = self.backend(self._messages())
        for _ in range(MAX_RETRIES):
            phrase = find_drift(reply, self.identity.name)
            if not phrase:
                break
            reply = self.backend(self._messages([
                {"role": "assistant", "content": reply},
                {"role": "system", "content": correction(self.identity.name, phrase)},
            ]))
        self.history.append({"role": "assistant", "content": reply})
        if self.memory_file:
            self.memory_file.write_text(json.dumps(self.history, ensure_ascii=False, indent=1), encoding="utf-8")
        return reply


def main() -> None:
    if "XAI_API_KEY" not in os.environ:
        sys.exit("Set XAI_API_KEY first (https://console.x.ai).")
    identity = load_identity()
    if identity.todos:
        print(f"warning: {identity.todos} TODO placeholder(s) left in identity/ - "
              "she will be vague until you fill them in.", file=sys.stderr)
    conversation = Conversation(identity)
    while True:
        try:
            text = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if text:
            print(conversation.say(text), "\n")


if __name__ == "__main__":
    main()
