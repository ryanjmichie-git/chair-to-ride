"""Rebuild a manifest from a return plan. Outbound legs are fixed blocks; returns are batches.

A Plan says, for every broker return: which van, which batch on that van, the window start
(``opens``), the earliest pickup (``not_before``) and the drop-off order inside the batch.
Everything else (ETAs, loads, windows, statuses, seq) is recomputed here, so the verifier never
has to trust a number the solver wrote.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from c2r.models import (
    Leg,
    Load,
    Manifest,
    Patient,
    Roster,
    Route,
    RouteStop,
    StopKind,
    TripStatus,
    Window,
)
from c2r.state import UNIT_NODE, State, actual_ready
from c2r.timeutil import to_hhmm, to_min, window_min
from c2r.verify import CLASS_OF, is_will_call

EMPTY = Load(ambulatory=0, wheelchair=0, stretcher=0)
Matrix = list[list[int]]
MIDNIGHT = 24 * 60


class Infeasible(ValueError):
    """The plan cannot be laid out inside the day; the caller treats it as illegal."""


@dataclass
class Batch:
    vehicle_id: str
    trip_ids: list[str]  # drop-off order


@dataclass
class Plan:
    batches: list[Batch] = field(default_factory=list)
    opens: dict[str, int] = field(default_factory=dict)  # window start, or will-call call time
    not_before: dict[str, int] = field(default_factory=dict)  # earliest the van may pick up
    requested: dict[str, int] = field(default_factory=dict)
    status: dict[str, TripStatus] = field(default_factory=dict)

    def copy(self) -> Plan:
        return copy.deepcopy(self)

    def batch_of(self, trip_id: str) -> Batch | None:
        return next((b for b in self.batches if trip_id in b.trip_ids), None)

    def remove(self, trip_id: str) -> None:
        """Take the trip out of the plan entirely: it becomes queued until re-scheduled."""
        for batch in self.batches:
            if trip_id in batch.trip_ids:
                batch.trip_ids.remove(trip_id)
        self.batches = [b for b in self.batches if b.trip_ids]
        for table in (self.opens, self.not_before, self.requested, self.status):
            table.pop(trip_id, None)


@dataclass
class _Task:
    start: int
    end: int
    start_node: int
    end_node: int
    stops: list[RouteStop]


def plan_from_manifest(state: State) -> Plan:
    """Read the baseline's own batching so J deltas are measured against the day as it is."""
    plan = Plan()
    returns = {trip.trip_id: trip for trip in state.return_trips()}
    for trip in returns.values():
        if trip.status == TripStatus.queued:
            continue
        opens = window_min(trip.window)[0] if trip.window else to_min(trip.requested_time)
        plan.opens[trip.trip_id] = opens
        plan.requested[trip.trip_id] = to_min(trip.requested_time)
        plan.status[trip.trip_id] = trip.status
    for route in state.manifest.routes:
        batch: Batch | None = None
        aboard = 0
        for stop in route.stops:
            if stop.trip_id not in returns:
                continue
            if stop.kind == StopKind.pickup:
                plan.not_before[stop.trip_id] = to_min(stop.eta)
                if batch is None:
                    batch = Batch(route.vehicle_id, [])
                    plan.batches.append(batch)
                aboard += 1
            elif batch is not None:
                batch.trip_ids.append(stop.trip_id)
                aboard -= 1
                if aboard == 0:
                    batch = None
    return plan


def committed_vans(state: State) -> dict[str, set[str]]:
    """Vans the baseline already sends for a shift's riders, either leg: the broker's commitment.

    Using one of them inside an opening is not extra vehicle hours; any other van is.
    """
    trips = {trip.trip_id: trip for trip in state.manifest.trips}
    pool: dict[str, set[str]] = {shift.shift_id.value: set() for shift in state.unit.shifts}
    for route in state.manifest.routes:
        for stop in route.stops:
            if stop.kind == StopKind.pickup:
                pool[state.patient_of(trips[stop.trip_id]).shift_id.value].add(route.vehicle_id)
    return pool


def _fixed_tasks(baseline: State, roster: Roster) -> dict[str, list[_Task]]:
    """Outbound legs as fixed blocks, shifted with their patient's chair start."""
    before = {p.patient_id: to_min(p.start_time) for p in baseline.roster.patients}
    after = {p.patient_id: to_min(p.start_time) for p in roster.patients}
    dwell = baseline.rules["broker"]["dwell_min"]
    trips = {trip.trip_id: trip for trip in baseline.manifest.trips}
    stops: dict[tuple[str, str], list[RouteStop]] = {}
    for route in baseline.manifest.routes:
        for stop in route.stops:
            trip = trips[stop.trip_id]
            if trip.leg != Leg.to:
                continue
            pid = baseline.patient_of(trip).patient_id
            eta = to_min(stop.eta) + after[pid] - before[pid]
            stops.setdefault((route.vehicle_id, trip.trip_id), []).append(
                stop.model_copy(update={"eta": to_hhmm(eta)})
            )
    tasks: dict[str, list[_Task]] = {}
    for (vehicle_id, trip_id), own in stops.items():
        mobility = baseline.patient_of(trips[trip_id]).mobility.value
        end = to_min(own[-1].eta) + dwell[mobility]
        tasks.setdefault(vehicle_id, []).append(
            _Task(to_min(own[0].eta), end, own[0].node, own[-1].node, own)
        )
    return tasks


def _window(opens: int, width: int) -> Window:
    return Window(root=[to_hhmm(opens), to_hhmm(opens + width)])


def _stop(trip_id: str, kind: StopKind, node: int, eta: int) -> RouteStop:
    if eta >= MIDNIGHT:
        raise Infeasible(f"{trip_id} {kind.value} would land after midnight")
    return RouteStop(trip_id=trip_id, kind=kind, node=node, eta=to_hhmm(eta), load_after=EMPTY)


