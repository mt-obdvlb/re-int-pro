"""Reproducible capture controller. Truth stays under .runtime/evaluator, outside Agent data."""

import argparse
import asyncio
import json
import random
import subprocess
import sys
import uuid
from pathlib import Path

import httpx
import redis
from probeops.observations import GRAPH, digest
from probeops.telemetry import now

ROOT = Path(__file__).resolve().parents[1]
FAULTS = ["pool_exhaustion", "queue_backlog", "cache_latency", "config_error", "normal", "unknown"]
COMPONENTS = dict(
    zip(FAULTS, ["database", "task-worker", "cache", "checkout-api", "", ""], strict=True)
)


async def capture(kind: str, seed: int, split: str, output: Path):
    rng = random.Random(seed)
    # Disjoint parameter intervals for development and held-out test families.
    severity = rng.uniform(0.13, 0.17) if split == "dev" else rng.uniform(0.22, 0.28)
    config = {
        "query_delay": severity if kind == "pool_exhaustion" else 0.002,
        "cache_delay": severity if kind == "cache_latency" else 0,
        "worker_delay": severity * 3 if kind == "queue_backlog" else 0.002,
        "request_timeout_ms": rng.randint(5, 30) if kind == "config_error" else 1000,
    }
    cache = redis.Redis(host="127.0.0.1", port=16379)
    cache.ping()
    cache.delete("probeops-lab:jobs")
    cache.set("probeops-lab:control", json.dumps(config))
    processes = []
    started = now()
    try:
        for role in ([], ["worker"]):
            processes.append(
                subprocess.Popen(
                    [sys.executable, str(ROOT / "lab/service.py"), *role],
                    cwd=ROOT,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
        async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
            for _ in range(80):
                try:
                    (await client.get("http://127.0.0.1:8011/healthz")).raise_for_status()
                    break
                except httpx.HTTPError:
                    if any(p.poll() is not None for p in processes):
                        raise RuntimeError("Lab service failed to start") from None
                    await asyncio.sleep(0.1)
            else:
                raise RuntimeError("Lab readiness timeout")
            # Eight rounds of concurrent real requests, not fabricated metrics.
            for _ in range(8):
                responses = await asyncio.gather(
                    *[client.get("http://127.0.0.1:8011/checkout") for _ in range(6)]
                )
                for response in responses:
                    response.raise_for_status()
                await asyncio.sleep(0.08)
            response = await client.get("http://127.0.0.1:8011/observations")
            response.raise_for_status()
            views = response.json()
        if kind == "unknown":
            views["metrics"], views["logs"], views["traces"], views["config"] = {}, {}, [], {}
        identifier = "inc_" + uuid.uuid4().hex[:16]
        value = {
            "incident": {
                "incident_id": identifier,
                "title": "结算服务异常检查",
                "alert": "检查本次结算窗口的响应、任务处理与配置是否异常。",
                "service": "checkout-api",
                "window_start": started,
                "window_end": now(),
                "dataset_version": "lab-v1",
            },
            "graph": GRAPH,
            **views,
            "provenance": {"kind": "captured-local-services", "requests": 48},
        }
        value["content_hash"] = digest(value)
        output.mkdir(parents=True, exist_ok=True)
        path = output / f"{identifier}.json"
        with path.open("x") as file:
            json.dump(value, file, ensure_ascii=False, indent=2)
        private = ROOT / ".runtime/evaluator"
        private.mkdir(parents=True, exist_ok=True)
        truth = {
            "incident_id": identifier,
            "component": COMPONENTS[kind],
            "fault_type": kind,
            "seed": seed,
            "split": split,
            "family": split,
            "injection": config,
            "content_hash": value["content_hash"],
        }
        with (private / "truth.jsonl").open("a") as file:
            file.write(json.dumps(truth) + "\n")
        print(json.dumps({"incident_id": identifier, "split": split, "captured": True}), flush=True)
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        cache.delete("probeops-lab:control", "probeops-lab:jobs")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", choices=["smoke", "dev", "full"], default="smoke")
    parser.add_argument("--output", type=Path, default=ROOT / "data/snapshots")
    args = parser.parse_args()
    # Single writer lock also prevents accidental overlap with another controller.
    import fcntl

    (ROOT / ".runtime").mkdir(exist_ok=True)
    with (ROOT / ".runtime/lab-capture.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for split in ["dev", "test"] if args.suite == "full" else ["dev"]:
            for index, kind in enumerate(FAULTS):
                count = (
                    1
                    if args.suite == "smoke"
                    else (4 if index < 4 else 2) * (3 if split == "test" else 1)
                )
                for repeat in range(count):
                    await capture(
                        kind,
                        1000 + index * 100 + repeat + (10000 if split == "test" else 0),
                        split,
                        args.output,
                    )


if __name__ == "__main__":
    asyncio.run(main())
