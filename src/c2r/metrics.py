"""Deterministic scoring of a chair schedule and a ride manifest; the model never counts."""

from __future__ import annotations

import argparse
import json
import sys
from itertools import pairwise
from pathlib import Path
from typing import Any

import yaml

from c2r.banner import BANNER
from c2r.models import (
    Leg,
    Manifest,
    Metrics,
    Patient,
    Provider,
    Roster,
    StopKind,
    TripStatus,
)
from c2r.timeutil import p90, to_min

PUBLISHED_MEAN_POST_WAIT = 62
DOCUMENTS = {"roster": Roster, "manifest": Manifest}


def _ready(patient: Patient) -> int:
    return (
        to_min(patient.start_time)
        + patient.late_start_min
        + int(patient.rx_duration_min)
        + patient.runover_min
        + int(patient.recovery_buffer_min)
    )


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 2) if values else 0.0


def compute_metrics(roster: Roster, manifest: Manifest, rules: dict[str, Any]) -> Metrics:
    patients = {patient.patient_id: patient for patient in roster.patients}
    riders = {rider.rider_id: rider for rider in roster.riders}
    pickups: dict[str, int] = {}
    dropoffs: dict[str, int] = {}
    for route in manifest.routes:
        for stop in route.stops:
            table = pickups if stop.kind == StopKind.pickup else dropoffs
            table[stop.trip_id] = to_min(stop.eta)
    waits: list[float] = []
    by_class: dict[str, list[float]] = {"ambulatory": [], "wheelchair": []}
    early: list[float] = []
    flagged = 0
    for trip in manifest.trips:
        rider = riders[trip.rider_id]
        if rider.provider != Provider.broker:
            continue
        patient = patients[rider.patient_id]
        if trip.leg == Leg.to:
            if trip.trip_id in dropoffs:
                early.append(to_min(patient.start_time) - dropoffs[trip.trip_id])
            continue
        if trip.status == TripStatus.queued or trip.trip_id not in pickups:
            flagged += 1
            continue
        wait = pickups[trip.trip_id] - _ready(patient)
        waits.append(wait)
        if patient.mobility.value in by_class:
            by_class[patient.mobility.value].append(wait)
    sessions: dict[str, list[tuple[int, int]]] = {}
    for patient in roster.patients:
        start = to_min(patient.start_time)
        sessions.setdefault(patient.chair_id, []).append(
            (start, start + int(patient.rx_duration_min))
        )
    conflicts = 0
    for chair in sessions.values():
        ordered = sorted(chair)
        conflicts += sum(1 for a, b in pairwise(ordered) if b[0] < a[1])
    target = rules["stop"]["target_post_wait"]
    vehicle_min = sum(
        to_min(route.stops[-1].eta) - to_min(route.stops[0].eta)
        for route in manifest.routes
        if route.stops
    )
    return Metrics(
        mean_post_wait=_mean(waits),
        p90_post_wait=p90(waits),
        wait_min_total=float(sum(waits)),
        early_wait_mean=_mean(early),
        within_30_share=round(sum(1 for w in waits if w <= target) / len(waits), 4)
        if waits
        else 0.0,
        conflicts=conflicts,
        equity_gap=round(abs(_mean(by_class["wheelchair"]) - _mean(by_class["ambulatory"])), 2),
        vehicle_min=float(vehicle_min),
        riders_flagged=flagged,
    )


def load(data_dir: Path) -> tuple[Roster, Manifest, dict[str, Any]]:
    rules = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "config" / "rules.yaml").read_text(encoding="utf-8")
    )
    documents = {
        name: model.model_validate_json((data_dir / f"{name}.json").read_text(encoding="utf-8"))
        for name, model in DOCUMENTS.items()
    }
    return documents["roster"], documents["manifest"], rules


def _table(metrics: Metrics) -> str:
    published = {"mean_post_wait": str(PUBLISHED_MEAN_POST_WAIT)}
    rows = [
        (name, f"{value:g}", published.get(name, "-"))
        for name, value in metrics.model_dump(mode="json").items()
    ]
    width = max(len(name) for name, _, _ in rows)
    lines = [BANNER, f"{'metric':<{width}}  {'value':>9}  published"]
    lines += [f"{name:<{width}}  {value:>9}  {mark:>9}" for name, value, mark in rows]
    return "\n".join(lines)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("data_dir")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    metrics = compute_metrics(*load(Path(args.data_dir)))
    if args.json:
        print(json.dumps(metrics.model_dump(mode="json"), indent=2, sort_keys=True))
    else:
        print(_table(metrics))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
