"""One day's state: unit, roster, manifest, fleet, travel and the rules, loaded once, copied often."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import yaml

from c2r.models import Fleet, Leg, Manifest, Patient, Provider, Rider, Roster, Travel, Trip, Unit
from c2r.timeutil import to_min

ROOT = Path(__file__).resolve().parents[2]
RULES_PATH = ROOT / "config" / "rules.yaml"
UNIT_NODE = 0
DOCUMENTS = {"unit": Unit, "roster": Roster, "manifest": Manifest, "fleet": Fleet, "travel": Travel}


@dataclass(frozen=True)
class State:
    unit: Unit
    roster: Roster
    manifest: Manifest
    fleet: Fleet
    travel: Travel
    rules: dict[str, Any]

    @property
    def patients(self) -> dict[str, Patient]:
        return {patient.patient_id: patient for patient in self.roster.patients}

    @property
    def riders(self) -> dict[str, Rider]:
        return {rider.rider_id: rider for rider in self.roster.riders}

    @property
    def broker_riders(self) -> dict[str, Rider]:
        return {r.rider_id: r for r in self.roster.riders if r.provider == Provider.broker}

    def patient_of(self, trip: Trip) -> Patient:
        return self.patients[self.riders[trip.rider_id].patient_id]

    def return_trips(self) -> list[Trip]:
        broker = self.broker_riders
        return [t for t in self.manifest.trips if t.leg == Leg.from_ and t.rider_id in broker]

    def with_(self, **changes: Any) -> State:
        return replace(self, **changes)


def load_rules(path: Path = RULES_PATH) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_state(data_dir: Path, rules: dict[str, Any] | None = None) -> State:
    documents = {
        name: model.model_validate_json((data_dir / f"{name}.json").read_text(encoding="utf-8"))
        for name, model in DOCUMENTS.items()
    }
    return State(rules=rules if rules is not None else load_rules(), **documents)


def session_end(patient: Patient) -> int:
    return to_min(patient.start_time) + int(patient.rx_duration_min)


def scheduled_ready(patient: Patient) -> int:
    """When the standing order assumes the patient can leave: end + recovery buffer."""
    return session_end(patient) + int(patient.recovery_buffer_min)


def actual_ready(patient: Patient) -> int:
    """When the patient can really leave: the schedule plus the day's late start and run-over."""
    return scheduled_ready(patient) + patient.late_start_min + patient.runover_min
