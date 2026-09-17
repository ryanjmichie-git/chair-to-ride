"""verify() is never vacuous: every code H1-H13 fires on a broken day and stays quiet on a legal one."""

from __future__ import annotations

from pathlib import Path

import pytest

from c2r.models import (
    Leg,
    Load,
    Mobility,
    RxDurationMin,
    StopKind,
    TripStatus,
    VehicleStatus,
    ViolationCode,
    Window,
)
from c2r.state import State, load_state, scheduled_ready
from c2r.timeutil import to_hhmm, to_min
from c2r.verify import verify

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "synthetic" / "42"


@pytest.fixture(scope="module")
def baseline() -> State:
    return load_state(DATA)


@pytest.fixture
def day(baseline: State) -> State:
    return baseline.with_(
        roster=baseline.roster.model_copy(deep=True),
        manifest=baseline.manifest.model_copy(deep=True),
        fleet=baseline.fleet.model_copy(deep=True),
    )


def codes(candidate: State, baseline: State) -> set[str]:
    return {violation.code.value for violation in verify(candidate, baseline).violations}


def _patient(day: State, **flags: bool):
    return next(p for p in day.roster.patients if all(getattr(p, k) == v for k, v in flags.items()))


def _scheduled_return(day: State):
    return next(
        t for t in day.return_trips() if t.status == TripStatus.scheduled and t.window is not None
    )


def _stop(day: State, trip_id: str, kind: StopKind):
    return next(
        s for r in day.manifest.routes for s in r.stops if s.trip_id == trip_id and s.kind == kind
    )


def test_baseline_is_legal_on_every_code(baseline: State) -> None:
    result = verify(baseline, baseline, schedule_version=0)
    assert result.violations == []
    assert all(code in ViolationCode for code in ["H1", "H7", "H13"])
    assert result.verify_hash.startswith("sha256:")
    assert result.metrics.mean_post_wait > 60


def test_verify_is_pure_and_hash_tracks_the_schedule(baseline: State, day: State) -> None:
    assert verify(day, baseline) == verify(day, baseline)
    assert verify(day, baseline).verify_hash == verify(baseline, baseline).verify_hash
    patient = _patient(day, clinically_fixed=False, consent_to_move=True)
    patient.start_time = to_hhmm(to_min(patient.start_time) + 15)
    assert verify(day, baseline).verify_hash != verify(baseline, baseline).verify_hash


def test_h1_overlap_on_a_chair(baseline: State, day: State) -> None:
    first, second = sorted(
        (p for p in day.roster.patients if p.chair_id == "C01"), key=lambda p: p.start_time
    )[:2]
    second.start_time = to_hhmm(to_min(first.start_time) + int(first.rx_duration_min))
    assert "H1" in codes(day, baseline)


def test_h2_prescription_changed(baseline: State, day: State) -> None:
    patient = day.roster.patients[0]
    patient.rx_duration_min = (
        RxDurationMin.integer_210
        if patient.rx_duration_min != RxDurationMin.integer_210
        else RxDurationMin.integer_240
    )
    assert "H2" in codes(day, baseline)


def test_h3_fixed_patient_moved(baseline: State, day: State) -> None:
    patient = _patient(day, clinically_fixed=True)
    patient.start_time = to_hhmm(to_min(patient.start_time) + 15)
    assert "H3" in codes(day, baseline)


def test_h4_non_consenting_patient_moved(baseline: State, day: State) -> None:
    patient = _patient(day, clinically_fixed=False, consent_to_move=False)
    patient.start_time = to_hhmm(to_min(patient.start_time) + 15)
    assert "H4" in codes(day, baseline)


def test_h5_bin_overloaded_and_start_outside_window(baseline: State, day: State) -> None:
    cohort = [p for p in day.roster.patients if p.shift_id.value == "S1"]
    for patient in cohort[:5]:
        patient.start_time = "06:00"
    assert "H5" in codes(day, baseline)
    cohort[0].start_time = "09:00"
    assert any(
        "outside" in v.detail and v.code.value == "H5" for v in verify(day, baseline).violations
    )


def test_h6_window_opens_before_ready(baseline: State, day: State) -> None:
    trip = _scheduled_return(day)
    ready = scheduled_ready(day.patient_of(trip))
    trip.window = Window(root=[to_hhmm(ready - 20), to_hhmm(ready + 10)])
    assert "H6" in codes(day, baseline)


def test_h7_window_too_wide_or_outside_negotiation_band(baseline: State, day: State) -> None:
    trip = _scheduled_return(day)
    opens = to_min(trip.window.root[0])
    trip.window = Window(root=[to_hhmm(opens), to_hhmm(opens + 45)])
    assert "H7" in codes(day, baseline)
    trip.window = Window(root=[to_hhmm(opens + 90), to_hhmm(opens + 120)])
    assert "H7" in codes(day, baseline)


