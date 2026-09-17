"""PreToolUse (Bash|PowerShell): refuse a `git commit` whose src/ diff exceeds K2's 400 lines."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import deny, read_event, repo_root

LIMIT = 400
QUOTED = re.compile(r"\"[^\"]*\"|'[^']*'")
COMMIT = re.compile(r"\bgit\s+commit\b")
ADD = re.compile(r"\bgit\s+add\b")


def _git(root: Path, *args: str) -> str | None:
    try:
        proc = subprocess.run(
            ["git", *args], cwd=str(root), capture_output=True, text=True, check=False
        )
    except OSError:
        return None
    return proc.stdout if proc.returncode == 0 else None


def _numstat(output: str) -> dict[str, int]:
    lines: dict[str, int] = {}
    for row in output.splitlines():
        parts = row.split("\t")
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            lines[parts[2]] = int(parts[0]) + int(parts[1])
    return lines


def changed_lines(root: Path, adds_first: bool) -> dict[str, int] | None:
    """Changed lines per src/ file the commit would carry, or None when git cannot tell."""
    if adds_first:
        tracked = _git(root, "diff", "HEAD", "--numstat", "--", "src/")
        untracked = _git(root, "ls-files", "--others", "--exclude-standard", "--", "src/")
        if tracked is None or untracked is None:
            return None
        lines = _numstat(tracked)
        for rel in untracked.split():
            try:
                lines[rel] = len((root / rel).read_text(encoding="utf-8").splitlines())
            except (OSError, UnicodeDecodeError):
                continue
        return lines
    staged = _git(root, "diff", "--cached", "--numstat", "--", "src/")
    return None if staged is None else _numstat(staged)


def main() -> int:
    event = read_event()
    command = (event.get("tool_input") or {}).get("command") or ""
    masked = QUOTED.sub(lambda m: m.group(0)[0] * 2 + " " * (len(m.group(0)) - 2), command)
    if not COMMIT.search(masked):
        return 0
    lines = changed_lines(repo_root(), adds_first=bool(ADD.search(masked)))
    if not lines:
        return 0
    total = sum(lines.values())
    if total <= LIMIT:
        return 0
    top = ", ".join(f"{rel} {n}" for rel, n in sorted(lines.items(), key=lambda kv: -kv[1])[:5])
    deny(
        f"K2: this commit changes {total} lines under src/ (limit {LIMIT}); "
        f"split it into smaller commits. Largest: {top}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
