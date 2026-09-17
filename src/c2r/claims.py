"""K4 helpers: numbers the model wrote versus numbers a tool computed, and the message budget.

The mediator never computes a number. Every numeric claim in its prose is matched against the
tool results of the run; the rest is logged as unverified. ``state_delta`` is what an apply
sends back instead of the manifest (H1: the per-iteration message stays small).
"""

from __future__ import annotations

import json
import re
from typing import Any

from c2r.moves import _pickups
from c2r.state import State
from c2r.timeutil import to_hhmm

MAX_MESSAGE_TOKENS = 4000
TIME = re.compile(r"(?<![\w:])(?:[01]?\d|2[0-3]):[0-5]\d(?![\w:])")
NUMBER = re.compile(r"(?<![\w:.])\d+(?:\.\d+)?(?![\w:]|\.\d)")


def numeric_claims(text: str) -> list[str]:
    """Clock times and bare numbers in prose; identifiers such as P31f or S12-B194 are not."""
    times = TIME.findall(text)
    masked = TIME.sub(" ", text)
    return list(dict.fromkeys(times + NUMBER.findall(masked)))


def numbers_in(value: Any) -> set[str]:
    """Every numeric form a tool result contains, so a claim can be matched by string."""
    found: set[str] = set()
    if isinstance(value, bool):
        return found
    if isinstance(value, int | float):
        found.add(f"{value:g}")
        found.add(str(round(value)))
        if isinstance(value, float):
            found.update({f"{value:.1f}", f"{value:.2f}", str(abs(round(value)))})
        found.add(f"{abs(value):g}")
    elif isinstance(value, str):
        found.update(numeric_claims(value))
    elif isinstance(value, dict):
        for item in value.values():
            found |= numbers_in(item)
    elif isinstance(value, list | tuple):
        for item in value:
            found |= numbers_in(item)
    return found


def estimate_tokens(value: Any) -> int:
    return len(json.dumps(value, separators=(",", ":"))) // 4


def trim(result: dict[str, Any], budget: int = MAX_MESSAGE_TOKENS) -> dict[str, Any]:
    """Drop the lowest-ranked candidates until the result fits the per-message budget."""
    for key in ("candidates", "next_candidates"):
        while key in result and len(result[key]) > 1 and estimate_tokens(result) > budget:
            result[key].pop()
    return result


def state_delta(before: State, after: State) -> dict[str, Any]:
    """What an apply changed: trips (vehicle, window, status, pickup) and chair starts."""
    old_trips = {t.trip_id: t for t in before.manifest.trips}
    old_pick, new_pick = _pickups(before), _pickups(after)
    trips: dict[str, dict[str, Any]] = {}
    for trip in after.manifest.trips:
        old = old_trips[trip.trip_id]
        changed: dict[str, Any] = {}
        if trip.vehicle_id != old.vehicle_id:
            changed["vehicle"] = [old.vehicle_id, trip.vehicle_id]
        old_w = list(old.window.root) if old.window else None
        new_w = list(trip.window.root) if trip.window else None
        if old_w != new_w:
            changed["window"] = [old_w, new_w]
        if trip.status != old.status:
            changed["status"] = [old.status.value, trip.status.value]
        a, b = old_pick.get(trip.trip_id), new_pick.get(trip.trip_id)
        if a != b:
            changed["pickup"] = [
                to_hhmm(a) if a is not None else None,
                to_hhmm(b) if b is not None else None,
            ]
        if changed:
            trips[trip.trip_id] = changed
    olds = before.patients
    patients = {
        p.patient_id: [olds[p.patient_id].start_time, p.start_time]
        for p in after.roster.patients
        if p.start_time != olds[p.patient_id].start_time
    }
    return {"trips": trips, "chair_starts": patients}
