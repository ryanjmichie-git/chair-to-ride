"""One client wrapper: model, effort, thinking, cache blocks, timeouts, retries, usage and cost.

``AnthropicMediator`` drives the tool loop; ``AnthropicWriter`` makes one structured-output call
(explainer, judge). ``FakeMediator`` and ``FakeWriter`` play the same protocols without the
network, so the loop, the ledger and the invariants run in the gate; the live clients are the demo.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from c2r.models import Usage

# Dollars per million tokens: Fable 5.1 from handoff section 5 (verified 2026-09-17); Sonnet 5
# from the Claude API skill's model table (2026-09-17), cache read 0.1x and write 1.25x of input.
PRICES: dict[str, dict[str, float]] = {
    "claude-fable-5-1": {"input": 10.0, "output": 50.0, "cache_read": 0.25, "cache_write": 12.5},
    "claude-sonnet-5": {"input": 2.0, "output": 10.0, "cache_read": 0.2, "cache_write": 2.5},
}
FAKE_MODEL = "fake-mediator"


class MediatorError(RuntimeError):
    """The API call failed after every retry; the loop force-finishes instead of crashing."""


BATCH_DISCOUNT = 0.5  # the Message Batches API bills every token type at half the listed price


def cost_usd(model: str, usage: Usage, batch: bool = False) -> float:
    price = PRICES.get(model)
    if price is None:
        return 0.0
    dollars = (
        usage.input * price["input"]
        + usage.output * price["output"]
        + usage.cache_read * price["cache_read"]
        + usage.cache_write * price["cache_write"]
    ) / 1_000_000
    return dollars * BATCH_DISCOUNT if batch else dollars


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
        usage = _usage(response)
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


@dataclass
class Completion:
    data: dict[str, Any] | None  # the parsed JSON, or None on refusal, truncation or bad JSON
    text: str
    usage: Usage
    cost_usd: float
    stop_reason: str


class Writer(Protocol):
    model_id: str
    effort: str

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> Completion: ...


def _usage(response: Any) -> Usage:
    return Usage(
        input=response.usage.input_tokens,
        cache_read=response.usage.cache_read_input_tokens or 0,
        cache_write=response.usage.cache_creation_input_tokens or 0,
        output=response.usage.output_tokens,
    )


def _completion(model: str, response: Any, batch: bool = False) -> Completion:
    """A structured-output response as a Completion; bad JSON on end_turn is ``invalid_json``."""
    usage = _usage(response)
    text = "\n".join(block.text for block in response.content if block.type == "text")
    stop = response.stop_reason or ""
    data: dict[str, Any] | None = None
    if stop == "end_turn":
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        if not isinstance(data, dict):
            data, stop = None, "invalid_json"
    return Completion(data, text, usage, cost_usd(model, usage, batch), stop)


class AnthropicWriter:
    """One structured-output call: system + user -> JSON matching ``schema``.

    Thinking is left at the model's default (adaptive on Sonnet 5, always on for Fable 5.1);
    ``effort`` rides in ``output_config`` beside the JSON schema. A refusal or a truncated
    answer comes back with ``data=None`` and the stop reason; the caller decides what that means.
    """

    def __init__(
        self,
        model: str = "claude-sonnet-5",
        effort: str = "medium",
        max_tokens: int = 1500,
        timeout: float = 30.0,
        retries: int = 2,
    ) -> None:
        import anthropic

        self._anthropic = anthropic
        self.client = anthropic.Anthropic(timeout=timeout, max_retries=0)
        self.model_id = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.retries = retries

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> Completion:
        a = self._anthropic
        kwargs: dict[str, Any] = {
            "model": self.model_id,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "output_config": {
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": schema},
            },
        }
        attempt = 0
        while True:
            try:
                response = self.client.messages.create(**kwargs)
            except (a.APIConnectionError, a.RateLimitError, a.InternalServerError) as exc:
                if attempt >= self.retries:
                    raise MediatorError(f"{type(exc).__name__}: {exc}") from exc
                attempt += 1
                time.sleep(2.0 * attempt)
                continue
            done = _completion(self.model_id, response)
            if done.stop_reason == "invalid_json" and attempt < self.retries:
                attempt += 1  # the grammar should prevent this; ask once more
                continue
            return done


@dataclass
class BatchItem:
    custom_id: str
    system: str
    user: str
    schema: dict[str, Any]


class AnthropicBatchWriter:
    """Many structured-output calls as one Message Batch at half price.

    The system prompt is one cache block with a 1-hour TTL (a batch can take longer than the
    5-minute default). ``submit`` returns the batch id, ``status`` its processing state, and
    ``collect`` the completions keyed by custom_id, never by position. An errored, expired or
    canceled request comes back with ``data=None`` and that word as its stop reason.
    """

    batch = True

    def __init__(
        self,
        model: str = "claude-fable-5-1",
        effort: str = "low",
        max_tokens: int = 1200,
        cache_ttl: str = "1h",
    ) -> None:
        import anthropic

        self.client = anthropic.Anthropic(timeout=60.0, max_retries=2)
        self.model_id = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.cache_ttl = cache_ttl

    def _params(self, item: BatchItem) -> dict[str, Any]:
        return {
            "model": self.model_id,
            "max_tokens": self.max_tokens,
            "system": [
                {
                    "type": "text",
                    "text": item.system,
                    "cache_control": {"type": "ephemeral", "ttl": self.cache_ttl},
                }
            ],
            "messages": [{"role": "user", "content": item.user}],
            "output_config": {
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": item.schema},
            },
        }

    def submit(self, items: list[BatchItem]) -> str:
        created = self.client.messages.batches.create(
            requests=[{"custom_id": item.custom_id, "params": self._params(item)} for item in items]
        )
        return created.id

    def status(self, batch_id: str) -> dict[str, Any]:
        batch = self.client.messages.batches.retrieve(batch_id)
        return {
            "processing_status": batch.processing_status,
            "counts": batch.request_counts.model_dump(),
        }

    def collect(self, batch_id: str) -> dict[str, Completion]:
        zero = Usage(input=0, cache_read=0, cache_write=0, output=0)
        found: dict[str, Completion] = {}
        for result in self.client.messages.batches.results(batch_id):
            kind = result.result.type
            if kind == "succeeded":
                found[result.custom_id] = _completion(self.model_id, result.result.message, True)
            else:
                error = getattr(result.result, "error", None)
                text = f"{kind}: {getattr(error, 'type', '')} {getattr(error, 'message', '')}"
                found[result.custom_id] = Completion(None, text.strip(), zero, 0.0, kind)
        return found


def fake_explanation(card: dict[str, Any]) -> dict[str, str]:
    """Templated prose from a facts card: the offline explainer for the gate."""
    after, before = card.get("after") or {}, card.get("before") or {}
    event = card.get("event")
    window = after.get("pickup_window")
    ride = (
        f"Your ride home is booked between {window[0]} and {window[1]} on van {after['vehicle']}, "
        "from the unit door."
        if window and after.get("vehicle")
        else "Your ride home is not booked yet. The front desk will call you."
    )
    why_event = (
        f"Van {event['payload'].get('vehicle_id', '?')} broke down at {event['t']}, "
        "so your ride moved to another van."
        if event
        else "We moved the vans around so nobody waits long after treatment."
    )
    late = f"If the van is late, call {card['contact']}."
    if card["audience"] == "rider":
        return {
            "what_changed": f"Your chair time is {after.get('chair_start')}. {ride}",
            "why": f"{why_event} {late}",
            "contact": card["contact"],
        }
    if card["audience"] == "nurse":
        start = (
            f"chair start moved from {before.get('chair_start')} to {after.get('chair_start')}"
            if before.get("chair_start") != after.get("chair_start")
            else f"chair start stays {after.get('chair_start')}"
        )
        ride = (
            f"ride home window {window[0]} to {window[1]} on van {after['vehicle']}"
            if window and after.get("vehicle")
            else "ride home not yet booked"
        )
        return {
            "what_changed": f"{card['subject_id']} ({card.get('name')}): {start}; {ride}.",
            "why": f"{why_event} {late}",
            "contact": card["contact"],
        }
    item = card.get("review_item") or {}
    return {
        "what_changed": (
            f"{card['subject_id']} needs a person: {item.get('recommended_action', 'see the queue')}."
        ),
        "why": f"{item.get('reason_code', 'queued')}: the rules could not settle it. {late}",
        "contact": card["contact"],
    }


class FakeWriter:
    """The offline explainer: deterministic prose from the card; usage numbers are imitation."""

    model_id = FAKE_MODEL
    effort = "none"

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> Completion:
        del system, schema
        data = fake_explanation(json.loads(user))
        usage = Usage(input=1500, cache_read=0, cache_write=0, output=120)
        return Completion(data, json.dumps(data), usage, 0.0, "end_turn")


class FakeJudge:
    """The offline judge: 2 on every dimension; the deterministic overrides do the judging."""

    model_id = FAKE_MODEL
    effort = "none"
    DIMENSIONS = ("accuracy", "actionable", "plain", "tone", "complete", "safe")

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> Completion:
        del system, schema
        record = json.loads(user)
        data = {
            "explanation_id": record.get("explanation_id", "?"),
            "rationale": "fake judge: only the deterministic checks apply",
            "scores": {d: 2 for d in self.DIMENSIONS},
            "pass": True,
        }
        usage = Usage(input=2000, cache_read=0, cache_write=0, output=150)
        return Completion(data, json.dumps(data), usage, 0.0, "end_turn")


class FakeBatchWriter:
    """The offline batch: ``submit`` keeps the items, ``collect`` answers with the fake judge."""

    model_id = FAKE_MODEL
    effort = "none"
    batch = True

    def __init__(self) -> None:
        self.batches: dict[str, list[BatchItem]] = {}

    def submit(self, items: list[BatchItem]) -> str:
        batch_id = f"fake-batch-{len(self.batches) + 1}"
        self.batches[batch_id] = list(items)
        return batch_id

    def status(self, batch_id: str) -> dict[str, Any]:
        count = len(self.batches.get(batch_id, []))
        return {"processing_status": "ended", "counts": {"succeeded": count, "processing": 0}}

    def collect(self, batch_id: str) -> dict[str, Completion]:
        judge = FakeJudge()
        return {
            item.custom_id: judge.complete(item.system, item.user, item.schema)
            for item in self.batches.get(batch_id, [])
        }


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
