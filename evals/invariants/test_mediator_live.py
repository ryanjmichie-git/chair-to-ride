"""I16-I20 and the CP2 definition of done on one live Fable 5.1 run (needs ANTHROPIC_API_KEY)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from c2r import ledger, orchestrator
from c2r.llm import AnthropicMediator
from c2r.models import LedgerEntry
from c2r.solver import Result
from c2r.state import State, load_state
from invariants.test_mediator import (
    DATA,
    check_definition_of_done,
    check_i16_numbers_come_from_tools,
    check_i17_no_phi,
    check_i18_ledger_replays_byte_for_byte,
    check_i19_every_apply_follows_a_clean_verify,
    check_i20_cache_share,
)

pytestmark = [
    pytest.mark.llm,
    pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="needs ANTHROPIC_API_KEY"),
]


@pytest.fixture(scope="module")
def baseline() -> State:
    return load_state(DATA)


@pytest.fixture(scope="module")
def out(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("cp2-live")


@pytest.fixture(scope="module")
def result(out: Path) -> Result:
    return orchestrator.run(DATA, out, AnthropicMediator(), echo=lambda *_: None)


@pytest.fixture(scope="module")
def entries(out: Path, result: Result) -> list[LedgerEntry]:
    del result
    return ledger.read(out / "ledger.jsonl")


def test_live_run_meets_the_definition_of_done(
    out: Path, result: Result, entries: list[LedgerEntry]
) -> None:
    check_definition_of_done(out, result, entries, budget_s=90)
    assert ledger.usage_summary(entries)["cost_usd"] > 0


def test_i16_live(entries: list[LedgerEntry]) -> None:
    check_i16_numbers_come_from_tools(entries)


def test_i17_live(out: Path, result: Result) -> None:
    del result
    check_i17_no_phi(out)


def test_i18_live(baseline: State, entries: list[LedgerEntry], out: Path) -> None:
    check_i18_ledger_replays_byte_for_byte(baseline, entries, out)


def test_i19_live(entries: list[LedgerEntry]) -> None:
    check_i19_every_apply_follows_a_clean_verify(entries)


def test_i20_cache_read_share_from_iteration_two(entries: list[LedgerEntry]) -> None:
    check_i20_cache_share(entries)
