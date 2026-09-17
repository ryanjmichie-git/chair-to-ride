"""The gate's shared offline mediator run, built once and cached by what it depends on.

The run is a pure function of the code under ``src/c2r``, ``config/``, the seed-42 day, the
mediator prompt and ``pyproject.toml``, so it lives under ``runs/.fake-run-cache/<digest>`` and
is rebuilt only when one of those changes. ``run_evals.py --gate`` calls ``ensure()`` serially
before pytest starts, so the run's own clock (``metrics.json["elapsed_s"]``, asserted by
test_mediator) is measured on an idle machine; the xdist workers then only copy it. A worker
that finds no cache (a bare ``pytest``) builds it behind a lock file; the others wait, and a
build that crashes leaves a FAILED marker so nobody waits for it.
"""

from __future__ import annotations

import hashlib
import os
import pickle
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "synthetic" / "42"
CACHE = ROOT / "runs" / ".fake-run-cache"
INPUTS = ("src/c2r", "config", "data/synthetic/42", "prompts/mediator.v1.md", "pyproject.toml")
BUILD_TIMEOUT_S = 240.0


def digest() -> str:
    sha = hashlib.sha256()
    for name in INPUTS:
        entry = ROOT / name
        files = [entry] if entry.is_file() else sorted(p for p in entry.rglob("*") if p.is_file())
        for path in files:
            if "__pycache__" in path.parts:
                continue
            sha.update(path.relative_to(ROOT).as_posix().encode("utf-8"))
            sha.update(path.read_bytes())
    return sha.hexdigest()[:16]


def _build(shared: Path):
    from c2r import orchestrator
    from c2r.llm import FakeMediator

    try:
        result = orchestrator.run(DATA, shared / "run", FakeMediator(), echo=lambda *_: None)
        (shared / "result.pkl").write_bytes(pickle.dumps(result))
        (shared / "DONE").write_text("1", encoding="utf-8")
    except BaseException as exc:
        (shared / "FAILED").write_text(f"{type(exc).__name__}: {exc}", encoding="utf-8")
        raise
    return result


def ensure(echo=None) -> Path:
    """The cached run's directory, building it first if this digest has none."""
    shared = CACHE / digest()
    shared.mkdir(parents=True, exist_ok=True)
    done, failed = shared / "DONE", shared / "FAILED"
    if done.is_file():
        return shared
    if failed.is_file():
        failed.unlink()  # a rebuild gets a fresh chance
        (shared / "LOCK").unlink(missing_ok=True)
    try:
        handle = os.open(shared / "LOCK", os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        handle = None
    if handle is not None:
        os.close(handle)
        for stale in CACHE.iterdir():
            if stale != shared and stale.is_dir():
                shutil.rmtree(stale, ignore_errors=True)
        started = time.monotonic()
        _build(shared)
        if echo:
            echo(f"fake run: built in {time.monotonic() - started:.1f} s -> {shared}")
        return shared
    started = time.monotonic()
    while not done.is_file():
        if failed.is_file():
            raise RuntimeError(f"the shared fake run failed: {failed.read_text(encoding='utf-8')}")
        if time.monotonic() - started > BUILD_TIMEOUT_S:
            raise TimeoutError(f"the shared fake run in {shared} was not built in time")
        time.sleep(0.5)
    return shared


def load(shared: Path):
    return pickle.loads((shared / "result.pkl").read_bytes())
