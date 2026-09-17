"""The dialysis unit's answer to a bundle, straight from config/unit_policy.md via rules.yaml."""

from __future__ import annotations

from c2r.models import Bundle, ReasonCode
from c2r.parties import ACCEPT, CHAIR_MOVES, PartyResponse, patients_touched, reject
from c2r.state import State, actual_ready, session_end
from c2r.timeutil import to_hhmm, to_min


def respond(baseline: State, candidate: State, bundle: Bundle) -> PartyResponse:
    """Judge the chair side of ``bundle`` given the state it produces (``candidate``)."""
    unit = baseline.rules["unit"]
    hypotension = baseline.rules["recovery_buffer_min"]["hypotension"]
    before, after = baseline.patients, candidate.patients
    for pid in patients_touched(bundle):
        patient = after[pid]
        if patient.clinically_fixed:
            return reject(ReasonCode.CLINICAL_NOTE, f"{pid} is fixed: {patient.fixed_reason}")
        if not patient.consent_to_move:
            return reject(ReasonCode.CONSENT_BLOCK, f"{pid} has not consented to a chair move")
        delta = to_min(patient.start_time) - to_min(before[pid].start_time)
        if abs(delta) > unit["max_chair_shift_min"]:
            return reject(
                ReasonCode.NO_FEASIBLE_WINDOW,
                f"{pid}: {delta:+d} min is more than the {unit['max_chair_shift_min']} the "
                "floor accepts",
            )
        opens, closes = (to_min(t) for t in unit["shifts"][patient.shift_id.value])
        if not opens <= to_min(patient.start_time) <= closes:
            return reject(
                ReasonCode.NO_FEASIBLE_WINDOW,
                f"{pid}: {patient.start_time} is outside the {patient.shift_id.value} put-on "
                f"window {to_hhmm(opens)}-{to_hhmm(closes)}",
            )
        if session_end(patient) > to_min(unit["close_time"]):
            return reject(
                ReasonCode.NO_FEASIBLE_WINDOW,
                f"{pid} would come off at {to_hhmm(session_end(patient))}, after the unit "
                f"closes at {unit['close_time']}",
            )
    if any(move.type in CHAIR_MOVES for move in bundle.moves):
        changed: dict[str, int] = {}
        for pid, patient in after.items():
            if patient.start_time != before[pid].start_time:
                changed[patient.shift_id.value] = changed.get(patient.shift_id.value, 0) + 1
        for shift_id, count in sorted(changed.items()):
            if count > unit["max_chair_changes_per_shift"]:
                return reject(
                    ReasonCode.NO_FEASIBLE_WINDOW,
                    f"{shift_id} would carry {count} chair changes; the floor absorbs "
                    f"{unit['max_chair_changes_per_shift']} a day",
                )
    for move in bundle.moves:
        if move.type != "shift_pickup_window":
            continue
        trip = next((t for t in candidate.manifest.trips if t.trip_id == move.trip_id), None)
        if trip is None or trip.window is None:
            continue
        patient = candidate.patient_of(trip)
        if int(patient.recovery_buffer_min) != hypotension:
            continue
        ready = actual_ready(patient)
        if to_min(trip.window.root[0]) < ready:
            return reject(
                ReasonCode.CLINICAL_NOTE,
                f"{patient.patient_id} has a hypotension note; no ride at the door before "
                f"{to_hhmm(ready)}",
            )
    return ACCEPT
