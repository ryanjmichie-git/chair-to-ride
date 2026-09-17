"""SessionStart: surface the active checkpoint, last run metrics and prompt versions."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import frontmatter, read_event, repo_root

METRIC_KEYS = ("mean_post_wait", "p90_post_wait", "riders_flagged")


def _newest(root: Path, name: str) -> Path | None:
    found = sorted(root.glob(f"runs/*/{name}"), key=lambda p: p.stat().st_mtime)
    return found[-1] if found else None


def _load(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _active_spec(root: Path) -> list[str]:
    index = root / "specs" / "INDEX.md"
    if not index.is_file():
        return []
    rows = [
        line.strip()
        for line in index.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("|") and "active" in line
    ]
    return [f"Active checkpoint: {rows[0]}"] if rows else []


def _metrics(root: Path) -> list[str]:
    path = _newest(root, "metrics.json")
    if path is None:
        return []
    data = _load(path)
    if not isinstance(data, dict):
        return []
    shown = [f"{key}={data[key]}" for key in METRIC_KEYS if key in data]
    return [f"Last run ({path.parent.name}): {', '.join(shown)}"] if shown else []


def _review_queue(root: Path) -> list[str]:
    path = _newest(root, "review_queue.json")
    if path is None:
        return []
    data = _load(path)
    items = data if isinstance(data, list) else (data or {}).get("items")
    if not isinstance(items, list):
        return []
    return [f"Review queue ({path.parent.name}): {len(items)} open item(s)"]


def _prompts(root: Path) -> list[str]:
    lines = []
    for path in sorted((root / "prompts").glob("*.v*.md")):
        fields = frontmatter(path.read_text(encoding="utf-8"))
        version = fields.get("version", "?")
        result = fields.get("eval_result") or "unevaluated"
        lines.append(f"  {path.name}: version={version} eval_result={result}")
    return ["Prompt versions:"] + lines if lines else []


def main() -> int:
    read_event()
    root = repo_root()
    brief = _active_spec(root) + _metrics(root) + _review_queue(root) + _prompts(root)
    if not brief:
        return 0
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": "\n".join(brief),
                }
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
