"""vehicle_min counts minutes a van has a rider aboard or is loading one, never idle span."""

from __future__ import annotations

from pathlib import Path

import pytest

from c2r.metrics import _busy_minutes, compute_metrics
from c2r.models import StopKind
from c2r.state import State, load_state
from c2r.timeutil import to_hhmm, to_min

DATA = Path(__file__).resolve().parents[2] / "data" / "synthetic" / "42"


@pytest.fixture(scope="module")
def baseline() -> State:
    return load_state(DATA)


def test_busy_minutes_merges_overlaps_and_skips_gaps() -> None:
    assert _busy_minutes([]) == 0
    assert _busy_minutes([(10, 30), (20, 40)]) == 30
    assert _busy_minutes([(10, 30), (300, 310)]) == 30
    assert _busy_minutes([(300, 310), (10, 30), (15, 25)]) == 30


def _first_gap_index(stops: list) -> int:
    """Index of the first pickup that starts a new task block after the van emptied."""
    aboard: set[str] = set()
    for i, stop in enumerate(stops):
        if stop.kind == StopKind.pickup:
            if i and not aboard:
                return i
            aboard.add(stop.trip_id)
        else:
            aboard.discard(stop.trip_id)
    raise AssertionError("route has a single task block")


def test_idle_time_between_task_blocks_is_not_counted(baseline: State) -> None:
    before = compute_metrics(baseline.roster, baseline.manifest, baseline.rules).vehicle_min
    route = baseline.manifest.routes[0]
    split = _first_gap_index(route.stops)
    delayed = [
        stop.model_copy(update={"eta": to_hhmm(to_min(stop.eta) + 60)}) if i >= split else stop
        for i, stop in enumerate(route.stops)
    ]
    routes = [route.model_copy(update={"stops": delayed}), *baseline.manifest.routes[1:]]
    manifest = baseline.manifest.model_copy(update={"routes": routes})
    after = compute_metrics(baseline.roster, manifest, baseline.rules).vehicle_min
    span_after = to_min(delayed[-1].eta) - to_min(delayed[0].eta)
    span_before = to_min(route.stops[-1].eta) - to_min(route.stops[0].eta)
    assert span_after == span_before + 60
    assert after == before


def test_on_task_minutes_are_well_below_the_span(baseline: State) -> None:
    metrics = compute_metrics(baseline.roster, baseline.manifest, baseline.rules)
    span = sum(
        to_min(route.stops[-1].eta) - to_min(route.stops[0].eta)
        for route in baseline.manifest.routes
        if route.stops
    )
    assert 0 < metrics.vehicle_min < span


def test_vehicle_min_is_the_sum_of_task_block_lengths(baseline: State) -> None:
    """Each block runs from its first pickup to its last dropoff plus that rider's loading dwell."""
    patients = {p.patient_id: p for p in baseline.roster.patients}
    riders = {r.rider_id: r for r in baseline.roster.riders}
    trips = {t.trip_id: t for t in baseline.manifest.trips}
    dwell = baseline.rules["broker"]["dwell_min"]
    expected = 0
    for route in baseline.manifest.routes:
        aboard: set[str] = set()
        start = 0
        for stop in route.stops:
            if stop.kind == StopKind.pickup:
                if not aboard:
                    start = to_min(stop.eta)
                aboard.add(stop.trip_id)
                continue
            aboard.discard(stop.trip_id)
            if not aboard:
                mobility = patients[riders[trips[stop.trip_id].rider_id].patient_id].mobility
                expected += to_min(stop.eta) + dwell[mobility.value] - start
    metrics = compute_metrics(baseline.roster, baseline.manifest, baseline.rules)
    assert metrics.vehicle_min == expected == 523
