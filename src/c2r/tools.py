"""Eight strict tools the mediator may call. Python executes them and guards every apply.

The model chooses; nothing here trusts a number it wrote. ``apply_bundle`` refuses unless the
hash comes from a zero-violation verify of that bundle on the current schedule version and both
parties accepted it (C1, K2, K4). Free-text numbers are checked against tool results (K4).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from c2r.claims import numbers_in, state_delta, trim
from c2r.metrics import compute_metrics
from c2r.models import Mobility, ReasonCode, ReviewItem, TripStatus
from c2r.moves import _queued_returns, chair_changes, j_score, post_waits
from c2r.parties import broker, unit
from c2r.routing import Plan, plan_from_manifest
from c2r.solver import Candidate, Result, chain_bundle, generate_candidates
from c2r.state import State, actual_ready
from c2r.timeutil import to_hhmm
from c2r.verify import schedule_hash, verify

SIDES = ["unit", "broker", "both"]
OWNERS = ["social_worker", "charge_nurse", "dispatcher"]
URGENCY = ["now", "today", "this week"]


def _tool(name: str, description: str, properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
        "strict": True,
    }


TOOLS: list[dict[str, Any]] = [
    _tool(
        "get_state",
        "Current metrics, J, schedule version and hash, queued returns and the worst waits. "
        "Every number you cite must come from a tool result like this one.",
        {},
    ),
    _tool(
        "generate_candidates",
        "Top-k legal bundles by J for a side, plus one chained bundle of up to six accepted "
        "moves. Replaces the current candidate list.",
        {
            "side": {"type": "string", "enum": SIDES},
            "k": {"type": "integer", "minimum": 1, "maximum": 6},
        },
    ),
    _tool(
        "propose_to_unit",
        "Ask the unit party about a candidate bundle: accepted, or a reason code and a hint.",
        {"bundle_id": {"type": "string"}},
    ),
    _tool(
        "propose_to_broker",
        "Ask the broker party about a candidate bundle: accepted, or a reason code and a hint.",
        {"bundle_id": {"type": "string"}},
    ),
    _tool(
        "verify",
        "Verify the schedule that applying a candidate bundle would produce: violations, "
        "metrics and the verify_hash that apply_bundle requires.",
        {"bundle_id": {"type": "string"}},
    ),
    _tool(
        "apply_bundle",
        "Apply a verified, accepted bundle. Refused unless verify_hash comes from a "
        "zero-violation verify of this bundle on the current schedule version and both parties "
        "accepted it. Returns the state delta and the next candidates.",
        {
            "bundle_id": {"type": "string"},
            "verify_hash": {"type": "string"},
            "rationale": {
                "type": "string",
                "description": "Why this bundle. If it is not the lowest J, name the nurse "
                "note, caregiver window or equity reason.",
            },
        },
    ),
    _tool(
        "flag_for_review",
        "Queue a trip, patient or vehicle for a human with a reason code, what was tried, "
        "a recommended action and a draft message.",
        {
            "subject": {"type": "string"},
            "reason_code": {"type": "string", "enum": [r.value for r in ReasonCode]},
            "what_was_tried": {"type": "array", "items": {"type": "string"}},
            "recommended_action": {"type": "string"},
            "draft_message": {"type": "string"},
            "owner": {"type": "string", "enum": OWNERS},
            "urgency": {"type": "string", "enum": URGENCY},
        },
    ),
    _tool(
        "finish",
        "End the run with a two-sentence plain-language summary for the charge nurse.",
        {"summary": {"type": "string"}},
    ),
]


@dataclass
class Session:
    baseline: State
    state: State
    plan: Plan
    run: Result
    j: float
    version: int = 0
    iteration: int = 0
    candidates: dict[str, Candidate] = field(default_factory=dict)
    verified: dict[str, tuple[int, str]] = field(default_factory=dict)
    accepted: dict[str, set[str]] = field(default_factory=dict)
    rejected: list = field(default_factory=list)
    flagged: list[ReviewItem] = field(default_factory=list)
    known: set[str] = field(default_factory=set)
    finished: bool = False
    summary: str = ""
    on_apply: Callable[[Session], None] | None = None
    started: float = field(default_factory=time.monotonic)


def new_session(baseline: State) -> Session:
    plan = plan_from_manifest(baseline)
    result = verify(baseline, baseline)
    j = j_score(baseline, baseline, result.metrics, _queued_returns(baseline))
    run = Result(baseline, baseline, plan, result, j_before=j, j_after=j)
    return Session(baseline, baseline, plan, run, j)


# --- state views ---------------------------------------------------------------------------


def _metrics(state: State):
    return compute_metrics(state.roster, state.manifest, state.rules)


def _dump(candidate: Candidate) -> dict[str, Any]:
    bundle = candidate.bundle.model_dump(mode="json")
    bundle["j_after"] = candidate.j
    return bundle


def _stop(session: Session, best: Candidate | None) -> dict[str, Any]:
    stop = session.baseline.rules["stop"]
    state = session.state
    waits = post_waits(state)
    unserved = [
        t.trip_id
        for t in state.return_trips()
        if t.status == TripStatus.queued and state.patient_of(t).mobility != Mobility.stretcher
    ]
    metrics = _metrics(state)
    targets_met = bool(
        waits
        and not unserved
        and max(waits.values()) <= stop["target_post_wait"]
        and metrics.equity_gap <= stop["target_equity_gap"]
    )
    improvement = 0.0 if best is None else round((session.j - best.j) / session.j * 100, 2)
    below = best is None or improvement < stop["min_improvement_pct"]
    elapsed = round(time.monotonic() - session.started, 1)
    reasons = [
        why
        for ok, why in (
            (targets_met, "targets met and every non-stretcher return scheduled"),
            (below, f"best J gain {improvement:g}% is under {stop['min_improvement_pct']}%"),
            (elapsed > stop["max_wall_s"], "wall clock exceeded"),
        )
        if ok
    ]
    return {
        "targets_met": targets_met,
        "best_improvement_pct": improvement,
        "below_min_improvement": below,
        "elapsed_s": elapsed,
        "should_finish": bool(reasons),
        "reason": "; ".join(reasons),
    }


# --- the tools -----------------------------------------------------------------------------


def _get_state(session: Session, _: dict[str, Any]) -> dict[str, Any]:
    state = session.state
    waits = post_waits(state)
    trips = {t.trip_id: t for t in state.manifest.trips}
    worst = sorted(waits.items(), key=lambda kv: -kv[1])[:5]
    return {
        "schedule_version": session.version,
        "verify_hash": schedule_hash(state),
        "metrics": _metrics(state).model_dump(mode="json"),
        "j": session.j,
        "queued_returns": {
            t.trip_id: f"ready {to_hhmm(actual_ready(p))}, {p.mobility.value}"
            for t in state.return_trips()
            if t.status == TripStatus.queued and (p := state.patient_of(t))
        },
        "worst_waits": [
            {"trip_id": tid, "wait_min": w, "vehicle": trips[tid].vehicle_id} for tid, w in worst
        ],
        "chair_changes": chair_changes(state, session.baseline),
        "applied": [a["bundle"]["bundle_id"] for a in session.run.applied],
        "elapsed_s": round(time.monotonic() - session.started, 1),
    }


def _candidates(session: Session, side: str, k: int) -> dict[str, Any]:
    tag = f"I{session.iteration:02d}-"
    full = generate_candidates(session.baseline, session.state, session.plan, side, None, tag)
    chain = chain_bundle(session.baseline, session.state, session.plan, tag, full)
    chosen = ([chain] if chain else []) + full[:k]
    chosen.sort(key=lambda c: (c.j, len(c.bundle.touches), c.bundle.bundle_id))
    session.candidates = {c.bundle.bundle_id: c for c in chosen}
    session.verified.clear()
    session.accepted.clear()
    best = chosen[0] if chosen else None
    return {
        "schedule_version": session.version,
        "j_now": session.j,
        "candidates": [_dump(c) for c in chosen],
        "stop": _stop(session, best),
    }


def _generate(session: Session, args: dict[str, Any]) -> dict[str, Any]:
    side = args.get("side", "both")
    if side not in SIDES:
        return {"error": f"side must be one of {SIDES}"}
    return _candidates(session, side, int(args.get("k", 6)))


def _refuse(reason: str) -> dict[str, Any]:
    return {"applied": False, "reason": reason}


def _lookup(session: Session, args: dict[str, Any]) -> Candidate | dict[str, Any]:
    bid = str(args.get("bundle_id", ""))
    if bid not in session.candidates:
        return {"error": f"unknown bundle_id {bid!r}; it is not in the current candidate list"}
    return session.candidates[bid]


def _propose(party, name: str):
    def handler(session: Session, args: dict[str, Any]) -> dict[str, Any]:
        cand = _lookup(session, args)
        if isinstance(cand, dict):
            return cand
        reply = party.respond(session.baseline, cand.state, cand.bundle)
        bid = cand.bundle.bundle_id
        if reply.accepted:
            session.accepted.setdefault(bid, set()).add(name)
        else:
            session.rejected.append((name, cand.bundle, f"{reply.reason_code.value}: {reply.hint}"))
        return {
            "bundle_id": bid,
            "party": name,
            "accepted": reply.accepted,
            "reason_code": reply.reason_code.value if reply.reason_code else None,
            "hint": reply.hint,
        }

    return handler


def _verify(session: Session, args: dict[str, Any]) -> dict[str, Any]:
    cand = _lookup(session, args)
    if isinstance(cand, dict):
        return cand
    result = cand.result(session.baseline, session.version)
    if not result.violations:
        session.verified[cand.bundle.bundle_id] = (session.version, result.verify_hash)
    return {
        "bundle_id": cand.bundle.bundle_id,
        "schedule_version": session.version,
        "verify_hash": result.verify_hash,
        "violations": [v.model_dump(mode="json") for v in result.violations],
        "metrics": result.metrics.model_dump(mode="json"),
        "j_after": cand.j,
    }


def _apply(session: Session, args: dict[str, Any]) -> dict[str, Any]:
    cand = _lookup(session, args)
    if isinstance(cand, dict):
        return _refuse(cand["error"])
    bid = cand.bundle.bundle_id
    if session.baseline.rules["autonomy_level"] < 1:
        return _refuse("autonomy level 0: proposals only, nothing is applied")
    stamp = session.verified.get(bid)
    if stamp is None or stamp != (session.version, str(args.get("verify_hash", ""))):
        return _refuse(
            f"verify_hash does not match a zero-violation verify of {bid} on schedule "
            f"version {session.version}; call verify first"
        )
    missing = {"unit", "broker"} - session.accepted.get(bid, set())
    if missing:
        return _refuse(f"{', '.join(sorted(missing))} did not accept {bid}; propose to both first")
    before = session.state
    session.run.applied.append(
        {
            "step": len(session.run.applied) + 1,
            "bundle": cand.bundle.model_dump(mode="json"),
            "j_before": session.j,
            "j_after": cand.j,
            "rationale": str(args.get("rationale", "")),
        }
    )
    session.state, session.plan, session.j = cand.state, cand.plan, cand.j
    session.version += 1
    if session.on_apply:
        session.on_apply(session)
    following = _candidates(session, "both", 6)
    return {
        "applied": True,
        "bundle": cand.bundle.model_dump(mode="json"),
        "schedule_version": session.version,
        "verify_hash": schedule_hash(session.state),
        "metrics": cand.metrics.model_dump(mode="json"),
        "j": session.j,
        "delta": state_delta(before, session.state),
        "next_candidates": following["candidates"],
        "stop": following["stop"],
    }


def _flag(session: Session, args: dict[str, Any]) -> dict[str, Any]:
    state = session.state
    subjects = (
        {t.trip_id for t in state.manifest.trips}
        | set(state.patients)
        | {v.vehicle_id for v in state.fleet.vehicles}
    )
    subject = str(args.get("subject", ""))
    if subject not in subjects:
        return {"queued": False, "reason": f"unknown subject {subject!r}"}
    draft = str(args.get("draft_message", ""))
    if not draft.startswith("SYNTHETIC"):
        draft = f"SYNTHETIC: {draft}"
    try:
        item = ReviewItem(
            item_id=f"M{len(session.flagged) + 1:02d}",
            subject=subject,
            reason_code=ReasonCode(args["reason_code"]),
            what_was_tried=[str(x) for x in args.get("what_was_tried", [])],
            recommended_action=str(args.get("recommended_action", "")),
            draft_message=draft,
            owner=str(args.get("owner", "social_worker")),
            urgency=str(args.get("urgency", "today")),
        )
    except (KeyError, ValueError) as exc:
        return {"queued": False, "reason": f"invalid review item: {exc}"}
    session.flagged.append(item)
    return {"queued": True, "item_id": item.item_id, "subject": subject}


def _finish(session: Session, args: dict[str, Any]) -> dict[str, Any]:
    session.finished = True
    session.summary = str(args.get("summary", ""))
    return {"finished": True, "applied": len(session.run.applied), "flagged": len(session.flagged)}


HANDLERS: dict[str, Callable[[Session, dict[str, Any]], dict[str, Any]]] = {
    "get_state": _get_state,
    "generate_candidates": _generate,
    "propose_to_unit": _propose(unit, "unit"),
    "propose_to_broker": _propose(broker, "broker"),
    "verify": _verify,
    "apply_bundle": _apply,
    "flag_for_review": _flag,
    "finish": _finish,
}


def dispatch(session: Session, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Run one tool; every result is JSON, every number in it becomes a verified claim."""
    handler = HANDLERS.get(name)
    if handler is None:
        result: dict[str, Any] = {"error": f"unknown tool {name!r}"}
    else:
        result = trim(handler(session, dict(args or {})))
    session.known |= numbers_in(result)
    return result
