"""Task-paired bootstrap; repetitions never become independent tasks."""

import argparse
import json
import random
import statistics
from collections import defaultdict
from pathlib import Path


def summarize(rows):
    if not rows:
        raise ValueError("Empty batch")
    if len({(r["model"], r["mode"]) for r in rows}) != 1:
        raise ValueError("Do not mix models or fake and live results")
    unique = {(r["incident_id"], r["strategy"], r["repeat"]) for r in rows}
    if len(unique) != len(rows):
        raise ValueError("Duplicate trial")
    tasks_all = {r["incident_id"] for r in rows}
    strategies_all = {r["strategy"] for r in rows}
    repeats_all = {r["repeat"] for r in rows}
    expected_trials = {(t, s, n) for t in tasks_all for s in strategies_all for n in repeats_all}
    if unique != expected_trials:
        raise ValueError("Incomplete paired batch; retain failures as rows, do not drop trials")
    for task in tasks_all:
        if len({r["snapshot_hash"] for r in rows if r["incident_id"] == task}) != 1:
            raise ValueError("Snapshot drift within paired task")
    known = [r for r in rows if r["fault_type"] not in {"normal", "unknown"}]
    groups = defaultdict(list)
    for row in rows:
        groups[row["strategy"]].append(row)
    result = {
        "mode": rows[0]["mode"],
        "model": rows[0]["model"],
        "trials": len(rows),
        "warning": "FakeLLM仅验证实验管线，不能证明模型或机制有效。"
        if rows[0]["mode"] == "fake"
        else "受控快照实验，不能外推生产诊断。",
        "strategies": {},
        "paired": {},
    }
    for strategy, values in groups.items():
        k = [r for r in values if r in known]
        negatives = [r for r in values if r["fault_type"] in {"normal", "unknown"}]
        latency = sorted(r["latency_ms"] for r in values)
        result["strategies"][strategy] = {
            "trials": len(values),
            "known_trials": len(k),
            "known_accuracy": statistics.mean(r["correct"] for r in k) if k else None,
            "negative_false_locations": sum(r["located"] for r in negatives),
            "system_failures": sum(r["status"] != "completed" for r in values),
            "mean_probes": statistics.mean(r["usage"]["probe_count"] for r in values),
            "cost_micro_cny": sum(
                sum(r["usage"][f"{s}_micro_cny"] for s in ["settled", "uncertain", "reserved"])
                for r in values
            ),
            "latency_p50_ms": statistics.median(latency),
            "latency_p95_ms": latency[min(len(latency) - 1, int(len(latency) * 0.95))],
        }
    tasks = defaultdict(lambda: defaultdict(list))
    for r in known:
        tasks[r["strategy"]][r["incident_id"]].append(int(r["correct"]))
    for baseline in ("react", "graph_greedy", "no_cost", "random_probe", "fixed"):
        left, right = tasks["competitive_cost"], tasks[baseline]
        if not left or set(left) != set(right):
            continue
        differences = [statistics.mean(left[t]) - statistics.mean(right[t]) for t in sorted(left)]
        rng = random.Random(42)
        bootstrap = sorted(
            statistics.mean(rng.choices(differences, k=len(differences))) for _ in range(10000)
        )
        result["paired"][baseline] = {
            "tasks": len(differences),
            "difference": statistics.mean(differences),
            "ci95": [bootstrap[250], bootstrap[9749]],
        }
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("results", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = summarize([json.loads(x) for x in args.results.read_text().splitlines()])
    args.output.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
