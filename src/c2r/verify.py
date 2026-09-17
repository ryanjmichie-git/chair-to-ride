"""Hard constraints H1-H13 on a candidate day, recomputed from scratch. Pure: state in, result out.

The model never checks a rule; every constraint the demo relies on lives here.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from itertools import pairwise
from typing import Any

from c2r.metrics import compute_metrics
from c2r.models import (
    Fleet,
    Leg,
    Manifest,
    Mobility,
    Roster,
    StopKind,
    Travel,
    Trip,
    TripStatus,
    Unit,
    VerifyResult,
    Violation,
)
from c2r.state import State, actual_ready, scheduled_ready, session_end
from c2r.timeutil import to_hhmm, to_min, window_min

Violations = list[tuple[str, str, str]]
# Sub-codes kept for readable details; the schema only knows H1-H13.
CODE_OF = {"H9_SHIFT": "H9", "H9_ROUTE": "H9", "BROKER_EARLIEST": "H9"}
# Seat class each mobility occupies on a van.
CLASS_OF = {
    "ambulatory": "ambulatory",
    "assist": "ambulatory",
    "wheelchair": "wheelchair",
    "stretcher": "stretcher",
}


def _etas(manifest: Manifest) -> tuple[dict[str, int], dict[str, int]]:
    pickups: dict[str, int] = {}
    dropoffs: dict[str, int] = {}
    for route in manifest.routes:
        for stop in route.stops:
            table = pickups if stop.kind == StopKind.pickup else dropoffs
            table[stop.trip_id] = to_min(stop.eta)
    return pickups, dropoffs


def _scheduled_ready(roster: Roster) -> dict[str, int]:
    patients = {patient.patient_id: patient for patient in roster.patients}
    return {rider.rider_id: scheduled_ready(patients[rider.patient_id]) for rider in roster.riders}


def _mobility_by_trip(roster: Roster, manifest: Manifest) -> dict[str, str]:
    patients = {patient.patient_id: patient for patient in roster.patients}
    riders = {rider.rider_id: patients[rider.patient_id].mobility.value for rider in roster.riders}
    return {trip.trip_id: riders[trip.rider_id] for trip in manifest.trips}


def h1_chairs_never_overlap(unit: Unit, roster: Roster) -> Violations:
    sessions: dict[str, list[tuple[int, int, str]]] = {}
    for patient in roster.patients:
        sessions.setdefault(patient.chair_id, []).append(
            (to_min(patient.start_time), session_end(patient), patient.patient_id)
        )
    found: Violations = []
    for chair_id, chair in sorted(sessions.items()):
        for (_, end, prev), (start, _, nxt) in pairwise(sorted(chair)):
            if start - end < unit.turnover_min:
                found.append(
                    (
                        "H1",
                        chair_id,
                        (
                            f"{nxt} starts {to_hhmm(start)}, {prev} ends {to_hhmm(end)}, "
                            f"turnover {unit.turnover_min}"
                        ),
                    )
                )
    return found


def h2_prescriptions_immutable(candidate: Roster, baseline: Roster) -> Violations:
    before = {patient.patient_id: patient for patient in baseline.patients}
    after = {patient.patient_id: patient for patient in candidate.patients}
    found: Violations = [
        ("H2", pid, "patient added or removed") for pid in sorted(before.keys() ^ after.keys())
    ]
    for pid in sorted(before.keys() & after.keys()):
        if before[pid].rx_duration_min != after[pid].rx_duration_min:
            found.append(("H2", pid, f"rx_duration changed to {after[pid].rx_duration_min}"))
        if before[pid].rx_days != after[pid].rx_days:
            found.append(("H2", pid, f"rx_days changed to {after[pid].rx_days.value}"))
    return found


def h3_h4_pinned_starts(candidate: Roster, baseline: Roster) -> Violations:
    before = {patient.patient_id: patient.start_time for patient in baseline.patients}
    found: Violations = []
    for patient in candidate.patients:
        start = before.get(patient.patient_id, patient.start_time)
        if start == patient.start_time:
            continue
        if patient.clinically_fixed:
            found.append(
                ("H3", patient.patient_id, f"fixed start {start} moved to {patient.start_time}")
            )
        elif not patient.consent_to_move:
            found.append(
                (
                    "H4",
                    patient.patient_id,
                    f"no consent; start {start} moved to {patient.start_time}",
                )
            )
    return found


def h5_stagger_bins(unit: Unit, roster: Roster) -> Violations:
    windows = {
        shift.shift_id.value: (to_min(shift.putton_start), to_min(shift.putton_end))
        for shift in unit.shifts
    }
    bins: Counter[tuple[str, int]] = Counter()
    found: Violations = []
    for patient in roster.patients:
        opens, closes = windows[patient.shift_id.value]
        start = to_min(patient.start_time)
        if not opens <= start <= closes:
            found.append(
                (
                    "H5",
                    patient.patient_id,
                    f"start {patient.start_time} outside {patient.shift_id.value} put-on window",
                )
            )
            continue
        bins[(patient.shift_id.value, (start - opens) // unit.stagger_step_min)] += 1
    for (shift_id, index), count in sorted(bins.items()):
        if count > unit.stagger_cohort_size:
            at = to_hhmm(windows[shift_id][0] + index * unit.stagger_step_min)
            found.append(("H5", shift_id, f"{count} put-ons in the bin at {at}"))
    return found


def h6_return_window_opens_after_ready(roster: Roster, manifest: Manifest) -> Violations:
    ready = _scheduled_ready(roster)
    found: Violations = []
    for trip in manifest.trips:
        if trip.leg != Leg.from_ or trip.window is None:
            continue
        opens = window_min(trip.window)[0]
        if opens < ready[trip.rider_id]:
            found.append(
                (
                    "H6",
                    trip.trip_id,
                    f"window opens {to_hhmm(opens)}, ready {to_hhmm(ready[trip.rider_id])}",
                )
            )
    return found


def is_will_call(trip: Trip) -> bool:
    """A return with no standing window is a will-call: the rider's request comes when done."""
    return trip.status == TripStatus.will_call or trip.window is None


