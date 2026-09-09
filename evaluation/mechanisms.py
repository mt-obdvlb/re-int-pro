"""Offline, label-blind policies; truth joins only after each diagnosis finishes.

This is initial-proposal replay, not a full adaptive LLM run. No provider imports.
The optional database export reads existing events; it never makes model calls.
"""

import argparse
import copy
import hashlib
import itertools
import json
import random
import sqlite3
import statistics
from pathlib import Path

from probeops.observations import PROBE_MAP, Gateway, SnapshotCatalog, digest
from probeops.reasoning import Proposal, expected, falsifiable_probes, select, update

VERSION = "mechanisms-v1"
SIGNATURES = (
    ("database", "pool_exhaustion", "pool_wait", "high", "pool_events"),
    ("task-worker", "queue_backlog", "queue_depth", "high", "queue_events"),
    ("cache", "cache_latency", "cache_latency", "high", "cache_events"),
    ("checkout-api", "config_error", "timeout_config", "low", "config_events"),
)
VARIANTS = {
    "legacy_cost": ("competitive_cost", False, 0.1, False),
    "verification_cost": ("competitive_cost", True, 0.1, False),
    "verification_no_cost": ("no_cost", True, 0.1, False),
    "legacy_no_cost": ("no_cost", False, 0.1, False),
    "fixed_order": ("fixed", False, 0.1, False),
    "random_order": ("random_probe", False, 0.1, False),
    "epsilon_0": ("competitive_cost", True, 0.0, False),
    "epsilon_001": ("competitive_cost", True, 0.01, False),
    "epsilon_1": ("competitive_cost", True, 1.0, False),
    "uniform_cost": ("competitive_cost", True, 0.1, True),
}


def initial_hypotheses(events):
    first = next((e for e in events if e["kind"] == "hypotheses_updated"), None)
    if first is None:
        return None
    hs = first.get("hypotheses")
    if not hs or any(
        h["score"] != 0
        or h["status"] != "active"
        or h["evidence_ids"]
        or not h["hypothesis_id"].startswith("h_0_")
        for h in hs
    ):
        raise ValueError("Initial candidate history missing or already updated; no reconstruction")
    Proposal.model_validate(
        {
            "candidates": [
                {
                    "component": h["component"],
                    "fault_type": h["fault_type"],
                    "predictions": [
                        {"probe_id": p["observation"], "expected": p["expected"]}
                        for p in h["predictions"]
                    ],
                }
                for h in hs
            ]
        }
    )
    return copy.deepcopy(hs)


def export_candidates(db_path, batch, tasks):
    rows = [json.loads(line) for line in batch.read_text().splitlines()]
    if len(rows) != len(tasks) or {r["incident_id"] for r in rows} != set(tasks):
        raise ValueError("Batch must contain every manifest development task exactly once")
    if len({(r["mode"], r["model"], r["strategy"], r["repeat"]) for r in rows}) != 1:
        raise ValueError("Mixed candidate-generation conditions")
    records = []
    with sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        for row in rows:
            rid = row["run_id"]
            frozen = json.loads(
                db.execute("SELECT body FROM run_context WHERE run_id=?", (rid,)).fetchone()[0]
            )
            if (
                hashlib.sha256(json.dumps(frozen, sort_keys=True).encode()).hexdigest()
                != row["config_hash"]
            ):
                raise ValueError("Frozen run configuration drift")
            if frozen["snapshot"]["content_hash"] != tasks[row["incident_id"]]["content_hash"]:
                raise ValueError("Candidate snapshot drift")
            if frozen["snapshot"]["content_hash"] != row["snapshot_hash"]:
                raise ValueError("Batch snapshot drift")
            events = [
                json.loads(b)
                for (b,) in db.execute(
                    "SELECT body FROM events WHERE run_id=? ORDER BY seq", (rid,)
                )
            ]
            records.append(
                {
                    "incident_id": row["incident_id"],
                    "snapshot_hash": row["snapshot_hash"],
                    "source_run_id": rid,
                    "config_hash": row["config_hash"],
                    "seed": frozen["seed"],
                    "prompt_version": frozen["prompt_version"],
                    "policy_version": frozen["policy_version"],
                    "cost_hash": digest(frozen["costs"]),
                    "initial": initial_hypotheses(events),
                    "source_status": row["status"],
                    "source_stop_reason": row["stop_reason"],
                    "source_usage": row["usage"],
                }
            )
    return {
        "version": VERSION,
        "kind": "initial-proposal-cache",
        "mode": rows[0]["mode"],
        "model": rows[0]["model"],
        "batch_hash": file_hash(batch),
        "items": records,
    }


