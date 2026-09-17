"""PostToolUse (Write): re-render the run timeline whenever a new schedule lands."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import read_event, rel_path, repo_root

SCHEDULE = re.compile(r"runs/.+/schedule_after\.json")


def main() -> int:
    event = read_event()
    rel = rel_path(event)
    if rel is None or not SCHEDULE.fullmatch(rel):
        return 0
    root = repo_root()
    if not (root / "src" / "c2r" / "viz" / "timeline.py").is_file():
        return 0
    run_dir = str(Path(rel).parent.as_posix())
    try:
        proc = subprocess.run(
            ["uv", "run", "python", "-m", "c2r.viz.timeline", run_dir],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        print(f"timeline render skipped: {exc}", file=sys.stderr)
        return 0
    if proc.returncode != 0:
        print(f"timeline render failed for {run_dir}:\n{proc.stderr}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
