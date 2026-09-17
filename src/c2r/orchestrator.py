"""The mediator loop: blocks A-C once, then candidates -> model turn -> tools -> ledger.

``python -m c2r.orchestrator data/synthetic/42 [--out runs/cp2] [--fake]``

The model chooses among solver bundles and calls the eight tools; Python verifies, applies,
counts and writes the ledger. Blocks A-C are built once and never change during the run (H2);
the per-turn message is a state delta plus candidates (H1).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from c2r.banner import BANNER
from c2r.claims import MAX_MESSAGE_TOKENS, estimate_tokens, numbers_in, numeric_claims
from c2r.ledger import Ledger, cache_share, usage_summary
from c2r.llm import AnthropicMediator, FakeMediator, Mediator, MediatorError, Turn
from c2r.solver import Result, finish_run, table, write_run
from c2r.state import ROOT, RULES_PATH, State, load_state
from c2r.tools import TOOLS, Session, dispatch, new_session
from c2r.verify import verify
from c2r.viz.timeline import render

PROMPT = ROOT / "prompts" / "mediator.v1.md"
CONFIG = ROOT / "config"
DATA_FILES = ("unit", "roster", "manifest", "fleet", "travel")
EPHEMERAL = {"type": "ephemeral"}
TURN_MARGIN_S = 15  # no new turn starts inside this margin of stop.max_wall_s


def frontmatter(text: str) -> tuple[dict[str, str], str]:
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    fields = {}
    for line in parts[1].splitlines():
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip()] = value.strip()
    return fields, parts[2]


def sha(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def git_sha() -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
        )
    except OSError:
        return "unknown"
    sha_ = proc.stdout.strip() or "unknown"
    dirty = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return f"{sha_}-dirty" if dirty.stdout.strip() else sha_


def travel_summary(state: State) -> str:
    zones: dict[str, list[int]] = {}
    for node in state.travel.nodes:
        zones.setdefault(node.zone.value, []).append(state.travel.matrix[0][node.node_id])
    lines = [
        f"Zone {zone}: {len(mins)} nodes, {min(mins)}-{max(mins)} min from the unit "
        f"(mean {round(sum(mins) / len(mins))})"
        for zone, mins in sorted(zones.items())
    ]
    return "\n".join(lines)


def compact(path: Path) -> str:
    return json.dumps(json.loads(path.read_text(encoding="utf-8")), separators=(",", ":"))


def build_blocks(state: State, data_dir: Path) -> tuple[list[dict], dict[str, int], dict[str, str]]:
    """Blocks A (prompt), B (policies + rules) and C (today's data), each a cache breakpoint."""
    fields, body = frontmatter(PROMPT.read_text(encoding="utf-8"))
    rules = {k: v for k, v in state.rules.items() if k != "synth"}
    block_a = body.strip()
    block_b = "\n\n".join(
        [
            (CONFIG / "unit_policy.md").read_text(encoding="utf-8").strip(),
            (CONFIG / "broker_policy.md").read_text(encoding="utf-8").strip(),
            "# rules.yaml\n```yaml\n" + yaml.safe_dump(rules, sort_keys=False) + "```",
        ]
    )
    block_c = "\n\n".join(
        [
            "# Today's data (SYNTHETIC). Times are HH:MM; nodes are grid points, not addresses.",
            "## roster.json\n" + compact(data_dir / "roster.json"),
            "## manifest.json\n" + compact(data_dir / "manifest.json"),
            "## fleet.json\n" + compact(data_dir / "fleet.json"),
            "## travel summary (minutes from the unit at node 0)\n" + travel_summary(state),
        ]
    )
    blocks = [
        {"type": "text", "text": text, "cache_control": EPHEMERAL}
        for text in (block_a, block_b, block_c)
    ]
    hashes = {
        f"{name}.json": sha((data_dir / f"{name}.json").read_text(encoding="utf-8"))
        for name in DATA_FILES
    }
    hashes.update(
        {
            "rules.yaml": sha(RULES_PATH.read_text(encoding="utf-8")),
            "block_a": sha(block_a),
            "block_b": sha(block_b),
            "block_c": sha(block_c),
        }
    )
    return blocks, {"mediator": int(fields.get("version", "0"))}, hashes


def _user(text: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = f"{text}\n{json.dumps(payload, separators=(',', ':'))}" if payload else text
    return {"role": "user", "content": [{"type": "text", "text": body}]}


def _mark(messages: list[dict[str, Any]]) -> None:
    """Move the fourth cache breakpoint to the latest user message (A, B, C hold the others)."""
    for message in messages:
        if message["role"] == "user":
            for block in message["content"]:
                block.pop("cache_control", None)
    messages[-1]["content"][-1]["cache_control"] = EPHEMERAL


def flag_unverified(text: str, unverified: list[str]) -> str:
    for claim in unverified:
        text = re.sub(
            rf"(?<![\w:.]){re.escape(claim)}(?![\w:]|\.\d)", f"{claim} [unverified]", text
        )
    return text


def _tool_line(name: str, args: dict[str, Any], result: dict[str, Any]) -> str:
    target = args.get("bundle_id") or args.get("subject") or ""
    if name in ("propose_to_unit", "propose_to_broker"):
        verdict = (
            "accepted"
            if result.get("accepted")
            else f"rejected {result.get('reason_code')}: {result.get('hint')}"
        )
    elif name == "verify":
        verdict = f"{len(result.get('violations', []))} violations, {str(result.get('verify_hash', ''))[:19]}"
    elif name == "apply_bundle":
        m = result.get("metrics", {})
        verdict = (
            f"applied -> mean {m.get('mean_post_wait')}, p90 {m.get('p90_post_wait')}, "
            f"flagged {m.get('riders_flagged')}, J {result.get('j')} (v{result.get('schedule_version')})"
            if result.get("applied")
            else f"refused: {result.get('reason')}"
        )
    elif name == "generate_candidates":
        verdict = f"{len(result.get('candidates', []))} candidates"
    elif name == "flag_for_review":
        verdict = result.get("item_id") or f"refused: {result.get('reason')}"
    else:
        verdict = result.get("error", "ok")
    return f"   {name}({target}): {verdict}"


def _interim(session: Session) -> Result:
    run = session.run
    return Result(
        run.baseline,
        session.state,
        session.plan,
        verify(session.state, run.baseline, session.version),
        run.applied,
        [],
        run.j_before,
        session.j,
    )


def run(
    data_dir: Path, out_dir: Path, mediator: Mediator, echo=print, rules: dict | None = None
) -> Result:
    """A full day: the on-disk baseline is the session's baseline and its starting state."""
    baseline = load_state(data_dir, rules)
    session = new_session(baseline)
    blocks, versions, hashes = build_blocks(baseline, data_dir)
    start = {
        "data_dir": str(data_dir),
        "seed": baseline.travel.seed,
        "autonomy_level": baseline.rules["autonomy_level"],
    }
    opening = "Iteration 1. Baseline metrics and the first candidates follow. Take Turn A."
    result, _ = run_session(
        session, blocks, versions, hashes, out_dir, mediator, opening, start, echo
    )
    return result


def run_session(
    session: Session,
    blocks: list[dict],
    versions: dict[str, int],
    hashes: dict[str, str],
    out_dir: Path,
    mediator: Mediator,
    opening: str,
    start: dict[str, Any],
    echo=print,
    payload: dict[str, Any] | None = None,
    margin_s: int = TURN_MARGIN_S,
    stop_after_apply: bool = False,
) -> tuple[Result, str]:
    """The loop on a prepared session: candidates -> model turn -> tools -> ledger, then the
    closing pass. ``start`` is ledgered with the run start (so its numbers are citable);
    ``payload`` rides in the opening user message beside the first candidates. With
    ``stop_after_apply`` the harness ends the run itself once an apply meets the stop rule,
    instead of spending a turn on the model's own finish (the re-plan's 30 s clock)."""
    started = time.monotonic()
    baseline = session.baseline
    stop = baseline.rules["stop"]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "ledger.jsonl").write_text("", encoding="utf-8")
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    book = Ledger(
        out_dir / "ledger.jsonl",
        run_id,
        git_sha(),
        mediator.model_id,
        mediator.effort,
        versions,
        hashes,
    )
    block_tokens = {k: estimate_tokens(b["text"]) for k, b in zip("abc", blocks, strict=True)}
    book.start(
        {
            **start,
            "block_tokens": block_tokens,
            "metrics_before": session.run.result.metrics.model_dump(mode="json"),
            "j_before": session.j,
        }
    )

    def timeline() -> None:
        (out_dir / "timeline.html").write_text(render(out_dir), encoding="utf-8", newline="\n")

    def on_apply(s: Session) -> None:  # K3: the schedule is visible after every apply
        write_run(_interim(s), out_dir)
        timeline()

    session.on_apply = on_apply
    first = dispatch(session, "generate_candidates", {"side": "both", "k": 6})
    book.tool(0, "generate_candidates", {"side": "both", "k": 6}, first)
    session.known |= numbers_in(book.entries[0].payload)  # the baseline metrics are citable
    messages = [
        _user(
            opening,
            {
                "metrics_before": session.run.result.metrics.model_dump(mode="json"),
                **(payload or {}),
                **first,
            },
        )
    ]
    echo(BANNER)
    echo(
        f"run {run_id} | {mediator.model_id} effort={mediator.effort} | cached blocks "
        f"A {block_tokens['a']} B {block_tokens['b']} C {block_tokens['c']} tokens | "
        f"J before {session.j}"
    )
    iteration, halt, cost = 0, "", 0.0
    while not session.finished:
        if iteration >= stop["max_iterations"]:
            halt = f"iteration cap {stop['max_iterations']}"
            break
        if time.monotonic() - started > stop["max_wall_s"] - margin_s:
            halt = f"wall clock near {stop['max_wall_s']} s"
            break
        iteration += 1
        session.iteration = iteration
        _mark(messages)
        try:
            turn: Turn = mediator.turn(blocks, TOOLS, messages)
        except MediatorError as exc:
            halt = f"model call failed: {exc}"
            iteration -= 1
            break
        prose = [turn.text] + [str(v) for c in turn.tool_calls for v in c.input.values()]
        claims = numeric_claims(" ".join(prose))  # K4 covers rationale, summary, drafts too
        unverified = [c for c in claims if c not in session.known]
        calls = [{"id": c.id, "name": c.name, "input": c.input} for c in turn.tool_calls]
        book.model_turn(
            iteration,
            turn.text,
            calls,
            claims,
            unverified,
            turn.usage,
            turn.cost_usd,
            turn.stop_reason,
        )
        cost += turn.cost_usd
        echo(
            f"[turn {iteration}] ${cost:.2f} cached {cache_share(turn.usage):.0%} "
            f"{round(time.monotonic() - started)}s | {flag_unverified(turn.text, unverified)}"
        )
        messages.append({"role": "assistant", "content": turn.content})
        if not turn.tool_calls:
            messages.append(
                _user("No tool was called. Take Turn A for one bundle, or call finish.", {})
            )
            continue
        results = []
        for call in turn.tool_calls:
            result = dispatch(session, call.name, call.input)
            book.tool(iteration, call.name, call.input, result)
            echo(_tool_line(call.name, call.input, result))
            if (
                stop_after_apply
                and call.name == "apply_bundle"
                and result.get("applied")
                and result["stop"]["should_finish"]
            ):
                halt = f"stop rule met: {result['stop']['reason']}"
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": call.id,
                    "content": json.dumps(result, separators=(",", ":")),
                }
            )
        size = sum(len(r["content"]) for r in results) // 4
        if size > MAX_MESSAGE_TOKENS:
            echo(f"   warning: tool results {size} tokens exceed the {MAX_MESSAGE_TOKENS} budget")
        messages.append({"role": "user", "content": results})
        if halt:
            break
    if not session.finished:
        forced = dispatch(session, "finish", {"summary": f"Stopped by the harness: {halt}."})
        book.tool(iteration, "finish", {"forced": halt}, forced)
        echo(f"   harness: {halt}; finishing")
    model_applied = len(session.run.applied)
    result = finish_run(
        baseline, session.state, session.plan, session.run, session.rejected, session.flagged
    )
    closing = [a["bundle"] for a in result.applied[model_applied:]]
    elapsed = round(time.monotonic() - started, 1)
    book.finish(
        iteration,
        {
            "summary": session.summary,
            "reason": halt or "model called finish",
            "closing_bundles": closing,
            "j_after": result.j_after,
            "metrics_after": result.result.metrics.model_dump(mode="json"),
            "elapsed_s": elapsed,
        },
    )
    summary = usage_summary(book.entries)
    write_run(result, out_dir, extra={"usage": summary, "run_id": run_id, "elapsed_s": elapsed})
    timeline()
    echo(table(result))
    echo(
        f"model turns {summary['iterations']}, tool calls {summary['tool_calls']}, "
        f"cost ${summary['cost_usd']:.2f}, cache-read share {summary['cache_read_share']:.0%}, "
        f"{elapsed} s; ledger {out_dir / 'ledger.jsonl'}"
    )
    if session.summary:
        echo(f"mediator: {session.summary}")
    return result, run_id


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("data_dir")
    parser.add_argument("--out", default="runs/cp2")
    parser.add_argument("--fake", action="store_true", help="scripted mediator, no API call")
    parser.add_argument("--model", default="claude-fable-5-1")
    parser.add_argument("--effort", default="medium")
    args = parser.parse_args()
    if args.fake:
        mediator: Mediator = FakeMediator()
    elif not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set; use --fake for the offline mediator", file=sys.stderr)
        return 2
    else:
        mediator = AnthropicMediator(model=args.model, effort=args.effort)
    result = run(Path(args.data_dir), Path(args.out), mediator)
    return 0 if not result.result.violations else 1


if __name__ == "__main__":
    raise SystemExit(main())
