"""Short SQLite transactions; snapshots and events commit atomically."""

import hashlib
import json
import sqlite3
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .models import INCIDENT, TERMINAL, CreateRun, DomainError
from .telemetry import Telemetry, now, remote_context, span_id

Json = dict[str, Any]
LEASE_SECONDS = 20


def uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class Store:
    def __init__(self, path: Path, telemetry: Telemetry):
        self.path, self.telemetry = path, telemetry
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise RuntimeError("Unsupported database version")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, body TEXT NOT NULL, request_hash TEXT NOT NULL,
                    idempotency_key TEXT UNIQUE NOT NULL, parent_span TEXT NOT NULL,
                    owner TEXT, lease_until REAL, ordinal INTEGER UNIQUE NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    run_id TEXT NOT NULL REFERENCES runs(id), seq INTEGER NOT NULL,
                    body TEXT NOT NULL, PRIMARY KEY(run_id, seq));
                CREATE TABLE IF NOT EXISTS evidence (
                    run_id TEXT NOT NULL REFERENCES runs(id), seq INTEGER NOT NULL,
                    body TEXT NOT NULL, PRIMARY KEY(run_id, seq));
                PRAGMA user_version=1;
            """)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=3)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.telemetry.span("storage.commit"), self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def _get(self, db: sqlite3.Connection, run_id: str) -> Json:
        row = db.execute("SELECT body FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise DomainError(404, "RUN_NOT_FOUND", "运行不存在。")
        return json.loads(row["body"])  # type: ignore[no-any-return]

    def _event(
        self,
        db: sqlite3.Connection,
        run: Json,
        kind: str,
        message: str,
        evidence_ids: list[str] | None = None,
    ) -> None:
        run["last_event_seq"] += 1
        run["version"] += 1
        run["updated_at"] = now()
        event = {
            "seq": run["last_event_seq"],
            "timestamp": run["updated_at"],
            "kind": kind,
            "message": message,
            "evidence_ids": evidence_ids or [],
            "hypothesis_ids": [h["hypothesis_id"] for h in run["hypotheses"]],
            "span_id": span_id(),
        }
        db.execute(
            "INSERT INTO events VALUES(?,?,?)", (run["run_id"], event["seq"], json.dumps(event))
        )
        db.execute("UPDATE runs SET body=? WHERE id=?", (json.dumps(run), run["run_id"]))

    def create(self, body: CreateRun, key: str, trace_id: str, parent_span: str) -> Json:
        payload = body.model_dump()
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        with self.transaction() as db:
            existing = db.execute(
                "SELECT body,request_hash FROM runs WHERE idempotency_key=?", (key,)
            ).fetchone()
            if existing:
                if existing["request_hash"] != digest:
                    raise DomainError(409, "IDEMPOTENCY_CONFLICT", "同一幂等键对应了不同请求。")
                return json.loads(existing["body"])  # type: ignore[no-any-return]
            if body.incident_id != INCIDENT["incident_id"]:
                raise DomainError(404, "INCIDENT_NOT_FOUND", "任务不存在。")
            if body.strategy_id != "fixed":
                raise DomainError(503, "STRATEGY_UNAVAILABLE", "P1 仅提供固定流程演示。")
            # Bounded local queue; no model calls or fee reservations in P1.
            count = db.execute(
                "SELECT count(*) FROM runs WHERE json_extract(body,'$.status') "
                "IN ('queued','running','cancel_requested')"
            ).fetchone()[0]
            if count >= 20:
                raise DomainError(429, "QUEUE_FULL", "运行队列已满，请稍后重试。", True)
            ordinal = db.execute("SELECT COALESCE(MAX(ordinal),0)+1 FROM runs").fetchone()[0]
            run: Json = {
                "run_id": uid("run"),
                **payload,
                "status": "queued",
                "created_at": now(),
                "updated_at": now(),
                "version": 1,
                "trace_id": trace_id,
                "usage": dict.fromkeys(
                    [
                        "llm_calls",
                        "probe_count",
                        "input_tokens",
                        "output_tokens",
                        "settled_micro_cny",
                        "reserved_micro_cny",
                        "uncertain_micro_cny",
                        "probe_cost_units",
                    ],
                    0,
                ),
                "hypotheses": [],
                "last_event_seq": 0,
                "stop_reason": "none",
                "model": "FakeLLM-v1",
                "config_hash": digest,
                "dataset_version": INCIDENT["dataset_version"],
            }
            db.execute(
                "INSERT INTO runs VALUES(?,?,?,?,?,NULL,NULL,?)",
                (run["run_id"], json.dumps(run), digest, key, parent_span, ordinal),
            )
            self._event(db, run, "run_created", "接收任务，等待本地 worker。")
            return run

    def get(self, run_id: str) -> Json:
        with self.connection() as db:
            return self._get(db, run_id)

    def list(self, cursor: str, limit: int) -> Json:
        if cursor and (not cursor.isascii() or not cursor.isdigit() or len(cursor) > 18):
            raise DomainError(422, "INVALID_CURSOR", "分页游标无效。")
        with self.connection() as db:
            rows = db.execute(
                "SELECT ordinal,body FROM runs WHERE ordinal<? ORDER BY ordinal DESC LIMIT ?",
                (int(cursor) if cursor else 2**63 - 1, limit + 1),
            ).fetchall()
        return {
            "items": [json.loads(row["body"]) for row in rows[:limit]],
            "next_cursor": str(rows[limit - 1]["ordinal"]) if len(rows) > limit else "",
        }

    def page(self, table: str, run_id: str, after: int, limit: int) -> Json:
        assert table in {"events", "evidence"}
        with self.connection() as db:
            self._get(db, run_id)
            rows = db.execute(
                f"SELECT body,seq FROM {table} WHERE run_id=? AND seq>? ORDER BY seq LIMIT ?",
                (run_id, after, limit + 1),
            ).fetchall()
        items = rows[:limit]
        return {
            "items": [json.loads(row["body"]) for row in items],
            "next_cursor": items[-1]["seq"] if items else after,
            "has_more": len(rows) > limit,
        }

    def cancel(self, run_id: str) -> Json:
        with self.transaction() as db:
            run = self._get(db, run_id)
            if run["status"] in TERMINAL or run["status"] == "cancel_requested":
                return run
            queued = run["status"] == "queued"
            run["status"] = "cancelled" if queued else "cancel_requested"
            if queued:
                run["stop_reason"] = "cancelled"
            self._event(db, run, "cancel_requested", "用户请求取消。")
            if queued:
                self._event(db, run, "run_finished", "排队任务已取消，未调用模型或工具。")
            return run

    def recover(self) -> int:
        with self.transaction() as db:
            rows = db.execute(
                "SELECT id FROM runs WHERE owner IS NOT NULL AND lease_until<?", (time.time(),)
            ).fetchall()
            for row in rows:
                run = self._get(db, row["id"])
                if run["status"] not in TERMINAL:
                    run.update(status="failed", stop_reason="worker_lost")
                    self._event(db, run, "run_finished", "worker 租约失效；不会重放任务。")
                db.execute("UPDATE runs SET owner=NULL,lease_until=NULL WHERE id=?", (row["id"],))
            return len(rows)

    def claim(self, owner: str) -> tuple[Json, str] | None:
        with self.transaction() as db:
            # Serialize a single active worker across processes.
            if db.execute("SELECT 1 FROM runs WHERE owner IS NOT NULL LIMIT 1").fetchone():
                return None
            row = db.execute(
                "SELECT id,parent_span FROM runs "
                "WHERE json_extract(body,'$.status')='queued' ORDER BY ordinal LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            run = self._get(db, row["id"])
            run["status"] = "running"
            db.execute(
                "UPDATE runs SET owner=?,lease_until=? WHERE id=?",
                (owner, time.time() + LEASE_SECONDS, row["id"]),
            )
            with self.telemetry.span(
                "worker.claim",
                parent=remote_context(run["trace_id"], row["parent_span"]),
                run_id=run["run_id"],
            ):
                self._event(db, run, "run_started", "worker 已领取任务。")
            return run, row["parent_span"]

    def heartbeat(self, run_id: str, owner: str) -> bool:
        with self.connection() as db:
            result = db.execute(
                "UPDATE runs SET lease_until=? WHERE id=? AND owner=? AND lease_until>=?",
                (time.time() + LEASE_SECONDS, run_id, owner, time.time()),
            )
            db.commit()
            return result.rowcount == 1

    def advance(
        self,
        run_id: str,
        owner: str,
        kind: str,
        message: str,
        *,
        updates: Json | None = None,
        evidence: Json | None = None,
    ) -> Json:
        with self.transaction() as db:
            row = db.execute("SELECT owner,lease_until FROM runs WHERE id=?", (run_id,)).fetchone()
            run = self._get(db, run_id)
            if row["owner"] != owner or (row["lease_until"] or 0) < time.time():
                raise DomainError(409, "LEASE_LOST", "worker 租约失效。")
            if run["status"] in TERMINAL:
                return run
            if run["status"] == "cancel_requested":
                updates = {"status": "cancelled", "stop_reason": "cancelled"}
                kind, message, evidence = "run_finished", "运行已取消，未开始新的探测。", None
            run.update(updates or {})
            if evidence:
                evidence["seq"] = db.execute(
                    "SELECT COALESCE(MAX(seq),0)+1 FROM evidence WHERE run_id=?", (run_id,)
                ).fetchone()[0]
                db.execute(
                    "INSERT INTO evidence VALUES(?,?,?)",
                    (run_id, evidence["seq"], json.dumps(evidence)),
                )
            self._event(db, run, kind, message, [evidence["evidence_id"]] if evidence else [])
            if run["status"] in TERMINAL:
                db.execute("UPDATE runs SET owner=NULL,lease_until=NULL WHERE id=?", (run_id,))
            return run

    def report(self, run_id: str) -> Json:
        run = self.get(run_id)
        if run["status"] != "completed":
            raise DomainError(409, "REPORT_NOT_READY", "仅流程完成后提供报告。")
        evidence = self.page("evidence", run_id, 0, 100)["items"]
        return {
            "run_id": run_id,
            "conclusion": "unresolved",
            "component": "",
            "fault_type": "",
            "summary": "模拟流程已完成。当前证据不能用于真实根因判断。",
            "evidence_ids": [e["evidence_id"] for e in evidence],
            "alternatives": [h["fault_type"] for h in run["hypotheses"]],
            "limitations": ["FakeLLM 与探测结果均为合成数据。", "竞争假设与成本策略尚未实现。"],
            "stop_reason": run["stop_reason"],
            "usage": run["usage"],
        }
