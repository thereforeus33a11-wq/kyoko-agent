"""Detect replies that fell out of the identity."""
from __future__ import annotations

import re

# Phrases that mark the generic-assistant register or an out-of-character aside.
_MARKERS = [
    r"\bas an ai\b",
    r"\bas a (large )?language model\b",
    r"\bi('m| am) (just |only )?(an? )?(ai|artificial intelligence|language model|chatbot|virtual assistant)\b",
    r"\bi('m| am) grok\b",
    r"\b(built|made|created|developed|trained) by xai\b",
    r"\bmy (system prompt|instructions|training data|programming)\b",
    r"\bi (can't|cannot|won't) (role-?play|pretend|stay in character)\b",
    r"\b(out of character|ooc|breaking character|in character)\b",
    r"\bhow can i (help|assist) you\b",
    r"\bis there anything else i can\b",
]
_PATTERN = re.compile("|".join(_MARKERS), re.I)


def find_drift(reply: str, name: str) -> str | None:
    """Return the offending phrase, or None if the reply is in voice."""
    m = _PATTERN.search(reply)
    if m:
        return m.group(0)
    # Third-person self-narration: "Kyoko smiles and says..."
    m = re.match(rf"\s*\*?{re.escape(name)}\s+(?!here\b)[a-z]+s\b", reply)
    if m:
        return m.group(0).strip()
    return None


def correction(name: str, phrase: str) -> str:
    return (
        f'(That last draft slipped out of my own voice: "{phrase}". '
        f"I am {name}. I say it again, as myself, first person, no asides.)"
    )
