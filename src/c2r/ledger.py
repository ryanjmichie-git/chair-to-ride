"""The decision ledger: one JSON line per model turn, tool call, run start and finish.

Python writes every entry; the model cannot skip or forge one. The ledger replays to the
after-schedule (I18), proves every apply followed a clean verify (I19), and carries the token
usage the cost meter and the cache-share check (I20) read.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from c2r.models import Bundle, LedgerEntry, Usage
from c2r.moves import apply
from c2r.routing import plan_from_manifest
from c2r.state import State

ZERO = Usage(input=0, cache_read=0, cache_write=0, output=0)


@dataclass
class Ledger:
    path: Path
    run_id: str
    git_sha: str
    model_id: str
    effort: str
    prompt_versions: dict[str, int]
    input_hashes: dict[str, str]
    entries: list[LedgerEntry] = field(default_factory=list)

    def _write(self, entry: LedgerEntry) -> LedgerEntry:
        self.entries.append(entry)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(entry.model_dump(mode="json"), sort_keys=True) + "\n")
        return entry

    def _entry(
        self,
        iteration: int,
        actor: str,
        event: str,
        payload: dict[str, Any],
        usage: Usage = ZERO,
        cost_usd: float = 0.0,
    ) -> LedgerEntry:
        return LedgerEntry(
            ts=datetime.now(UTC).isoformat(timespec="seconds"),
            run_id=self.run_id,
            git_sha=self.git_sha,
            iteration=iteration,
            actor=actor,
            event=event,
            payload=payload,
            model_id=self.model_id,
            effort=self.effort,
            prompt_versions=self.prompt_versions,
            usage=usage,
            cost_usd=round(cost_usd, 6),
            input_hashes=self.input_hashes,
        )

    def start(self, payload: dict[str, Any]) -> LedgerEntry:
        return self._write(self._entry(0, "tool", "run_start", payload))

    def model_turn(
        self,
        iteration: int,
        text: str,
        tool_calls: list[dict[str, Any]],
        claims: list[str],
        unverified: list[str],
        usage: Usage,
        cost_usd: float,
        stop_reason: str,
    ) -> LedgerEntry:
        payload = {
            "text": text,
            "tool_calls": tool_calls,
            "claims": claims,
            "unverified": unverified,
            "stop_reason": stop_reason,
        }
        return self._write(self._entry(iteration, "model", "model_turn", payload, usage, cost_usd))

    def tool(
        self, iteration: int, name: str, tool_input: dict[str, Any], result: dict[str, Any]
    ) -> LedgerEntry:
        payload = {"input": tool_input, "result": result}
        return self._write(self._entry(iteration, "tool", name, payload))

    def finish(self, iteration: int, payload: dict[str, Any]) -> LedgerEntry:
        return self._write(self._entry(iteration, "tool", "finish", payload))


def read(path: Path) -> list[LedgerEntry]:
    return [
        LedgerEntry.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def applied_bundles(entries: list[LedgerEntry]) -> list[Bundle]:
    """Every bundle the run applied, in order: the model's applies, then the closing pass."""
    bundles = [
        Bundle.model_validate(e.payload["result"]["bundle"])
        for e in entries
        if e.event == "apply_bundle" and e.payload.get("result", {}).get("applied")
    ]
    closing = next(
        (e.payload.get("closing_bundles", []) for e in entries if e.event == "finish"), []
    )
    return bundles + [Bundle.model_validate(b) for b in closing]


def replay(baseline: State, entries: list[LedgerEntry]) -> State:
    """Fold every applied bundle over the baseline; the result must equal schedule_after.json."""
    state, plan = baseline, plan_from_manifest(baseline)
    for bundle in applied_bundles(entries):
        state, plan = apply(baseline, state, plan, bundle)
    return state


def cache_share(usage: Usage) -> float:
    total = usage.input + usage.cache_read + usage.cache_write
    return round(usage.cache_read / total, 4) if total else 0.0


def usage_summary(entries: list[LedgerEntry]) -> dict[str, Any]:
    """Tokens by type, cache-read share per model turn and overall, dollars, counts."""
    turns = [e for e in entries if e.actor == "model"]
    totals = Usage(
        input=sum(e.usage.input for e in turns),
        cache_read=sum(e.usage.cache_read for e in turns),
        cache_write=sum(e.usage.cache_write for e in turns),
        output=sum(e.usage.output for e in turns),
    )
    calls = [e for e in entries if e.actor == "tool" and e.event not in ("run_start", "finish")]
    proposals = {"unit": [0, 0], "broker": [0, 0]}
    for e in calls:
        side = {"propose_to_unit": "unit", "propose_to_broker": "broker"}.get(e.event)
        if side:
            proposals[side][0 if e.payload["result"].get("accepted") else 1] += 1
    return {
        "model_id": turns[0].model_id if turns else "",
        "effort": turns[0].effort if turns else "",
        "iterations": max((e.iteration for e in turns), default=0),
        "tokens": totals.model_dump(),
        "cache_read_share": cache_share(totals),
        "cache_read_share_by_iteration": {str(e.iteration): cache_share(e.usage) for e in turns},
        "cost_usd": round(sum(e.cost_usd for e in entries), 4),
        "tool_calls": len(calls),
        "bundles_applied": sum(
            1 for e in calls if e.event == "apply_bundle" and e.payload["result"].get("applied")
        ),
        "proposals_accepted_rejected": {k: tuple(v) for k, v in proposals.items()},
        "unverified_claims": sum(len(e.payload.get("unverified", [])) for e in turns),
    }
