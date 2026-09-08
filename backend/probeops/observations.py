"""Immutable, bounded observation gateway. No evaluator imports or live network access."""

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from .models import INCIDENT, DomainError, StrictModel
from .telemetry import now, span_id

Json = dict[str, Any]
Band = Literal["high", "normal", "low", "unknown"]
SERVICES = ("checkout-api", "task-worker", "cache", "database")
GRAPH = {"checkout-api": ["cache", "database", "task-worker"], "task-worker": ["database"]}


class Probe(StrictModel):
    probe_id: str
    tool_name: Literal["query_metrics", "query_logs", "get_trace", "read_config"]
    service: Literal["checkout-api", "task-worker", "cache", "database"]
    key: str
    threshold: float
    units: str
    cost: float = Field(ge=0.1)


# Provisional costs are calibrated by the controller using development snapshots only.
PROBES = [
    Probe.model_validate(
        dict(probe_id=i, tool_name=t, service=s, key=k, threshold=v, units=u, cost=c)
    )
    for i, t, s, k, v, u, c in [
        ("api_latency", "query_metrics", "checkout-api", "latency_ms", 150.0, "ms", 1.0),
        ("pool_wait", "query_metrics", "database", "pool_wait_ms", 80.0, "ms", 0.5),
        ("queue_depth", "query_metrics", "task-worker", "queue_depth", 5.0, "jobs", 0.4),
        ("cache_latency", "query_metrics", "cache", "latency_ms", 80.0, "ms", 0.6),
        ("pool_events", "query_logs", "database", "pool_wait", 0.0, "events", 1.5),
        ("queue_events", "query_logs", "task-worker", "job_delayed", 0.0, "events", 1.5),
        ("cache_events", "query_logs", "cache", "cache_slow", 0.0, "events", 1.5),
        ("config_events", "query_logs", "checkout-api", "config_rejected", 0.0, "events", 1.5),
        ("request_trace", "get_trace", "checkout-api", "request", 150.0, "ms", 2.0),
        ("timeout_config", "read_config", "checkout-api", "request_timeout_ms", 1000.0, "ms", 0.3),
    ]
]
PROBE_MAP = {p.probe_id: p for p in PROBES}


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class SnapshotCatalog:
    def __init__(self, directory: Path):
        self.directory = directory

    def list(self) -> list[Json]:
        result = [INCIDENT]
        if self.directory.exists():
            for path in sorted(self.directory.glob("inc_*.json")):
                result.append(self.load(path.stem)["incident"])
        return result

    def load(self, incident_id: str) -> Json:
        if not re.fullmatch(r"inc_[a-f0-9]{16}", incident_id):
            raise DomainError(404, "INCIDENT_NOT_FOUND", "任务不存在。")
        path = self.directory / f"{incident_id}.json"
        if not path.is_file():
            raise DomainError(404, "INCIDENT_NOT_FOUND", "任务不存在。")
        if path.stat().st_size > 2_000_000:
            raise DomainError(503, "SNAPSHOT_INVALID", "观测快照超过限制。")
        try:
            data: Json = json.loads(path.read_text())
            expected = data.pop("content_hash")
            if digest(data) != expected or data["incident"]["incident_id"] != incident_id:
                raise ValueError
            if set(data) != {
                "incident",
                "graph",
                "metrics",
                "logs",
                "traces",
                "config",
                "provenance",
            }:
                raise ValueError
            data["content_hash"] = expected
            return data
        except (ValueError, KeyError, TypeError):
            raise DomainError(503, "SNAPSHOT_INVALID", "观测快照无效或内容哈希不符。") from None

    def incident(self, incident_id: str) -> Json:
        return (
            INCIDENT
            if incident_id == INCIDENT["incident_id"]
            else self.load(incident_id)["incident"]
        )


class Gateway:
    def __init__(self, snapshot: Json):
        self.snapshot = snapshot
        self.seen: set[str] = set()

    def observe(self, probe_id: str) -> tuple[Json, Band, float]:
        if probe_id not in PROBE_MAP:
            raise DomainError(422, "TOOL_DENIED", "探测不在只读白名单中。")
        p = PROBE_MAP[probe_id]
        key = digest([self.snapshot["content_hash"], p.model_dump()])
        if key in self.seen:
            raise DomainError(409, "DUPLICATE_PROBE", "同一快照探测不可重复计为证据。")
        self.seen.add(key)
        start = time.perf_counter()
        value: Any = None
        if p.tool_name == "query_metrics":
            value = self.snapshot["metrics"].get(p.service, {}).get(p.key)
            if isinstance(value, list):
                value = value[:120]
        elif p.tool_name == "query_logs":
            logs = self.snapshot["logs"].get(p.service)
            if logs is not None:
                value = [x for x in logs if x["event_type"] == p.key][:50]
        elif p.tool_name == "get_trace":
            # Only IDs in the captured request index, never caller supplied paths or URLs.
            value = self.snapshot["traces"][:1] or None
        else:
            value = self.snapshot["config"].get(p.service, {}).get(p.key)
        band: Band = "unknown"
        if value is not None:
            if p.tool_name == "query_logs":
                band = "high" if value else "normal"
            elif p.tool_name == "get_trace":
                band = "high" if value[0]["duration_ms"] > p.threshold else "normal"
            else:
                values = value if isinstance(value, list) else [value]
                if values:
                    average = sum(values) / len(values)
                    band = "high" if average > p.threshold else "normal"
                    if p.tool_name == "read_config" and average < 100:
                        band = "low"
        content = {
            "service": p.service,
            "observation": p.key,
            "value": value,
            "band": band,
            "units": p.units,
        }
        encoded = json.dumps(content, ensure_ascii=False, sort_keys=True)
        outcome = "empty" if value is None else "ok"
        if len(encoded.encode()) > 32000:
            # Do not score a truncated observation as a reliable normal/high result.
            encoded, band, outcome = encoded[:3400] + " [truncated]", "unknown", "truncated"
        elif len(encoded) > 3600:
            # The full bounded observation is scored and hashed; the API summary is compact.
            encoded = json.dumps(
                {
                    "service": p.service,
                    "observation": p.key,
                    "count": len(value),
                    "sample": value[:3],
                    "band": band,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        incident = self.snapshot["incident"]
        evidence = {
            "evidence_id": "ev_" + key[:24],
            "probe_id": probe_id,
            "tool_name": p.tool_name,
            "observed_at": now(),
            "window_start": incident["window_start"],
            "window_end": incident["window_end"],
            "summary": encoded,
            "content_hash": digest(content),
            "outcome": outcome,
            "source": f"snapshot://{incident['incident_id']}/{p.tool_name}/{p.service}",
            "span_id": span_id(),
        }
        return evidence, band, (time.perf_counter() - start) * 1000
