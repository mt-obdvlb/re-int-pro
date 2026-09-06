"""Read local OTel exports for one run trace, without loading request payloads."""

import argparse
import json
import re

from probeops.config import settings

parser = argparse.ArgumentParser()
parser.add_argument("trace_id")
args = parser.parse_args()
if not re.fullmatch(r"[0-9a-f]{32}", args.trace_id):
    parser.error("trace_id must be 32 lowercase hexadecimal characters")
found = []
for path in settings().probeops_telemetry_dir.glob("*-spans.jsonl*"):
    with path.open() as stream:
        for line in stream:
            try:
                span = json.loads(line)
            except json.JSONDecodeError:
                continue
            if span.get("trace_id") == args.trace_id:
                found.append(span)
for span in sorted(found, key=lambda item: item["start_time"]):
    elapsed = (span["end_time"] - span["start_time"]) / 1_000_000
    print(
        f"{span['span_id']} <- {span['parent_span_id'] or 'root'} "
        f"{span['name']} {span['status']} {elapsed:.2f}ms"
    )
if not found:
    print("No spans found. Check trace_id, exporter flush, and telemetry directory.")
    raise SystemExit(1)
