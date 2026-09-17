"""Replay an ``events.jsonl`` entry against a finished run and re-plan the rest of the day.

``python -m c2r.perturb --event vehicle_down --at 13:40 [--data data/synthetic/42]
[--run runs/cp2] [--out runs/cp3] [--fake] [--model ...] [--effort low]``

The running state (the source run's ``schedule_after.json``) with the event applied becomes the
session's baseline and its starting state; ``State.now`` freezes everything before the event
(verify.py H3/H9). The same mediator loop, prompt and cache blocks as the full-day run then
re-plan under a 30 s clock. Only ``vehicle_down`` is wired at CP3; ``EVENTS`` is where the other
four slot in.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from c2r.claims import state_delta
from c2r.ledger import read as read_ledger
from c2r.llm import AnthropicMediator, FakeMediator, Mediator
from c2r.models import Event, Leg, Manifest, Roster, VehicleStatus, Window
from c2r.orchestrator import build_blocks, run_session, sha
from c2r.routing import Plan, build_manifest, plan_from_manifest
from c2r.solver import Result
from c2r.state import State, actual_ready, load_state
from c2r.timeutil import to_hhmm, to_min
from c2r.tools import new_session

REPLAN_STOP = {"max_wall_s": 30, "max_iterations": 4}
TURN_MARGIN_S = 15  # no turn starts inside this margin; a turn is capped at TURN_TIMEOUT_S
TURN_TIMEOUT_S = 12.0  # a low-effort turn takes 5-10 s; no retry, the closing pass is the fallback
Handler = Callable[[State, Plan, Event], tuple[State, Plan, list[str]]]


def load_event(data_dir: Path, kind: str, at: str | None = None) -> Event:
    """The ``events.jsonl`` entry of this type (and time, when given), or what is available."""
    path = data_dir / "events.jsonl"
    events = [
        Event.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    matches = [e for e in events if e.type.value == kind and (at is None or e.t == at)]
    if not matches:
        have = ", ".join(f"{e.type.value} at {e.t}" for e in events)
        raise ValueError(f"no {kind} event at {at} in {path}; the file has: {have}")
    return matches[0]


def running_state(original: State, run_dir: Path) -> State:
    """The day as the source run left it, its chair moves booked against the weekly budget."""
    after = json.loads((run_dir / "schedule_after.json").read_text(encoding="utf-8"))
    roster = Roster.model_validate(after["roster"])
    starts = {p.patient_id: p.start_time for p in original.roster.patients}
    patients = [
        p.model_copy(update={"moves_this_week": p.moves_this_week + 1})
        if p.start_time != starts.get(p.patient_id, p.start_time)
        else p
        for p in roster.patients
    ]
    return original.with_(
        roster=roster.model_copy(update={"patients": patients}),
        manifest=Manifest.model_validate(after["manifest"]),
    )


def _vehicle_down(state: State, plan: Plan, event: Event) -> tuple[State, Plan, list[str]]:
    """The van's shift ends at t (verify's t_down); its returns from t on come off the plan."""
    van = event.payload["vehicle_id"]
    now = to_min(event.t)
    if van not in {v.vehicle_id for v in state.fleet.vehicles}:
        raise ValueError(f"{van} is not in the fleet")
    vehicles = [
        v.model_copy(
            update={
                "status": VehicleStatus.down,
                "shift": Window(root=[v.shift.root[0], event.t]),
            }
        )
        if v.vehicle_id == van
        else v
        for v in state.fleet.vehicles
    ]
    state = state.with_(fleet=state.fleet.model_copy(update={"vehicles": vehicles}))
    trips = {t.trip_id: t for t in state.manifest.trips}
    affected = list(
        dict.fromkeys(
            stop.trip_id
            for route in state.manifest.routes
            if route.vehicle_id == van
            for stop in route.stops
            if to_min(stop.eta) >= now
        )
    )
    outbound = [t for t in affected if trips[t].leg == Leg.to]
    if outbound:  # outbound legs are pinned to their van; re-homing them is a CP4 move type
        raise NotImplementedError(f"{van} carries outbound legs after {event.t}: {outbound}")
    for trip_id in affected:
        plan.remove(trip_id)
    return state, plan, affected


EVENTS: dict[str, Handler] = {"vehicle_down": _vehicle_down}


def describe(event: Event) -> str:
    if event.type.value == "vehicle_down":
        return f"vehicle {event.payload['vehicle_id']} is down"
    return f"{event.type.value} {json.dumps(event.payload, sort_keys=True)}"


def event_state(
    original: State, run_dir: Path, event: Event, rules: dict[str, Any] | None = None
) -> tuple[State, Plan, list[str]]:
    """The running state with the event applied and ``now`` set; the plan; the trips it hit.

    Pure: the same inputs give the same state, so a ledger replays from it (I18).
    """
    handler = EVENTS.get(event.type.value)
    if handler is None:
        raise NotImplementedError(f"{event.type.value} is not wired; EVENTS has {sorted(EVENTS)}")
    state = running_state(original, run_dir)
    if rules is not None:
        state = state.with_(rules=rules)
    state, plan, affected = handler(state, plan_from_manifest(state), event)
    manifest = build_manifest(state, state.roster, plan)
    return state.with_(manifest=manifest, now=to_min(event.t)), plan, affected


def run(
    data_dir: Path,
    run_dir: Path,
    out_dir: Path,
    event: Event,
    mediator: Mediator,
    echo=print,
    rules: dict[str, Any] | None = None,
    cache_ttl: str | None = None,
) -> Result:
    original = load_state(data_dir, rules)
    replan_rules = copy.deepcopy(original.rules)
    replan_rules["stop"].update(REPLAN_STOP)
    state, _, affected = event_state(original, run_dir, event, replan_rules)
    session = new_session(state)
    blocks, versions, hashes = build_blocks(original, data_dir, cache_ttl)  # same bytes as the day
    source_ledger = run_dir / "ledger.jsonl"
    source_run_id = read_ledger(source_ledger)[0].run_id if source_ledger.is_file() else None
    hashes["source.schedule_after.json"] = sha(
        (run_dir / "schedule_after.json").read_text(encoding="utf-8")
    )
    hashes["event"] = sha(event.model_dump_json())
    trips = {t.trip_id: t for t in state.manifest.trips}
    riders = {
        trip_id: (
            f"{state.patient_of(trips[trip_id]).mobility.value}, ready "
            f"{to_hhmm(actual_ready(state.patient_of(trips[trip_id])))}, now queued"
        )
        for trip_id in affected
    }
    record = {
        "event": event.model_dump(mode="json"),
        "now": event.t,
        "source_dir": str(run_dir),
        "source_run_id": source_run_id,
        "affected": affected,
        "fleet": [v.model_dump(mode="json") for v in state.fleet.vehicles],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "event.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    start = {
        "data_dir": str(data_dir),
        "seed": original.travel.seed,
        "autonomy_level": original.rules["autonomy_level"],
        "event": record["event"],
        "now": event.t,
        "source_dir": str(run_dir),
        "source_run_id": source_run_id,
        "affected": affected,
        "affected_riders": riders,
    }
    opening = (
        f"Event at {event.t}: {describe(event)}. The day was already re-timed once (run "
        f"{source_run_id}); `delta_since_block_c` is what differs from block C, and "
        f"`affected_riders` are the returns this event left without a van. Nothing before "
        f"{event.t} can change; the clock is {REPLAN_STOP['max_wall_s']} s. Take Turn A."
    )
    payload = {
        "event": record["event"],
        "delta_since_block_c": state_delta(original, state),
        "affected_riders": riders,
    }
    echo(f"event: {describe(event)} at {event.t}; {len(affected)} return(s) affected: {affected}")
    result, _ = run_session(
        session,
        blocks,
        versions,
        hashes,
        out_dir,
        mediator,
        opening,
        start,
        echo,
        payload=payload,
        margin_s=TURN_MARGIN_S,
        stop_after_apply=True,
    )
    return result


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", required=True, choices=sorted(EVENTS))
    parser.add_argument("--at", default=None, help="HH:MM of the events.jsonl entry")
    parser.add_argument("--data", default="data/synthetic/42")
    parser.add_argument("--run", default="runs/cp2", help="the finished run to replay against")
    parser.add_argument("--out", default="runs/cp3")
    parser.add_argument("--fake", action="store_true", help="scripted mediator, no API call")
    parser.add_argument("--model", default="claude-fable-5-1")
    parser.add_argument("--effort", default="low")
    args = parser.parse_args()
    run_dir = Path(args.run)
    if not (run_dir / "schedule_after.json").is_file():
        print(f"{run_dir} has no schedule_after.json; run `make mediate` first", file=sys.stderr)
        return 2
    if args.fake:
        mediator: Mediator = FakeMediator()
    elif not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set; use --fake for the offline mediator", file=sys.stderr)
        return 2
    else:
        mediator = AnthropicMediator(
            model=args.model, effort=args.effort, timeout=TURN_TIMEOUT_S, retries=0
        )
    event = load_event(Path(args.data), args.event, args.at)
    result = run(Path(args.data), run_dir, Path(args.out), event, mediator)
    return 0 if not result.result.violations else 1


if __name__ == "__main__":
    raise SystemExit(main())
