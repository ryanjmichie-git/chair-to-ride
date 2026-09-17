"""Repo checks for the JSON Schemas, the generated models and config/rules.yaml."""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "specs" / "schemas"
MODELS_DIR = ROOT / "src" / "c2r" / "models"
SCHEMAS = sorted(SCHEMA_DIR.glob("*.schema.json"))
DOCUMENTS = {
    "unit.json": "unit.schema.json",
    "roster.json": "roster.schema.json",
    "manifest.json": "manifest.schema.json",
    "fleet.json": "fleet.schema.json",
    "travel.json": "travel.schema.json",
}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _registry() -> Registry:
    registry = Registry()
    for path in SCHEMAS:
        contents = _load(path)
        registry = registry.with_resource(contents["$id"], Resource.from_contents(contents))
    return registry


def _validator(schema_name: str) -> Draft202012Validator:
    return Draft202012Validator(_load(SCHEMA_DIR / schema_name), registry=_registry())


def _makefile_models_command() -> str:
    lines = (ROOT / "Makefile").read_text(encoding="utf-8").splitlines()
    return lines[lines.index("models:") + 1].strip()


def test_schema_files_are_the_expected_set() -> None:
    assert len(SCHEMAS) == 15


@pytest.mark.parametrize("path", SCHEMAS, ids=lambda path: path.name)
def test_schema_is_valid_draft_2020_12(path: Path) -> None:
    Draft202012Validator.check_schema(_load(path))


def test_generated_models_are_not_stale(tmp_path: Path) -> None:
    shutil.copy(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    output = tmp_path / "models"
    command = _makefile_models_command().replace("src/c2r/models", output.as_posix())
    subprocess.run(shlex.split(command), cwd=ROOT, check=True)
    committed = {path.name: path.read_bytes() for path in sorted(MODELS_DIR.glob("*.py"))}
    regenerated = {path.name: path.read_bytes() for path in sorted(output.glob("*.py"))}
    assert regenerated == committed


def test_rules_yaml_validates() -> None:
    rules = yaml.safe_load((ROOT / "config" / "rules.yaml").read_text(encoding="utf-8"))
    _validator("rules.schema.json").validate(rules)


def test_synthetic_documents_validate() -> None:
    directories = sorted(p for p in (ROOT / "data" / "synthetic").glob("*") if p.is_dir())
    if not directories:
        pytest.skip("no synthetic data generated yet")
    event_validator = _validator("event.schema.json")
    for directory in directories:
        for filename, schema_name in DOCUMENTS.items():
            _validator(schema_name).validate(_load(directory / filename))
        events = directory / "events.jsonl"
        if not events.exists():
            continue
        for line in events.read_text(encoding="utf-8").splitlines():
            if line.strip():
                event_validator.validate(json.loads(line))