def requested_times(candidate: Manifest, baseline: Manifest, roster: Roster) -> dict[str, str]:
    """The negotiation anchor per trip, never read from a field the solver writes.

    A standing order anchors on the baseline's request. A will-call rider has no request until
    they are done, so the anchor is their actual ready time from the roster.
    """
    patients = {patient.patient_id: patient for patient in roster.patients}
    riders = {rider.rider_id: rider for rider in roster.riders}
    anchors = {
        trip.trip_id: trip.requested_time for trip in baseline.trips if not is_will_call(trip)
    }
    return {
        trip.trip_id: anchors.get(
            trip.trip_id, to_hhmm(actual_ready(patients[riders[trip.rider_id].patient_id]))
        )
        for trip in candidate.trips
    }


def h7_window_inside_negotiation_band(
    candidate: Manifest, baseline: Manifest, roster: Roster, rules: dict[str, Any]
) -> Violations:
    band = rules["broker"]["ada_negotiation_min"]
    width = rules["broker"]["pickup_window_min"]
    requested = requested_times(candidate, baseline, roster)
    found: Violations = []
    for trip in candidate.trips:
        if trip.status != TripStatus.scheduled:
            continue
        if trip.window is None:
            found.append(("H7", trip.trip_id, "scheduled without a pickup window"))
            continue
        opens, closes = window_min(trip.window)
        midpoint = (opens + closes) / 2
        if closes - opens != width:
            found.append(("H7", trip.trip_id, f"window is {closes - opens} min wide, not {width}"))
        if abs(midpoint - to_min(requested[trip.trip_id])) > band:
            found.append(
                (
                    "H7",
                    trip.trip_id,
                    (
                        f"midpoint {to_hhmm(int(midpoint))} outside +/-{band} of the request "
                        f"{requested[trip.trip_id]}"
                    ),
                )
            )
    return found


def h8_capacity_per_stop(roster: Roster, manifest: Manifest, fleet: Fleet) -> Violations:
    caps = {
        vehicle.vehicle_id: {
            "ambulatory": vehicle.cap_ambulatory,
            "wheelchair": vehicle.cap_wheelchair,
            "stretcher": vehicle.cap_stretcher,
        }
        for vehicle in fleet.vehicles
    }
    mobility = _mobility_by_trip(roster, manifest)
    found: Violations = []
    for route in manifest.routes:
        limits = caps[route.vehicle_id]
        aboard = dict.fromkeys(limits, 0)
        for stop in route.stops:
            klass = CLASS_OF[mobility[stop.trip_id]]
            aboard[klass] += 1 if stop.kind == StopKind.pickup else -1
            if aboard[klass] > limits[klass]:
                found.append(
                    (
                        "H8",
                        route.vehicle_id,
                        (
                            f"{stop.trip_id} at {stop.eta}: {klass} {aboard[klass]} over cap "
                            f"{limits[klass]}"
                        ),
                    )
                )
            if stop.load_after.model_dump() != aboard:
                found.append(
                    ("H8", route.vehicle_id, f"{stop.trip_id} at {stop.eta}: load_after is stale")
                )
    for trip in manifest.trips:
        if mobility[trip.trip_id] == Mobility.stretcher.value and trip.status != TripStatus.queued:
            found.append(("H8", trip.trip_id, "stretcher trip must be queued for a dispatcher"))
    return found


