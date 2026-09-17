"""Write ``cost_report.md`` from every ledger under ``runs/``: tokens by type, cache-read
share and dollars by model, then one row per ledger. Numbers are never typed in by hand
(handoff section 10); ``make cost-report`` or the end of ``--full`` regenerates the file.
"""

from __future__ import annotations

import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from c2r.ledger import cache_share, read
from c2r.models import Usage

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
OUT = ROOT / "cost_report.md"
ROLE = {
    "ledger.jsonl": "mediator",
    "explain.jsonl": "explainer",
    "judge.jsonl": "judge",
    "calibration.jsonl": "judge (calibration)",
}
ZERO = Usage(input=0, cache_read=0, cache_write=0, output=0)


def _add(total: Usage, usage: Usage) -> Usage:
    return Usage(
        input=total.input + usage.input,
        cache_read=total.cache_read + usage.cache_read,
        cache_write=total.cache_write + usage.cache_write,
        output=total.output + usage.output,
    )


def gather(runs: Path = RUNS) -> list[dict[str, Any]]:
    """One row per ledger file: role, model, effort, tokens, cache share, dollars, batch flag."""
    rows: list[dict[str, Any]] = []
    for path in sorted(runs.rglob("*.jsonl")):
        if path.name not in ROLE:
            continue
        entries = read(path)
        turns = [e for e in entries if e.actor == "model"]
        if not turns:
            continue
        usage = ZERO
        for entry in turns:
            usage = _add(usage, entry.usage)
        summary = path.parent / "judge_summary.json"
        batch = (
            path.name == "judge.jsonl"
            and summary.is_file()
            and '"batch_id"' in summary.read_text(encoding="utf-8")
        )
        rows.append(
            {
                "run": path.parent.relative_to(runs).as_posix(),
                "role": ROLE[path.name],
                "model": turns[0].model_id,
                "effort": turns[0].effort,
                "calls": len(turns),
                "usage": usage,
                "cache_share": cache_share(usage),
                "cost_usd": round(sum(e.cost_usd for e in entries), 4),
                "batch": batch,
            }
        )
    return rows


def by_model(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    totals: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"usage": ZERO, "cost_usd": 0.0, "calls": 0}
    )
    for row in rows:
        slot = totals[row["model"]]
        slot["usage"] = _add(slot["usage"], row["usage"])
        slot["cost_usd"] = round(slot["cost_usd"] + row["cost_usd"], 4)
        slot["calls"] += row["calls"]
    return dict(sorted(totals.items()))


def render(rows: list[dict[str, Any]]) -> str:
    models = by_model(rows)
    grand = round(sum(r["cost_usd"] for r in rows), 2)
    lines = [
        "# Cost report",
        "",
        (
            f"Generated {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())} from every ledger "
            f"under `runs/` ({len(rows)} ledgers). SYNTHETIC DATA. Every number below is summed "
            "from `ledger.jsonl`, `explain.jsonl`, `judge.jsonl` and `calibration.jsonl`; "
            "nothing is typed in."
        ),
        "",
        "## Dollars by model",
        "",
        "| Model | Calls | Input | Cache read | Cache write | Output | Cache-read share | USD |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for model, slot in models.items():
        u = slot["usage"]
        lines.append(
            f"| {model} | {slot['calls']} | {u.input:,} | {u.cache_read:,} | {u.cache_write:,} | "
            f"{u.output:,} | {cache_share(u):.0%} | ${slot['cost_usd']:.2f} |"
        )
    calls = sum(s["calls"] for s in models.values())
    lines += [
        f"| **all** | {calls} | | | | | | **${grand:.2f}** |",
        "",
        "## Ledgers",
        "",
        (
            "| Run | Role | Model | Effort | Calls | Input | Cache read | Cache write | Output | "
            "Cache-read share | USD |"
        ),
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        u = row["usage"]
        role = row["role"] + (" (batch, half price)" if row["batch"] else "")
        lines.append(
            f"| {row['run']} | {role} | {row['model']} | {row['effort']} | {row['calls']} | "
            f"{u.input:,} | {u.cache_read:,} | {u.cache_write:,} | {u.output:,} | "
            f"{row['cache_share']:.0%} | ${row['cost_usd']:.2f} |"
        )
    lines += [
        "",
        (
            "Cache-read share is cache-read tokens over all input tokens (input + cache read + "
            "cache write). Batch rows were billed through the Message Batches API at half the "
            "listed prices; the fake models cost $0."
        ),
        "",
    ]
    return "\n".join(lines)


def write(runs: Path = RUNS, out: Path = OUT) -> Path:
    out.write_text(render(gather(runs)), encoding="utf-8", newline="\n")
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    rows = gather()
    path = write()
    print(f"cost report: {len(rows)} ledgers, ${sum(r['cost_usd'] for r in rows):.2f}; {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
