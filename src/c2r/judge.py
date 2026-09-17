"""The judge: Fable 5.1 at low effort scores an explanation 0-2 on six dimensions; Python
overrides what it can prove.

``python -m c2r.judge runs/cp2 [--fake]`` scores a run's ``explanations.json``;
``python -m c2r.judge --golden [--fake]`` scores the 12-item golden set and reports agreement.

Overrides (handoff 9.C): a number absent from the cited refs zeroes accuracy; a reading grade
over 8 caps plain at 1; pass = total >= 10 and accuracy == 2, whatever the model said. A refusal
or an unusable answer scores 0 across the board and is listed as needs-human-edit; no fallback
model, so the judge is always the same model. Scores are written with
``model_dump(by_alias=True)`` so the ``pass`` key keeps its name.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from c2r.explain import check_numbers, contact_named, load_run, missing_times
from c2r.ledger import Ledger, usage_summary
from c2r.llm import AnthropicWriter, BatchItem, Completion, FakeJudge, Writer
from c2r.models import JudgeScore, JudgeScores
from c2r.orchestrator import frontmatter, git_sha, sha
from c2r.state import ROOT

MODEL = "claude-fable-5-1"
EFFORT = "low"
PROMPT = ROOT / "prompts" / "judge.v1.md"
GOLDEN = ROOT / "evals" / "data" / "golden_explanations.json"
CALIBRATION = ROOT / "evals" / "data" / "judge_calibration.json"
DIMENSIONS = ("accuracy", "actionable", "plain", "tone", "complete", "safe")
PASS_TOTAL = 10
MAX_GRADE = 8.0
SCHEMA = {
    "type": "object",
    "properties": {
        "explanation_id": {"type": "string"},
        "rationale": {"type": "string"},
        "scores": {
            "type": "object",
            "properties": {d: {"type": "integer", "enum": [0, 1, 2]} for d in DIMENSIONS},
            "required": list(DIMENSIONS),
            "additionalProperties": False,
        },
        "pass": {"type": "boolean"},
    },
    "required": ["explanation_id", "rationale", "scores", "pass"],
    "additionalProperties": False,
}


def _prompt() -> tuple[str, int]:
    fields, body = frontmatter(PROMPT.read_text(encoding="utf-8"))
    return body.strip(), int(fields.get("version", "0"))


# --- the verdict ------------------------------------------------------------------------------


def override(record: dict[str, Any], raw: dict[str, Any]) -> JudgeScore:
    """The model's scores after the rules Python can prove; pass is always recomputed."""
    given = raw.get("scores") or {}
    scores = {d: min(2, max(0, int(given.get(d, 0) or 0))) for d in DIMENSIONS}
    notes: list[str] = []
    invented = check_numbers(record)
    if invented:
        scores["accuracy"] = 0
        notes.append(f"numbers not in the cited refs: {', '.join(invented)}")
    grade = float(record["explanation"].get("reading_grade", 0.0))
    if grade > MAX_GRADE and scores["plain"] > 1:
        scores["plain"] = 1
        notes.append(f"reading grade {grade:g} is over {MAX_GRADE:g}")
    missing = missing_times(record)
    if missing:
        scores["actionable"] = 0
        notes.append(f"missing new times: {', '.join(missing)}")
    if not contact_named(record) and scores["complete"] > 1:
        scores["complete"] = 1
        notes.append(f"the note does not name the contact, {record['facts']['contact']}")
    total = sum(scores.values())
    passed = total >= PASS_TOTAL and scores["accuracy"] == 2
    if bool(raw.get("pass")) != passed:
        notes.append(f"pass recomputed: total {total}/12, accuracy {scores['accuracy']}")
    rationale = str(raw.get("rationale", "")).strip()
    if notes:
        rationale = f"{rationale} [python: {'; '.join(notes)}]".strip()
    return JudgeScore(
        explanation_id=record["explanation_id"],
        scores=JudgeScores(**scores),
        rationale=rationale,
        pass_=passed,
    )


