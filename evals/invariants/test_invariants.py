"""I1-I15 on the solver's after-state for seed 42, each checked directly and through verify()."""

from __future__ import annotations

from collections import Counter
from itertools import pairwise
from pathlib import Path

import pytest

from c2r.models import Leg, Mobility, StopKind, TripStatus
from c2r.solver import Result, post_waits, solve
from c2r.state import State, load_state, scheduled_ready, session_end
from c2r.timeutil import to_min, window_min
from c2r.verify import CLASS_OF, requested_times, verify

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "synthetic" / "42"


@pytest.fixture(scope="module")
def baseline() -> State:
    return load_state(DATA)


@pytest.fixture(scope="module")
def run(baseline: State) -> Result:
    return solve(baseline)


@pytest.fixture(scope="module")
def after(run: Result) -> State:
    return run.state


def codes(run: Result) -> set[str]:
    return {v.code.value for v in run.result.violations}


def stops(state: State):
    return [(route, stop) for route in state.manifest.routes for stop in route.stops]


def etas(state: State, kind: StopKind) -> dict[str, int]:
    return {stop.trip_id: to_min(stop.eta) for _, stop in stops(state) if stop.kind == kind}


def test_after_state_verifies_clean_and_beats_the_baseline(baseline: State, run: Result) -> None:
    before = verify(baseline, baseline).metrics
    assert run.result.violations == []
    assert run.result.metrics.mean_post_wait < before.mean_post_wait
    assert run.result.metrics.p90_post_wait < before.p90_post_wait
    assert run.result.metrics.conflicts == 0
    assert run.applied, "the solver applied nothing"


def test_solver_is_deterministic(baseline: State, run: Result) -> None:
    short = baseline.with_(
        rules={**baseline.rules, "stop": {**baseline.rules["stop"], "max_iterations": 1}}
    )
    first, second = solve(short), solve(short)
    assert first.result.verify_hash == second.result.verify_hash
    assert [b["bundle"] for b in first.applied] == [b["bundle"] for b in second.applied]
    assert first.applied
    assert first.applied[0]["bundle"] == run.applied[0]["bundle"]


def test_i1_chairs_never_overlap_and_keep_turnover(after: State, run: Result) -> None:
    sessions: dict[str, list[tuple[int, int]]] = {}
    for p in after.roster.patients:
        sessions.setdefault(p.chair_id, []).append((to_min(p.start_time), session_end(p)))
    for chair in sessions.values():
        for (_, end), (start, _) in pairwise(sorted(chair)):
            assert start - end >= after.unit.turnover_min
    assert "H1" not in codes(run)


def test_i2_prescriptions_unchanged(baseline: State, after: State, run: Result) -> None:
    before = baseline.patients
    for p in after.roster.patients:
        assert p.rx_duration_min == before[p.patient_id].rx_duration_min
        assert p.rx_days == before[p.patient_id].rx_days
    assert "H2" not in codes(run)


def test_i3_fixed_patients_keep_their_start(baseline: State, after: State, run: Result) -> None:
    for p in after.roster.patients:
        if p.clinically_fixed:
            assert p.start_time == baseline.patients[p.patient_id].start_time
    assert "H3" not in codes(run)


def test_i4_non_consenting_patients_keep_their_start(
    baseline: State, after: State, run: Result
) -> None:
    for p in after.roster.patients:
        if not p.consent_to_move:
            assert p.start_time == baseline.patients[p.patient_id].start_time
    assert "H4" not in codes(run)


def test_i5_stagger_bins_never_exceed_the_cohort(after: State, run: Result) -> None:
    opens = {s.shift_id.value: to_min(s.putton_start) for s in after.unit.shifts}
    bins = Counter(
        (
            p.shift_id.value,
            (to_min(p.start_time) - opens[p.shift_id.value]) // after.unit.stagger_step_min,
        )
        for p in after.roster.patients
    )
    assert max(bins.values()) <= after.unit.stagger_cohort_size
    assert "H5" not in codes(run)


def test_i6_return_windows_open_at_or_after_ready(after: State, run: Result) -> None:
    for trip in after.return_trips():
        if trip.window is not None:
            assert window_min(trip.window)[0] >= scheduled_ready(after.patient_of(trip))
    assert "H6" not in codes(run)


def test_i7_windows_sit_inside_the_negotiation_band_or_the_trip_is_queued(
    baseline: State, after: State, run: Result
) -> None:
    band = after.rules["broker"]["ada_negotiation_min"]
    requested = requested_times(after.manifest, baseline.manifest, after.roster)
    for trip in after.manifest.trips:
        if trip.status == TripStatus.scheduled:
            opens, closes = window_min(trip.window)
            assert abs((opens + closes) / 2 - to_min(requested[trip.trip_id])) <= band
        else:
            assert trip.status in (TripStatus.queued, TripStatus.will_call)
    assert "H7" not in codes(run)


