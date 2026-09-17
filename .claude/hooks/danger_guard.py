"""PreToolUse (Bash|PowerShell): refuse destructive commands outside a temp or scratchpad root."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import deny, read_event

PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r|-r\b|-R\b|--recursive\b)"),
        "recursive rm",
    ),
    (re.compile(r"\bRemove-Item\b[^|;]*-Recurse", re.IGNORECASE), "Remove-Item -Recurse"),
    (re.compile(r"\bgit\s+push\b[^|;]*(--force-with-lease\b|--force\b|-f\b)"), "git push --force"),
    (re.compile(r"\bgit\s+reset\s+--hard\b"), "git reset --hard"),
    (re.compile(r"\bgit\s+clean\b[^|;]*-[a-zA-Z]*f"), "git clean -f"),
    (re.compile(r"\bgit\s+checkout\s+--\s+\."), "git checkout -- ."),
    (re.compile(r"\bgit\s+branch\s+-D\b"), "git branch -D"),
]
QUOTED = re.compile(r"\"[^\"]*\"|'[^']*'")


def _normalise(path: str) -> str:
    drive = re.match(r"^/([a-zA-Z])/(.*)$", path)
    if drive:
        path = f"{drive.group(1).upper()}:/{drive.group(2)}"
    return os.path.normcase(os.path.normpath(path))


def _safe_roots(event: dict[str, object]) -> list[str]:
    local = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        os.environ.get("TEMP", ""),
        os.path.join(local, "Temp") if local else "",
        str(event.get("scratchpad_dir") or ""),
    ]
    return [_normalise(os.path.expandvars(c)) for c in candidates if c]


def _rm_targets_safe(command: str, roots: list[str]) -> bool:
    match = re.search(r"\brm\b(.*)$", command)
    if not match or not roots:
        return False
    targets: list[str] = []
    for token in match.group(1).split():
        if token in ("&&", "||", "|", ";"):
            break
        if not token.startswith("-"):
            targets.append(token.strip("\"'"))
    if not targets:
        return False
    return all(
        any(_normalise(os.path.expandvars(os.path.expanduser(t))).startswith(r) for r in roots)
        for t in targets
    )


def main() -> int:
    event = read_event()
    command = (event.get("tool_input") or {}).get("command") or ""
    if not command:
        return 0
    scan = QUOTED.sub('""', command)
    hits = [label for pattern, label in PATTERNS if pattern.search(scan)]
    if not hits:
        return 0
    if hits == ["recursive rm"] and _rm_targets_safe(command, _safe_roots(event)):
        return 0
    deny(f"blocked destructive command ({', '.join(hits)}); ask before running it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
