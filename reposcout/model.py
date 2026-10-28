import asyncio
import os
from dataclasses import dataclass, field

from openai import APIConnectionError, APIStatusError, AsyncOpenAI


@dataclass
class Reply:
    content: str
    tool_calls: list = field(default_factory=list)
    tokens: int = 0
    model: str = ""


class Model:
    def __init__(self, models):
        key = os.getenv("OPENROUTER_API_KEY", "")
        if not key.startswith("sk-or-") or key == "sk-or-...":
            raise SystemExit("Add your OPENROUTER_API_KEY to .env")
        self.client = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=key, max_retries=0, timeout=90)
        self.models = [m for m in models if m]

    async def chat(self, messages, tools):
        error = None
        for model in self.models:
            for attempt in range(2):
                try:
                    r = await self.client.chat.completions.create(
                        model=model, messages=messages, temperature=0, **({"tools": tools} if tools else {}))
                    msg = r.choices[0].message
                    calls = [{"id": c.id, "name": c.function.name, "arguments": c.function.arguments or "{}"}
                             for c in msg.tool_calls or []]
                    return Reply(msg.content or "", calls, r.usage.total_tokens if r.usage else 0, model)
                except (APIStatusError, APIConnectionError, IndexError, TypeError) as e:
                    error = e
                    print(f"[{model} failed: {e}]")
                    if getattr(e, "status_code", None) in (400, 401, 403, 404):
                        break
                    await asyncio.sleep(3 * (attempt + 1))
        raise RuntimeError(f"All models failed: {error}")
