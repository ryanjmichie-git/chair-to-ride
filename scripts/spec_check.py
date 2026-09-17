"""Exit 0 only when a checkpoint spec carries all five required sections with a body."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HEADERS = (
    "## Goal",
    "## Files",
    "## Out of scope",
    "## Definition of done",
    "## Verification command",
)


def _has_body(lines: list[str], header: str) -> bool:
    for index, line in enumerate(lines):
        if line.strip() != header:
            continue
        for body in lines[index + 1 :]:
            if body.startswith("## "):
                return False
            if body.strip():
                return True
        return False
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("spec")
    args = parser.parse_args()
    path = Path(args.spec)
    if not path.is_file():
        print(f"spec not found: {args.spec}")
        return 1
    lines = path.read_text(encoding="utf-8").splitlines()
    missing = [header for header in HEADERS if not _has_body(lines, header)]
    if missing:
        print(f"{args.spec}: missing or empty sections:")
        for header in missing:
            print(f"  {header}")
        return 1
    print(f"{args.spec}: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
