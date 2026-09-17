"""Shared fixtures: one offline mediator run per session, reused by the CP2 and CP3 tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from c2r import orchestrator
from c2r.llm import FakeMediator
from c2r.solver import Result

DATA = Path(__file__).resolve().parents[1] / "data" / "synthetic" / "42"


@dataclass
class FakeRun:
    out: Path
    result: Result


@pytest.fixture(scope="session")
def fake_run(tmp_path_factory: pytest.TempPathFactory) -> FakeRun:
    """The CP2 loop with the scripted mediator; every module that needs a finished run reads it."""
    out = tmp_path_factory.mktemp("cp2-fake")
    result = orchestrator.run(DATA, out, FakeMediator(), echo=lambda *_: None)
    return FakeRun(out, result)