def unscored(record: dict[str, Any], reason: str) -> JudgeScore:
    """No usable verdict (refusal, truncation, bad JSON): fails, and a human reads it."""
    return JudgeScore(
        explanation_id=record["explanation_id"],
        scores=JudgeScores(**{d: 0 for d in DIMENSIONS}),
        rationale=f"no usable verdict from the judge ({reason}); needs human edit",
        pass_=False,
    )


def _user(record: dict[str, Any]) -> str:
    return json.dumps(
        {
            "explanation_id": record["explanation_id"],
            "explanation": record["explanation"],
            "facts": record["facts"],
        },
        sort_keys=True,
    )


def _verdict(
    record: dict[str, Any],
    done: Completion | None,
    number: int,
    book: Ledger | None,
    echo,
) -> JudgeScore:
    if done is None:
        verdict = unscored(record, "missing from the batch results")
    elif done.data:
        verdict = override(record, done.data)
    else:
        verdict = unscored(record, done.stop_reason)
    if book is not None and done is not None:
        text = json.dumps(verdict.model_dump(by_alias=True), sort_keys=True)
        book.model_turn(number, text, [], [], [], done.usage, done.cost_usd, done.stop_reason)
    flags = " ".join(f"{d[:3]}{getattr(verdict.scores, d)}" for d in DIMENSIONS)
    echo(f"   {verdict.explanation_id} {'pass' if verdict.pass_ else 'FAIL'} {flags}")
    return verdict


def judge_records(
    records: list[dict[str, Any]], judge: Writer, echo=print, book: Ledger | None = None
) -> list[JudgeScore]:
    system, _ = _prompt()
    return [
        _verdict(record, judge.complete(system, _user(record), SCHEMA), number, book, echo)
        for number, record in enumerate(records, 1)
    ]


def summarize(
    verdicts: list[JudgeScore], expected: dict[str, bool] | None = None
) -> dict[str, Any]:
    count = len(verdicts)
    summary: dict[str, Any] = {
        "count": count,
        "pass_rate": round(sum(1 for v in verdicts if v.pass_) / count, 4) if count else 0.0,
        "mean_scores": {
            d: round(sum(getattr(v.scores, d) for v in verdicts) / count, 2) if count else 0.0
            for d in DIMENSIONS
        },
        "needs_human_edit": [v.explanation_id for v in verdicts if not v.pass_],
    }
    if expected is not None:
        agree = [v for v in verdicts if expected.get(v.explanation_id) == v.pass_]
        summary["golden_agreement"] = f"{len(agree)}/{count}"
        summary["disagreements"] = [
            {
                "explanation_id": v.explanation_id,
                "expected_pass": expected.get(v.explanation_id),
                "judge_pass": v.pass_,
                "rationale": v.rationale,
            }
            for v in verdicts
            if expected.get(v.explanation_id) != v.pass_
        ]
    return summary


def _write(out_dir: Path, verdicts: list[JudgeScore], summary: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in (
        ("judge_scores.json", [v.model_dump(by_alias=True) for v in verdicts]),
        ("judge_summary.json", summary),
    ):
        (out_dir / name).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )


def _book(
    out_dir: Path, run_id: str, judge: Writer, hashes: dict[str, str], name: str = "judge.jsonl"
) -> Ledger:
    system, version = _prompt()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / name).write_text("", encoding="utf-8")
    return Ledger(
        out_dir / name,
        run_id,
        git_sha(),
        judge.model_id,
        judge.effort,
        {"judge": version},
        {**hashes, PROMPT.name: sha(system)},
    )


def _open_run(run_dir: Path, judge: Writer) -> tuple[list[dict[str, Any]], Ledger]:
    raw = (run_dir / "explanations.json").read_text(encoding="utf-8")
    book = _book(run_dir, load_run(run_dir).run_id, judge, {"explanations.json": sha(raw)})
    return json.loads(raw), book