def result(steps, costs, diagnosis=None, stop="unresolved"):
    return {
        "diagnosis": diagnosis,
        "stop": stop,
        "probes": [s["probe_id"] for s in steps],
        "probe_count": len(steps),
        # Always charge the original calibrated costs, including uniform-cost ablation.
        "probe_cost_units": sum(costs[s["probe_id"]] for s in steps),
        "steps": steps,
    }


def rule_diagnose(snapshot, costs):
    """Domain rule baseline: no model proposals, predictions, task IDs or truth."""
    gateway = Gateway(snapshot)
    steps, bands = [], {}
    for _, _, pid, _, _ in SIGNATURES:
        evidence, band, _ = gateway.observe(pid)
        bands[pid] = band if evidence["outcome"] == "ok" else "unknown"
        steps.append({"probe_id": pid, "band": bands[pid]})
    matches = [
        s
        for s in SIGNATURES
        if bands[s[2]] == s[3]
        and all(bands[other[2]] == "normal" for other in SIGNATURES if other != s)
    ]
    if len(matches) != 1:
        return result(steps, costs)
    component, fault, _, _, log = matches[0]
    evidence, band, _ = gateway.observe(log)
    steps.append({"probe_id": log, "band": band})
    if evidence["outcome"] == "ok" and band == "high":
        return result(steps, costs, {"component": component, "fault_type": fault}, "supported")
    return result(steps, costs)


def replay(
    snapshot, initial, costs, variant, seed=42, *, require_complete=False, allow_falsification=False
):
    if initial is None:
        return result([], costs, stop="missing_initial")
    strategy, verification, smoothing, uniform = VARIANTS[variant]
    hs = copy.deepcopy(initial)
    gateway, observed, steps = Gateway(snapshot), [], []
    remaining, stagnant = list(PROBE_MAP), 0
    decision_costs = dict.fromkeys(costs, 0.1) if uniform else costs
    stop = "exhausted"
    for step in range(len(PROBE_MAP)):
        decision = select(
            strategy,
            hs,
            remaining,
            seed + step,
            costs=decision_costs,
            observations=observed,
            verification=verification,
            smoothing=smoothing,
            require_complete=require_complete,
            allow_falsification=allow_falsification,
        )
        active = [h for h in hs if h["status"] != "contradicted"]
        if (
            strategy in {"competitive_cost", "no_cost"}
            and len(active) > 1
            and decision["disagreement_pairs"] == 0
            and not (allow_falsification and falsifiable_probes(hs, remaining))
        ):
            stop = "indistinguishable"
            break
        pid = decision["probe_id"]
        evidence, band, _ = gateway.observe(pid)
        steps.append({**decision, "band": band})
        remaining.remove(pid)
        observed.append((evidence, band))
        hs = update(hs, observed, require_complete=require_complete)
        supported = next((h for h in hs if h["status"] == "supported"), None)
        if supported:
            return result(
                steps,
                costs,
                {k: supported[k] for k in ("component", "fault_type")},
                "supported",
            )
        stagnant = stagnant + 1 if band == "unknown" else 0
        if stagnant >= 2:
            stop = "missing_observations"
            break
        if all(h["status"] == "contradicted" for h in hs):
            stop = "all_refuted_no_reproposal"
            break
    return result(steps, costs, stop=stop)


