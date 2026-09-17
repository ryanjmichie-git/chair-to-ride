"""Deterministic unit and broker parties: accept or reject a bundle with a reason and a hint."""

from __future__ import annotations

from dataclasses import dataclass

from c2r.models import Bundle, ReasonCode

CHAIR_MOVES = {"shift_chair_start", "swap_chairs"}


@dataclass(frozen=True)
class PartyResponse:
    accepted: bool
    reason_code: ReasonCode | None = None
    hint: str = ""


ACCEPT = PartyResponse(True)


def reject(code: ReasonCode, hint: str) -> PartyResponse:
    return PartyResponse(False, code, hint)


def patients_touched(bundle: Bundle) -> list[str]:
    ids = [getattr(move, "patient_id", None) for move in bundle.moves]
    ids += [getattr(move, "patient_a", None) for move in bundle.moves]
    ids += [getattr(move, "patient_b", None) for move in bundle.moves]
    return sorted({pid for pid in ids if pid})


def trips_touched(bundle: Bundle) -> list[str]:
    """Return legs the bundle changes, including the returns of every moved patient."""
    ids: set[str] = {f"{pid}f" for pid in patients_touched(bundle)}
    for move in bundle.moves:
        if getattr(move, "trip_id", None):
            ids.add(move.trip_id)
        ids.update(getattr(move, "trip_ids", []))
    return sorted(ids)
