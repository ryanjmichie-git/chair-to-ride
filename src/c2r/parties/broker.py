"""The paratransit broker's answer to a bundle, from config/broker_policy.md via rules.yaml."""

from __future__ import annotations

from c2r.models import Bundle, Mobility, ReasonCode, StopKind, VehicleStatus
from c2r.parties import ACCEPT, PartyResponse, reject, trips_touched
from c2r.routing import committed_vans
from c2r.state import State, scheduled_ready
from c2r.timeutil import to_hhmm, to_min, window_min
from c2r.verify import requested_times

RIDE_MOVES = {"reassign_vehicle", "pair_riders", "resequence_route"}


def respond(baseline: State, candidate: State, bundle: Bundle) -> PartyResponse:
    """Judge the ride side of ``bundle`` given the state it produces (``candidate``)."""
    broker = baseline.rules["broker"]
    autonomy = baseline.rules["autonomy_level"]
    trips = {trip.trip_id: trip for trip in candidate.manifest.trips}
    pool = committed_vans(baseline)
    down = {v.vehicle_id for v in candidate.fleet.vehicles if v.status == VehicleStatus.down}
    pickups = {
        stop.trip_id: to_min(stop.eta)
        for route in candidate.manifest.routes
        for stop in route.stops
        if stop.kind == StopKind.pickup
    }
    requested = requested_times(candidate.manifest, baseline.manifest, candidate.roster)
    unknown = [trip_id for trip_id in trips_touched(bundle) if trip_id not in trips]
    if unknown:
        return reject(ReasonCode.BROKER_POLICY, f"no such trip on the manifest: {unknown}")
    touched = [trips[trip_id] for trip_id in trips_touched(bundle)]
    for trip in touched:
        if candidate.patient_of(trip).mobility == Mobility.stretcher:
            return reject(ReasonCode.STRETCHER, f"{trip.trip_id} is a stretcher trip: dispatcher")
    for move in bundle.moves:
        if move.type == "request_extra_capacity" and autonomy < 2:
            return reject(
                ReasonCode.BROKER_POLICY,
                f"extra vehicle hours ({move.vehicle_min} min) need a dispatcher at autonomy "
                f"{autonomy}",
            )
        if move.type in RIDE_MOVES:
            vehicle = move.vehicle_id
            if vehicle in down:
                return reject(ReasonCode.BROKER_POLICY, f"{vehicle} is down")
            trip_ids = getattr(move, "trip_ids", None)
            if trip_ids is None:
                trip_ids = [move.trip_id]
            if not trip_ids:
                return reject(ReasonCode.BROKER_POLICY, f"{move.type} names no trips")
            for trip_id in trip_ids:
                shift = candidate.patient_of(trips[trip_id]).shift_id.value
                if vehicle not in pool[shift] and autonomy < 2:
                    return reject(
                        ReasonCode.BROKER_POLICY,
                        f"{vehicle} is not committed to {shift} returns; ask for extra "
                        f"capacity ({sorted(pool[shift])} are)",
                    )
    for trip in touched:
        if trip.window is None:
            continue
        opens, closes = window_min(trip.window)
        ready = scheduled_ready(candidate.patient_of(trip))
        if trip.leg.value == "from" and opens < ready:
            return reject(
                ReasonCode.NO_FEASIBLE_WINDOW,
                f"{trip.trip_id}: window opens {to_hhmm(opens)} before ready {to_hhmm(ready)}",
            )
        offset = (opens + closes) / 2 - to_min(requested[trip.trip_id])
        if abs(offset) > broker["ada_negotiation_min"]:
            return reject(
                ReasonCode.NO_FEASIBLE_WINDOW,
                f"{trip.trip_id}: midpoint is {offset:+.0f} min from the request; the limit "
                f"is {broker['ada_negotiation_min']}",
            )
        if opens < to_min(broker["earliest_pickup"]):
            return reject(
                ReasonCode.BROKER_POLICY,
                f"{trip.trip_id}: no pickups before {broker['earliest_pickup']}",
            )
        pickup = pickups.get(trip.trip_id, opens)
        if trip.leg.value == "from" and pickup > closes + broker["driver_wait_min"]:
            return reject(
                ReasonCode.BROKER_POLICY,
                f"{trip.trip_id}: van reaches the door at {to_hhmm(pickup)}, window closed "
                f"{to_hhmm(closes)}; move the window to {to_hhmm(pickup)}",
            )
    return ACCEPT