def audit_predictions(snapshot, initial, truth):
    if initial is None:
        return {"missing_initial": True, "true_candidate_present": False}
    gateway = Gateway(snapshot)
    observations = [gateway.observe(pid)[:2] for pid in PROBE_MAP]
    target = next(
        (
            h
            for h in initial
            if (h["component"], h["fault_type"]) == (truth["component"], truth["fault_type"])
        ),
        None,
    )
    available = [(e, b) for e, b in observations if e["outcome"] == "ok" and b != "unknown"]
    predicted = [
        (e, b) for e, b in available if target and expected(target, e["probe_id"]) != "unknown"
    ]
    mismatches = [
        {"probe_id": e["probe_id"], "expected": expected(target, e["probe_id"]), "actual": b}
        for e, b in predicted
        if expected(target, e["probe_id"]) != b
    ]
    return {
        "missing_initial": False,
        "true_candidate_present": target is not None,
        "available_observations": len(available),
        "true_candidate_known_predictions": len(predicted),
        "true_candidate_matching_predictions": len(predicted) - len(mismatches),
        "mismatches": mismatches,
        "identical_candidate_pairs": sum(
            all(expected(a, pid) == expected(b, pid) for pid in PROBE_MAP)
            for a, b in itertools.combinations(initial, 2)
        ),
    }


def score(value, truth):
    diagnosis = value["diagnosis"]
    return {
        **value,
        "located": diagnosis is not None,
        "correct": diagnosis is not None
        and (diagnosis["component"], diagnosis["fault_type"])
        == (truth["component"], truth["fault_type"]),
    }


def paired_interval(values):
    if not values:
        return None
    rng = random.Random(42)
    boot = sorted(statistics.mean(rng.choices(values, k=len(values))) for _ in range(10000))
    return {
        "tasks": len(values),
        "difference": statistics.mean(values),
        "ci95": [boot[250], boot[9749]],
    }


