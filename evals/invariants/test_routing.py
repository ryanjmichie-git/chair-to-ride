"""The route builder reproduces the baseline from its own plan and never invents a number."""

from __future__ import annotations

from pathlib import Path

import pytest

from c2r.models import Mobility, TripStatus
from c2r.routing import Batch, build_manifest, committed_vans, plan_from_manifest
from c2r.state import State, actual_ready, load_state
from c2r.timeutil import to_hhmm, to_min
from c2r.verify import verify

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "synthetic" / "42"


@pytest.fixture(scope="module")
def baseline() -> State:
    return load_state(DATA)


def shift_chair(baseline: State, patient_id: str, delta: int) -> State:
    roster = baseline.roster.model_copy(deep=True)
    patient = next(p for p in roster.patients if p.patient_id == patient_id)
    patient.start_time = to_hhmm(to_min(patient.start_time) + delta)
    plan = plan_from_manifest(baseline)
    trip_id = f"{patient_id}f"
    if trip_id in plan.opens:
        plan.opens[trip_id] += delta
        plan.not_before[trip_id] = plan.opens[trip_id]
    return baseline.with_(roster=roster, manifest=build_manifest(baseline, roster, plan))


def consenting_rider(baseline: State):
    return next(
        p
        for p in baseline.roster.patients
        if p.consent_to_move
        and not p.clinically_fixed
        and p.rider_id in baseline.broker_riders
        and p.mobility != Mobility.stretcher
        and f"{p.patient_id}f" in plan_from_manifest(baseline).opens
    )


def pickup_of(state: State, trip_id: str) -> int:
    return next(
        to_min(s.eta)
        for r in state.manifest.routes
        for s in r.stops
        if s.trip_id == trip_id and s.kind.value == "pickup"
    )


def test_rebuilding_the_baseline_from_its_own_plan_reproduces_it(baseline: State) -> None:
    plan = plan_from_manifest(baseline)
    rebuilt = build_manifest(baseline, baseline.roster, plan)
    assert rebuilt.model_dump(mode="json") == baseline.manifest.model_dump(mode="json")
    assert verify(baseline.with_(manifest=rebuilt), baseline).violations == []


def test_committed_vans_are_one_per_shift_on_seed_42(baseline: State) -> None:
    assert committed_vans(baseline) == {"S1": {"V1"}, "S2": {"V2"}, "S3": {"V3"}}


def test_a_window_moved_to_the_ready_time_cuts_that_riders_wait(baseline: State) -> None:
    plan = plan_from_manifest(baseline)
    trip = next(
        t
        for t in baseline.return_trips()
        if t.status == TripStatus.will_call and t.trip_id in plan.opens
    )
    ready = actual_ready(baseline.patient_of(trip))
    plan.remove(trip.trip_id)
    plan.batches.append(Batch("V1", [trip.trip_id]))
    plan.opens[trip.trip_id] = plan.not_before[trip.trip_id] = plan.requested[trip.trip_id] = ready
    plan.status[trip.trip_id] = TripStatus.scheduled
    candidate = baseline.with_(manifest=build_manifest(baseline, baseline.roster, plan))
    result = verify(candidate, baseline)
    assert pickup_of(candidate, trip.trip_id) - ready < 60
    assert {v.code.value for v in result.violations} <= {"H9"}


def test_a_chair_shift_moves_the_outbound_leg_with_it(baseline: State) -> None:
    patient = consenting_rider(baseline)
    candidate = shift_chair(baseline, patient.patient_id, 15)
    trip = next(t for t in candidate.manifest.trips if t.trip_id == f"{patient.patient_id}t")
    start = to_min(patient.start_time) + 15
    assert trip.window.root == [to_hhmm(start - 30), to_hhmm(start)]
    assert "H12" not in {v.code.value for v in verify(candidate, baseline).violations}


def test_a_standing_order_keeps_its_request_so_h7_still_bites(baseline: State) -> None:
    plan = plan_from_manifest(baseline)
    trip = next(t for t in baseline.return_trips() if t.status == TripStatus.scheduled)
    plan.opens[trip.trip_id] += 100
    plan.requested[trip.trip_id] += 100
    plan.not_before[trip.trip_id] = plan.opens[trip.trip_id]
    candidate = baseline.with_(manifest=build_manifest(baseline, baseline.roster, plan))
    rebuilt = next(t for t in candidate.manifest.trips if t.trip_id == trip.trip_id)
    assert rebuilt.requested_time == trip.requested_time
    assert "H7" in {v.code.value for v in verify(candidate, baseline).violations}


def test_plan_remove_queues_the_trip(baseline: State) -> None:
    plan = plan_from_manifest(baseline)
    trip = next(t for t in baseline.return_trips() if t.status == TripStatus.scheduled)
    plan.remove(trip.trip_id)
    assert trip.trip_id not in plan.opens and plan.batch_of(trip.trip_id) is None
    candidate = baseline.with_(manifest=build_manifest(baseline, baseline.roster, plan))
    rebuilt = next(t for t in candidate.manifest.trips if t.trip_id == trip.trip_id)
    assert rebuilt.status == TripStatus.queued
    assert verify(candidate, baseline).violations == []


def test_interleaved_pickups_and_dropoffs_stay_in_one_batch(baseline: State) -> None:
    manifest = baseline.manifest.model_copy(deep=True)
    route = next(r for r in manifest.routes if r.vehicle_id == "V1")
    stops = route.stops
    shared = next(
        i
        for i in range(len(stops) - 3)
        if stops[i].kind.value == "pickup"
        and stops[i + 1].kind.value == "pickup"
        and stops[i].node == 0
        and stops[i + 1].node == 0
    )
    # P pickup, Q pickup, P dropoff, Q dropoff  ->  P pickup, P dropoff, Q pickup, Q dropoff
    # is a different batching; the reader must follow the load, not the pickup run.
    stops[shared + 1], stops[shared + 2] = stops[shared + 2], stops[shared + 1]
    plan = plan_from_manifest(baseline.with_(manifest=manifest))
    first, second = stops[shared].trip_id, stops[shared + 2].trip_id
    assert plan.batch_of(first) is not plan.batch_of(second)
