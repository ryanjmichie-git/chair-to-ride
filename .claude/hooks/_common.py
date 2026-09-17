"""Shared stdlib helpers for the Chair-to-Ride Claude Code hooks."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, NoReturn


def read_event() -> dict[str, Any]:
    try:
        event = json.load(sys.stdin)
    except (OSError, ValueError):
        sys.exit(0)
    if not isinstance(event, dict):
        sys.exit(0)
    return event


def repo_root() -> Path:
    override = os.environ.get("C2R_ROOT")
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parents[2]


def rel_path(event: dict[str, Any]) -> str | None:
    raw = (event.get("tool_input") or {}).get("file_path")
    if not raw:
        return None
    root = repo_root()
    target = Path(str(raw))
    if not target.is_absolute():
        target = root / target
    try:
        return target.resolve().relative_to(root).as_posix()
    except (ValueError, OSError):
        return None


def frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return {}
    fields: dict[str, str] = {}
    for line in lines[1:end]:
        key, sep, value = line.partition(":")
        if sep and key.strip():
            fields[key.strip()] = value.strip().strip("\"'")
    return fields


def glob_match(path: str, glob: str) -> bool:
    parts: list[str] = []
    i = 0
    while i < len(glob):
        if glob.startswith("**/", i):
            parts.append("(.*/)?")
            i += 3
        elif glob.startswith("**", i):
            parts.append(".*")
            i += 2
        elif glob[i] == "*":
            parts.append("[^/]*")
            i += 1
        else:
            parts.append(re.escape(glob[i]))
            i += 1
    return re.fullmatch("".join(parts), path) is not None


def deny(reason: str) -> NoReturn:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )
    print(reason, file=sys.stderr)
    sys.exit(2)


def block(reason: str) -> NoReturn:
    print(json.dumps({"decision": "block", "reason": reason}))
    print(reason, file=sys.stderr)
    sys.exit(2)
