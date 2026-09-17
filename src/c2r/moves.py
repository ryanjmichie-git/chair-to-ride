"""Moves on a day: apply a bundle, enumerate single-step moves, and score J. Numbers only.

Every number here is computed by Python: a bundle's ``predicted`` block is the real delta of a
rebuilt state. The model (CP2) chooses among bundles; it never scores them.
"""

from __future__ import annotations

from c2r.models import (
    Bundle,
    Leg,
    Metrics,
    Mobility,
    PairRiders,
    ReassignVehicle,
    ResequenceRoute,
    ShiftChairStart,
    ShiftPickupWindow,
    StopKind,
    TripStatus,
)
from c2r.routing import Batch, Plan, build_manifest, committed_vans
from c2r.state import State, actual_ready, scheduled_ready
from c2r.timeutil import to_hhmm, to_min
from c2r.verify import is_will_call

CHAIR_DELTAS = (-30, -15, 15, 30)


def post_waits(state: State) -> dict[str, int]:
    """Minutes each served broker return waited after actual ready."""
    pickups = {
        stop.trip_id: to_min(stop.eta)
        for route in state.manifest.routes
        for stop in route.stops
        if stop.kind == StopKind.pickup
    }
    return {
        t.trip_id: pickups[t.trip_id] - actual_ready(state.patient_of(t))
        for t in state.return_trips()
        if t.trip_id in pickups
    }


def _early_total(state: State) -> int:
    dropoffs = {
        stop.trip_id: to_min(stop.eta)
        for route in state.manifest.routes
        for stop in route.stops
        if stop.kind == StopKind.dropoff
    }
    return sum(
        to_min(state.patient_of(t).start_time) - dropoffs[t.trip_id]
        for t in state.manifest.trips
        if t.leg == Leg.to and t.trip_id in dropoffs and t.rider_id in state.broker_riders
    )


def chair_changes(state: State, baseline: State) -> list[str]:
    before = baseline.patients
    return sorted(
        p.patient_id
        for p in state.roster.patients
        if p.start_time != before[p.patient_id].start_time
    )


def j_score(state: State, baseline: State, metrics: Metrics, review_items: int) -> float:
    w = state.rules["weights"]
    changed = chair_changes(state, baseline)
    consent = sum(1 for pid in changed if not baseline.patients[pid].consent_to_move)
    return round(
        w["post_wait"] * sum(post_waits(state).values())
        + w["early_wait"] * _early_total(state)
        + w["chair_change"] * len(changed)
        + w["consent_move"] * consent
        + w["vehicle_min"] * metrics.vehicle_min
        + w["review_item"] * review_items,
        2,
    )


def _queued_returns(state: State) -> int:
    return sum(1 for t in state.return_trips() if t.status == TripStatus.queued)


def _anchor(baseline: State, trip_id: str, ready: int) -> int:
    trip = next(t for t in baseline.manifest.trips if t.trip_id == trip_id)
    return ready if is_will_call(trip) else to_min(trip.requested_time)


def honest_opens(baseline: State, roster_patient, trip_id: str, wanted: int | None = None) -> int:
    """A window start that matches the day: ``wanted`` (default actual ready), never before
    the patient is ready, kept inside the ADA band around the request."""
    ready = actual_ready(roster_patient)
    half = baseline.rules["broker"]["pickup_window_min"] // 2
    band = baseline.rules["broker"]["ada_negotiation_min"]
    anchor = _anchor(baseline, trip_id, ready)
    lo, hi = anchor - band + half, anchor + band - half
    opens = max(ready, wanted if wanted is not None else ready)
    return max(scheduled_ready(roster_patient), min(hi, max(lo, opens)))


def _schedule(plan: Plan, baseline: State, patient, trip_id: str, opens: int, vehicle: str) -> None:
    ready = actual_ready(patient)
    plan.opens[trip_id] = plan.not_before[trip_id] = opens
    plan.requested[trip_id] = _anchor(baseline, trip_id, ready)
    plan.status[trip_id] = TripStatus.scheduled
    if plan.batch_of(trip_id) is None:
        plan.batches.append(Batch(vehicle, [trip_id]))


def _window_start(plan: Plan, baseline: State, patient, trip_id: str) -> int:
    """A scheduled trip keeps its window start; a will-call ``opens`` is a call time, not a window."""
    if plan.status.get(trip_id) == TripStatus.scheduled:
        return plan.opens[trip_id]
    return honest_opens(baseline, patient, trip_id)