def test_i8_capacity_by_class_is_never_exceeded(after: State, run: Result) -> None:
    caps = {
        v.vehicle_id: {
            "ambulatory": v.cap_ambulatory,
            "wheelchair": v.cap_wheelchair,
            "stretcher": v.cap_stretcher,
        }
        for v in after.fleet.vehicles
    }
    trips = {t.trip_id: t for t in after.manifest.trips}
    for route in after.manifest.routes:
        aboard = {"ambulatory": 0, "wheelchair": 0, "stretcher": 0}
        for stop in route.stops:
            klass = CLASS_OF[after.patient_of(trips[stop.trip_id]).mobility.value]
            aboard[klass] += 1 if stop.kind == StopKind.pickup else -1
            assert aboard[klass] <= caps[route.vehicle_id][klass]
    assert "H8" not in codes(run)


def test_i9_stretcher_trips_are_always_queued(after: State, run: Result) -> None:
    stretcher = [
        t for t in after.manifest.trips if after.patient_of(t).mobility == Mobility.stretcher
    ]
    assert stretcher
    assert all(t.status == TripStatus.queued for t in stretcher)
    assert any(item.reason_code.value == "STRETCHER" for item in run.review)


def test_i10_route_timing_is_feasible_inside_vehicle_shifts(after: State, run: Result) -> None:
    dwell = after.rules["broker"]["dwell_min"]
    trips = {t.trip_id: t for t in after.manifest.trips}
    shifts = {v.vehicle_id: window_min(v.shift) for v in after.fleet.vehicles}
    for route in after.manifest.routes:
        opens, closes = shifts[route.vehicle_id]
        assert opens <= to_min(route.stops[0].eta) and to_min(route.stops[-1].eta) <= closes
        for prev, nxt in pairwise(route.stops):
            mobility = after.patient_of(trips[prev.trip_id]).mobility.value
            assert (
                to_min(nxt.eta)
                >= to_min(prev.eta) + dwell[mobility] + after.travel.matrix[prev.node][nxt.node]
            )
    assert "H9" not in codes(run)


def test_i11_ride_time_within_caps(after: State, run: Result) -> None:
    pickups, dropoffs = etas(after, StopKind.pickup), etas(after, StopKind.dropoff)
    longest, ratio = after.rules["broker"]["max_ride_min"], after.rules["broker"]["max_ride_ratio"]
    for trip in after.manifest.trips:
        if trip.trip_id in pickups:
            direct = after.travel.matrix[trip.origin_node][trip.dest_node]
            assert dropoffs[trip.trip_id] - pickups[trip.trip_id] <= min(longest, ratio * direct)
    assert "H10" not in codes(run)


def test_i12_nobody_is_stranded(after: State, run: Result) -> None:
    pickups, dropoffs = etas(after, StopKind.pickup), etas(after, StopKind.dropoff)
    holds = {item.subject for item in run.review}
    for trip in after.return_trips():
        if trip.status == TripStatus.queued:
            assert trip.trip_id in holds, f"{trip.trip_id} queued without a review item"
        else:
            assert trip.trip_id in pickups and trip.trip_id in dropoffs
    assert "H11" not in codes(run)


def test_i13_outbound_legs_land_inside_the_chair_band(after: State, run: Result) -> None:
    dropoffs = etas(after, StopKind.dropoff)
    width = after.rules["broker"]["pickup_window_min"]
    for trip in after.manifest.trips:
        if trip.leg == Leg.to and trip.status == TripStatus.scheduled:
            start = to_min(after.patient_of(trip).start_time)
            assert start - width <= dropoffs[trip.trip_id] <= start
    assert "H12" not in codes(run)


def test_i14_equity_budget_one_move_per_week(baseline: State, after: State, run: Result) -> None:
    limit = after.rules["max_moves_per_patient_per_week"]
    for p in after.roster.patients:
        moved = int(p.start_time != baseline.patients[p.patient_id].start_time)
        assert p.moves_this_week + moved <= limit
    assert "H13" not in codes(run)


def test_i15_equity_gap_within_target(run: Result) -> None:
    assert run.result.metrics.equity_gap <= run.baseline.rules["stop"]["target_equity_gap"]


def test_every_served_wait_is_measured_after_actual_ready(after: State) -> None:
    assert all(wait >= 0 for wait in post_waits(after).values())