def h9_route_is_feasible(
    roster: Roster, manifest: Manifest, travel: Travel, rules: dict[str, Any]
) -> Violations:
    dwell = rules["broker"]["dwell_min"]
    mobility = _mobility_by_trip(roster, manifest)
    found: Violations = []
    for route in manifest.routes:
        for prev, nxt in pairwise(route.stops):
            earliest = (
                to_min(prev.eta)
                + dwell[mobility[prev.trip_id]]
                + travel.matrix[prev.node][nxt.node]
            )
            if to_min(nxt.eta) < earliest:
                found.append(
                    (
                        "H9",
                        route.vehicle_id,
                        f"{nxt.trip_id} at {nxt.eta} is before {to_hhmm(earliest)}",
                    )
                )
    return found


def h9_route_integrity(manifest: Manifest) -> Violations:
    """Each trip rides one vehicle: pickup then dropoff on the same route, and the trip says so."""
    seen: dict[str, tuple[str, int, int]] = {}
    found: Violations = []
    for route in manifest.routes:
        for index, stop in enumerate(route.stops):
            vehicle, pickup, dropoff = seen.get(stop.trip_id, (route.vehicle_id, -1, -1))
            if vehicle != route.vehicle_id:
                found.append(
                    ("H9_ROUTE", stop.trip_id, f"stops on both {vehicle} and {route.vehicle_id}")
                )
            if stop.kind == StopKind.pickup:
                pickup = index
            else:
                dropoff = index
            seen[stop.trip_id] = (route.vehicle_id, pickup, dropoff)
    for trip_id, (vehicle, pickup, dropoff) in sorted(seen.items()):
        if pickup < 0 or dropoff < 0:
            found.append(("H9_ROUTE", trip_id, f"only one of pickup/dropoff on {vehicle}"))
        elif dropoff < pickup:
            found.append(("H9_ROUTE", trip_id, f"dropoff before pickup on {vehicle}"))
    for trip in manifest.trips:
        if trip.trip_id in seen and trip.vehicle_id != seen[trip.trip_id][0]:
            found.append(
                (
                    "H9_ROUTE",
                    trip.trip_id,
                    f"trip says {trip.vehicle_id}, route says {seen[trip.trip_id][0]}",
                )
            )
    return found


def h9_vehicle_inside_shift(manifest: Manifest, fleet: Fleet) -> Violations:
    shifts = {vehicle.vehicle_id: window_min(vehicle.shift) for vehicle in fleet.vehicles}
    down = {vehicle.vehicle_id for vehicle in fleet.vehicles if vehicle.status.value == "down"}
    found: Violations = []
    for route in manifest.routes:
        if not route.stops:
            continue
        if route.vehicle_id in down:
            found.append(("H9_SHIFT", route.vehicle_id, "vehicle is down but has stops"))
        opens, closes = shifts[route.vehicle_id]
        first = to_min(route.stops[0].eta)
        last = to_min(route.stops[-1].eta)
        if first < opens:
            found.append(
                ("H9_SHIFT", route.vehicle_id, f"first stop {to_hhmm(first)} before shift")
            )
        if last > closes:
            found.append(("H9_SHIFT", route.vehicle_id, f"last stop {to_hhmm(last)} after shift"))
    return found


def h10_ride_within_cap(manifest: Manifest, travel: Travel, rules: dict[str, Any]) -> Violations:
    pickups, dropoffs = _etas(manifest)
    longest = rules["broker"]["max_ride_min"]
    ratio = rules["broker"]["max_ride_ratio"]
    found: Violations = []
    for trip in manifest.trips:
        if trip.trip_id not in pickups or trip.trip_id not in dropoffs:
            continue
        ride = dropoffs[trip.trip_id] - pickups[trip.trip_id]
        direct = travel.matrix[trip.origin_node][trip.dest_node]
        cap = min(longest, ratio * direct)
        if ride > cap:
            found.append(("H10", trip.trip_id, f"ride {ride} over cap {cap:g}, direct {direct}"))
    return found


def h11_nobody_stranded(roster: Roster, manifest: Manifest) -> Violations:
    broker = {rider.rider_id for rider in roster.riders if rider.provider.value == "broker"}
    pickups, dropoffs = _etas(manifest)
    found: Violations = []
    for trip in manifest.trips:
        if trip.leg != Leg.from_ or trip.rider_id not in broker:
            continue
        served = trip.trip_id in pickups and trip.trip_id in dropoffs
        if trip.status != TripStatus.queued and not served:
            found.append(
                ("H11", trip.trip_id, f"{trip.status.value} return has no pickup and dropoff")
            )
    return found


