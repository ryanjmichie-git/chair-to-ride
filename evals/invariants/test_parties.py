"""The unit and broker parties say no for the reasons their policies give, and yes otherwise."""

from __future__ import annotations

from pathlib import Path

import pytest

from c2r.models import (
    Bundle,
    Mobility,
    PairRiders,
    Predicted,
    ReasonCode,
    ReassignVehicle,
    RequestExtraCapacity,
    ShiftChairStart,
    ShiftPickupWindow,
    TripStatus,
)
from c2r.parties import broker, unit
from c2r.routing import Batch, build_manifest, plan_from_manifest
from c2r.state import State, actual_ready, load_state, scheduled_ready
from c2r.timeutil import to_hhmm, to_min

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "synthetic" / "42"
NO_CHANGE = Predicted(
    delta_wait_min=0, delta_early_min=0, chair_changes=0, consent_moves=0, vehicle_min=0
)


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


def bundle(*moves) -> Bundle:
    return Bundle(
        bundle_id="B-test",
        side="both",
        moves=list(moves),
        predicted=NO_CHANGE,
        touches=[],
        notes_relevant=[],
    )


def chair_move(patient_id: str, delta: int) -> ShiftChairStart:
    return ShiftChairStart(type="shift_chair_start", patient_id=patient_id, delta_min=delta)


def window_move(trip_id: str, delta: int) -> ShiftPickupWindow:
    return ShiftPickupWindow(type="shift_pickup_window", trip_id=trip_id, delta_min=delta)


def scheduled_return(baseline: State):
    return next(t for t in baseline.return_trips() if t.status == TripStatus.scheduled and t.window)


def test_unit_rejects_fixed_non_consenting_and_oversized_moves(baseline: State) -> None:
    fixed = next(p for p in baseline.roster.patients if p.clinically_fixed)
    reply = unit.respond(baseline, baseline, bundle(chair_move(fixed.patient_id, 15)))
    assert (reply.accepted, reply.reason_code) == (False, ReasonCode.CLINICAL_NOTE)
    refusing = next(
        p for p in baseline.roster.patients if not p.consent_to_move and not p.clinically_fixed
    )
    reply = unit.respond(baseline, baseline, bundle(chair_move(refusing.patient_id, 15)))
    assert reply.reason_code == ReasonCode.CONSENT_BLOCK
    patient = consenting_rider(baseline)
    big = shift_chair(baseline, patient.patient_id, 45)
    reply = unit.respond(baseline, big, bundle(chair_move(patient.patient_id, 45)))
    assert reply.reason_code == ReasonCode.NO_FEASIBLE_WINDOW
    assert "45" in reply.hint


def test_unit_accepts_a_15_minute_move_of_a_consenting_patient(baseline: State) -> None:
    patient = consenting_rider(baseline)
    candidate = shift_chair(baseline, patient.patient_id, 15)
    reply = unit.respond(baseline, candidate, bundle(chair_move(patient.patient_id, 15)))
    assert reply.accepted, reply.hint


def test_unit_caps_chair_changes_per_shift(baseline: State) -> None:
    roster = baseline.roster.model_copy(deep=True)
    movable = [
        p
        for p in roster.patients
        if p.shift_id.value == "S1" and p.consent_to_move and not p.clinically_fixed
    ][:5]
    assert len(movable) == 5
    for patient in movable:
        patient.start_time = to_hhmm(to_min(patient.start_time) + 15)
    candidate = baseline.with_(roster=roster)
    reply = unit.respond(
        baseline, candidate, bundle(*[chair_move(p.patient_id, 15) for p in movable])
    )
    assert reply.reason_code == ReasonCode.NO_FEASIBLE_WINDOW
    assert "S1" in reply.hint


def test_unit_keeps_the_last_session_inside_closing_time(baseline: State) -> None:
    roster = baseline.roster.model_copy(deep=True)
    patient = max(
        (
            p
            for p in roster.patients
            if p.shift_id.value == "S3" and p.consent_to_move and not p.clinically_fixed
        ),
        key=lambda p: to_min(p.start_time) + int(p.rx_duration_min),
    )
    patient.start_time = to_hhmm(to_min(patient.start_time) + 30)
    # Seed 42's latest session ends 20:15, so an early close is needed to reach the rule.
    early = {**baseline.rules, "unit": {**baseline.rules["unit"], "close_time": "20:30"}}
    strict = baseline.with_(rules=early)
    candidate = strict.with_(roster=roster)
    reply = unit.respond(strict, candidate, bundle(chair_move(patient.patient_id, 30)))
    assert reply.reason_code == ReasonCode.NO_FEASIBLE_WINDOW
    assert "closes" in reply.hint