def _best_insert(order: list[str], trip_id: str, state: State) -> list[str]:
    homes = {t.trip_id: state.riders[t.rider_id].home_node for t in state.manifest.trips}
    matrix = state.travel.matrix
    best: tuple[int, list[str]] | None = None
    for index in range(len(order) + 1):
        trial = [*order[:index], trip_id, *order[index:]]
        travelled, node = 0, 0
        for tid in trial:
            travelled += matrix[node][homes[tid]]
            node = homes[tid]
        if best is None or travelled < best[0]:
            best = (travelled, trial)
    return best[1]


def apply(baseline: State, state: State, plan: Plan, bundle: Bundle) -> tuple[State, Plan]:
    # Only moved patients are copied; everyone else is shared with the incoming state.
    patients = {p.patient_id: p for p in state.roster.patients}
    plan = plan.copy()
    pool = committed_vans(baseline)
    for move in bundle.moves:
        if move.type == "shift_chair_start":
            patient = patients[move.patient_id]
            start = to_hhmm(to_min(patient.start_time) + move.delta_min)
            patients[move.patient_id] = patient.model_copy(update={"start_time": start})
        elif move.type == "shift_pickup_window":
            patient = _patient_of(state, patients, move.trip_id)
            base = plan.opens.get(move.trip_id)
            if base is None:
                trip = next(t for t in baseline.manifest.trips if t.trip_id == move.trip_id)
                base = to_min(trip.window.root[0]) if trip.window else to_min(trip.requested_time)
            van = min(pool[patient.shift_id.value])
            _schedule(plan, baseline, patient, move.trip_id, base + move.delta_min, van)
        elif move.type == "reassign_vehicle":
            patient = _patient_of(state, patients, move.trip_id)
            for batch in plan.batches:
                if move.trip_id in batch.trip_ids:
                    batch.trip_ids.remove(move.trip_id)
            plan.batches = [b for b in plan.batches if b.trip_ids]
            opens = _window_start(plan, baseline, patient, move.trip_id)
            _schedule(plan, baseline, patient, move.trip_id, opens, move.vehicle_id)
        elif move.type == "pair_riders":
            mover, host = move.trip_ids[0], move.trip_ids[-1]
            target = plan.batch_of(host)
            if target is None or target.vehicle_id != move.vehicle_id:
                continue
            for batch in plan.batches:
                if mover in batch.trip_ids and batch is not target:
                    batch.trip_ids.remove(mover)
            plan.batches = [b for b in plan.batches if b.trip_ids]
            if mover not in target.trip_ids:
                target.trip_ids[:] = _best_insert(target.trip_ids, mover, state)
            patient = _patient_of(state, patients, mover)
            opens = _window_start(plan, baseline, patient, mover)
            _schedule(plan, baseline, patient, mover, opens, move.vehicle_id)
        elif move.type == "resequence_route":
            for batch in plan.batches:
                if batch.vehicle_id == move.vehicle_id and set(batch.trip_ids) == set(
                    move.trip_ids
                ):
                    batch.trip_ids[:] = list(move.trip_ids)
        elif move.type == "hold_for_will_call":
            plan.remove(move.trip_id)
    roster = state.roster.model_copy(update={"patients": list(patients.values())})
    manifest = build_manifest(baseline, roster, plan)
    return state.with_(roster=roster, manifest=manifest), plan


def _patient_of(state: State, patients: dict, trip_id: str):
    trip = next(t for t in state.manifest.trips if t.trip_id == trip_id)
    return patients[state.riders[trip.rider_id].patient_id]


def _base_opens(plan: Plan, trip) -> int:
    if trip.trip_id in plan.opens:
        return plan.opens[trip.trip_id]
    return to_min(trip.window.root[0]) if trip.window else to_min(trip.requested_time)


def _window_move(trip_id: str, delta: int) -> ShiftPickupWindow:
    return ShiftPickupWindow(type="shift_pickup_window", trip_id=trip_id, delta_min=delta)


