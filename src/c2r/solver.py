"""Greedy local search over bundles, the review queue, and the run artefacts.

The solver proposes; ``verify`` judges; the parties answer for their policies. No LLM here.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from c2r.banner import BANNER
from c2r.metrics import compute_metrics
from c2r.models import (
    Bundle,
    HoldForWillCall,
    Metrics,
    Mobility,
    Predicted,
    ReasonCode,
    ReviewItem,
    TripStatus,
    VerifyResult,
)
from c2r.moves import (
    _early_total,
    _moves,
    _pickups,
    _queued_returns,
    _touched_returns,
    _window_fixes,
    _window_move,
    _with_fixes,
    apply,
    chair_changes,
    honest_opens,
    j_score,
    post_waits,
)
from c2r.parties import broker, unit
from c2r.review import legal_options, review_queue
from c2r.routing import Infeasible, Plan, build_manifest, plan_from_manifest
from c2r.state import State, load_state
from c2r.verify import all_violations, verify


@dataclass
class Candidate:
    bundle: Bundle
    state: State
    plan: Plan
    metrics: Metrics
    j: float

    def result(self, baseline: State, version: int = 0) -> VerifyResult:
        """The full, hashed verify result; computed only for a bundle that is actually taken."""
        return verify(self.state, baseline, version)


@dataclass
class Result:
    baseline: State
    state: State
    plan: Plan
    result: VerifyResult
    applied: list[dict[str, Any]] = field(default_factory=list)
    review: list[ReviewItem] = field(default_factory=list)
    j_before: float = 0.0
    j_after: float = 0.0
    served: Metrics | None = None  # after the search, before any rider is held for will-call


def generate_candidates(
    baseline: State,
    state: State,
    plan: Plan,
    side: str = "both",
    k: int | None = 6,
    tag: str = "",
) -> list[Candidate]:
    """Top-k legal bundles by J, with predicted deltas from the real rebuilt state."""
    vehicle_before = compute_metrics(state.roster, state.manifest, state.rules).vehicle_min
    waits_before = sum(post_waits(state).values())
    early_before = _early_total(state)
    hypo = baseline.rules["recovery_buffer_min"]["hypotension"]
    found: list[Candidate] = []
    for index, (bundle_side, moves) in enumerate(_moves(baseline, state, plan, side)):
        bundle = Bundle(
            bundle_id=f"{tag}B{index + 1:03d}",
            side=bundle_side,
            moves=moves,
            predicted=Predicted(
                delta_wait_min=0, delta_early_min=0, chair_changes=0, consent_moves=0, vehicle_min=0
            ),
            touches=[],
            notes_relevant=[],
        )
        try:
            new_state, new_plan = apply(baseline, state, plan, bundle)
            fixes = _window_fixes(baseline, state, new_state, new_plan, bundle)
            if fixes:
                bundle = _with_fixes(bundle, fixes)
                new_state, new_plan = apply(baseline, state, plan, bundle)
        except Infeasible:
            continue
        if all_violations(new_state, baseline):
            continue
        metrics = compute_metrics(new_state.roster, new_state.manifest, new_state.rules)
        touched = sorted(
            {new_state.patient_of(t).patient_id for t in _touched_returns(new_state, bundle)}
        )
        changed = chair_changes(new_state, baseline)
        bundle.touches = touched
        bundle.predicted = Predicted(
            delta_wait_min=sum(post_waits(new_state).values()) - waits_before,
            delta_early_min=_early_total(new_state) - early_before,
            chair_changes=len([pid for pid in touched if pid in changed]),
            consent_moves=0,
            vehicle_min=int(metrics.vehicle_min - vehicle_before),
        )
        bundle.notes_relevant = [
            f"{pid}: hypotension_note"
            for pid in touched
            if int(new_state.patients[pid].recovery_buffer_min) == hypo
        ]
        j = j_score(new_state, baseline, metrics, _queued_returns(new_state))
        found.append(Candidate(bundle, new_state, new_plan, metrics, j))
    found.sort(key=lambda c: (c.j, len(c.bundle.touches), c.bundle.bundle_id))
    return found if k is None else found[:k]


def _first_accepted(
    baseline: State, candidates: list[Candidate], rejected: list
) -> Candidate | None:
    for candidate in candidates:
        reply_u = unit.respond(baseline, candidate.state, candidate.bundle)
        reply_b = broker.respond(baseline, candidate.state, candidate.bundle)
        if reply_u.accepted and reply_b.accepted:
            return candidate
        who, reply = ("unit", reply_u) if not reply_u.accepted else ("broker", reply_b)
        rejected.append((who, candidate.bundle, f"{reply.reason_code.value}: {reply.hint}"))
    return None


def solve(baseline: State) -> Result:
    """Greedy local search: the best bundle both parties accept, until J stops improving."""
    stop = baseline.rules["stop"]
    state, plan = baseline, plan_from_manifest(baseline)
    result = verify(state, baseline)
    j = j_score(state, baseline, result.metrics, _queued_returns(state))
    run = Result(baseline, state, plan, result, j_before=j, j_after=j)
    started = time.monotonic()
    rejected: list[tuple[str, Bundle, str]] = []
    candidates: list[Candidate] = []
    # One move per step here; a mediator round (CP2) applies up to max_moves_per_bundle moves.
    steps = stop["max_iterations"] * baseline.rules["max_moves_per_bundle"]
    for step in range(steps):
        if time.monotonic() - started > stop["max_wall_s"]:
            break
        candidates = generate_candidates(baseline, state, plan, k=None, tag=f"S{step + 1:02d}-")
        chosen = _first_accepted(baseline, candidates, rejected)
        if chosen is None or j - chosen.j < j * stop["min_improvement_pct"] / 100:
            break
        run.applied.append(
            {
                "step": step + 1,
                "bundle": chosen.bundle.model_dump(mode="json"),
                "j_before": j,
                "j_after": chosen.j,
            }
        )
        state, plan, metrics, j = chosen.state, chosen.plan, chosen.metrics, chosen.j
        waits = post_waits(state)
        unserved = [
            t
            for t in state.return_trips()
            if t.status == TripStatus.queued and state.patient_of(t).mobility != Mobility.stretcher
        ]
        if (
            waits
            and not unserved
            and max(waits.values()) <= stop["target_post_wait"]
            and metrics.equity_gap <= stop["target_equity_gap"]
        ):
            break
    state, plan, j = _retime_stale_windows(baseline, state, plan, run, rejected)
    run.served = compute_metrics(state.roster, state.manifest, state.rules)
    # Judge options on the final state, not on the last loop's stale candidate list.
    final = generate_candidates(baseline, state, plan, k=None, tag="F-")
    options = legal_options(baseline, state, final)
    run.review = review_queue(baseline, state, plan, rejected, options, j)
    holds = [
        item
        for item in run.review
        if item.reason_code == ReasonCode.NO_FEASIBLE_WINDOW and item.subject in plan.status
    ]
    for item in holds:  # the handoff's stop rule: still over 45 min -> queued, on the record
        plan.remove(item.subject)
        state = state.with_(manifest=build_manifest(baseline, state.roster, plan))
        new_j = j_score(
            state,
            baseline,
            compute_metrics(state.roster, state.manifest, state.rules),
            _queued_returns(state),
        )
        hold = HoldForWillCall(
            type="hold_for_will_call", trip_id=item.subject, reason=item.recommended_action
        )
        run.applied.append(
            {
                "step": len(run.applied) + 1,
                "bundle": _bundle(
                    f"H{len(run.applied) + 1:03d}",
                    "broker",
                    [hold],
                    [
                        state.patient_of(
                            next(t for t in state.manifest.trips if t.trip_id == item.subject)
                        ).patient_id
                    ],
                ).model_dump(mode="json"),
                "j_before": j,
                "j_after": new_j,
            }
        )
        j = new_j
    if holds:
        state, plan, j = _retime_stale_windows(baseline, state, plan, run, rejected)
    run.state, run.plan, run.result = state, plan, verify(state, baseline, len(run.applied))
    run.j_after = j_score(state, baseline, run.result.metrics, _queued_returns(state))
    return run


def _bundle(bundle_id: str, side: str, moves: list, touches: list[str]) -> Bundle:
    return Bundle(
        bundle_id=bundle_id,
        side=side,
        moves=moves,
        predicted=Predicted(
            delta_wait_min=0, delta_early_min=0, chair_changes=0, consent_moves=0, vehicle_min=0
        ),
        touches=touches,
        notes_relevant=[],
    )


def _retime_stale_windows(
    baseline: State, state: State, plan: Plan, run: Result, rejected: list
) -> tuple[State, Plan, float]:
    """Closing pass: promise every rider the window the van will actually keep.

    Usually J-neutral; a re-timing both parties accept is applied even if J moves a little,
    because a window the van cannot keep is a broken promise, not a saving.
    """
    width = baseline.rules["broker"]["pickup_window_min"]
    metrics = compute_metrics(state.roster, state.manifest, state.rules)
    j = j_score(state, baseline, metrics, _queued_returns(state))
    for trip in sorted(state.return_trips(), key=lambda t: t.trip_id):
        tid = trip.trip_id
        pickup = _pickups(state).get(tid)
        if pickup is None or plan.status.get(tid) != TripStatus.scheduled:
            continue
        opens = plan.opens[tid]
        if opens <= pickup <= opens + width:
            continue
        target = honest_opens(baseline, state.patient_of(trip), tid, pickup - width // 2)
        if target == opens:
            continue
        bundle = Bundle(
            bundle_id=f"W{len(run.applied) + 1:03d}",
            side="broker",
            moves=[_window_move(tid, target - opens)],
            predicted=Predicted(
                delta_wait_min=0, delta_early_min=0, chair_changes=0, consent_moves=0, vehicle_min=0
            ),
            touches=[state.patient_of(trip).patient_id],
            notes_relevant=[],
        )
        try:
            new_state, new_plan = apply(baseline, state, plan, bundle)
        except Infeasible:
            continue
        if all_violations(new_state, baseline):
            continue
        new_metrics = compute_metrics(new_state.roster, new_state.manifest, new_state.rules)
        new_j = j_score(new_state, baseline, new_metrics, _queued_returns(new_state))
        candidate = Candidate(bundle, new_state, new_plan, new_metrics, new_j)
        if _first_accepted(baseline, [candidate], rejected) is None:
            continue
        run.applied.append(
            {
                "step": len(run.applied) + 1,
                "bundle": bundle.model_dump(mode="json"),
                "j_before": j,
                "j_after": new_j,
            }
        )
        state, plan, j = new_state, new_plan, new_j
    return state, plan, j


def write_run(run: Result, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    def dump(name: str, payload: Any) -> None:
        (out_dir / name).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )

    for name, state in (("schedule_before.json", run.baseline), ("schedule_after.json", run.state)):
        dump(
            name,
            {
                "roster": state.roster.model_dump(mode="json"),
                "manifest": state.manifest.model_dump(mode="json"),
            },
        )
    dump("verify_after.json", run.result.model_dump(mode="json"))
    dump("bundles.json", run.applied)
    dump("review_queue.json", [item.model_dump(mode="json") for item in run.review])
    before = verify(run.baseline, run.baseline).metrics
    dump(
        "metrics.json",
        {
            "before": before.model_dump(mode="json"),
            "after": run.result.metrics.model_dump(mode="json"),
            "after_before_holds": run.served.model_dump(mode="json") if run.served else None,
            "j_before": run.j_before,
            "j_after": run.j_after,
        },
    )


def table(run: Result) -> str:
    before = verify(run.baseline, run.baseline).metrics.model_dump(mode="json")
    after = run.result.metrics.model_dump(mode="json")
    width = max(len(k) for k in before)
    lines = [BANNER, f"{'metric':<{width}}  {'before':>9}  {'after':>9}"]
    lines += [f"{k:<{width}}  {before[k]:>9g}  {after[k]:>9g}" for k in before]
    lines.append(f"{'J':<{width}}  {run.j_before:>9g}  {run.j_after:>9g}")
    if run.served is not None:
        lines.append(
            f"before holding anyone for will-call: mean {run.served.mean_post_wait:g}, "
            f"p90 {run.served.p90_post_wait:g}, flagged {run.served.riders_flagged}"
        )
    lines.append(
        f"bundles applied: {len(run.applied)}; review items: {len(run.review)}; violations: {len(run.result.violations)}"
    )
    return "\n".join(lines)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("data_dir")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    run = solve(load_state(Path(args.data_dir)))
    if args.out:
        write_run(run, Path(args.out))
    print(table(run))
    return 0 if not run.result.violations else 1


if __name__ == "__main__":
    raise SystemExit(main())
