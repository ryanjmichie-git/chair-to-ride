"""Plain-language explanations from a run's own files.

``python -m c2r.explain runs/cp2 [--fake] [--model claude-sonnet-5] [--effort medium]``

Python builds a facts card per subject and audience (``facts.py``); the writer only phrases it;
Python fills the times, the refs and the reading grade, then checks every number in the prose
against the entries the card cites (I16). K6: a rider in the review queue gets no rider note
until a human resolves the item; the dispatcher gets one instead. Every call is a line in the
run's ``explain.jsonl`` with its usage, so the cost meter reports dollars by model.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import textstat

from c2r.claims import numbers_in, numeric_claims
from c2r.facts import facts_card, load_run, patient_of_subject, resolve_refs, subjects
from c2r.ledger import Ledger, usage_summary
from c2r.llm import AnthropicWriter, FakeWriter, Writer
from c2r.models import Explanation, NewTimes, Window
from c2r.orchestrator import frontmatter, git_sha, sha
from c2r.state import ROOT

__all__ = [
    "build",
    "check_numbers",
    "explain_run",
    "explanation_id",
    "facts_card",
    "load_run",
    "missing_times",
    "patient_of_subject",
    "reading_grade",
    "resolve_refs",
    "subjects",
]

PROMPT = ROOT / "prompts" / "explainer.v1.md"
SCHEMA = {
    "type": "object",
    "properties": {
        "what_changed": {"type": "string"},
        "why": {"type": "string"},
        "contact": {"type": "string"},
    },
    "required": ["what_changed", "why", "contact"],
    "additionalProperties": False,
}


# --- the checks -------------------------------------------------------------------------------


def _prose(record: dict[str, Any]) -> str:
    e = record["explanation"]
    return f"{e['what_changed']} {e['why']} {e['contact']}"


def check_numbers(record: dict[str, Any]) -> list[str]:
    """I16: the numbers in the prose that no cited ref (nor the new times) contains."""
    known = numbers_in(record["facts"]["refs"]) | numbers_in(record["explanation"]["new_times"])
    return [claim for claim in numeric_claims(_prose(record)) if claim not in known]


def missing_times(record: dict[str, Any]) -> list[str]:
    """The new times (chair start, ride window open) a rider or nurse note fails to state."""
    if record["explanation"]["audience"] == "dispatcher":
        return []  # the dispatcher note carries the review item, not a booked ride
    times = record["explanation"]["new_times"]
    wanted = [times["chair_start"]] + (times["pickup_window"] or [])[:1]
    text = record["explanation"]["what_changed"]
    return [t for t in wanted if t and t not in text]


def reading_grade(text: str) -> float:
    return round(float(textstat.flesch_kincaid_grade(text)), 1)


# --- the run ----------------------------------------------------------------------------------


def explanation_id(subject_id: str, audience: str) -> str:
    return f"E{subject_id[1:]}{audience[0]}"


def build(card: dict[str, Any], output: dict[str, Any]) -> Explanation:
    after = card["after"]
    booked = bool(after) and after.get("status") == "scheduled" and after.get("vehicle")
    window = after.get("pickup_window") if booked else None  # a queued trip's window is stale
    what, why = str(output.get("what_changed", "")), str(output.get("why", ""))
    return Explanation(
        audience=card["audience"],
        subject_id=card["subject_id"],
        what_changed=what,
        why=why,
        new_times=NewTimes(
            chair_start=after.get("chair_start") if after else None,
            pickup_window=Window(root=list(window)) if window else None,
        ),
        ledger_refs=list(card["refs"]),
        contact=str(output.get("contact") or card["contact"]),
        reading_grade=reading_grade(f"{what} {why}"),
    )


def explain_run(run_dir: Path, writer: Writer, echo=print) -> list[dict[str, Any]]:
    files = load_run(run_dir)
    fields, body = frontmatter(PROMPT.read_text(encoding="utf-8"))
    system = body.strip()
    (run_dir / "explain.jsonl").write_text("", encoding="utf-8")
    book = Ledger(
        run_dir / "explain.jsonl",
        files.run_id,
        git_sha(),
        writer.model_id,
        writer.effort,
        {"explainer": int(fields.get("version", "0"))},
        {
            "ledger.jsonl": sha("\n".join(files.lines)),
            "schedule_after.json": sha(json.dumps(files.after, sort_keys=True)),
            "explainer.v1.md": sha(system),
        },
    )
    records: list[dict[str, Any]] = []
    for number, (subject_id, audience) in enumerate(subjects(files), 1):
        card = facts_card(files, subject_id, audience)
        done = writer.complete(system, json.dumps(card, sort_keys=True), SCHEMA)
        if done.data is None:
            book.model_turn(
                number, done.text, [], [], [], done.usage, done.cost_usd, done.stop_reason
            )
            echo(f"   {explanation_id(subject_id, audience)}: no explanation ({done.stop_reason})")
            continue
        explanation = build(card, done.data)
        record = {
            "explanation_id": explanation_id(subject_id, audience),
            "explanation": explanation.model_dump(mode="json"),
            "facts": card,
        }
        text = json.dumps(record["explanation"], sort_keys=True)
        claims = numeric_claims(_prose(record))
        unverified = check_numbers(record)
        book.model_turn(
            number, text, [], claims, unverified, done.usage, done.cost_usd, done.stop_reason
        )
        records.append(record)
        flag = f" [{len(unverified)} unverified: {', '.join(unverified)}]" if unverified else ""
        echo(
            f"   {record['explanation_id']} grade {explanation.reading_grade}{flag}: "
            f"{explanation.what_changed}"
        )
    (run_dir / "explanations.json").write_text(
        json.dumps(records, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    summary = usage_summary(book.entries)
    metrics_path = run_dir / "metrics.json"
    if metrics_path.is_file():
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        metrics["usage_explain"] = summary
        metrics_path.write_text(
            json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )
    echo(
        f"{len(records)} explanations, {summary['unverified_claims']} unverified numbers, "
        f"cost ${summary['cost_usd']:.2f}; {run_dir / 'explanations.json'}"
    )
    return records


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir")
    parser.add_argument("--fake", action="store_true", help="templated prose, no API call")
    parser.add_argument("--model", default="claude-sonnet-5")
    parser.add_argument("--effort", default="medium")
    args = parser.parse_args()
    if args.fake:
        writer: Writer = FakeWriter()
    elif not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set; use --fake for the offline writer", file=sys.stderr)
        return 2
    else:
        writer = AnthropicWriter(model=args.model, effort=args.effort)
    records = explain_run(Path(args.run_dir), writer)
    return 0 if records else 1


if __name__ == "__main__":
    raise SystemExit(main())
