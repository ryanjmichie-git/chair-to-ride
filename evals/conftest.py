"""Shared fixtures: one offline mediator run per session, reused by every module.

``evals/fakerun.py`` builds it once and caches it by the digest of its inputs; each xdist
worker copies the cached run into its own directory so no module's writes (explanations,
verdicts) reach another worker.
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from c2r.solver import Result

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fakerun  # the path above makes this importable

DATA = fakerun.DATA


@dataclass
class FakeRun:
    out: Path
    result: Result


@pytest.fixture(scope="session")
def fake_run(tmp_path_factory: pytest.TempPathFactory) -> FakeRun:
    """The CP2 loop with the scripted mediator; every module that needs a finished run reads it."""
    try:
        shared = fakerun.ensure()
    except (RuntimeError, TimeoutError) as exc:
        pytest.fail(str(exc))
    out = tmp_path_factory.mktemp("cp2-fake")
    shutil.copytree(shared / "run", out, dirs_exist_ok=True)
    return FakeRun(out, fakerun.load(shared))
