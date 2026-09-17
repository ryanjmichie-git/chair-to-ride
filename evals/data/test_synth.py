"""Realism checks on data/synthetic/42: the generated day has to look like a real bad Wednesday."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
import yaml

from c2r.metrics import compute_metrics
from c2r.models import Event, Fleet, Manifest, Roster, Travel, Unit
from c2r.phi import find_phi
from c2r.timeutil import to_min

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "synthetic" / "42"
FILES = ["unit.json", "roster.json", "manifest.json", "fleet.json", "travel.json"]
RX_SHARES = {210: 0.15, 225: 0.20, 240: 0.45, 255: 0.10, 270: 0.10}
MOBILITY_SHARES = {"ambulatory": 0.55, "assist": 0.15, "wheelchair": 0.27, "stretcher": 0.03}
FLAG_SHARES = {"clinically_fixed": 0.15, "consent_to_move": 0.75, "hypotension": 0.20}
TOLERANCE = 2
NOTE_CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "consistent": {"type": "boolean"},
        "issues": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["consistent", "issues"],
    "additionalProperties": False,
}


@pytest.fixture(scope="module")
def unit() -> Unit:
    return Unit.model_validate_json((DATA / "unit.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def roster() -> Roster:
    return Roster.model_validate_json((DATA / "roster.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def manifest() -> Manifest:
    return Manifest.model_validate_json((DATA / "manifest.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def travel() -> Travel:
    return Travel.model_validate_json((DATA / "travel.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def rules() -> dict[str, Any]:
    return yaml.safe_load((ROOT / "config" / "rules.yaml").read_text(encoding="utf-8"))


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for item in value.values() for s in _strings(item)]
    if isinstance(value, list):
        return [s for item in value for s in _strings(item)]
    return []


def test_rx_duration_distribution(roster: Roster) -> None:
    counts = Counter(int(p.rx_duration_min) for p in roster.patients)
    for duration, share in RX_SHARES.items():
        assert abs(counts[duration] - share * len(roster.patients)) <= TOLERANCE


def test_mobility_distribution(roster: Roster) -> None:
    counts = Counter(p.mobility.value for p in roster.patients)
    for mobility, share in MOBILITY_SHARES.items():
        assert abs(counts[mobility] - share * len(roster.patients)) <= TOLERANCE
    assert counts["stretcher"] == 1


def test_flag_and_rider_distribution(roster: Roster) -> None:
    total = len(roster.patients)
    counts = {
        "clinically_fixed": sum(1 for p in roster.patients if p.clinically_fixed),
        "consent_to_move": sum(1 for p in roster.patients if p.consent_to_move),
        "hypotension": sum(1 for p in roster.patients if int(p.recovery_buffer_min) == 35),
    }
    for flag, share in FLAG_SHARES.items():
        assert abs(counts[flag] - share * total) <= TOLERANCE
    assert sum(1 for p in roster.patients if p.rider_id) == len(roster.riders) == 22
    assert Counter(r.provider.value for r in roster.riders) == {"broker": 18, "family": 4}


def test_chair_utilisation(unit: Unit, roster: Roster) -> None:
    slots = len(unit.chairs) * len(unit.shifts)
    assert 0.85 <= len(roster.patients) / slots <= 1.0


def test_every_shift_has_fixed_and_non_consenting_patients(roster: Roster) -> None:
    for shift in ("S1", "S2", "S3"):
        cohort = [p for p in roster.patients if p.shift_id.value == shift]
        assert sum(1 for p in cohort if p.clinically_fixed) >= 1
        assert sum(1 for p in cohort if not p.consent_to_move) >= 2


def test_stagger_bins_are_never_over_cohort_size(unit: Unit, roster: Roster) -> None:
    bins = Counter((p.shift_id.value, p.start_time) for p in roster.patients)
    assert max(bins.values()) <= unit.stagger_cohort_size


def test_chair_sessions_do_not_overlap_and_keep_turnover(unit: Unit, roster: Roster) -> None:
    for chair in unit.chairs:
        sessions = sorted(
            (to_min(p.start_time), to_min(p.start_time) + int(p.rx_duration_min))
            for p in roster.patients
            if p.chair_id == chair.chair_id
        )
        for (_, end), (start, _) in pairwise(sessions):
            assert start - end >= unit.turnover_min


def test_every_rider_is_within_the_ride_time_cap(roster: Roster, travel: Travel) -> None:
    for rider in roster.riders:
        assert travel.matrix[rider.home_node][0] <= 38
        assert travel.matrix[0][rider.home_node] <= 38


def test_baseline_post_wait_is_in_the_calibrated_band(
    roster: Roster, manifest: Manifest, rules: dict[str, Any]
) -> None:
    metrics = compute_metrics(roster, manifest, rules)
    assert 65 <= metrics.mean_post_wait <= 80
    assert 100 <= metrics.p90_post_wait <= 140
    assert metrics.conflicts == 0


@pytest.mark.parametrize("filename", [*FILES, "events.jsonl"])
def test_no_string_matches_a_phi_pattern(filename: str) -> None:
    text = (DATA / filename).read_text(encoding="utf-8")
    documents = (
        [json.loads(line) for line in text.splitlines() if line.strip()]
        if filename.endswith(".jsonl")
        else [json.loads(text)]
    )
    for document in documents:
        for value in _strings(document):
            assert find_phi(value) == []


@pytest.mark.parametrize("filename", FILES)
def test_provenance_keys_are_present(filename: str) -> None:
    document = json.loads((DATA / filename).read_text(encoding="utf-8"))
    assert document["synthetic"] is True
    assert document["generator"] == "c2r.synth v1"
    assert document["seed"] == 42


def test_every_event_line_parses() -> None:
    lines = (DATA / "events.jsonl").read_text(encoding="utf-8").splitlines()
    events = [Event.model_validate_json(line) for line in lines if line.strip()]
    assert [event.type.value for event in events] == [
        "vehicle_down",
        "chair_down",
        "late_arrival",
        "add_on_patient",
        "travel_slowdown",
    ]


def test_regenerating_reproduces_every_file_byte_for_byte(tmp_path: Path) -> None:
    subprocess.run(
        [sys.executable, "-m", "c2r.synth", "--seed", "42", "--out", str(tmp_path)],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    for filename in [*FILES, "events.jsonl"]:
        assert (tmp_path / filename).read_bytes() == (DATA / filename).read_bytes()


def test_fleet_matches_the_broker_capacity_rules(rules: dict[str, Any]) -> None:
    fleet = Fleet.model_validate_json((DATA / "fleet.json").read_text(encoding="utf-8"))
    capacity = rules["broker"]["van_capacity"]
    for vehicle in fleet.vehicles:
        van = capacity["standard" if int(vehicle.vehicle_id[1]) <= 3 else "lift"]
        assert vehicle.cap_ambulatory == van["ambulatory"]
        assert vehicle.cap_wheelchair == van["wheelchair"]
        assert vehicle.status.value == "ok"


@pytest.mark.llm
@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="needs ANTHROPIC_API_KEY")
def test_notes_reference_only_facts_in_the_record(roster: Roster) -> None:
    import anthropic

    client = anthropic.Anthropic()
    riders = {rider.patient_id: rider for rider in roster.riders}
    consistent = 0
    for patient in roster.patients:
        rider = riders.get(patient.patient_id)
        record = patient.model_dump(mode="json")
        if rider is not None:
            record["rider"] = rider.model_dump(mode="json")
        response = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=1000,
            system=(
                "You check a synthetic dialysis record against its notes. Return consistent=true "
                "only if every fact stated in nurse_note and rider_note appears in the record."
            ),
            messages=[{"role": "user", "content": json.dumps(record, sort_keys=True)}],
            output_config={"format": {"type": "json_schema", "schema": NOTE_CHECK_SCHEMA}},
        )
        text = next(block.text for block in response.content if block.type == "text")
        consistent += int(json.loads(text)["consistent"])
    assert consistent / len(roster.patients) >= 0.95
