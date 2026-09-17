"""Facts cards: what a run's own files say about one subject, keyed so every number has a ref.

Refs: ``L-17`` is line 17 of ``ledger.jsonl``; ``S-P29f`` / ``S-P29`` a trip's or a patient's
row in ``schedule_after.json`` (a trip row carries its stops); ``B-...`` the same row in
``schedule_before.json``; ``R-R01`` a review-queue item. The explainer cites exactly the refs
on its card, and the I16 check matches its numbers against those refs only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from c2r.models import Patient
from c2r.state import actual_ready
from c2r.timeutil import to_hhmm

CONTACT = {
    "rider": "the unit front desk",
    "nurse": "the broker dispatcher",
    "dispatcher": "the charge nurse",
}
NOT_FACTS = (  # stripped from every resolved ref (I16): proposals are not facts about the
    "candidates",  # schedule, and bookkeeping (tokens, dollars, iteration and version
    "next_candidates",  # counters, clock stamps, grid nodes, stop sequence numbers) must
    "usage",  # not make an invented small number look sourced
    "cost_usd",
    "iteration",
    "schedule_version",
    "elapsed_s",
    "ts",
    "git_sha",
    "run_id",
    "model_id",
    "effort",
    "input_hashes",
    "prompt_versions",
    "node",
    "seq",
)


@dataclass
class RunFiles:
    before: dict[str, Any]
    after: dict[str, Any]
    bundles: list[dict[str, Any]]
    queue: list[dict[str, Any]]
    lines: list[str]
    event: dict[str, Any] | None

    @property
    def run_id(self) -> str:
        return json.loads(self.lines[0])["run_id"] if self.lines else ""


def load_run(run_dir: Path) -> RunFiles:
    def read(name: str) -> Any:
        return json.loads((run_dir / name).read_text(encoding="utf-8"))

    event_path = run_dir / "event.json"
    return RunFiles(
        before=read("schedule_before.json"),
        after=read("schedule_after.json"),
        bundles=read("bundles.json"),
        queue=read("review_queue.json"),
        lines=[
            line
            for line in (run_dir / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ],
        event=read("event.json") if event_path.is_file() else None,
    )


def patient_of_subject(subject: str) -> str:
    """A review-queue subject is a trip (P30f), a patient (P30) or a vehicle (V3)."""
    if subject.startswith("P") and subject[-1] in "tf" and len(subject) == 4:
        return subject[:-1]
    return subject


# --- refs -----------------------------------------------------------------------------------


def _row(schedule: dict[str, Any], ident: str) -> dict[str, Any]:
    for trip in schedule["manifest"]["trips"]:
        if trip["trip_id"] == ident:
            stops = [
                {"vehicle": r["vehicle_id"], "kind": s["kind"], "eta": s["eta"]}
                for r in schedule["manifest"]["routes"]
                for s in r["stops"]
                if s["trip_id"] == ident
            ]
            return {**trip, "stops": stops}
    for patient in schedule["roster"]["patients"]:
        if patient["patient_id"] == ident:
            return dict(patient)
    raise KeyError(ident)


def _facts_only(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _facts_only(v) for k, v in value.items() if k not in NOT_FACTS}
    if isinstance(value, list):
        return [_facts_only(v) for v in value]
    return value


def resolve_refs(run_dir: Path, refs: list[str]) -> dict[str, Any]:
    """Each ref to the JSON it names; a ref nothing in the run dir matches raises KeyError."""
    files = load_run(run_dir)
    return {ref: resolve(files, ref) for ref in refs}


def resolve(files: RunFiles, ref: str) -> Any:
    kind, _, ident = ref.partition("-")
    if kind == "L" and ident.isdigit() and 1 <= int(ident) <= len(files.lines):
        return _facts_only(json.loads(files.lines[int(ident) - 1]))
    if kind == "S":
        return _row(files.after, ident)
    if kind == "B":
        return _row(files.before, ident)
    if kind == "R":
        for item in files.queue:
            if item["item_id"] == ident:
                return dict(item)
    raise KeyError(ref)


# --- the card ---------------------------------------------------------------------------------


def _move_text(move: dict[str, Any]) -> str:
    kind = move["type"]
    if kind == "reassign_vehicle":
        return f"{move['trip_id']} to van {move['vehicle_id']}"
    if kind == "shift_pickup_window":
        return f"{move['trip_id']} pickup window {move['delta_min']:+d} min"
    if kind == "shift_chair_start":
        return f"{move['patient_id']} chair start {move['delta_min']:+d} min"
    if kind == "pair_riders":
        return f"{' and '.join(move['trip_ids'])} together on van {move['vehicle_id']}"
    if kind == "hold_for_will_call":
        return f"{move['trip_id']} held for will-call: {move['reason']}"
    return f"{kind} {json.dumps({k: v for k, v in move.items() if k != 'type'}, sort_keys=True)}"


def _mentions(move: dict[str, Any], patient_id: str) -> bool:
    ids = {move.get("trip_id"), move.get("patient_id"), *move.get("trip_ids", [])}
    return any(i and patient_of_subject(i) == patient_id for i in ids)


def _ledger_lines(files: RunFiles) -> tuple[dict[str, int], int | None]:
    """Bundle id -> the 1-based ledger line that applied it (closing bundles: the run finish),
    and the run-start line (the event, when there is one, is ledgered there)."""
    lines: dict[str, int] = {}
    start: int | None = None
    for number, line in enumerate(files.lines, 1):
        entry = json.loads(line)
        if entry["event"] == "run_start":
            start = number
        elif entry["event"] == "apply_bundle" and entry["payload"]["result"].get("applied"):
            lines[entry["payload"]["result"]["bundle"]["bundle_id"]] = number
        elif entry["event"] == "run_finish":
            for bundle in entry["payload"].get("closing_bundles", []):
                lines[bundle["bundle_id"]] = number
    return lines, start


def _times(schedule: dict[str, Any], patient_id: str) -> dict[str, Any]:
    patient = next(
        (p for p in schedule["roster"]["patients"] if p["patient_id"] == patient_id), None
    )
    if patient is None:
        return {}
    trip = next(
        (t for t in schedule["manifest"]["trips"] if t["trip_id"] == f"{patient_id}f"), None
    )
    pickup = next(
        (
            s["eta"]
            for r in schedule["manifest"]["routes"]
            for s in r["stops"]
            if trip and s["trip_id"] == trip["trip_id"] and s["kind"] == "pickup"
        ),
        None,
    )
    return {
        "chair_start": patient["start_time"],
        "pickup_window": trip["window"] if trip else None,
        "vehicle": trip["vehicle_id"] if trip and pickup else None,
        "status": trip["status"] if trip else None,
        "pickup_eta": pickup,
    }


def facts_card(files: RunFiles, subject_id: str, audience: str) -> dict[str, Any]:
    """Everything the writer may say about one subject and audience."""
    after = _times(files.after, subject_id)
    before = _times(files.before, subject_id)
    patient = next(
        (p for p in files.after["roster"]["patients"] if p["patient_id"] == subject_id), None
    )
    rider = next(
        (r for r in files.after["roster"]["riders"] if r["patient_id"] == subject_id), None
    )
    lines, start = _ledger_lines(files)
    refs: dict[str, Any] = {}
    if files.event and start:
        refs[f"L-{start}"] = resolve(files, f"L-{start}")
    changes = []
    for applied in files.bundles:
        bundle = applied["bundle"]
        moves = [m for m in bundle["moves"] if _mentions(m, subject_id)]
        if subject_id not in bundle["touches"] and not moves:
            continue
        ref = f"L-{lines[bundle['bundle_id']]}" if bundle["bundle_id"] in lines else None
        changes.append(
            {
                "bundle_id": bundle["bundle_id"],
                "moves": [_move_text(m) for m in moves],
                "rationale": applied.get("rationale", ""),
                "ref": ref,
            }
        )
        if ref:
            refs[ref] = resolve(files, ref)
    item = next((i for i in files.queue if patient_of_subject(i["subject"]) == subject_id), None)
    if item:
        refs[f"R-{item['item_id']}"] = dict(item)
    for kind, schedule in (("S", files.after), ("B", files.before)):
        for ident in (subject_id, f"{subject_id}f"):
            try:
                refs[f"{kind}-{ident}"] = _row(schedule, ident)
            except KeyError:
                continue
    return {
        "subject_id": subject_id,
        "audience": audience,
        "name": patient["display_name"] if patient else None,
        "contact": CONTACT[audience],
        "mobility": patient["mobility"] if patient else None,
        "language": rider["language"] if rider else None,
        "caregiver_window": rider["caregiver_window"] if rider else None,
        "ready_time": to_hhmm(actual_ready(Patient.model_validate(patient))) if patient else None,
        "before": before,
        "after": after,
        "event": files.event["event"] if files.event else None,
        "changes": changes,
        "review_item": item,
        "refs": refs,
    }


def subjects(files: RunFiles) -> list[tuple[str, str]]:
    """(patient id, audience) pairs: riders touched and not queued (K6), nurses for chair
    moves, the dispatcher for every review item."""
    touched = sorted({pid for b in files.bundles for pid in b["bundle"]["touches"]})
    queued = [patient_of_subject(item["subject"]) for item in files.queue]
    starts = {p["patient_id"]: p["start_time"] for p in files.before["roster"]["patients"]}
    moved = [
        p["patient_id"]
        for p in files.after["roster"]["patients"]
        if p["start_time"] != starts.get(p["patient_id"], p["start_time"])
    ]
    pairs = [(pid, "rider") for pid in touched if pid not in queued]
    pairs += [(pid, "nurse") for pid in moved]
    pairs += [(pid, "dispatcher") for pid in dict.fromkeys(queued)]
    return pairs
