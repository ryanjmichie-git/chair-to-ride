"""PreToolUse: refuse edits and commits that touch frozen source (CP4: src/c2r except viz/).

``.claude/freeze.json`` says what is frozen::

    {"active": true, "since": "cp4", "frozen": ["src/c2r/**"], "allowed": ["src/c2r/viz/**"],
     "waivers": [{"path": "src/c2r/verify.py", "spec": "specs/cp5-rehearse.md", "reviewer": "..."}]}

On Edit|Write the target path is checked; on Bash|PowerShell a ``git commit`` is checked against
the files it would carry (staged, or the working tree after ``git add``). A waiver names the
spec update and the reviewer who signed off, which is what lifts the freeze for one file.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import deny, glob_match, read_event, rel_path, repo_root

FREEZE = Path(".claude") / "freeze.json"
QUOTED = re.compile(r"\"[^\"]*\"|'[^']*'")
COMMIT = re.compile(r"\bgit\s+commit\b")
ADD = re.compile(r"\bgit\s+add\b")
# `git commit -a` / `-am` / `--all` / `--include` / `-i`, or a pathspec after the options, commits
# the working tree rather than the index; those are checked like `git add && git commit`.
TREE_COMMIT = re.compile(
    r"\bgit\s+commit\b(?:.*\s(?:-[a-zA-Z]*a[a-zA-Z]*|--all|--include|-i)(?:\s|$)|.*\s--\s|.*\ssrc/)"
)


def load_freeze(root: Path) -> dict | None:
    path = root / FREEZE
    if not path.is_file():
        return None
    try:
        freeze = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    return freeze if isinstance(freeze, dict) and freeze.get("active") else None


def frozen(freeze: dict, rel: str) -> bool:
    """True when ``rel`` is under a frozen glob, not under an allowed one, and has no waiver."""
    if not any(glob_match(rel, g) for g in freeze.get("frozen", [])):
        return False
    if any(glob_match(rel, g) for g in freeze.get("allowed", [])):
        return False
    return not any(
        w.get("path") == rel and w.get("spec") and w.get("reviewer")
        for w in freeze.get("waivers", [])
    )


def _git(root: Path, *args: str) -> list[str] | None:
    try:
        proc = subprocess.run(
            ["git", *args], cwd=str(root), capture_output=True, text=True, check=False
        )
    except OSError:
        return None
    return proc.stdout.split() if proc.returncode == 0 else None


def commit_paths(root: Path, adds_first: bool) -> list[str] | None:
    if adds_first:
        tracked = _git(root, "diff", "HEAD", "--name-only", "--", "src/")
        untracked = _git(root, "ls-files", "--others", "--exclude-standard", "--", "src/")
        return None if tracked is None or untracked is None else tracked + untracked
    return _git(root, "diff", "--cached", "--name-only", "--", "src/")


def _reason(freeze: dict, paths: list[str], what: str) -> str:
    return (
        f"code freeze ({freeze.get('since', '?')}): {what} touches frozen source "
        f"{', '.join(paths)}. Only {', '.join(freeze.get('allowed', []))} is open. A change "
        "needs a spec update and reviewer sign-off; record both as a waiver in .claude/freeze.json."
    )


def main() -> int:
    event = read_event()
    root = repo_root()
    freeze = load_freeze(root)
    if freeze is None:
        return 0
    tool = event.get("tool_name", "")
    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        rel = rel_path(event)
        if rel and frozen(freeze, rel):
            deny(_reason(freeze, [rel], "this edit"))
        return 0
    command = (event.get("tool_input") or {}).get("command") or ""
    masked = QUOTED.sub(lambda m: m.group(0)[0] * 2 + " " * (len(m.group(0)) - 2), command)
    if not COMMIT.search(masked):
        return 0
    tree = bool(ADD.search(masked) or TREE_COMMIT.search(masked))
    paths = commit_paths(root, adds_first=tree)
    hits = sorted({p for p in paths or [] if frozen(freeze, p)})
    if hits:
        deny(_reason(freeze, hits, "this commit"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
