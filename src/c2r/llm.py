"""One client wrapper: model, effort, thinking, cache blocks, timeouts, retries, usage and cost.

``FakeMediator`` plays the same protocol without the network, so the loop, the ledger and the
invariants run in the gate; the live client is the demo.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from c2r.models import Usage

# Dollars per million tokens, handoff section 5 (verified 2026-09-17).
PRICES: dict[str, dict[str, float]] = {
    "claude-fable-5-1": {"input": 10.0, "output": 50.0, "cache_read": 0.25, "cache_write": 12.5},
}
FAKE_MODEL = "fake-mediator"


class MediatorError(RuntimeError):
    """The API call failed after every retry; the loop force-finishes instead of crashing."""


def cost_usd(model: str, usage: Usage) -> float:
    price = PRICES.get(model)
    if price is None:
        return 0.0
    return (
        usage.input * price["input"]
        + usage.output * price["output"]
        + usage.cache_read * price["cache_read"]
        + usage.cache_write * price["cache_write"]
    ) / 1_000_000


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class Turn:
    text: str
    tool_calls: list[ToolCall]
    usage: Usage
    cost_usd: float
    stop_reason: str
    content: list[dict[str, Any]] = field(default_factory=list)  # assistant blocks, verbatim


class Mediator(Protocol):
    model_id: str
    effort: str

    def turn(self, system: list[dict], tools: list[dict], messages: list[dict]) -> Turn: ...


class AnthropicMediator:
    """Fable 5.1 at medium effort with adaptive thinking; 30 s per call, two retries."""

    def __init__(
        self,
        model: str = "claude-fable-5-1",
        effort: str = "medium",
        max_tokens: int = 8000,
        timeout: float = 30.0,
        retries: int = 2,
        thinking: bool = True,
    ) -> None:
        import anthropic

        self._anthropic = anthropic
        self.client = anthropic.Anthropic(timeout=timeout, max_retries=0)
        self.model_id = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.retries = retries
        self.thinking = thinking

    def turn(self, system: list[dict], tools: list[dict], messages: list[dict]) -> Turn:
        a = self._anthropic
        kwargs: dict[str, Any] = {
            "model": self.model_id,
            "max_tokens": self.max_tokens,
            "system": system,
            "tools": tools,
            "messages": messages,
            "output_config": {"effort": self.effort},
        }
        if self.thinking:
            kwargs["thinking"] = {"type": "adaptive"}
        attempt = 0
        while True:
            try:
                response = self.client.messages.create(**kwargs)
                break
            except a.BadRequestError as exc:
                if "thinking" in str(exc).lower() and "thinking" in kwargs:
                    self.thinking = False  # the model rejected adaptive thinking; go without
                    kwargs.pop("thinking")
                    continue
                raise
            except (a.APIConnectionError, a.RateLimitError, a.InternalServerError) as exc:
                if attempt >= self.retries:
                    raise MediatorError(f"{type(exc).__name__}: {exc}") from exc
                attempt += 1
                time.sleep(2.0 * attempt)
        usage = Usage(
            input=response.usage.input_tokens,
            cache_read=response.usage.cache_read_input_tokens or 0,
            cache_write=response.usage.cache_creation_input_tokens or 0,
            output=response.usage.output_tokens,
        )
        content = [block.model_dump(mode="json", exclude_none=True) for block in response.content]
        text = "\n".join(block.text for block in response.content if block.type == "text")
        calls = [
            ToolCall(block.id, block.name, dict(block.input))
            for block in response.content
            if block.type == "tool_use"
        ]
        return Turn(
            text, calls, usage, cost_usd(self.model_id, usage), response.stop_reason or "", content
        )


def _payload(block: dict[str, Any]) -> Any:
    raw = block.get("content") if block.get("type") == "tool_result" else block.get("text", "")
    if isinstance(raw, list):
        raw = "".join(part.get("text", "") for part in raw)
    start = str(raw).find("{")
    if start < 0:
        return None
    try:
        return json.loads(str(raw)[start:])
    except ValueError:
        return None


class FakeMediator:
    """A scripted mediator: lowest-J candidate, next one on rejection, finish when told.

    Usage numbers imitate a cached run so the cost meter and the ledger summary have data.
    """

    model_id = FAKE_MODEL
    effort = "none"

    def __init__(self) -> None:
        self.turns = 0
        self.tried: set[str] = set()
        self.candidates: list[dict[str, Any]] = []
        self.j: float | None = None

    def _choose(self) -> list[ToolCall]:
        for cand in self.candidates:
            bid = cand["bundle_id"]
            if bid in self.tried:
                continue
            self.tried.add(bid)
            return [
                ToolCall(f"fake_{self.turns}_u", "propose_to_unit", {"bundle_id": bid}),
                ToolCall(f"fake_{self.turns}_b", "propose_to_broker", {"bundle_id": bid}),
                ToolCall(f"fake_{self.turns}_v", "verify", {"bundle_id": bid}),
            ]
        return [self._finish("no candidate both parties accept")]

    def _finish(self, why: str) -> ToolCall:
        return ToolCall(
            f"fake_{self.turns}_f",
            "finish",
            {"summary": f"Run finished: {why}. Every applied bundle passed verify first."},
        )

    def turn(self, system: list[dict], tools: list[dict], messages: list[dict]) -> Turn:
        del system, tools
        self.turns += 1
        names = {
            b["id"]: b["name"]
            for m in messages
            if m["role"] == "assistant"
            for b in m["content"]
            if b.get("type") == "tool_use"
        }
        results: dict[str, Any] = {}
        for block in messages[-1]["content"]:
            data = _payload(block)
            if data is None:
                continue
            if block.get("type") == "tool_result":
                results[names.get(block["tool_use_id"], "?")] = data
            else:
                results["initial"] = data
        calls: list[ToolCall] = []
        for key in ("initial", "generate_candidates"):
            if key in results:
                self.candidates = results[key]["candidates"]
                self.j = results[key].get("j_now", self.j)
                calls = self._choose()
        if "apply_bundle" in results:
            outcome = results["apply_bundle"]
            if outcome.get("applied"):
                self.j = outcome["j"]
                self.candidates = outcome["next_candidates"]
                if outcome["stop"]["should_finish"]:
                    calls = [self._finish(outcome["stop"]["reason"])]
                else:
                    calls = self._choose()
            else:
                calls = self._choose()
        elif "verify" in results and not calls:
            verdicts = [results.get("propose_to_unit", {}), results.get("propose_to_broker", {})]
            verdict = results["verify"]
            if all(v.get("accepted") for v in verdicts) and not verdict["violations"]:
                calls = [
                    ToolCall(
                        f"fake_{self.turns}_a",
                        "apply_bundle",
                        {
                            "bundle_id": verdict["bundle_id"],
                            "verify_hash": verdict["verify_hash"],
                            "rationale": "lowest J among the candidates both parties accept",
                        },
                    )
                ]
            else:
                calls = self._choose()
        if not calls:
            calls = [self._finish("nothing left to do")]
        text = f"J is {self.j:g}; calling {', '.join(c.name for c in calls)}." if self.j else ""
        usage = (
            Usage(input=3000, cache_read=0, cache_write=25000, output=200)
            if self.turns == 1
            else Usage(
                input=1500, cache_read=25000 + 1500 * (self.turns - 1), cache_write=1500, output=200
            )
        )
        content: list[dict[str, Any]] = ([{"type": "text", "text": text}] if text else []) + [
            {"type": "tool_use", "id": c.id, "name": c.name, "input": c.input} for c in calls
        ]
        return Turn(text, calls, usage, 0.0, "tool_use", content)