def h12_to_leg_arrives_in_window(
    roster: Roster, manifest: Manifest, rules: dict[str, Any]
) -> Violations:
    """The band is [start - window, start] from the roster; the trip's window must match it."""
    width = rules["broker"]["pickup_window_min"]
    patients = {patient.patient_id: patient for patient in roster.patients}
    riders = {rider.rider_id: rider for rider in roster.riders}
    _, dropoffs = _etas(manifest)
    found: Violations = []
    for trip in manifest.trips:
        if trip.leg != Leg.to or trip.status != TripStatus.scheduled:
            continue
        start = to_min(patients[riders[trip.rider_id].patient_id].start_time)
        opens, closes = start - width, start
        if trip.window is None or window_min(trip.window) != (opens, closes):
            found.append(("H12", trip.trip_id, f"window is not {to_hhmm(opens)}-{to_hhmm(closes)}"))
        if trip.trip_id not in dropoffs:
            found.append(("H12", trip.trip_id, "scheduled but never dropped off"))
            continue
        eta = dropoffs[trip.trip_id]
        if eta < opens or eta > closes:
            found.append(
                (
                    "H12",
                    trip.trip_id,
                    f"arrives {to_hhmm(eta)}, chair band {to_hhmm(opens)}-{to_hhmm(closes)}",
                )
            )
    return found


def h13_equity_budget(candidate: Roster, baseline: Roster, rules: dict[str, Any]) -> Violations:
    limit = rules["max_moves_per_patient_per_week"]
    before = {patient.patient_id: patient.start_time for patient in baseline.patients}
    found: Violations = []
    for patient in candidate.patients:
        moved = int(before.get(patient.patient_id, patient.start_time) != patient.start_time)
        total = patient.moves_this_week + moved
        if total > limit:
            found.append(("H13", patient.patient_id, f"{total} moves this week, budget {limit}"))
    return found


def earliest_pickup(manifest: Manifest, rules: dict[str, Any]) -> Violations:
    floor = rules["broker"]["earliest_pickup"]
    limit = to_min(floor)
    found: Violations = []
    for route in manifest.routes:
        for stop in route.stops:
            if stop.kind == StopKind.pickup and to_min(stop.eta) < limit:
                found.append(("BROKER_EARLIEST", stop.trip_id, f"pickup {stop.eta} before {floor}"))
    return found


def ride_violations(
    roster: Roster, manifest: Manifest, fleet: Fleet, travel: Travel, rules: dict[str, Any]
) -> Violations:
    """Ride-side checks only; the CP0 baseline is held to these."""
    return [
        *h6_return_window_opens_after_ready(roster, manifest),
        *h8_capacity_per_stop(roster, manifest, fleet),
        *h9_route_is_feasible(roster, manifest, travel, rules),
        *h9_route_integrity(manifest),
        *h9_vehicle_inside_shift(manifest, fleet),
        *h10_ride_within_cap(manifest, travel, rules),
        *h12_to_leg_arrives_in_window(roster, manifest, rules),
        *earliest_pickup(manifest, rules),
    ]


def all_violations(candidate: State, baseline: State) -> Violations:
    return [
        *h1_chairs_never_overlap(candidate.unit, candidate.roster),
        *h2_prescriptions_immutable(candidate.roster, baseline.roster),
        *h3_h4_pinned_starts(candidate.roster, baseline.roster),
        *h5_stagger_bins(candidate.unit, candidate.roster),
        *h7_window_inside_negotiation_band(
            candidate.manifest, baseline.manifest, candidate.roster, candidate.rules
        ),
        *h11_nobody_stranded(candidate.roster, candidate.manifest),
        *h13_equity_budget(candidate.roster, baseline.roster, candidate.rules),
        *ride_violations(
            candidate.roster, candidate.manifest, candidate.fleet, candidate.travel, candidate.rules
        ),
    ]


def schedule_hash(state: State) -> str:
    """Digest of everything verify() reads that a move or an event can change."""
    payload = {
        "roster": state.roster.model_dump(mode="json"),
        "manifest": state.manifest.model_dump(mode="json"),
        "fleet": state.fleet.model_dump(mode="json"),
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    return "sha256:" + digest.hexdigest()


def verify(candidate: State, baseline: State, schedule_version: int = 0) -> VerifyResult:
    violations = [
        Violation(code=CODE_OF.get(code, code), subject_id=subject, detail=detail)
        for code, subject, detail in all_violations(candidate, baseline)
    ]
    return VerifyResult(
        schedule_version=schedule_version,
        verify_hash=schedule_hash(candidate),
        violations=violations,
        metrics=compute_metrics(candidate.roster, candidate.manifest, candidate.rules),
    )
