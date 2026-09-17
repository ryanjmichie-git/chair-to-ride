"""CLAUDE.md contract: 60 lines, an @specs/INDEX.md import, and at most 15 lessons."""

from __future__ import annotations

from pathlib import Path

import pytest

CLAUDE_MD = Path(__file__).resolve().parents[2] / "CLAUDE.md"
MAX_LINES = 60
MAX_LESSONS = 15


def _lines() -> list[str]:
    if not CLAUDE_MD.is_file():
        pytest.fail(f"{CLAUDE_MD} is missing")
    return CLAUDE_MD.read_text(encoding="utf-8").splitlines()


def test_at_most_60_lines() -> None:
    lines = _lines()
    assert len(lines) <= MAX_LINES, f"CLAUDE.md is {len(lines)} lines"


def test_imports_spec_index() -> None:
    assert "@specs/INDEX.md" in [line.strip() for line in _lines()]


def test_lessons_heading_is_capped() -> None:
    lines = _lines()
    starts = [i for i, line in enumerate(lines) if line.strip() == "# Lessons"]
    assert len(starts) == 1, "CLAUDE.md needs exactly one '# Lessons' heading"
    bullets = 0
    for line in lines[starts[0] + 1 :]:
        if line.startswith("#"):
            break
        if line.lstrip().startswith("- "):
            bullets += 1
    assert bullets <= MAX_LESSONS, f"CLAUDE.md holds {bullets} lessons"