def test_unit_hypotension_note_keeps_the_ride_off_the_door_early(baseline: State) -> None:
    hypotension = baseline.rules["recovery_buffer_min"]["hypotension"]
    trip = next(
        t
        for t in baseline.return_trips()
        if int(baseline.patient_of(t).recovery_buffer_min) == hypotension
        and baseline.patient_of(t).mobility != Mobility.stretcher
    )
    patient = baseline.patient_of(trip)
    assert actual_ready(patient) > scheduled_ready(patient), "needs a late runner"
    plan = plan_from_manifest(baseline)
    plan.remove(trip.trip_id)
    plan.batches.append(Batch("V3", [trip.trip_id]))
    plan.opens[trip.trip_id] = plan.not_before[trip.trip_id] = scheduled_ready(patient)
    plan.requested[trip.trip_id] = scheduled_ready(patient) + 15
    plan.status[trip.trip_id] = TripStatus.scheduled
    candidate = baseline.with_(manifest=build_manifest(baseline, baseline.roster, plan))
    reply = unit.respond(baseline, candidate, bundle(window_move(trip.trip_id, 0)))
    assert reply.reason_code == ReasonCode.CLINICAL_NOTE
    assert to_hhmm(actual_ready(patient)) in reply.hint


def test_broker_rejects_stretcher_out_of_band_and_uncommitted_vans(baseline: State) -> None:
    stretcher = next(
        t for t in baseline.return_trips() if baseline.patient_of(t).mobility == Mobility.stretcher
    )
    reply = broker.respond(baseline, baseline, bundle(window_move(stretcher.trip_id, 0)))
    assert reply.reason_code == ReasonCode.STRETCHER
    plan = plan_from_manifest(baseline)
    trip = scheduled_return(baseline)
    plan.opens[trip.trip_id] += 90
    plan.not_before[trip.trip_id] = plan.opens[trip.trip_id]
    candidate = baseline.with_(manifest=build_manifest(baseline, baseline.roster, plan))
    reply = broker.respond(baseline, candidate, bundle(window_move(trip.trip_id, 90)))
    assert reply.reason_code == ReasonCode.NO_FEASIBLE_WINDOW
    manifest = baseline.manifest.model_copy(deep=True)
    manifest.routes = [r for r in manifest.routes if r.vehicle_id != "V5"]
    without_v5 = baseline.with_(manifest=manifest)
    reply = broker.respond(
        without_v5,
        without_v5,
        bundle(ReassignVehicle(type="reassign_vehicle", trip_id=trip.trip_id, vehicle_id="V5")),
    )
    assert reply.reason_code == ReasonCode.BROKER_POLICY
    assert "V5" in reply.hint
    reply = broker.respond(
        baseline,
        baseline,
        bundle(
            RequestExtraCapacity(type="request_extra_capacity", vehicle_min=40, reason="lift van")
        ),
    )
    assert reply.reason_code == ReasonCode.BROKER_POLICY


def test_broker_rejects_rather_than_crashes_on_bad_moves(baseline: State) -> None:
    reply = broker.respond(
        baseline, baseline, bundle(PairRiders(type="pair_riders", trip_ids=[], vehicle_id="V1"))
    )
    assert (reply.accepted, reply.reason_code) == (False, ReasonCode.BROKER_POLICY)
    reply = broker.respond(baseline, baseline, bundle(window_move("P36f", 0)))
    assert (reply.accepted, reply.reason_code) == (False, ReasonCode.BROKER_POLICY)


def test_broker_accepts_uncommitted_vans_at_autonomy_2(baseline: State) -> None:
    manifest = baseline.manifest.model_copy(deep=True)
    manifest.routes = [r for r in manifest.routes if r.vehicle_id != "V5"]
    trusted = baseline.with_(manifest=manifest, rules={**baseline.rules, "autonomy_level": 2})
    trip = scheduled_return(baseline)
    reply = broker.respond(
        trusted,
        trusted,
        bundle(PairRiders(type="pair_riders", trip_ids=[trip.trip_id], vehicle_id="V5")),
    )
    assert reply.accepted, reply.hint


def test_broker_rejects_a_window_the_van_cannot_honour(baseline: State) -> None:
    plan = plan_from_manifest(baseline)
    trip = scheduled_return(baseline)
    plan.opens[trip.trip_id] = scheduled_ready(baseline.patient_of(trip))
    plan.not_before[trip.trip_id] = plan.opens[trip.trip_id] + 45
    candidate = baseline.with_(manifest=build_manifest(baseline, baseline.roster, plan))
    reply = broker.respond(baseline, candidate, bundle(window_move(trip.trip_id, 0)))
    assert reply.reason_code == ReasonCode.BROKER_POLICY
    assert "window closed" in reply.hint
