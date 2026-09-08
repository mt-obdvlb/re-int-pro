"""Run frozen paired configurations; truth is only read here, never passed to the Agent."""

import argparse
import asyncio
import hashlib
import json
import time
from pathlib import Path

from probeops.config import Settings
from probeops.models import STRATEGIES, CreateRun
from probeops.storage import Store
from probeops.telemetry import Telemetry
from probeops.worker import execute


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshots", type=Path, default=Path("data/snapshots"))
    parser.add_argument("--truth", type=Path, default=Path(".runtime/evaluator/truth.jsonl"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=["fake", "bailian"], default="fake")
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--repeats", type=int, choices=[1, 3], default=1)
    parser.add_argument(
        "--strategies",
        nargs="+",
        choices=[s["strategy_id"] for s in STRATEGIES],
        default=[s["strategy_id"] for s in STRATEGIES],
    )
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Output already exists; use a new batch path, never overwrite results.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    cfg = Settings(
        llm_mode=args.mode, probeops_snapshot_dir=args.snapshots.resolve(), fake_delay_seconds=0
    )
    telemetry = Telemetry(cfg.probeops_telemetry_dir, "evaluation", cfg.log_level)
    store = Store(cfg.probeops_db_path, telemetry, cfg)
    truths = [json.loads(line) for line in args.truth.read_text().splitlines()]
    truths = [
        t
        for t in truths
        if t["split"] == args.split and (args.snapshots / f"{t['incident_id']}.json").exists()
    ][: args.limit]
    if not truths:
        raise SystemExit("No matching frozen tasks")
    try:
        with args.output.open("x") as output:
            for truth in truths:
                snapshot = store.catalog.load(truth["incident_id"])
                if snapshot["content_hash"] != truth["content_hash"]:
                    raise RuntimeError("Frozen observation hash mismatch")
                for repeat in range(args.repeats):
                    for strategy in args.strategies:
                        with telemetry.span("evaluation.run") as span:
                            body = CreateRun.model_validate(
                                {
                                    "incident_id": truth["incident_id"],
                                    "strategy_id": strategy,
                                    "limits": {
                                        "max_steps": 12,
                                        "max_llm_calls": 16,
                                        "max_wall_seconds": 180,
                                        "max_cost_micro_cny": 250000,
                                    },
                                }
                            )
                            key = f"{args.output.stem}-{truth['incident_id']}-{strategy}-{repeat}"

                            run = store.create(
                                body,
                                hashlib.sha256(key.encode()).hexdigest(),
                                f"{span.get_span_context().trace_id:032x}",
                                f"{span.get_span_context().span_id:016x}",
                                seed=42 + repeat,
                            )
                            start = time.perf_counter()
                            while store.get(run["run_id"])["status"] == "queued":
                                if not await execute(store, "evaluator", 0):
                                    raise RuntimeError(
                                        "Stop the interactive worker before batch evaluation"
                                    )
                            final = store.get(run["run_id"])
                            report = (
                                store.report(run["run_id"])
                                if final["status"] == "completed"
                                else None
                            )
                            located = report is not None and report["conclusion"] == "located"
                            correct = (
                                located
                                and report["component"] == truth["component"]
                                and report["fault_type"] == truth["fault_type"]
                            )
                            result = {
                                "incident_id": truth["incident_id"],
                                "snapshot_hash": snapshot["content_hash"],
                                "strategy": strategy,
                                "repeat": repeat,
                                "mode": args.mode,
                                "model": final["model"],
                                "run_id": run["run_id"],
                                "config_hash": final["config_hash"],
                                "status": final["status"],
                                "stop_reason": final["stop_reason"],
                                "fault_type": truth["fault_type"],
                                "correct": bool(correct),
                                "located": located,
                                "usage": final["usage"],
                                "latency_ms": (time.perf_counter() - start) * 1000,
                                "report": report,
                            }
                            output.write(json.dumps(result, ensure_ascii=False) + "\n")
                            output.flush()
    finally:
        telemetry.close()


if __name__ == "__main__":
    asyncio.run(main())
