"""Ping each configured model and report whether structured outputs are accepted."""

from __future__ import annotations

import os
import sys

import anthropic

MODELS = ("claude-fable-5-1", "claude-sonnet-5", "claude-haiku-4-5-20251001")
STRUCTURED_MODEL = "claude-fable-5-1"
SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}


def _ping(client: anthropic.Anthropic, model: str) -> str:
    try:
        client.messages.create(
            model=model, max_tokens=5, messages=[{"role": "user", "content": "ping"}]
        )
    except anthropic.AnthropicError as exc:
        return f"error: {exc}"
    return "ok"


def _structured(client: anthropic.Anthropic) -> str:
    try:
        client.messages.create(
            model=STRUCTURED_MODEL,
            max_tokens=5,
            messages=[{"role": "user", "content": "ping"}],
            output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        )
    except TypeError:
        return "SDK lacks output_config; upgrade anthropic"
    except anthropic.AnthropicError as exc:
        return f"error: {exc}"
    return "structured outputs accepted"


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set — skipping model check")
        return 0
    client = anthropic.Anthropic()
    rows = [(model, _ping(client, model)) for model in MODELS]
    rows.append((f"{STRUCTURED_MODEL} (output_config)", _structured(client)))
    width = max(len(name) for name, _ in rows)
    for name, status in rows:
        print(f"{name:<{width}}  {status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
