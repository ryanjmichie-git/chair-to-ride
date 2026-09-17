"""The live scenario suite behind ``run_evals.py --full``.

For every seed and every scenario file in ``evals/scenarios/`` a cell runs under
``runs/full/<seed>/<scenario>/``: the baseline is a full mediator day (Fable 5.1, 1-h cache),
``vehicle_breakdown`` a re-plan against that day, the explainer writes the notes, and one
Message Batch judges every note at half price. Scenarios marked ``wired: false`` are reported
NOT WIRED and cost nothing. Cells that already finished are skipped, and a judge batch that
outlives the process is finished by ``--full-collect``; the gate never reads this directory.
"""

from __future__ import annotations

import json
import os
import statistics
import time
import traceback
from pathlib import Path
from typing import Any

from c2r import explain, judge, orchestrator, perturb, synth
from c2r.llm import (
    AnthropicBatchWriter,
    AnthropicMediator,
    AnthropicWriter,
    FakeBatchWriter,
    FakeMediator,
    FakeWriter,
)
from c2r.models import ShiftId, TripStatus
from c2r.moves import post_waits

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "evals" / "scenarios"
RUNS = ROOT / "runs" / "full"
RUNS_FAKE = ROOT / "runs" / "full-fake"  # so an offline rehearsal never marks a live cell done
CACHE_TTL = "1h"
JUDGE_MAX_WAIT_S = 3600.0


def QUIET(*_: Any) -> None:  # the cells' own echo goes to the progress log instead
    return None


def scenarios(root: Path = SCENARIOS) -> list[dict[str, Any]]:
    found = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(root.glob("*.json"))]
    order = {"baseline": 0, "vehicle_breakdown": 1}
    return sorted(found, key=lambda s: (order.get(s["name"], 9), s["name"]))


def _dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


class Log:
    def __init__(self, path: Path, echo=print) -> None:
        self.path, self.echo = path, echo
        path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, line: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(f"{stamp} {line}\n")
        self.echo(f"{stamp} {line}")


def ensure_data(seed: int) -> Path:
    data = ROOT / "data" / "synthetic" / str(seed)
    if not (data / "manifest.json").is_file():
        synth.generate(seed, data)
    return data


def _cost(metrics: dict[str, Any]) -> float:
    keys = ("usage", "usage_explain", "usage_judge")
    return round(sum(float(metrics[k]["cost_usd"]) for k in keys if k in metrics), 4)


# --- required outcomes (handoff section 9.B), all from the run's own numbers --------------------


def _check_baseline(required: dict[str, Any], metrics: dict[str, Any], state) -> dict[str, bool]:
    after, before = metrics["after"], metrics["before"]
    returns = max(len(state.return_trips()), 1)
    removed = 1 - after["wait_min_total"] / max(before["wait_min_total"], 1)
    return {
        "mean_post_wait_max": after["mean_post_wait"] <= required["mean_post_wait_max"],
        "p90_post_wait_max": after["p90_post_wait"] <= required["p90_post_wait_max"],
        "wait_removed_share_min": removed >= required["wait_removed_share_min"],
        "queue_share_max": after["riders_flagged"] / returns <= required["queue_share_max"],
        "runtime_s_max": metrics["elapsed_s"] <= required["runtime_s_max"],
    }


def _check_breakdown(
    required: dict[str, Any], metrics: dict[str, Any], result, event: dict[str, Any]
) -> dict[str, bool]:
    state = result.state
    van = event["event"]["payload"]["vehicle_id"]
    trips = {t.trip_id: t for t in state.manifest.trips}
    stranded = [
        tid
        for tid in event["affected"]
        if tid in trips
        and trips[tid].status in (TripStatus.scheduled, TripStatus.will_call)
        and (
            trips[tid].vehicle_id == van
            or trips[tid].status == TripStatus.scheduled
            and trips[tid].vehicle_id is None
        )
    ]
    waits = post_waits(state)
    s2 = [w for tid, w in waits.items() if state.patient_of(trips[tid]).shift_id == ShiftId.S2]
    return {
        "none_stranded": not stranded,
        "violations_max": len(result.result.violations) <= required["violations_max"],
        "replan_s_max": metrics["elapsed_s"] <= required["replan_s_max"],
        "s2_mean_post_wait_max": (statistics.fmean(s2) if s2 else 0.0)
        <= required["s2_mean_post_wait_max"],
    }


# --- cells -----------------------------------------------------------------------------------------


def _cell_path(seed: int, name: str, runs: Path) -> Path:
    return runs / str(seed) / name


def _write_cell(out: Path, record: dict[str, Any]) -> dict[str, Any]:
    _dump(out / "cell.json", record)
    return record