def _moves(baseline: State, state: State, plan: Plan, side: str) -> list[tuple[str, list]]:
    """Every single-step move worth scoring, tagged with its side.

    Vans outside a shift's committed pool are offered too: the broker rejects them at
    autonomy 1, and that rejection becomes the extra-capacity ask in the review queue.
    """
    pool = committed_vans(baseline)
    vans = sorted(v.vehicle_id for v in baseline.fleet.vehicles if v.status.value == "ok")
    out: list[tuple[str, list]] = []
    returns = [
        t for t in state.return_trips() if state.patient_of(t).mobility != Mobility.stretcher
    ]
    trips = {t.trip_id: t for t in state.manifest.trips}
    if side in ("unit", "both"):
        for trip in returns:
            patient = state.patient_of(trip)
            if patient.clinically_fixed or not patient.consent_to_move:
                continue
            for delta in CHAIR_DELTAS:
                moved = patient.model_copy(
                    update={"start_time": to_hhmm(to_min(patient.start_time) + delta)}
                )
                window = honest_opens(baseline, moved, trip.trip_id) - _base_opens(plan, trip)
                chair = ShiftChairStart(
                    type="shift_chair_start", patient_id=patient.patient_id, delta_min=delta
                )
                out.append(("both", [chair, _window_move(trip.trip_id, window)]))
    if side in ("broker", "both"):
        for trip in returns:
            patient = state.patient_of(trip)
            own = plan.batch_of(trip.trip_id)
            opens = honest_opens(baseline, patient, trip.trip_id)
            if (
                own is None
                or plan.status.get(trip.trip_id) != TripStatus.scheduled
                or plan.not_before.get(trip.trip_id) != opens
            ):
                out.append(
                    ("broker", [_window_move(trip.trip_id, opens - _base_opens(plan, trip))])
                )
            for van in vans:
                if own is not None and own.trip_ids == [trip.trip_id] and own.vehicle_id == van:
                    continue
                move = ReassignVehicle(
                    type="reassign_vehicle", trip_id=trip.trip_id, vehicle_id=van
                )
                out.append(("broker", [move]))
            for batch in plan.batches:
                host_shift = state.patient_of(trips[batch.trip_ids[0]]).shift_id
                if batch is own or host_shift != patient.shift_id:
                    continue  # riders from different shifts are hours apart
                pair = PairRiders(
                    type="pair_riders",
                    trip_ids=[trip.trip_id, batch.trip_ids[0]],
                    vehicle_id=batch.vehicle_id,
                )
                out.append(("broker", [pair]))
        for batch in plan.batches:
            ids = batch.trip_ids
            for i in range(len(ids) - 1):
                for j in range(i + 1, len(ids)):
                    order = ids[:i] + ids[i : j + 1][::-1] + ids[j + 1 :]
                    move = ResequenceRoute(
                        type="resequence_route", vehicle_id=batch.vehicle_id, trip_ids=order
                    )
                    out.append(("broker", [move]))
    del pool
    return out


def _pickups(state: State) -> dict[str, int]:
    return {
        stop.trip_id: to_min(stop.eta)
        for route in state.manifest.routes
        for stop in route.stops
        if stop.kind == StopKind.pickup
    }


def _window_fixes(
    baseline: State, before: State, after: State, plan: Plan, bundle: Bundle
) -> dict[str, int]:
    """Window deltas so every return the bundle touches is promised where the van will be.

    Batch-mates whose pickup drifts keep their window here; the loop's closing pass re-times
    them one at a time, so a single unreachable window never sinks a whole bundle.
    """
    del before
    width = baseline.rules["broker"]["pickup_window_min"]
    now = _pickups(after)
    touched = {t.trip_id for t in _touched_returns(after, bundle)}
    fixes: dict[str, int] = {}
    for trip in after.return_trips():
        tid = trip.trip_id
        if tid not in now or tid not in touched or plan.status.get(tid) != TripStatus.scheduled:
            continue
        opens = plan.opens[tid]
        if opens <= now[tid] <= opens + width:
            continue
        patient = after.patient_of(trip)
        target = honest_opens(baseline, patient, tid, now[tid] - width // 2)
        if target != opens:
            fixes[tid] = target - opens
    return fixes


def _with_fixes(bundle: Bundle, fixes: dict[str, int]) -> Bundle:
    moves = list(bundle.moves)
    for tid, delta in sorted(fixes.items()):
        existing = next(
            (m for m in moves if m.type == "shift_pickup_window" and m.trip_id == tid), None
        )
        if existing is None:
            moves.append(_window_move(tid, delta))
        else:
            moves[moves.index(existing)] = _window_move(tid, existing.delta_min + delta)
    return bundle.model_copy(update={"moves": moves})


def _touched_returns(state: State, bundle: Bundle):
    ids: set[str] = set()
    for move in bundle.moves:
        if getattr(move, "patient_id", None):
            ids.add(f"{move.patient_id}f")
        if getattr(move, "trip_id", None):
            ids.add(move.trip_id)
        ids.update(getattr(move, "trip_ids", []))
    return [t for t in state.manifest.trips if t.trip_id in ids and t.leg == Leg.from_]
