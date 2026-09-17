"""The four ride-side hard constraints a manifest has to satisfy: H6, H9, H10, H12."""

from __future__ import annotations

from typing import Any

from c2r.models import Fleet, Leg, Manifest, Roster, StopKind, Travel, TripStatus
from c2r.timeutil import to_hhmm, to_min, window_min

Violations = list[tuple[str, str, str]]


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
    return {
        rider.rider_id: to_min(patients[rider.patient_id].start_time)
        + int(patients[rider.patient_id].rx_duration_min)
        + int(patients[rider.patient_id].recovery_buffer_min)
        for rider in roster.riders
    }


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


def h9_vehicle_inside_shift(manifest: Manifest, fleet: Fleet) -> Violations:
    shifts = {vehicle.vehicle_id: window_min(vehicle.shift) for vehicle in fleet.vehicles}
    found: Violations = []
    for route in manifest.routes:
        if not route.stops:
            continue
        opens, closes = shifts[route.vehicle_id]
        first = to_min(route.stops[0].eta)
        last = to_min(route.stops[-1].eta)
        if first < opens:
            found.append(("H9", route.vehicle_id, f"first stop {to_hhmm(first)} before shift"))
        if last > closes:
            found.append(("H9", route.vehicle_id, f"last stop {to_hhmm(last)} after shift"))
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


def h12_to_leg_arrives_in_window(manifest: Manifest) -> Violations:
    _, dropoffs = _etas(manifest)
    found: Violations = []
    for trip in manifest.trips:
        if trip.leg != Leg.to or trip.status != TripStatus.scheduled or trip.window is None:
            continue
        if trip.trip_id not in dropoffs:
            found.append(("H12", trip.trip_id, "scheduled but never dropped off"))
            continue
        opens, closes = window_min(trip.window)
        eta = dropoffs[trip.trip_id]
        if eta < opens or eta > closes:
            found.append(
                (
                    "H12",
                    trip.trip_id,
                    f"arrives {to_hhmm(eta)}, window {to_hhmm(opens)}-{to_hhmm(closes)}",
                )
            )
    return found


def ride_violations(
    roster: Roster, manifest: Manifest, fleet: Fleet, travel: Travel, rules: dict[str, Any]
) -> Violations:
    return [
        *h6_return_window_opens_after_ready(roster, manifest),
        *h9_vehicle_inside_shift(manifest, fleet),
        *h10_ride_within_cap(manifest, travel, rules),
        *h12_to_leg_arrives_in_window(manifest),
    ]