def run_cell(
    scenario: dict[str, Any], seed: int, data: Path, fake: bool, log: Log, runs: Path = RUNS
) -> dict[str, Any]:
    name = scenario["name"]
    out = _cell_path(seed, name, runs)
    record: dict[str, Any] = {
        "scenario": name,
        "seed": seed,
        "dir": str(out),
        "wired": bool(scenario["wired"]),
    }
    if (out / "cell.json").is_file() and _load(out / "cell.json").get("status") == "ok":
        log(f"seed {seed} {name}: done earlier, skipped")
        return _load(out / "cell.json")
    if not scenario["wired"]:
        reason = scenario.get("not_wired_reason", "")
        log(f"seed {seed} {name}: NOT WIRED ({reason})")
        return _write_cell(out, {**record, "status": "not_wired", "reason": reason})
    started = time.monotonic()
    try:
        if name == "baseline":
            mediator = FakeMediator() if fake else AnthropicMediator(effort="medium")
            result = orchestrator.run(data, out, mediator, echo=QUIET, cache_ttl=CACHE_TTL)
            checks = _check_baseline(
                scenario["required"], _load(out / "metrics.json"), result.state
            )
        elif name == "vehicle_breakdown":
            source = _cell_path(seed, "baseline", runs)
            if not (source / "schedule_after.json").is_file():
                raise RuntimeError("the baseline cell has no schedule_after.json")
            event = perturb.load_event(data, scenario["event"]["type"], scenario["event"]["at"])
            mediator = (
                FakeMediator()
                if fake
                else AnthropicMediator(effort="low", timeout=perturb.TURN_TIMEOUT_S, retries=0)
            )
            result = perturb.run(
                data, source, out, event, mediator, echo=QUIET, cache_ttl=CACHE_TTL
            )
            checks = _check_breakdown(
                scenario["required"], _load(out / "metrics.json"), result, _load(out / "event.json")
            )
        else:
            raise NotImplementedError(f"{name} is marked wired but the suite has no runner")
        notes = explain.explain_run(out, FakeWriter() if fake else AnthropicWriter(), echo=QUIET)
        metrics = _load(out / "metrics.json")
        record.update(
            {
                "status": "ok",
                "elapsed_s": metrics["elapsed_s"],
                "wall_s": round(time.monotonic() - started, 1),
                "cost_usd": _cost(metrics),
                "cache_read_share": metrics["usage"]["cache_read_share"],
                "notes": len(notes),
                "after": metrics["after"],
                "checks": checks,
                "required_met": all(checks.values()),
            }
        )
        met = "all met" if all(checks.values()) else str(checks)
        log(
            f"seed {seed} {name}: ok in {record['wall_s']} s, ${record['cost_usd']:.2f}, "
            f"{len(notes)} notes, checks {met}"
        )
    except NotImplementedError as exc:
        record.update({"status": "not_wired", "reason": str(exc)})
        log(f"seed {seed} {name}: NOT WIRED for this seed: {exc}")
    except Exception as exc:  # noqa: BLE001 - one cell's crash must not end the suite
        record.update({"status": "error", "error": f"{type(exc).__name__}: {exc}"})
        out.mkdir(parents=True, exist_ok=True)
        (out / "traceback.txt").write_text(traceback.format_exc(), encoding="utf-8")
        log(f"seed {seed} {name}: ERROR {record['error']}")
    return _write_cell(out, record)


# --- the judge batch and the summary ---------------------------------------------------------------


def _judge(cells: list[dict[str, Any]], fake: bool, log: Log, runs: Path) -> dict[str, Any]:
    state_path = runs / "judge_batch.json"
    writer = (
        FakeBatchWriter()
        if fake
        else AnthropicBatchWriter(model=judge.MODEL, effort=judge.EFFORT, max_tokens=1200)
    )
    if state_path.is_file():
        state = _load(state_path)
        if state.get("collected"):
            log(f"judge batch {state['batch_id']}: collected earlier")
            return state
        log(f"judge batch {state['batch_id']}: collecting")
        return judge.judge_collect(state_path, writer, echo=QUIET)
    run_dirs = [
        Path(c["dir"])
        for c in cells
        if c.get("status") == "ok" and (Path(c["dir"]) / "explanations.json").is_file()
    ]
    if not run_dirs:
        log("judge batch: no notes to judge")
        return {"batch_id": None, "collected": True, "runs": []}
    poll = 0.0 if fake else 30.0
    return judge.judge_batch(
        run_dirs, writer, state_path, log, poll_s=poll, max_wait_s=JUDGE_MAX_WAIT_S
    )


