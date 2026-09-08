"""Freeze hashes and calibrate probe costs using only development observations."""

import argparse
import json
import statistics
from pathlib import Path

from probeops.observations import PROBES, Gateway, SnapshotCatalog, digest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshots", type=Path, default=Path("data/benchmark"))
    parser.add_argument("--truth", type=Path, default=Path(".runtime/evaluator/truth.jsonl"))
    args = parser.parse_args()
    manifest = {"version": "lab-v1", "kind": "captured-local-services", "items": []}
    truth = {x["incident_id"]: x for x in map(json.loads, args.truth.read_text().splitlines())}
    costs = {p.probe_id: [] for p in PROBES}
    catalog = SnapshotCatalog(args.snapshots)
    for file in sorted(args.snapshots.glob("inc_*.json")):
        snap = catalog.load(file.stem)
        label = truth[file.stem]
        manifest["items"].append(
            {
                "incident_id": file.stem,
                "content_hash": snap["content_hash"],
                "split": label["split"],
                "family": label["family"],
            }
        )
        if label["split"] == "dev":
            for p in PROBES:
                evidence, _, elapsed = Gateway(snap).observe(p.probe_id)
                costs[p.probe_id].append((elapsed, len(evidence["summary"].encode())))
    calibration = {
        "version": "cost-v1",
        "formula": "p50_ms/100 + p50_bytes/4096, min 0.1",
        "manifest_hash": digest(manifest),
        "costs": {
            pid: max(
                0.1,
                statistics.median(ms for ms, _ in values) / 100
                + statistics.median(size for _, size in values) / 4096,
            )
            for pid, values in costs.items()
        },
    }
    for path, value in [
        (args.snapshots.parent / "manifest.json", manifest),
        (args.snapshots.parent / "costs.json", calibration),
    ]:
        with path.open("x") as output:
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.write("\n")
    print(json.dumps({"snapshots": len(manifest["items"]), "cost_version": "cost-v1"}))


if __name__ == "__main__":
    main()