def summarize(rows):
    known = [r for r in rows if r["fault_type"] not in {"normal", "unknown"}]
    negatives = [r for r in rows if r not in known]
    output = {"tasks": len(rows), "known_tasks": len(known), "negative_tasks": len(negatives)}
    output["variants"] = {}
    for name in [*VARIANTS, "rules"]:
        output["variants"][name] = {
            "known_correct": sum(r["variants"][name]["correct"] for r in known),
            "known_false_locations": sum(
                r["variants"][name]["located"] and not r["variants"][name]["correct"] for r in known
            ),
            "negative_false_locations": sum(r["variants"][name]["located"] for r in negatives),
            "correct_with_unobserved_refutations": (
                sum(
                    r["variants"][name]["correct"]
                    and any(
                        m["probe_id"] not in r["variants"][name]["probes"]
                        for m in r["audit"].get("mismatches", [])
                    )
                    for r in known
                )
                if name != "rules"
                else None  # A model's predictions are not the rule baseline's assumptions.
            ),
            "mean_probes": statistics.mean(r["variants"][name]["probe_count"] for r in rows),
            "mean_proxy_cost": statistics.mean(
                r["variants"][name]["probe_cost_units"] for r in rows
            ),
        }
    output["paired"] = {}
    for name in [n for n in VARIANTS if n != "verification_cost"]:
        common = [
            r
            for r in known
            if r["variants"][name]["correct"] and r["variants"]["verification_cost"]["correct"]
        ]
        output["paired"][name] = {
            "accuracy": paired_interval(
                [
                    int(r["variants"]["verification_cost"]["correct"])
                    - int(r["variants"][name]["correct"])
                    for r in known
                ]
            ),
            "common_success_probes": paired_interval(
                [
                    r["variants"]["verification_cost"]["probe_count"]
                    - r["variants"][name]["probe_count"]
                    for r in common
                ]
            ),
            "common_success_proxy_cost": paired_interval(
                [
                    r["variants"]["verification_cost"]["probe_cost_units"]
                    - r["variants"][name]["probe_cost_units"]
                    for r in common
                ]
            ),
            "common_consistent_success_probes": paired_interval(
                [
                    r["variants"]["verification_cost"]["probe_count"]
                    - r["variants"][name]["probe_count"]
                    for r in common
                    if not r["audit"].get("mismatches")
                ]
            ),
            "changed_sequences": sum(
                r["variants"]["verification_cost"]["probes"] != r["variants"][name]["probes"]
                for r in rows
            ),
        }
    audits = [r["audit"] for r in known]
    output["prediction_audit"] = {
        "covered_known_tasks": sum(a["true_candidate_present"] for a in audits),
        "missing_initial_tasks": sum(r["audit"]["missing_initial"] for r in rows),
        "available_cells": sum(a.get("available_observations", 0) for a in audits),
        "known_prediction_cells": sum(a.get("true_candidate_known_predictions", 0) for a in audits),
        "matching_cells": sum(a.get("true_candidate_matching_predictions", 0) for a in audits),
        "tasks_with_identical_candidates": sum(
            r["audit"].get("identical_candidate_pairs", 0) > 0 for r in rows
        ),
    }
    return output


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cost_audit(costs):
    # At most four hypotheses => D <= 6. If the denominator ratio is below
    # 6/5, even the closest adjacent positive D values cannot reverse order.
    minimum, maximum = min(costs.values()), max(costs.values())
    ratio = (maximum + 0.1) / (minimum + 0.1)
    return {
        "minimum": minimum,
        "maximum": maximum,
        "at_original_floor": sum(c == 0.1 for c in costs.values()),
        "denominator_ratio_at_epsilon_01": ratio,
        "sufficient_threshold_for_dominant_disagreement": 6 / 5,
        "cost_can_only_break_disagreement_ties": ratio < 6 / 5,
        "original_ms_and_bytes_components_saved": False,
    }


