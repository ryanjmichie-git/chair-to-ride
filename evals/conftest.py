"""Shared fixtures: one offline mediator run per pytest session, reused by every module.

Under pytest-xdist each worker asks for the run; the first one to take the lock builds it in a
directory all workers can see, the others wait for it, and every worker then works on its own
copy so no module's writes (explanations, verdicts) reach another worker.
"""

from __future__ import annotations

import os
import pickle
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from c2r import orchestrator
from c2r.llm import FakeMediator
from c2r.solver import Result

DATA = Path(__file__).resolve().parents[1] / "data" / "synthetic" / "42"
BUILD_TIMEOUT_S = 300.0


@dataclass
class FakeRun:
    out: Path
    result: Result


def _shared_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    base = tmp_path_factory.getbasetemp()
    return base.parent if base.name.startswith("popen-") else base  # xdist workers share the parent


def _build(shared: Path) -> Result:
    result = orchestrator.run(DATA, shared / "run", FakeMediator(), echo=lambda *_: None)
    (shared / "result.pkl").write_bytes(pickle.dumps(result))
    (shared / "DONE").write_text("1", encoding="utf-8")
    return result


@pytest.fixture(scope="session")
def fake_run(tmp_path_factory: pytest.TempPathFactory) -> FakeRun:
    """The CP2 loop with the scripted mediator; every module that needs a finished run reads it."""
    shared = _shared_root(tmp_path_factory) / "cp2-fake-shared"
    shared.mkdir(parents=True, exist_ok=True)
    done = shared / "DONE"
    if not done.is_file():
        try:
            handle = os.open(shared / "LOCK", os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            handle = None
        if handle is not None:
            os.close(handle)
            result = _build(shared)
        else:
            started = time.monotonic()
            while not done.is_file():
                if time.monotonic() - started > BUILD_TIMEOUT_S:
                    pytest.fail(f"the shared fake run in {shared} was not built in time")
                time.sleep(0.5)
            result = pickle.loads((shared / "result.pkl").read_bytes())
    else:
        result = pickle.loads((shared / "result.pkl").read_bytes())
    out = tmp_path_factory.mktemp("cp2-fake")
    shutil.copytree(shared / "run", out, dirs_exist_ok=True)
    return FakeRun(out, result)
