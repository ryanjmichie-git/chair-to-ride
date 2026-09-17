"""PreToolUse (Bash): allow only commands whose every segment starts with an allowed prefix."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import deny, read_event

SEPARATORS = re.compile(r"&&|\|\||;|\|")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow", action="append", default=[])
    args = parser.parse_args()
    event = read_event()
    command = (event.get("tool_input") or {}).get("command") or ""
    if not command.strip():
        return 0
    for segment in (s.strip() for s in SEPARATORS.split(command)):
        if segment and not any(segment.startswith(p) for p in args.allow):
            deny(f"'{segment}' is outside this agent's allowed commands ({', '.join(args.allow)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