def _with_loads(stops: list[RouteStop], mobility: dict[str, str]) -> list[RouteStop]:
    aboard = {"ambulatory": 0, "wheelchair": 0, "stretcher": 0}
    out: list[RouteStop] = []
    for stop in stops:
        aboard[CLASS_OF[mobility[stop.trip_id]]] += 1 if stop.kind == StopKind.pickup else -1
        out.append(stop.model_copy(update={"load_after": Load(**aboard)}))
    return out


@dataclass(frozen=True)
class _Geo:
    """Per-trip lookups the batch simulation needs."""

    target: dict[str, int]
    homes: dict[str, int]
    dwell: dict[str, int]
    matrix: Matrix


def _serve(batch: Batch, arrive: int, geo: _Geo) -> _Task:
    """Pick the batch up at the unit from ``arrive`` on, then drop off in the batch's order."""
    time, stops = arrive, []
    for trip_id in sorted(batch.trip_ids, key=lambda t: (geo.target[t], t)):
        time = max(time, geo.target[trip_id])
        stops.append(_stop(trip_id, StopKind.pickup, UNIT_NODE, time))
        time += geo.dwell[trip_id]
    node = UNIT_NODE
    for trip_id in batch.trip_ids:
        time += geo.matrix[node][geo.homes[trip_id]]
        node = geo.homes[trip_id]
        stops.append(_stop(trip_id, StopKind.dropoff, node, time))
        time += geo.dwell[trip_id]
    return _Task(to_min(stops[0].eta), time, UNIT_NODE, node, stops)


def _place(
    tasks: list[_Task], batch: Batch, shift: tuple[int, int], depot: int, geo: _Geo
) -> _Task:
    """First opening between the van's tasks where the batch fits; else after the last one."""
    timeline = sorted(tasks, key=lambda t: (t.start, t.end))
    heads = [(shift[0], depot)] + [(t.end, t.end_node) for t in timeline]
    tails = [(t.start, t.start_node) for t in timeline] + [(shift[1], None)]
    served = None
    for (prev_end, prev_node), (next_start, next_node) in zip(heads, tails, strict=True):
        served = _serve(batch, prev_end + geo.matrix[prev_node][UNIT_NODE], geo)
        deadhead = 0 if next_node is None else geo.matrix[served.end_node][next_node]
        if served.end + deadhead <= next_start:
            return served
    return served


def build_manifest(baseline: State, roster: Roster, plan: Plan) -> Manifest:
    """The candidate manifest for ``roster`` (chair starts) and ``plan`` (returns)."""
    broker: dict[str, Any] = baseline.rules["broker"]
    width = broker["pickup_window_min"]
    patients = {p.patient_id: p for p in roster.patients}
    riders = baseline.riders
    # Shallow copies: every field a move can change is reassigned below, never mutated in place.
    trips = {t.trip_id: t.model_copy() for t in baseline.manifest.trips}
    patient: dict[str, Patient] = {
        t.trip_id: patients[riders[t.rider_id].patient_id] for t in trips.values()
    }
    mobility = {trip_id: p.mobility.value for trip_id, p in patient.items()}
    geo = _Geo(
        target={
            trip_id: max(plan.not_before.get(trip_id, 0), opens, actual_ready(patient[trip_id]))
            for trip_id, opens in plan.opens.items()
        },
        homes={t.trip_id: riders[t.rider_id].home_node for t in trips.values()},
        dwell={trip_id: broker["dwell_min"][m] for trip_id, m in mobility.items()},
        matrix=baseline.travel.matrix,
    )
    vehicles = {v.vehicle_id: v for v in baseline.fleet.vehicles}
    tasks = _fixed_tasks(baseline, roster)
    ordered = sorted(
        plan.batches, key=lambda b: (min(geo.target[t] for t in b.trip_ids), b.trip_ids)
    )
    for batch in ordered:
        van = vehicles[batch.vehicle_id]
        own = tasks.setdefault(batch.vehicle_id, [])
        own.append(_place(own, batch, window_min(van.shift), van.depot_node, geo))
    will_call = {t.trip_id for t in baseline.manifest.trips if is_will_call(t)}
    for trip in baseline.return_trips():
        trip = trips[trip.trip_id]
        trip.vehicle_id, trip.seq = None, None
        trip.status = plan.status.get(trip.trip_id, TripStatus.queued)
        if trip.trip_id not in plan.status:
            continue  # queued: left exactly as the baseline had it
        trip.window = (
            _window(plan.opens[trip.trip_id], width)
            if trip.status == TripStatus.scheduled
            else None
        )
        if trip.trip_id in will_call:
            # A will-call rider has no request until they are done; the plan supplies it.
            trip.requested_time = to_hhmm(plan.requested[trip.trip_id])
    routes: list[Route] = []
    for vehicle_id in sorted(tasks):
        timeline = sorted(tasks[vehicle_id], key=lambda t: (t.start, t.end))
        stops = [stop for task in timeline for stop in task.stops]
        routes.append(Route(vehicle_id=vehicle_id, stops=_with_loads(stops, mobility)))
        for index, stop in enumerate(stops):
            if stop.kind == StopKind.pickup:
                trips[stop.trip_id].vehicle_id, trips[stop.trip_id].seq = vehicle_id, index
    for trip in trips.values():
        if trip.leg == Leg.to and trip.status == TripStatus.scheduled:
            trip.window = _window(to_min(patient[trip.trip_id].start_time) - width, width)
    return baseline.manifest.model_copy(update={"trips": list(trips.values()), "routes": routes})
