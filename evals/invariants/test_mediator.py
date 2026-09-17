"""I16-I19 on an offline mediator run (FakeMediator), plus the CP2 definition of done.

The checks are plain functions so test_mediator_live.py can run them on a real ledger.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from c2r import ledger, orchestrator
from c2r.claims import numbers_in
from c2r.llm import FakeMediator
from c2r.models import LedgerEntry
from c2r.phi import find_phi
from c2r.solver import Result
from c2r.state import State, load_rules, load_state

DATA = Path(__file__).resolve().parents[2] / "data" / "synthetic" / "42"
OUTPUTS = (
    "ledger.jsonl",
    "review_queue.json",
    "schedule_after.json",
    "metrics.json",
    "timeline.html",
)


@pytest.fixture(scope="module")
def baseline() -> State:
    return load_state(DATA)


@pytest.fixture(scope="module")
def out(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("cp2-fake")


@pytest.fixture(scope="module")
def result(out: Path) -> Result:
    return orchestrator.run(DATA, out, FakeMediator(), echo=lambda *_: None)


@pytest.fixture(scope="module")
def entries(out: Path, result: Result) -> list[LedgerEntry]:
    del result
    return ledger.read(out / "ledger.jsonl")


# --- the checks, shared with the live test ---------------------------------------------------


def check_i16_numbers_come_from_tools(entries: list[LedgerEntry]) -> None:
    """Every number the model wrote is either verified against an earlier tool result or
    listed as unverified in its ledger entry."""
    known: set[str] = set()
    for entry in entries:
        if entry.actor == "tool":
            known |= numbers_in(entry.payload)
            continue
        claims = set(entry.payload["claims"])
        unverified = set(entry.payload["unverified"])
        assert unverified <= claims
        for claim in claims - unverified:
            assert claim in known, f"iteration {entry.iteration}: {claim!r} not in any tool result"


def check_i17_no_phi(out: Path) -> None:
    for path in out.iterdir():
        if path.suffix in (".json", ".jsonl", ".html", ".md"):
            assert find_phi(path.read_text(encoding="utf-8")) == [], path.name


def check_i18_ledger_replays_byte_for_byte(
    baseline: State, entries: list[LedgerEntry], out: Path
) -> None:
    replayed = ledger.replay(baseline, entries)
    dump = json.dumps(
        {
            "roster": replayed.roster.model_dump(mode="json"),
            "manifest": replayed.manifest.model_dump(mode="json"),
        },
        indent=2,
        sort_keys=True,
    )
    assert dump + "\n" == (out / "schedule_after.json").read_bytes().decode("utf-8")


def check_i19_every_apply_follows_a_clean_verify(entries: list[LedgerEntry]) -> None:
    applies = 0
    for index, entry in enumerate(entries):
        if entry.event != "apply_bundle" or not entry.payload["result"].get("applied"):
            continue
        applies += 1
        bid, given = entry.payload["input"]["bundle_id"], entry.payload["input"]["verify_hash"]
        version = entry.payload["result"]["schedule_version"] - 1
        earlier = [
            e.payload["result"]
            for e in entries[:index]
            if e.event == "verify" and e.payload["result"].get("bundle_id") == bid
        ]
        assert earlier, f"apply of {bid} has no earlier verify"
        latest = earlier[-1]  # the most recent verify of that bundle, not any old preview
        assert latest["verify_hash"] == given and not latest["violations"], (bid, given)
        assert latest["schedule_version"] == version, (bid, version)
        assert entry.payload["result"]["verify_hash"] == given, "applied state != verified preview"
    assert applies >= 1


def check_i20_cache_share(entries: list[LedgerEntry], floor: float = 0.80) -> None:
    turns = [e for e in entries if e.actor == "model" and e.iteration >= 2]
    assert turns
    for entry in turns:
        assert ledger.cache_share(entry.usage) >= floor, (entry.iteration, entry.usage)


def check_definition_of_done(
    out: Path, result: Result, entries: list[LedgerEntry], budget_s: float
) -> None:
    summary = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
    assert summary["elapsed_s"] <= budget_s
    assert summary["usage"]["iterations"] <= 12
    assert json.loads((out / "review_queue.json").read_text(encoding="utf-8"))
    assert len(entries) > 3
    for name in OUTPUTS:
        assert (out / name).is_file(), name
    assert not result.result.violations
    assert result.j_after < result.j_before


# --- offline run ---------------------------------------------------------------------------


def test_offline_run_meets_the_definition_of_done(
    out: Path, result: Result, entries: list[LedgerEntry]
) -> None:
    check_definition_of_done(out, result, entries, budget_s=60)
    assert entries[0].event == "run_start" and entries[-1].event == "run_finish"
    assert result.result.metrics.mean_post_wait <= 25
    assert result.review[0].reason_code.value == "STRETCHER"


def test_i16_numbers_come_from_tools(entries: list[LedgerEntry]) -> None:
    check_i16_numbers_come_from_tools(entries)
    assert any(e.payload["claims"] for e in entries if e.actor == "model")


def test_i17_no_phi_in_any_output(out: Path, result: Result) -> None:
    del result
    check_i17_no_phi(out)


def test_i18_ledger_replays_byte_for_byte(
    baseline: State, entries: list[LedgerEntry], out: Path
) -> None:
    check_i18_ledger_replays_byte_for_byte(baseline, entries, out)


def test_i19_every_apply_follows_a_clean_verify(entries: list[LedgerEntry]) -> None:
    check_i19_every_apply_follows_a_clean_verify(entries)


def test_i20_check_runs_on_the_imitation_usage(entries: list[LedgerEntry]) -> None:
    check_i20_cache_share(entries)


def test_every_ledger_entry_carries_provenance(entries: list[LedgerEntry]) -> None:
    run_ids = {e.run_id for e in entries}
    assert len(run_ids) == 1
    for entry in entries:
        assert entry.prompt_versions == {"mediator": 1}
        assert {"roster.json", "manifest.json", "block_a", "block_c"} <= set(entry.input_hashes)
        assert entry.git_sha and entry.model_id


def test_a_tampered_verify_hash_breaks_i19(entries: list[LedgerEntry]) -> None:
    tampered = [e.model_copy(deep=True) for e in entries]
    for entry in tampered:
        if entry.event == "verify":
            entry.payload["result"]["verify_hash"] = "sha256:0"
    with pytest.raises(AssertionError):
        check_i19_every_apply_follows_a_clean_verify(tampered)


def test_the_harness_forces_finish_at_the_iteration_cap(tmp_path: Path) -> None:
    rules = copy.deepcopy(load_rules())
    rules["stop"]["max_iterations"] = 1
    out = tmp_path / "capped"
    result = orchestrator.run(DATA, out, FakeMediator(), echo=lambda *_: None, rules=rules)
    entries = ledger.read(out / "ledger.jsonl")
    forced = [e for e in entries if e.event == "finish" and "forced" in e.payload["input"]]
    assert forced and "iteration cap" in forced[0].payload["input"]["forced"]
    assert entries[-1].payload["reason"].startswith("iteration cap")
    assert max(e.iteration for e in entries if e.actor == "model") == 1
    assert not result.result.violations
    check_i18_ledger_replays_byte_for_byte(load_state(DATA), entries, out)