def test_h8_capacity_and_stretcher(baseline: State, day: State) -> None:
    stop = day.manifest.routes[0].stops[0]
    stop.load_after = Load(ambulatory=9, wheelchair=0, stretcher=0)
    assert "H8" in codes(day, baseline)
    stretcher = next(
        t for t in day.manifest.trips if day.patient_of(t).mobility == Mobility.stretcher
    )
    stretcher.status = TripStatus.scheduled
    assert any(
        "stretcher" in v.detail and v.code.value == "H8" for v in verify(day, baseline).violations
    )


def test_h9_infeasible_timing_and_outside_shift(baseline: State, day: State) -> None:
    route = day.manifest.routes[0]
    route.stops[1].eta = route.stops[0].eta
    assert "H9" in codes(day, baseline)
    route.stops[0].eta = "05:00"
    assert sum(1 for v in verify(day, baseline).violations if v.code.value == "H9") >= 2


def test_h9_down_vehicle_takes_no_stops(baseline: State, day: State) -> None:
    vehicle = day.fleet.vehicles[0]
    vehicle.status = VehicleStatus.down
    assert "H9" in codes(day, baseline)


def test_h10_ride_too_long(baseline: State, day: State) -> None:
    trip = _scheduled_return(day)
    stop = _stop(day, trip.trip_id, StopKind.dropoff)
    stop.eta = to_hhmm(to_min(stop.eta) + 90)
    assert "H10" in codes(day, baseline)


def test_h11_scheduled_return_without_stops(baseline: State, day: State) -> None:
    trip = _scheduled_return(day)
    for route in day.manifest.routes:
        route.stops = [s for s in route.stops if s.trip_id != trip.trip_id]
    assert "H11" in codes(day, baseline)


def test_h12_to_leg_lands_late(baseline: State, day: State) -> None:
    trip = next(
        t for t in day.manifest.trips if t.leg == Leg.to and t.status == TripStatus.scheduled
    )
    stop = _stop(day, trip.trip_id, StopKind.dropoff)
    stop.eta = to_hhmm(to_min(trip.window.root[1]) + 5)
    assert "H12" in codes(day, baseline)


def test_h13_budget_spent(baseline: State, day: State) -> None:
    patient = _patient(day, clinically_fixed=False, consent_to_move=True)
    patient.moves_this_week = 1
    patient.start_time = to_hhmm(to_min(patient.start_time) + 15)
    assert "H13" in codes(day, baseline)


def test_hash_covers_every_field_verify_reads(baseline: State, day: State) -> None:
    before = verify(baseline, baseline).verify_hash
    day.roster.patients[0].rx_duration_min = RxDurationMin.integer_210
    assert verify(day, baseline).verify_hash != before
    day.roster.patients[0].rx_duration_min = baseline.roster.patients[0].rx_duration_min
    day.fleet.vehicles[0].status = VehicleStatus.down
    assert verify(day, baseline).verify_hash != before


def test_h12_stale_to_leg_window_after_a_chair_move(baseline: State, day: State) -> None:
    trip = next(
        t
        for t in day.manifest.trips
        if t.leg == Leg.to
        and t.status == TripStatus.scheduled
        and day.patient_of(t).consent_to_move
        and not day.patient_of(t).clinically_fixed
    )
    patient = day.patient_of(trip)
    patient.start_time = to_hhmm(to_min(patient.start_time) - 30)
    assert "H12" in codes(day, baseline)


def test_h11_will_call_return_with_no_stops(baseline: State, day: State) -> None:
    trip = next(t for t in day.return_trips() if t.status == TripStatus.will_call)
    for route in day.manifest.routes:
        route.stops = [s for s in route.stops if s.trip_id != trip.trip_id]
    assert "H11" in codes(day, baseline)


def test_h8_load_is_recomputed_not_trusted(baseline: State, day: State) -> None:
    route = day.manifest.routes[0]
    route.stops[0].load_after = Load(ambulatory=0, wheelchair=0, stretcher=0)
    assert any(
        "stale" in v.detail and v.code.value == "H8" for v in verify(day, baseline).violations
    )


def test_h9_trip_split_across_vehicles_or_dropoff_first(baseline: State, day: State) -> None:
    source, target = day.manifest.routes[0], day.manifest.routes[1]
    moved = source.stops.pop(1)
    target.stops.append(moved)
    found = [v for v in verify(day, baseline).violations if v.code.value == "H9"]
    assert any("both" in v.detail for v in found)
    day.manifest.routes[0].stops.reverse()
    found = [v for v in verify(day, baseline).violations if v.code.value == "H9"]
    assert any("dropoff before pickup" in v.detail for v in found)
