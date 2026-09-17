"""PostToolUse (Edit|Write): run the invariant suite after a solver, verify, rules or parties edit."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import block, read_event, rel_path, repo_root

WATCHED = re.compile(r"src/c2r/(solver|verify|rules|parties)")


def main() -> int:
    event = read_event()
    rel = rel_path(event)
    if rel is None or not WATCHED.match(rel):
        return 0
    root = repo_root()
    invariants = root / "evals" / "invariants"
    if not any(invariants.glob("test_*.py")):
        return 0
    try:
        proc = subprocess.run(
            ["uv", "run", "pytest", "evals/invariants", "-q", "-x"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 0
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout + proc.stderr).splitlines()[-40:])
        block(f"invariant tests fail after editing {rel}:\n{tail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
