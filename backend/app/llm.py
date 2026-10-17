"""Single entry point to Claude. Requires ANTHROPIC_API_KEY; there is no offline fallback."""
from __future__ import annotations

import json


def complete(s, prompt: str, max_tokens: int = 600, system: str | None = None) -> str:
    s.require("anthropic_api_key")
    import anthropic
    client = anthropic.Anthropic(api_key=s.anthropic_api_key)
    kwargs = {"model": s.anthropic_model, "max_tokens": max_tokens,
              "messages": [{"role": "user", "content": prompt}]}
    if system:
        kwargs["system"] = system
    msg = client.messages.create(**kwargs)
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()


def complete_json(s, prompt: str, max_tokens: int = 600, system: str | None = None) -> dict:
    text = complete(s, prompt, max_tokens, system)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError(f"model did not return JSON: {text[:200]}")
    return json.loads(text[start:end + 1])
