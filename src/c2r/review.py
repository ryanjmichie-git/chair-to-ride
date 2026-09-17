"""The human-review queue: what the solver could not settle, with reason codes and a next step."""

from __future__ import annotations

from c2r.metrics import compute_metrics
from c2r.models import Mobility, ReasonCode, ReviewItem, TripStatus
from c2r.moves import _queued_returns, _touched_returns, j_score, post_waits
from c2r.parties import broker, unit
from c2r.routing import Plan
from c2r.state import State, actual_ready
from c2r.timeutil import to_hhmm

QUEUE_ABOVE_MIN = 45


def legal_options(baseline: State, state: State, candidates: list) -> dict[str, tuple[str, float]]:
    """For each still-queued return, the best legal bundle both parties accept, judged on the
    state the candidates were generated from (the final one)."""
    queued = {
        t.trip_id
        for t in state.return_trips()
        if t.status == TripStatus.queued and state.patient_of(t).mobility != Mobility.stretcher
    }
    options: dict[str, tuple[str, float]] = {}
    for candidate in candidates:
        after = {t.trip_id: t for t in candidate.state.manifest.trips}
        ids = {
            t.trip_id
            for t in _touched_returns(candidate.state, candidate.bundle)
            if t.trip_id in queued and after[t.trip_id].status == TripStatus.scheduled
        }
        if not ids - set(options):
            continue
        reply_u = unit.respond(baseline, candidate.state, candidate.bundle)
        reply_b = broker.respond(baseline, candidate.state, candidate.bundle)
        if not (reply_u.accepted and reply_b.accepted):
            continue
        for tid in sorted(ids - set(options)):
            options[tid] = (candidate.bundle.bundle_id, candidate.j)
    return options


def review_queue(
    baseline: State,
    state: State,
    plan: Plan,
    rejected,
    options: dict[str, tuple[str, float]],
    j: float,
) -> list[ReviewItem]:
    """One item per return the solver could not settle, plus the broker's capacity asks."""
    del plan
    j = j_score(
        state,
        baseline,
        compute_metrics(state.roster, state.manifest, state.rules),
        _queued_returns(state),
    )
    items: list[ReviewItem] = []
    waits = post_waits(state)
    for trip in state.return_trips():
        patient = state.patient_of(trip)
        tried = sorted(
            {
                b.bundle_id
                for _, b, _ in rejected
                if trip.trip_id in {m.trip_id for m in b.moves if hasattr(m, "trip_id")}
            }
        )
        if patient.mobility == Mobility.stretcher:
            items.append(
                _item(
                    len(items),
                    trip.trip_id,
                    ReasonCode.STRETCHER,
                    tried,
                    "book stretcher crew and equipment by hand",
                    "dispatcher",
                    "today",
                )
            )
        elif trip.trip_id in options:
            when = to_hhmm(actual_ready(patient))
            bundle_id, cost = options[trip.trip_id]
            items.append(
                _item(
                    len(items),
                    trip.trip_id,
                    ReasonCode.BROKER_POLICY,
                    [*tried, bundle_id],
                    f"a van for this return is legal but scores J {cost:g} against {j:g} for "
                    f"a hold (J counts wait, early wait and on-task vehicle minutes); ask the "
                    f"dispatcher for a van at {when} or hold for will-call",
                    "dispatcher",
                    "today",
                )
            )
        elif trip.status == TripStatus.queued or waits.get(trip.trip_id, 0) > QUEUE_ABOVE_MIN:
            when = to_hhmm(actual_ready(patient))
            items.append(
                _item(
                    len(items),
                    trip.trip_id,
                    ReasonCode.NO_FEASIBLE_WINDOW,
                    tried,
                    f"hold for will-call from {when}; confirm a ride by phone",
                    "social_worker",
                    "today",
                )
            )
    asks = {}
    for who, bundle, why in rejected:
        if who == "broker" and why.startswith("BROKER_POLICY") and "not committed" in why:
            van = bundle.moves[0].vehicle_id
            asks.setdefault(van, (bundle.bundle_id, why))
    for van, (bundle_id, why) in sorted(asks.items()):
        items.append(
            _item(
                len(items),
                van,
                ReasonCode.BROKER_POLICY,
                [bundle_id],
                f"ask the broker for {van} hours: {why.split(': ', 1)[1]}",
                "dispatcher",
                "this week",
            )
        )
    return items


def _item(
    n: int, subject: str, code: ReasonCode, tried: list[str], action: str, owner: str, urgency: str
) -> ReviewItem:
    return ReviewItem(
        item_id=f"R{n + 1:02d}",
        subject=subject,
        reason_code=code,
        what_was_tried=tried,
        recommended_action=action,
        draft_message=f"SYNTHETIC: {subject}: {action}.",
        owner=owner,
        urgency=urgency,
    )
