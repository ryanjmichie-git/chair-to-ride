"""Append one lesson bullet under the CLAUDE.md '# Lessons' heading, capped at 15."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

CAP = 15


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("lesson")
    args = parser.parse_args()
    path = Path(__file__).resolve().parents[1] / "CLAUDE.md"
    if not path.is_file():
        print("CLAUDE.md not found")
        return 1
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip() == "# Lessons"), None)
    if start is None:
        print("CLAUDE.md has no '# Lessons' heading")
        return 1
    count = 0
    last = start
    cursor = start + 1
    while cursor < len(lines) and not lines[cursor].startswith("#"):
        if lines[cursor].lstrip().startswith("- "):
            count += 1
            last = cursor
        cursor += 1
    if count >= CAP:
        print(f"CLAUDE.md already holds {CAP} lessons; prune one before adding another")
        return 1
    lines.insert(last + 1, f"- {args.lesson}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"added lesson {count + 1}/{CAP}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
