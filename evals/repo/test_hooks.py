"""Drive every Claude Code hook as a subprocess against a synthetic repo tree."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".claude" / "hooks"
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
SSN = '{"note": "SSN 123-45-6789"}'
CLEAN = '{"note": "Node 17, Zone C at 06:30"}'


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


def run_hook(
    name: str, event: dict[str, object], root: Path, *args: str
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "C2R_ROOT": str(root), "TEMP": str(root / "temp")}
    env.pop("PYTHONPATH", None)
    return subprocess.run(
        [sys.executable, str(HOOKS / name), *args],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        cwd=str(root),
        env=env,
        check=False,
    )


def write_event(root: Path, rel: str, content: str = "", event_name: str = "PreToolUse") -> dict:
    return {
        "session_id": "s1",
        "cwd": str(root),
        "hook_event_name": event_name,
        "permission_mode": "default",
        "tool_name": "Write",
        "tool_input": {"file_path": str(root / rel), "content": content},
    }


def bash_event(root: Path, command: str) -> dict:
    return {
        "session_id": "s1",
        "cwd": str(root),
        "hook_event_name": "PreToolUse",
        "permission_mode": "default",
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }


def stop_event(root: Path, active: bool = False) -> dict:
    return {
        "session_id": "s1",
        "cwd": str(root),
        "hook_event_name": "Stop",
        "permission_mode": "default",
        "stop_hook_active": active,
    }


def test_phi_guard_blocks_data_real(repo: Path) -> None:
    proc = run_hook("phi_guard.py", write_event(repo, "data/real/x.json", CLEAN), repo)
    assert proc.returncode == 2
    assert "data/real" in proc.stderr


def test_phi_guard_blocks_phi_under_data(repo: Path) -> None:
    proc = run_hook("phi_guard.py", write_event(repo, "data/x.json", SSN), repo)
    assert proc.returncode == 2
    assert "ssn" in proc.stderr


def test_phi_guard_ignores_source_files(repo: Path) -> None:
    proc = run_hook("phi_guard.py", write_event(repo, "src/x.py", SSN), repo)
    assert proc.returncode == 0


def test_phi_guard_allows_clean_data(repo: Path) -> None:
    proc = run_hook("phi_guard.py", write_event(repo, "data/x.json", CLEAN), repo)
    assert proc.returncode == 0


def test_phi_guard_fails_open_on_bad_stdin(repo: Path) -> None:
    proc = subprocess.run(
        [sys.executable, str(HOOKS / "phi_guard.py")],
        input="not json",
        capture_output=True,
        text=True,
        cwd=str(repo),
        env={**os.environ, "C2R_ROOT": str(repo)},
        check=False,
    )
    assert proc.returncode == 0


def test_phi_guard_fails_open_on_non_dict_tool_input(repo: Path) -> None:
    event = {
        "session_id": "s1",
        "cwd": str(repo),
        "hook_event_name": "PreToolUse",
        "permission_mode": "default",
        "tool_name": "Write",
        "tool_input": "not-a-dict",
    }
    proc = run_hook("phi_guard.py", event, repo)
    assert proc.returncode == 0, proc.stderr


def test_prompt_freeze_blocks_frozen_version(repo: Path) -> None:
    proc = run_hook("prompt_freeze.py", write_event(repo, "prompts/frozen.v1.md", "x"), repo)
    assert proc.returncode == 2
    assert "frozen" in proc.stderr


def test_prompt_freeze_allows_unevaluated_version(repo: Path) -> None:
    proc = run_hook("prompt_freeze.py", write_event(repo, "prompts/open.v1.md", "x"), repo)
    assert proc.returncode == 0


def test_prompt_freeze_allows_new_version(repo: Path) -> None:
    proc = run_hook("prompt_freeze.py", write_event(repo, "prompts/new.v2.md", "x"), repo)
    assert proc.returncode == 0


@pytest.mark.parametrize(
    "command",
    [
        "git push --force",
        "git push -f",
        "rm -rf src",
        "rm -Rf src",
        "rm -fR src",
        "git reset --hard",
        'rm -rf "$TEMP/x" && rm -rf src',
        "rm -rf $TEMP/x ; rm -rf src",
    ],
)
def test_danger_guard_blocks(repo: Path, command: str) -> None:
    proc = run_hook("danger_guard.py", bash_event(repo, command), repo)
    assert proc.returncode == 2


@pytest.mark.parametrize(
    "command",
    [
        "git push",
        "git push origin feature-f",
        'echo "rm -rf"',
        'rm -rf "$TEMP/x"',
        'rm -rf "$TEMP/x" && rm -rf "$TEMP/y"',
    ],
)
def test_danger_guard_allows(repo: Path, command: str) -> None:
    proc = run_hook("danger_guard.py", bash_event(repo, command), repo)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize(
    ("rel", "args", "expected"),
    [
        ("prompts/a.md", ("--deny", "prompts/**"), 2),
        ("src/a.py", ("--deny", "prompts/**"), 0),
        ("src/a.py", ("--allow", "runs/**"), 2),
        ("runs/r1/x.json", ("--allow", "runs/**"), 0),
        ("prompts/a.md", ("--deny", "prompts/**", "viz/**"), 2),
        ("viz/a.js", ("--deny", "prompts/**", "viz/**"), 2),
        ("src/a.py", ("--deny", "prompts/**", "viz/**"), 0),
        ("runs/r1/x.json", ("--allow", "runs/**", "docs/**"), 0),
        ("docs/a.md", ("--allow", "runs/**", "docs/**"), 0),
        ("src/a.py", ("--allow", "runs/**", "docs/**"), 2),
    ],
)
def test_path_guard(repo: Path, rel: str, args: tuple[str, ...], expected: int) -> None:
    proc = run_hook("path_guard.py", write_event(repo, rel), repo, *args)
    assert proc.returncode == expected, proc.stderr


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("git diff HEAD", 0),
        ("uv run pytest -q && git status", 0),
        ("git commit -m x", 2),
    ],
)
def test_bash_allow(repo: Path, command: str, expected: int) -> None:
    proc = run_hook(
        "bash_allow.py",
        bash_event(repo, command),
        repo,
        "--allow",
        "git diff",
        "--allow",
        "git status",
        "--allow",
        "uv run pytest",
    )
    assert proc.returncode == expected, proc.stderr


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("git diff HEAD", 0),
        ("git log --oneline", 0),
        ("pytest -q", 0),
        ("uv run pytest -q && git status", 0),
        ("git commit -m x", 2),
    ],
)
def test_bash_allow_multi_value_form(repo: Path, command: str, expected: int) -> None:
    proc = run_hook(
        "bash_allow.py",
        bash_event(repo, command),
        repo,
        "--allow",
        "pytest",
        "uv run pytest",
        "git diff",
        "git log",
        "git status",
    )
    assert proc.returncode == expected, proc.stderr


def test_eval_gate_skips_when_already_active(repo: Path) -> None:
    proc = run_hook("eval_gate.py", stop_event(repo, active=True), repo)
    assert proc.returncode == 0
    assert not (repo / "ran.flag").exists()


def test_eval_gate_passes_with_passing_runner(repo: Path) -> None:
    proc = run_hook("eval_gate.py", stop_event(repo), repo)
    assert proc.returncode == 0, proc.stderr
    assert (repo / "ran.flag").is_file(), "the stub runner was never invoked"
    marker = repo / "runs" / ".gate_ok"
    assert marker.is_file(), "runs/.gate_ok was not written"
    assert marker.read_text(encoding="utf-8").strip() != ""


def test_eval_gate_cache_hit_skips_the_runner(repo: Path) -> None:
    assert run_hook("eval_gate.py", stop_event(repo), repo).returncode == 0
    (repo / "ran.flag").unlink()
    proc = run_hook("eval_gate.py", stop_event(repo), repo)
    assert proc.returncode == 0, proc.stderr
    assert not (repo / "ran.flag").exists(), "a cached digest still re-ran the runner"


def test_eval_gate_reruns_after_a_source_change(repo: Path) -> None:
    assert run_hook("eval_gate.py", stop_event(repo), repo).returncode == 0
    (repo / "ran.flag").unlink()
    (repo / "src" / "c2r" / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    assert run_hook("eval_gate.py", stop_event(repo), repo).returncode == 0
    assert (repo / "ran.flag").is_file(), "a source change did not invalidate the digest"


def test_session_brief_reports_active_checkpoint(repo: Path) -> None:
    event = {
        "session_id": "s1",
        "cwd": str(repo),
        "hook_event_name": "SessionStart",
        "permission_mode": "default",
        "source": "startup",
    }
    proc = run_hook("session_brief.py", event, repo)
    assert proc.returncode == 0
    assert "active" in proc.stdout


def test_session_brief_is_silent_on_empty_repo(tmp_path: Path) -> None:
    event = {
        "session_id": "s1",
        "cwd": str(tmp_path),
        "hook_event_name": "SessionStart",
        "permission_mode": "default",
        "source": "startup",
    }
    proc = run_hook("session_brief.py", event, tmp_path)
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


def test_pytest_quick_ignores_unwatched_paths(repo: Path) -> None:
    event = write_event(repo, "src/c2r/viz/timeline.py", "x", "PostToolUse")
    proc = run_hook("pytest_quick.py", event, repo)
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


def test_render_timeline_skips_without_renderer(repo: Path) -> None:
    event = write_event(repo, "runs/r1/schedule_after.json", "{}", "PostToolUse")
    proc = run_hook("render_timeline.py", event, repo)
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""