def _close_run(
    run_dir: Path, verdicts: list[JudgeScore], book: Ledger, echo, extra: dict[str, Any] | None
) -> dict[str, Any]:
    """Write judge_scores.json and judge_summary.json; put the usage into metrics.json."""
    summary = summarize(verdicts)
    usage = usage_summary(book.entries)
    if extra:
        usage.update(extra)
        summary.update(extra)
    summary["usage"] = usage
    _write(run_dir, verdicts, summary)
    metrics_path = run_dir / "metrics.json"
    if metrics_path.is_file():
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        metrics["usage_judge"] = usage
        metrics_path.write_text(
            json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )
    echo(
        f"judged {summary['count']}: pass rate {summary['pass_rate']:.0%}, needs human edit "
        f"{summary['needs_human_edit']}, cost ${usage['cost_usd']:.2f}; {run_dir / 'judge_summary.json'}"
    )
    return summary


def judge_run(run_dir: Path, judge: Writer, echo=print) -> list[JudgeScore]:
    """Score a run's explanations; write judge_scores.json, judge_summary.json, judge.jsonl."""
    records, book = _open_run(run_dir, judge)
    verdicts = judge_records(records, judge, echo, book)
    _close_run(run_dir, verdicts, book, echo, None)
    return verdicts


# --- many runs in one Message Batch --------------------------------------------------------------


def _custom_id(index: int, record: dict[str, Any]) -> str:
    """``<run index>-<explanation id>``: the API allows only ``[a-zA-Z0-9_-]`` in a custom_id."""
    return f"{index}-{record['explanation_id']}"


def judge_batch(
    run_dirs: list[Path],
    writer,
    state_path: Path,
    echo=print,
    poll_s: float = 30.0,
    max_wait_s: float = 7200.0,
) -> dict[str, Any]:
    """Every run's explanations in one batch (half price, 1-h cached prompt); verdicts land in
    each run the way ``judge_run`` writes them.

    The batch id is written to ``state_path`` first, so a process that dies or gives up waiting
    (``max_wait_s``) leaves enough for ``judge_collect`` to finish later. Never a gate's business.
    """
    system, _ = _prompt()
    items: list[BatchItem] = []
    for index, run_dir in enumerate(run_dirs):
        records = json.loads((run_dir / "explanations.json").read_text(encoding="utf-8"))
        items += [BatchItem(_custom_id(index, r), system, _user(r), SCHEMA) for r in records]
    batch_id = writer.submit(items)
    state = {
        "batch_id": batch_id,
        "runs": [str(p) for p in run_dirs],
        "items": len(items),
        "submitted": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "collected": False,
    }
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8", newline="\n")
    echo(f"judge batch {batch_id}: {len(items)} verdicts requested across {len(run_dirs)} runs")
    started = time.monotonic()
    while True:
        status = writer.status(batch_id)
        if status["processing_status"] == "ended":
            break
        if time.monotonic() - started > max_wait_s:
            echo(f"judge batch {batch_id} still {status['processing_status']}; collect later")
            return {**state, "status": status["processing_status"]}
        time.sleep(poll_s)
    return judge_collect(state_path, writer, echo)


def judge_collect(state_path: Path, writer, echo=print) -> dict[str, Any]:
    """Fetch a submitted batch's results and write every run's verdicts, ledger and usage."""
    state = json.loads(state_path.read_text(encoding="utf-8"))
    batch_id = state["batch_id"]
    status = writer.status(batch_id)
    if status["processing_status"] != "ended":
        echo(f"judge batch {batch_id} is still {status['processing_status']}; collect later")
        return {**state, "status": status["processing_status"]}
    results = writer.collect(batch_id)
    summaries: dict[str, Any] = {}
    for index, name in enumerate(state["runs"]):
        run_dir = Path(name)
        records, book = _open_run(run_dir, writer)
        verdicts = [
            _verdict(record, results.get(_custom_id(index, record)), number, book, echo)
            for number, record in enumerate(records, 1)
        ]
        summaries[name] = _close_run(run_dir, verdicts, book, echo, {"batch_id": batch_id})
    state.update({"collected": True, "status": "ended", "results": len(results)})
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8", newline="\n")
    return {**state, "summaries": summaries}


