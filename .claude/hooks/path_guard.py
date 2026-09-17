"""PreToolUse (Edit|Write): enforce per-agent allow and deny path globs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import deny, glob_match, read_event, rel_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow", action="append", nargs="+", default=[])
    parser.add_argument("--deny", action="append", nargs="+", default=[])
    args = parser.parse_args()
    allow = [g for group in args.allow for g in group]
    denied = [g for group in args.deny for g in group]
    event = read_event()
    rel = rel_path(event)
    if rel is None:
        tool_input = event.get("tool_input")
        raw = tool_input.get("file_path") if isinstance(tool_input, dict) else None
        if raw and allow:
            deny(f"{raw} is outside the repo root ({', '.join(allow)} only)")
        return 0
    for pattern in denied:
        if glob_match(rel, pattern):
            deny(f"{rel} is denied for this agent by path glob {pattern}")
    if allow and not any(glob_match(rel, g) for g in allow):
        deny(f"{rel} is outside this agent's allowed paths ({', '.join(allow)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
