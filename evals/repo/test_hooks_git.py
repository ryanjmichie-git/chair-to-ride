"""The git-aware hooks (K2 diff size, CP4 code freeze) driven as subprocesses against a
throwaway git repo. Split from test_hooks.py so xdist can run the two halves side by side."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from test_hooks import bash_event, run_hook, write_event


def _git_repo(repo: Path, src_lines: int) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@x",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@x",
    }
    subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True, env=env)
    subprocess.run(["git", "add", "-A"], cwd=str(repo), check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=str(repo), check=True, env=env)
    (repo / "src" / "c2r" / "big.py").write_text("x = 1\n" * src_lines, encoding="utf-8")


def test_k2_guard_blocks_a_large_staged_src_diff(repo: Path) -> None:
    _git_repo(repo, 401)
    subprocess.run(["git", "add", "-A"], cwd=str(repo), check=True)
    proc = run_hook("k2_guard.py", bash_event(repo, 'git commit -m "cp1: big"'), repo)
    assert proc.returncode == 2
    assert "401 lines" in proc.stderr and "src/c2r/big.py" in proc.stderr


def test_k2_guard_counts_what_git_add_would_stage(repo: Path) -> None:
    _git_repo(repo, 401)
    proc = run_hook("k2_guard.py", bash_event(repo, 'git add -A && git commit -m "cp1: big"'), repo)
    assert proc.returncode == 2
    proc = run_hook("k2_guard.py", bash_event(repo, 'git commit -m "cp1: nothing staged"'), repo)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize(
    "command", ['git commit -m "cp1: small"', 'echo "git commit"', "git status"]
)
def test_k2_guard_allows_small_diffs_and_other_commands(repo: Path, command: str) -> None:
    _git_repo(repo, 400)
    subprocess.run(["git", "add", "-A"], cwd=str(repo), check=True)
    proc = run_hook("k2_guard.py", bash_event(repo, command), repo)
    assert proc.returncode == 0, proc.stderr


def test_k2_guard_fails_open_outside_a_git_repo(repo: Path) -> None:
    proc = run_hook("k2_guard.py", bash_event(repo, 'git commit -m "x"'), repo)
    assert proc.returncode == 0, proc.stderr


# --- code freeze (CP4) -------------------------------------------------------------------------

FREEZE = {
    "active": True,
    "since": "cp4",
    "frozen": ["src/c2r/**"],
    "allowed": ["src/c2r/viz/**"],
    "waivers": [{"path": "src/c2r/waived.py", "spec": "specs/cp5.md", "reviewer": "B"}],
}


def _freeze(repo: Path, active: bool = True) -> None:
    (repo / ".claude").mkdir(exist_ok=True)
    (repo / ".claude" / "freeze.json").write_text(
        json.dumps({**FREEZE, "active": active}), encoding="utf-8"
    )


@pytest.mark.parametrize("rel", ["src/c2r/solver.py", "src/c2r/parties/unit.py"])
def test_code_freeze_denies_a_frozen_edit(repo: Path, rel: str) -> None:
    _freeze(repo)
    proc = run_hook("code_freeze.py", write_event(repo, rel, "x = 1"), repo)
    assert proc.returncode == 2
    assert "code freeze" in proc.stderr and rel in proc.stderr and "waiver" in proc.stderr


@pytest.mark.parametrize(
    "rel", ["src/c2r/viz/timeline.py", "src/c2r/waived.py", "evals/suite.py", "docs/x.md"]
)
def test_code_freeze_allows_viz_waived_and_other_paths(repo: Path, rel: str) -> None:
    _freeze(repo)
    proc = run_hook("code_freeze.py", write_event(repo, rel, "x = 1"), repo)
    assert proc.returncode == 0, proc.stderr


def test_code_freeze_is_off_without_an_active_file(repo: Path) -> None:
    proc = run_hook("code_freeze.py", write_event(repo, "src/c2r/solver.py", "x"), repo)
    assert proc.returncode == 0, proc.stderr
    _freeze(repo, active=False)
    proc = run_hook("code_freeze.py", write_event(repo, "src/c2r/solver.py", "x"), repo)
    assert proc.returncode == 0, proc.stderr


def test_code_freeze_denies_a_commit_carrying_frozen_source(repo: Path) -> None:
    _freeze(repo)
    _git_repo(repo, 3)  # writes src/c2r/big.py, untracked
    proc = run_hook(
        "code_freeze.py", bash_event(repo, 'git add -A && git commit -m "cp5: x"'), repo
    )
    assert proc.returncode == 2 and "src/c2r/big.py" in proc.stderr
    proc = run_hook("code_freeze.py", bash_event(repo, 'git commit -m "cp5: nothing staged"'), repo)
    assert proc.returncode == 0, proc.stderr
    subprocess.run(["git", "add", "-A"], cwd=str(repo), check=True)
    proc = run_hook("code_freeze.py", bash_event(repo, 'git commit -m "cp5: staged"'), repo)
    assert proc.returncode == 2 and "this commit" in proc.stderr


def test_code_freeze_allows_a_viz_only_commit(repo: Path) -> None:
    _freeze(repo)
    _git_repo(repo, 0)
    (repo / "src" / "c2r" / "big.py").unlink()
    (repo / "src" / "c2r" / "viz").mkdir()
    (repo / "src" / "c2r" / "viz" / "timeline.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(repo), check=True)
    proc = run_hook("code_freeze.py", bash_event(repo, 'git commit -m "cp5: viz"'), repo)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize(
    "command",
    [
        'git commit -am "cp5: x"',
        'git commit -a -m "cp5: x"',
        'git commit --all -m "cp5: x"',
        'git commit -m "cp5: x" -- src/c2r/big.py',
    ],
)
def test_code_freeze_denies_a_working_tree_commit(repo: Path, command: str) -> None:
    _freeze(repo)
    _git_repo(repo, 3)
    subprocess.run(["git", "add", "-A"], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "tracked"], cwd=str(repo), check=True)
    (repo / "src" / "c2r" / "big.py").write_text("x = 2\n", encoding="utf-8")  # modified, unstaged
    proc = run_hook("code_freeze.py", bash_event(repo, command), repo)
    assert proc.returncode == 2 and "src/c2r/big.py" in proc.stderr, (command, proc.stderr)
