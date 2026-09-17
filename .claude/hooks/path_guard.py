"""PreToolUse (Edit|Write): enforce per-agent allow and deny path globs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import deny, glob_match, read_event, rel_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow", action="append", default=[])
    parser.add_argument("--deny", action="append", default=[])
    args = parser.parse_args()
    event = read_event()
    rel = rel_path(event)
    if rel is None:
        return 0
    for pattern in args.deny:
        if glob_match(rel, pattern):
            deny(f"{rel} is denied for this agent by path glob {pattern}")
    if args.allow and not any(glob_match(rel, p) for p in args.allow):
        deny(f"{rel} is outside this agent's allowed paths ({', '.join(args.allow)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
