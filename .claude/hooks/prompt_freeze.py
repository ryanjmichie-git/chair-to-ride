"""PreToolUse (Edit|Write): refuse edits to a prompt version that already carries an eval_result."""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import deny, frontmatter, read_event, rel_path, repo_root

VERSIONED = re.compile(r"prompts/[^/]+\.v\d+\.md")
UNSET = ("", "null", "~")


def main() -> int:
    event = read_event()
    rel = rel_path(event)
    if rel is None or not VERSIONED.fullmatch(rel):
        return 0
    path = repo_root() / rel
    if not path.is_file():
        return 0
    result = frontmatter(path.read_text(encoding="utf-8")).get("eval_result")
    if result is not None and result.lower() not in UNSET:
        deny(f"{rel} has eval_result: {result} — prompt version is frozen; bump the version")
    return 0


if __name__ == "__main__":
    sys.exit(main())