# --- the golden set and the calibration file ---------------------------------------------------


def load_golden(path: Path = GOLDEN) -> list[dict[str, Any]]:
    """Twelve hand-verdicted records: seven that should pass, five that fail one named bucket."""
    items = json.loads(path.read_text(encoding="utf-8"))
    for item in items:
        item["record"]["explanation_id"] = item["golden_id"]
    return items


def judge_golden(judge: Writer, out_dir: Path, echo=print) -> dict[str, Any]:
    items = load_golden()
    records = [item["record"] for item in items]
    expected = {item["golden_id"]: bool(item["expected"]["pass"]) for item in items}
    book = _book(
        out_dir,
        "golden",
        judge,
        {"golden_explanations.json": sha(GOLDEN.read_text(encoding="utf-8"))},
    )
    verdicts = judge_records(records, judge, echo, book)
    summary = summarize(verdicts, expected)
    summary["usage"] = usage_summary(book.entries)
    _write(out_dir, verdicts, summary)
    return summary


def calibration_status(
    path: Path = CALIBRATION, verdicts: dict[str, bool] | None = None
) -> dict[str, Any]:
    """How many of the ten items the clinical teammate has graded, and how many agree with
    the judge's verdicts (when given)."""
    items = json.loads(path.read_text(encoding="utf-8"))
    graded = [i for i in items if i.get("human_pass") is not None]
    agree = [
        i
        for i in graded
        if verdicts is not None and verdicts.get(i["calibration_id"]) == bool(i["human_pass"])
    ]
    return {"items": len(items), "graded": len(graded), "agreement": len(agree)}


def judge_calibration(judge: Writer, out_dir: Path, echo=print) -> dict[str, Any]:
    items = json.loads(CALIBRATION.read_text(encoding="utf-8"))
    records = []
    for item in items:
        record = dict(item["record"])
        record["explanation_id"] = item["calibration_id"]
        records.append(record)
    book = _book(
        out_dir,
        "calibration",
        judge,
        {"judge_calibration.json": sha(CALIBRATION.read_text(encoding="utf-8"))},
        name="calibration.jsonl",
    )
    verdicts = judge_records(records, judge, echo, book)
    (out_dir / "calibration_scores.json").write_text(
        json.dumps([v.model_dump(by_alias=True) for v in verdicts], indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    status = calibration_status(verdicts={v.explanation_id: v.pass_ for v in verdicts})
    status["usage"] = usage_summary(book.entries)
    return status


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", nargs="?", help="a run with explanations.json")
    parser.add_argument("--golden", action="store_true", help="score the golden set instead")
    parser.add_argument("--out", default="runs/golden-judge")
    parser.add_argument("--fake", action="store_true", help="all 2s; overrides only, no API call")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--effort", default=EFFORT)
    args = parser.parse_args()
    if args.fake:
        judge: Writer = FakeJudge()
    elif not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set; use --fake for the offline judge", file=sys.stderr)
        return 2
    else:
        judge = AnthropicWriter(model=args.model, effort=args.effort, max_tokens=1200)
    if args.golden:
        summary = judge_golden(judge, Path(args.out))
        print(
            f"golden agreement {summary['golden_agreement']}; {Path(args.out) / 'judge_summary.json'}"
        )
        return 0
    if not args.run_dir:
        parser.error("give a run dir or --golden")
    verdicts = judge_run(Path(args.run_dir), judge)
    return 0 if all(v.pass_ for v in verdicts) else 1


if __name__ == "__main__":
    raise SystemExit(main())
