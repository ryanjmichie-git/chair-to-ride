"""Drive every Claude Code hook as a subprocess against a synthetic repo tree."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".claude" / "hooks"
SSN = '{"note": "SSN 123-45-6789"}'
CLEAN = '{"note": "Node 17, Zone C at 06:30"}'


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


HOOK_COMMAND_PREFIX = 'python "${CLAUDE_PROJECT_DIR}/.claude/hooks/'
BLOCK_FROZEN = (
    "---\nname: judge\nversion: 2\neval_result:\n  accuracy: 0.91\n  plain: 0.88\n---\n\nbody\n"
)
FAIL_RUNNER = "print('GATE FAIL (evals/repo: 1 failed, 0.1s)')\nraise SystemExit(1)\n"
INVARIANT_STUB = "def test_ok() -> None:\n    assert True\n"


def run_without_path(
    name: str, event: dict[str, object], root: Path
) -> subprocess.CompletedProcess[str]:
    empty = root / "nopath"
    empty.mkdir(exist_ok=True)
    env = {**os.environ, "C2R_ROOT": str(root), "TEMP": str(root / "temp"), "PATH": str(empty)}
    env.pop("PYTHONPATH", None)
    return subprocess.run(
        [sys.executable, str(HOOKS / name)],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        cwd=str(root),
        env=env,
        check=False,
    )


def settings_hook_commands() -> list[str]:
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    return [
        hook["command"]
        for events in settings["hooks"].values()
        for entry in events
        for hook in entry["hooks"]
    ]


def agent_hook_commands() -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for path in sorted((ROOT / ".claude" / "agents").glob("*.md")):
        lines = path.read_text(encoding="utf-8").splitlines()
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
        for line in lines[1:end]:
            key, sep, value = line.strip().partition(":")
            raw = value.strip()
            if sep and key == "command" and raw:
                found.append((path.name, json.loads(raw) if raw.startswith('"') else raw))
    return found


def test_settings_hook_commands_are_project_dir_absolute() -> None:
    commands = settings_hook_commands()
    assert len(commands) == 10
    for command in commands:
        assert command.startswith(HOOK_COMMAND_PREFIX), command


def test_agent_hook_commands_are_project_dir_absolute() -> None:
    commands = agent_hook_commands()
    assert len(commands) == 7
    for name, command in commands:
        assert command.startswith(HOOK_COMMAND_PREFIX), f"{name}: {command}"


def test_prompt_freeze_blocks_a_block_mapping_eval_result(repo: Path) -> None:
    (repo / "prompts" / "block.v1.md").write_text(BLOCK_FROZEN, encoding="utf-8")
    proc = run_hook("prompt_freeze.py", write_event(repo, "prompts/block.v1.md", "x"), repo)
    assert proc.returncode == 2
    assert "frozen" in proc.stderr


@pytest.mark.parametrize(
    "command",
    [
        'bash -c "rm -rf src"',
        "sh -c 'rm -rf src'",
        "mkdir -p data/real",
        'touch "data/real/x.json"',
        "echo hi > data/real/f.json",
        "cp roster.json data/real/roster.json",
        "mv roster.json data/real/roster.json",
    ],
)
def test_danger_guard_blocks_masked_shells_and_data_real(repo: Path, command: str) -> None:
    proc = run_hook("danger_guard.py", bash_event(repo, command), repo)
    assert proc.returncode == 2


@pytest.mark.parametrize(
    "command",
    ["mkdir -p data/synthetic/43", "cp a.json data/synthetic/43/a.json", "ls data/synthetic"],
)
def test_danger_guard_still_allows_synthetic_paths(repo: Path, command: str) -> None:
    proc = run_hook("danger_guard.py", bash_event(repo, command), repo)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("command", ["git diff > out.txt", "git status && git diff >> out.txt"])
def test_bash_allow_denies_redirection(repo: Path, command: str) -> None:
    proc = run_hook(
        "bash_allow.py", bash_event(repo, command), repo, "--allow", "git diff", "git status"
    )
    assert proc.returncode == 2
    assert "redirect" in proc.stderr


def test_path_guard_denies_a_path_outside_the_repo(repo: Path) -> None:
    event = {
        "session_id": "s1",
        "cwd": str(repo),
        "hook_event_name": "PreToolUse",
        "permission_mode": "default",
        "tool_name": "Write",
        "tool_input": {"file_path": str(repo.parent / "outside.py"), "content": "x"},
    }
    assert run_hook("path_guard.py", event, repo, "--allow", "runs/**").returncode == 2
    assert run_hook("path_guard.py", event, repo, "--deny", "prompts/**").returncode == 0


def test_eval_gate_reports_a_skip_when_uv_is_missing(repo: Path) -> None:
    proc = run_without_path("eval_gate.py", stop_event(repo), repo)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["systemMessage"].startswith("eval gate skipped:")
    assert not (repo / "runs" / ".gate_ok").is_file()


def test_pytest_quick_reports_a_skip_when_uv_is_missing(repo: Path) -> None:
    invariants = repo / "evals" / "invariants"
    invariants.mkdir()
    (invariants / "test_stub.py").write_text(INVARIANT_STUB, encoding="utf-8")
    event = write_event(repo, "src/c2r/solver.py", "x", "PostToolUse")
    proc = run_without_path("pytest_quick.py", event, repo)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["systemMessage"].startswith("invariant tests skipped:")


def test_eval_gate_blocks_when_the_runner_fails(repo: Path) -> None:
    (repo / "evals" / "run_evals.py").write_text(FAIL_RUNNER, encoding="utf-8")
    proc = run_hook("eval_gate.py", stop_event(repo), repo)
    assert proc.returncode == 2
    assert "GATE FAIL" in proc.stderr
    assert json.loads(proc.stdout)["decision"] == "block"
    assert not (repo / "runs" / ".gate_ok").is_file()