def unscored_summary(rows):
    """Portable replay needs no private truth; never invent accuracy without labels."""
    return {
        "tasks": len(rows),
        "scored": False,
        "variants": {
            name: {
                "located": sum(r["variants"][name]["diagnosis"] is not None for r in rows),
                "mean_probes": statistics.mean(r["variants"][name]["probe_count"] for r in rows),
                "mean_proxy_cost": statistics.mean(
                    r["variants"][name]["probe_cost_units"] for r in rows
                ),
            }
            for name in [*VARIANTS, "rules"]
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots", type=Path, default=Path("data/benchmark"))
    parser.add_argument("--manifest", type=Path, default=Path("data/manifest.json"))
    parser.add_argument("--costs", type=Path, default=Path("data/costs.json"))
    parser.add_argument("--truth", type=Path, default=Path(".runtime/evaluator/truth.jsonl"))
    parser.add_argument(
        "--unscored", action="store_true", help="Replay without reading hidden labels"
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--batch", type=Path)
    source.add_argument("--candidates", type=Path)
    parser.add_argument("--db", type=Path, default=Path(".runtime/probeops.sqlite3"))
    parser.add_argument(
        "--output", type=Path, required=True, help="New directory, never overwritten"
    )
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Output exists; choose a new directory")
    manifest = json.loads(args.manifest.read_text())
    tasks = {x["incident_id"]: x for x in manifest["items"] if x["split"] == "dev"}
    calibration = json.loads(args.costs.read_text())
    if calibration["manifest_hash"] != digest(manifest):
        raise ValueError("Cost calibration manifest mismatch")
    costs = calibration["costs"]
    cache = (
        export_candidates(args.db, args.batch, tasks)
        if args.batch
        else json.loads(args.candidates.read_text())
    )
    if (
        cache["version"] != VERSION
        or len(cache["items"]) != len(tasks)
        or {c["incident_id"] for c in cache["items"]} != set(tasks)
    ):
        raise ValueError("Incomplete or duplicate candidate inventory")
    if len({(c["prompt_version"], c["policy_version"], c["seed"]) for c in cache["items"]}) != 1:
        raise ValueError("Mixed generation conditions")
    truths = {}
    if not args.unscored:
        labels = [json.loads(line) for line in args.truth.read_text().splitlines()]
        truths = {r["incident_id"]: r for r in labels if r["incident_id"] in tasks}
        if len(truths) != len(tasks) or sum(r["incident_id"] in tasks for r in labels) != len(
            tasks
        ):
            raise ValueError("Missing or duplicate truth")
    catalog, rows = SnapshotCatalog(args.snapshots), []
    for entry in cache["items"]:
        iid = entry["incident_id"]
        snapshot = catalog.load(iid)
        if {
            snapshot["content_hash"],
            entry["snapshot_hash"],
            tasks[iid]["content_hash"],
        } != {snapshot["content_hash"]}:
            raise ValueError("Snapshot or truth drift")
        if entry["cost_hash"] != digest(costs):
            raise ValueError("Original cost drift")
        hs = entry["initial"]
        if hs is not None:
            hs = initial_hypotheses([{"kind": "hypotheses_updated", "hypotheses": hs}])
        variants = {name: replay(snapshot, hs, costs, name, entry["seed"]) for name in VARIANTS}
        variants["rules"] = rule_diagnose(snapshot, costs)
        # No truth enters the policy calls above.
        row = {
            "incident_id": iid,
            "snapshot_hash": snapshot["content_hash"],
            "initial_hash": digest(hs),
            "variants": variants,
        }
        if not args.unscored:
            truth = truths[iid]
            if truth["split"] != "dev" or truth["content_hash"] != snapshot["content_hash"]:
                raise ValueError("Truth snapshot or split drift")
            row.update(
                fault_type=truth["fault_type"],
                audit=audit_predictions(snapshot, hs, truth),
                variants={k: score(v, truth) for k, v in variants.items()},
            )
        rows.append(row)
    summary = {
        "version": VERSION,
        "kind": "development-initial-proposal-replay",
        "model": cache["model"],
        "mode": cache["mode"],
        "candidate_cache_hash": digest(cache),
        "source_batch_hash": cache["batch_hash"],
        "manifest_hash": digest(manifest),
        "source_hashes": {
            str(p): file_hash(p)
            for p in [
                Path("evaluation/mechanisms.py"),
                Path("backend/probeops/reasoning.py"),
                Path("backend/probeops/observations.py"),
                Path("docs/strengthening-protocol.md"),
            ]
        },
        "new_api_cost_micro_cny": 0,
        "source_full_runs_cost_micro_cny": sum(
            e["source_usage"]["settled_micro_cny"] for e in cache["items"]
        ),
        "source_full_runs_uncertain_micro_cny": sum(
            e["source_usage"]["uncertain_micro_cny"] for e in cache["items"]
        ),
        "cost_audit": cost_audit(costs),
        "limits": [
            "initial candidates only; no adaptive proposals",
            "development tasks; not held-out estimates",
            "proxy cost is not LLM fee or online latency",
            "domain rules have hand-authored signatures",
            "matching predictions and tool diversity do not prove causality",
        ],
        **(unscored_summary(rows) if args.unscored else {"scored": True, **summarize(rows)}),
    }
    args.output.mkdir(parents=True)
    for name, content in [
        ("candidates.json", cache),
        ("results.json", rows),
        ("summary.json", summary),
    ]:
        with (args.output / name).open("x") as output:
            json.dump(content, output, ensure_ascii=False, indent=2)
            output.write("\n")
    print(json.dumps({"tasks": len(rows), "output": str(args.output), "api_calls": 0}))


if __name__ == "__main__":
    main()
