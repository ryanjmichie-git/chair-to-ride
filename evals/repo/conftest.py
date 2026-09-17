"""The throwaway repo tree every hook test drives a hook against (shared by test_hooks*.py)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FROZEN = "---\nname: mediator\nversion: 1\neval_result: pass\n---\n\nbody\n"
OPEN = "---\nname: explainer\nversion: 1\neval_result: null\n---\n\nbody\n"
INDEX = (
    "| Checkpoint | Status | Spec | Deliverable |\n"
    "|---|---|---|---|\n"
    "| CP1 | active | specs/cp1.md | scaffold |\n"
)
STUB_RUNNER = (
    "import pathlib\n"
    "pathlib.Path(__file__).resolve().parents[1].joinpath('ran.flag').write_text('1')\n"
    "raise SystemExit(0)\n"
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "frozen.v1.md").write_text(FROZEN, encoding="utf-8")
    (tmp_path / "prompts" / "open.v1.md").write_text(OPEN, encoding="utf-8")
    (tmp_path / "src" / "c2r").mkdir(parents=True)
    (tmp_path / "src" / "c2r" / "__init__.py").write_text("", encoding="utf-8")
    shutil.copyfile(ROOT / "src" / "c2r" / "phi.py", tmp_path / "src" / "c2r" / "phi.py")
    (tmp_path / "evals").mkdir()
    (tmp_path / "evals" / "run_evals.py").write_text(STUB_RUNNER, encoding="utf-8")
    (tmp_path / "specs").mkdir()
    (tmp_path / "specs" / "INDEX.md").write_text(INDEX, encoding="utf-8")
    (tmp_path / "temp").mkdir()
    return tmp_path
