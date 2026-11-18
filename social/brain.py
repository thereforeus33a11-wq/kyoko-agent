"""Thin wrapper around a local Ollama model."""
from ollama import AsyncClient


class Brain:
    def __init__(self, model: str, system_prompt: str, host: str | None = None):
        self.model = model
        self.system_prompt = system_prompt
        self.client = AsyncClient(host=host)

    async def write(self, history: list[dict], instruction: str | None = None) -> str:
        messages = [{"role": "system", "content": self.system_prompt}, *history]
        if instruction:
            messages.append({"role": "system", "content": instruction})
        resp = await self.client.chat(model=self.model, messages=messages)
        text = resp["message"]["content"].strip()
        return text[:1900] or "…"  # Discord's message limit is 2000 chars