def summarize(cells: list[dict[str, Any]], batch: dict[str, Any], runs: Path) -> dict[str, Any]:
    wired_by_name = {sc["name"]: bool(sc["wired"]) for sc in scenarios()}
    by_scenario: dict[str, dict[str, Any]] = {}
    for cell in cells:
        wired = wired_by_name.get(cell["scenario"], bool(cell.get("wired")))
        entry = by_scenario.setdefault(
            cell["scenario"], {"cells": {}, "wired": wired, "not_wired_seeds": []}
        )
        cell = dict(cell)
        judged = Path(cell["dir"]) / "judge_summary.json"
        if judged.is_file():
            summary = _load(judged)
            cell["judge_pass_rate"] = summary["pass_rate"]
            cell["needs_human_edit"] = summary["needs_human_edit"]
            cell["cost_usd"] = _cost(_load(Path(cell["dir"]) / "metrics.json"))
        entry["cells"][str(cell["seed"])] = cell
        if entry["wired"] and cell["status"] == "not_wired":
            entry["not_wired_seeds"].append(cell["seed"])
    for entry in by_scenario.values():
        cells_ = list(entry["cells"].values())
        entry["pass_k"] = entry["wired"] and all(
            c["status"] == "ok" and c.get("required_met") for c in cells_
        )
        if not entry["wired"]:
            entry["status"] = "NOT WIRED"
        elif entry["pass_k"]:
            entry["status"] = "PASS"
        elif entry["not_wired_seeds"]:
            seeds = ",".join(str(s) for s in entry["not_wired_seeds"])
            entry["status"] = f"FAIL (not wired for seed {seeds})"
        else:
            entry["status"] = "FAIL"
    ok = [c for c in cells if c["status"] == "ok"]
    shares = [c["cache_read_share"] for c in ok if "cache_read_share" in c]
    wired = [n for n, e in by_scenario.items() if e["wired"]]
    verdict = "PASS" if wired and all(by_scenario[n]["pass_k"] for n in wired) else "FAIL"
    keys = ("batch_id", "collected", "status", "items", "results")
    summary = {
        "verdict": verdict,
        "wired_scenarios": wired,
        "not_wired": [n for n, e in by_scenario.items() if not e["wired"]],
        "cells_ok": len(ok),
        "cells": len(cells),
        "cost_usd": round(sum(float(c.get("cost_usd", 0)) for c in ok), 4),
        "mean_cache_read_share": round(statistics.fmean(shares), 4) if shares else 0.0,
        "judge_batch": {k: batch.get(k) for k in keys},
        "scenarios": by_scenario,
        "finished": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _dump(runs / "summary.json", summary)
    return summary


def _line(summary: dict[str, Any], runs: Path) -> str:
    scen = " ".join(f"{n}={e['status']}" for n, e in summary["scenarios"].items())
    pending = "" if summary["judge_batch"].get("collected") else "; judge batch pending"
    return (
        f"FULL {summary['verdict']} ({summary['cells_ok']}/{summary['cells']} cells ok, "
        f"${summary['cost_usd']:.2f}, cache read {summary['mean_cache_read_share']:.0%}; {scen}"
        f"{pending}; {runs / 'summary.json'})"
    )


def _cost_report(log: Log) -> None:
    import cost_report

    log(f"cost report: {cost_report.write()}")


def full(seeds: list[int], fake: bool = False, echo=print, runs: Path | None = None) -> int:
    runs = runs or (RUNS_FAKE if fake else RUNS)
    if not fake and not os.environ.get("ANTHROPIC_API_KEY"):
        echo("FULL SKIP (ANTHROPIC_API_KEY is not set; use --fake or uv run --env-file .env)")
        return 2
    log = Log(runs / "progress.log", echo)
    log(f"full suite: seeds {seeds}, {'fake' if fake else 'live'} models")
    cells: list[dict[str, Any]] = []
    for seed in seeds:
        data = ensure_data(seed)
        for scenario in scenarios():
            cells.append(run_cell(scenario, seed, data, fake, log, runs))
    batch = _judge(cells, fake, log, runs)
    summary = summarize(cells, batch, runs)
    if not fake:
        _cost_report(log)
    log(_line(summary, runs))
    return 0 if summary["verdict"] == "PASS" and batch.get("collected") else 1


def collect(fake: bool = False, echo=print, runs: Path | None = None) -> int:
    """Finish a judge batch submitted by an earlier ``--full``, then rewrite the summary."""
    runs = runs or (RUNS_FAKE if fake else RUNS)
    log = Log(runs / "progress.log", echo)
    cells = [_load(p) for p in sorted(runs.glob("*/*/cell.json"))]
    if not cells:
        log(f"full-collect: nothing under {runs}")
        return 1
    batch = _judge(cells, fake, log, runs)
    summary = summarize(cells, batch, runs)
    if not fake:
        _cost_report(log)
    log(_line(summary, runs))
    return 0 if summary["verdict"] == "PASS" and batch.get("collected") else 1
