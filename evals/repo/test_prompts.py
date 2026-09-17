"""Prompt files are versioned, one frontmatter key per line, and free of PHI patterns.

``eval_result`` must be a scalar or a one-line flow mapping: the freeze hook's parser turns a
block mapping into the sentinel ``<block>`` and freezes the file (CP3 definition of done).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from c2r.phi import find_phi

ROOT = Path(__file__).resolve().parents[2]
PROMPTS = sorted((ROOT / "prompts").glob("*.v*.md"))
DATA = sorted((ROOT / "evals" / "data").glob("*.json"))
MODELS = {"claude-fable-5-1", "claude-sonnet-5", "claude-haiku-4-5-20251001"}
REQUIRED = ("name", "version", "model", "changed_by", "change_reason", "eval_result")


def _frontmatter(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines and lines[0].strip() == "---", path.name
    end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    fields: dict[str, str] = {}
    for line in lines[1:end]:
        assert not line[:1].isspace(), f"{path.name}: block value {line!r}; keep one key per line"
        key, sep, value = line.partition(":")
        assert sep and key.strip(), f"{path.name}: not a key: value line: {line!r}"
        fields[key.strip()] = value.strip()
    return fields


@pytest.mark.parametrize("path", PROMPTS, ids=[p.name for p in PROMPTS])
def test_frontmatter_is_one_line_per_key(path: Path) -> None:
    fields = _frontmatter(path)
    assert set(REQUIRED) <= set(fields), path.name
    assert fields["version"].isdigit(), fields["version"]
    assert re.fullmatch(rf"{fields['name']}\.v{fields['version']}\.md", path.name)
    assert fields["model"] in MODELS, fields["model"]
    result = fields["eval_result"]
    assert result == "null" or not result.startswith("{") or result.endswith("}"), result


def test_the_three_live_prompts_exist() -> None:
    assert {p.name for p in PROMPTS} >= {"mediator.v1.md", "explainer.v1.md", "judge.v1.md"}


@pytest.mark.parametrize("path", PROMPTS + DATA, ids=[p.name for p in PROMPTS + DATA])
def test_no_phi_pattern_in_prompts_or_eval_data(path: Path) -> None:
    assert find_phi(path.read_text(encoding="utf-8")) == [], path.name


def test_golden_and_calibration_files_are_well_formed() -> None:
    golden = json.loads((ROOT / "evals" / "data" / "golden_explanations.json").read_text("utf-8"))
    assert [g["golden_id"] for g in golden] == [f"G{n:02d}" for n in range(1, 13)]
    calibration = json.loads(
        (ROOT / "evals" / "data" / "judge_calibration.json").read_text("utf-8")
    )
    assert [c["calibration_id"] for c in calibration] == [f"C{n:02d}" for n in range(1, 11)]
    assert all(c["human_pass"] in (None, True, False) for c in calibration)
