"""Cross prompt versions with prefix/complete verification, using fixed proposal caches."""

import argparse
import json
from pathlib import Path

from mechanisms import (
    audit_predictions,
    export_candidates,
    file_hash,
    initial_hypotheses,
    paired_interval,
    replay,
    score,
)
from probeops.observations import SnapshotCatalog, digest

MODES = {
    "prefix": (False, False),
    "complete": (True, False),
    "complete_falsification": (True, True),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, default=Path("docs/evidence/dev-proposals.json"))
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--after-batch", type=Path)
    source.add_argument("--after", type=Path)
    parser.add_argument("--db", type=Path, default=Path(".runtime/probeops.sqlite3"))
    parser.add_argument("--truth", type=Path, default=Path(".runtime/evaluator/truth.jsonl"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Output exists; preserve prior experiments")
    manifest = json.loads(Path("data/manifest.json").read_text())
    tasks = {x["incident_id"]: x for x in manifest["items"] if x["split"] == "dev"}
    calibration = json.loads(Path("data/costs.json").read_text())
    if calibration["manifest_hash"] != digest(manifest):
        raise ValueError("Calibration drift")
    costs = calibration["costs"]
    before = json.loads(args.before.read_text())
    after = (
        export_candidates(args.db, args.after_batch, tasks)
        if args.after_batch
        else json.loads(args.after.read_text())
    )
    if (before["mode"], before["model"]) != (after["mode"], after["model"]):
        raise ValueError("Model drift")
    labels = [json.loads(x) for x in args.truth.read_text().splitlines()]
    truth = {x["incident_id"]: x for x in labels if x["incident_id"] in tasks}
    if set(truth) != set(tasks) or sum(x["incident_id"] in tasks for x in labels) != len(tasks):
        raise ValueError("Incomplete or duplicate truth")
    catalog, rows = SnapshotCatalog(Path("data/benchmark")), []
    for name, cache, prompt in [("before", before, "proposal-v2"), ("after", after, "proposal-v3")]:
        if len(cache["items"]) != len(tasks) or {e["incident_id"] for e in cache["items"]} != set(
            tasks
        ):
            raise ValueError("Incomplete or duplicate proposal inventory")
        for entry in cache["items"]:
            iid = entry["incident_id"]
            snapshot = catalog.load(iid)
            if (
                len(
                    {
                        snapshot["content_hash"],
                        entry["snapshot_hash"],
                        tasks[iid]["content_hash"],
                        truth[iid]["content_hash"],
                    }
                )
                != 1
                or truth[iid]["split"] != "dev"
                or entry["cost_hash"] != digest(costs)
                or entry["prompt_version"] != prompt
                or entry["policy_version"]
                != ("competitive-v2" if name == "before" else "competitive-v4")
                or entry["seed"] != 42
            ):
                raise ValueError("Frozen context drift")
            initial = entry["initial"]
            if initial is not None:
                initial = initial_hypotheses(
                    [{"kind": "hypotheses_updated", "hypotheses": initial}]
                )
            for mode, (complete, falsification) in MODES.items():
                value = replay(
                    snapshot,
                    initial,
                    costs,
                    "verification_cost",
                    42,
                    require_complete=complete,
                    allow_falsification=falsification,
                )
                # Truth is joined after the label-blind decision loop.
                scored = score(value, truth[iid])
                audit = audit_predictions(snapshot, initial, truth[iid])
                chosen = next(
                    (
                        h
                        for h in initial or []
                        if value["diagnosis"] == {k: h[k] for k in ("component", "fault_type")}
                    ),
                    None,
                )
                unchecked = (
                    [
                        p["observation"]
                        for p in chosen["predictions"]
                        if p["expected"] != "unknown" and p["observation"] not in value["probes"]
                    ]
                    if chosen
                    else []
                )
                if complete and value["diagnosis"] is not None and unchecked:
                    raise AssertionError(
                        "Complete verification left an explicit prediction unchecked"
                    )
                rows.append(
                    {
                        "incident_id": iid,
                        "prompt": name,
                        "complete": complete,
                        "verification": mode,
                        "fault_type": truth[iid]["fault_type"],
                        "audit": audit,
                        "unchecked": unchecked,
                        **scored,
                    }
                )
    groups, comparisons = {}, {}
    for name in ("before", "after"):
        for mode in MODES:
            group = [r for r in rows if (r["prompt"], r["verification"]) == (name, mode)]
            known = [r for r in group if r["fault_type"] not in {"normal", "unknown"}]
            groups[f"{name}_{mode}"] = {
                "tasks": len(group),
                "known_tasks": len(known),
                "known_correct": sum(r["correct"] for r in known),
                "known_false_locations": sum(r["located"] and not r["correct"] for r in known),
                "negative_false_locations": sum(r["located"] for r in group if r not in known),
                "mean_probes": sum(r["probe_count"] for r in group) / len(group),
                "mean_proxy_cost": sum(r["probe_cost_units"] for r in group) / len(group),
                "located_with_unchecked_predictions": sum(bool(r["unchecked"]) for r in group),
                "correct_with_unobserved_refutations": sum(
                    r["correct"]
                    and any(
                        m["probe_id"] not in r["probes"] for m in r["audit"].get("mismatches", [])
                    )
                    for r in known
                ),
                "candidate_coverage": sum(r["audit"]["true_candidate_present"] for r in known),
                "known_prediction_cells": sum(
                    r["audit"].get("true_candidate_known_predictions", 0) for r in known
                ),
                "matching_prediction_cells": sum(
                    r["audit"].get("true_candidate_matching_predictions", 0) for r in known
                ),
                "missing_initial_tasks": sum(r["audit"]["missing_initial"] for r in group),
            }
        for target, baseline in [("complete", "prefix"), ("complete_falsification", "complete")]:
            left = {
                r["incident_id"]: r
                for r in rows
                if r["prompt"] == name
                and r["verification"] == target
                and r["fault_type"] not in {"normal", "unknown"}
            }
            right = {
                r["incident_id"]: r
                for r in rows
                if r["prompt"] == name
                and r["verification"] == baseline
                and r["fault_type"] not in {"normal", "unknown"}
            }
            comparisons[f"{name}_{target}_minus_{baseline}"] = {
                "accuracy": paired_interval(
                    [int(left[i]["correct"]) - int(right[i]["correct"]) for i in sorted(left)]
                ),
                "common_success_extra_probes": paired_interval(
                    [
                        left[i]["probe_count"] - right[i]["probe_count"]
                        for i in sorted(left)
                        if left[i]["correct"] and right[i]["correct"]
                    ]
                ),
            }
    summary = {
        "kind": "development-prompt-by-verification-replay",
        "model": before["model"],
        "mode": before["mode"],
        "before_cache_hash": digest(before),
        "after_cache_hash": digest(after),
        "groups": groups,
        "within_cache_paired": comparisons,
        "new_api_cost_micro_cny": 0,
        "after_source_full_runs_cost_micro_cny": sum(
            e["source_usage"]["settled_micro_cny"] for e in after["items"]
        ),
        "after_source_full_runs_uncertain_micro_cny": sum(
            e["source_usage"]["uncertain_micro_cny"] for e in after["items"]
        ),
        "source_hashes": {
            str(p): file_hash(p)
            for p in map(
                Path,
                [
                    "evaluation/reliability.py",
                    "evaluation/mechanisms.py",
                    "backend/probeops/reasoning.py",
                    "backend/probeops/prompts.py",
                    "backend/probeops/engine.py",
                    "docs/reliability-protocol.md",
                    "docs/reliability-followup.md",
                ],
            )
        },
        "limits": [
            "Development only; one generated matrix per task per prompt",
            "Across-prompt changes include sampling variation",
            "Full checks establish prediction consistency, not causal correctness",
            "Unknown predictions are excluded; report coverage alongside consistency",
        ],
    }
    args.output.mkdir(parents=True)
    for filename, value in [
        ("candidates.json", after),
        ("results.json", rows),
        ("summary.json", summary),
    ]:
        with (args.output / filename).open("x") as output:
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.write("\n")
    print(json.dumps({"tasks_per_cache": len(tasks), "replay_trials": len(rows), "api_calls": 0}))


if __name__ == "__main__":
    main()
