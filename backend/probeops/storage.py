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

from .config import Settings
from .models import INCIDENT, TERMINAL, CreateRun, DomainError
from .observations import PROBES, SnapshotCatalog
from .reasoning import POLICY_VERSION
from .telemetry import Telemetry, now, remote_context, span_id

Json = dict[str, Any]
LEASE_SECONDS = 20


def uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class Store:
    def __init__(self, path: Path, telemetry: Telemetry, config: Settings | None = None):
        self.path, self.telemetry = path, telemetry
        self.config = config or Settings(_env_file=None)  # type: ignore[call-arg]
        self.catalog = SnapshotCatalog(self.config.probeops_snapshot_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > 2:
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
                CREATE TABLE IF NOT EXISTS run_context (
                    run_id TEXT PRIMARY KEY REFERENCES runs(id), body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS charges (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
                    state TEXT NOT NULL, amount INTEGER NOT NULL CHECK(amount>=0),
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS charge_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, charge_id TEXT NOT NULL,
                    state TEXT NOT NULL, amount INTEGER NOT NULL, timestamp TEXT NOT NULL);
                PRAGMA user_version=2;
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
        decision: Json | None = None,
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
        if decision is not None:
            event["decision"] = decision
        if kind == "hypotheses_updated":
            event["hypotheses"] = run["hypotheses"]
        db.execute(
            "INSERT INTO events VALUES(?,?,?)", (run["run_id"], event["seq"], json.dumps(event))
        )
        db.execute("UPDATE runs SET body=? WHERE id=?", (json.dumps(run), run["run_id"]))

    def create(
        self, body: CreateRun, key: str, trace_id: str, parent_span: str, *, seed: int = 42
    ) -> Json:
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
            incident = self.catalog.incident(body.incident_id)
            demo = body.incident_id == INCIDENT["incident_id"]
            if demo and body.strategy_id != "fixed":
                raise DomainError(503, "STRATEGY_UNAVAILABLE", "历史演示快照仅用于固定流程。")
            mode = "fake" if demo else self.config.llm_mode
            if mode == "bailian" and not self.config.bailian_api.get_secret_value():
                raise DomainError(503, "PROVIDER_UNAVAILABLE", "百炼服务端密钥尚未配置。")
            frozen = {
                "mode": mode,
                "policy_version": POLICY_VERSION,
                "prompt_version": "proposal-v2",
                "seed": seed,
                "model": self.config.bailian_model if mode == "bailian" else "FakeLLM-v2",
                "snapshot": None if demo else self.catalog.load(body.incident_id),
                "tools": [p.model_dump() for p in PROBES],
                "costs": {p.probe_id: p.cost for p in PROBES},
                "price_micro_cny_per_million": {"input": 800000, "output": 2000000},
            }
            cost_path = self.config.probeops_snapshot_dir.parent / "costs.json"
            if cost_path.is_file():
                import math

                calibration = json.loads(cost_path.read_text())
                costs = calibration["costs"]
                if set(costs) != {p.probe_id for p in PROBES} or any(
                    not isinstance(c, (int, float)) or not math.isfinite(c) or c < 0.1
                    for c in costs.values()
                ):
                    raise DomainError(503, "CALIBRATION_INVALID", "成本标定无效。")
                frozen["costs"] = costs
                frozen["calibration"] = calibration
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
                "model": "FakeLLM-v1" if demo else frozen["model"],
                "config_hash": hashlib.sha256(
                    json.dumps(frozen, sort_keys=True).encode()
                ).hexdigest(),
                "dataset_version": incident["dataset_version"],
            }
            db.execute(
                "INSERT INTO runs VALUES(?,?,?,?,?,NULL,NULL,?)",
                (run["run_id"], json.dumps(run), digest, key, parent_span, ordinal),
            )
            db.execute("INSERT INTO run_context VALUES(?,?)", (run["run_id"], json.dumps(frozen)))
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
                    self._uncertain(db, run)
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
        decision: Json | None = None,
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
            self._event(
                db, run, kind, message, [evidence["evidence_id"]] if evidence else [], decision
            )
            if run["status"] in TERMINAL:
                self._uncertain(db, run)
                db.execute("UPDATE runs SET body=? WHERE id=?", (json.dumps(run), run_id))
                db.execute("UPDATE runs SET owner=NULL,lease_until=NULL WHERE id=?", (run_id,))
            return run

    def report(self, run_id: str) -> Json:
        run = self.get(run_id)
        if run["status"] != "completed":
            raise DomainError(409, "REPORT_NOT_READY", "仅流程完成后提供报告。")
        evidence = self.page("evidence", run_id, 0, 100)["items"]
        winner = next((h for h in run["hypotheses"] if h["status"] == "supported"), None)
        located = run["stop_reason"] == "evidence_sufficient" and winner is not None
        legacy = run["model"] == "FakeLLM-v1"
        return {
            "run_id": run_id,
            "conclusion": "located" if located else "unresolved",
            "component": winner["component"] if located and winner else "",
            "fault_type": winner["fault_type"] if located and winner else "",
            "summary": "候选满足两类观测通道支持与分差条件。"
            if located and winner
            else "证据不足以唯一定位；保留竞争解释。",
            "evidence_ids": winner["evidence_ids"]
            if located and winner
            else [e["evidence_id"] for e in evidence],
            "alternatives": [
                h["fault_type"] for h in run["hypotheses"] if not located or h != winner
            ],
            "limitations": (
                ["历史合成快照，不支持真实诊断。"]
                if legacy
                else [
                    "仅针对冻结观测，支持分数不是概率；相关观测不证明因果。",
                    "候选集可能遗漏真实原因；本地受控环境不能代表生产系统。",
                ]
            )
            + (
                ["使用规则 FakeLLM，结果仅验证程序行为。"]
                if run["model"].startswith("Fake")
                else []
            ),
            "stop_reason": run["stop_reason"],
            "usage": run["usage"],
        }

    def frozen(self, run_id: str) -> Json:
        with self.connection() as db:
            row = db.execute("SELECT body FROM run_context WHERE run_id=?", (run_id,)).fetchone()
        if not row:
            return {"mode": "fake", "snapshot": None, "seed": 42}
        return json.loads(row[0])  # type: ignore[no-any-return]

    def budget(self) -> Json:
        with self.connection() as db:
            sums = dict(
                db.execute("SELECT state,SUM(amount) FROM charges GROUP BY state").fetchall()
            )
        cap = min(450000000, self.config.probeops_spend_cap_micro_cny)
        return {
            "currency": "CNY",
            "cap_micro_cny": 500000000,
            "admission_cap_micro_cny": cap,
            **{f"{s}_micro_cny": sums.get(s, 0) for s in ("settled", "reserved", "uncertain")},
            "available_micro_cny": max(0, cap - sum(sums.values())),
        }

    def reserve(self, run_id: str, owner: str, amount: int) -> str:
        if amount < 0:
            raise ValueError("Invalid reservation")
        with self.transaction() as db:
            run = self._get(db, run_id)
            row = db.execute("SELECT owner,lease_until FROM runs WHERE id=?", (run_id,)).fetchone()
            if run["status"] != "running" or row[0] != owner or row[1] < time.time():
                raise DomainError(409, "RUN_STOPPED", "运行已停止或租约失效。")
            usage = run["usage"]
            if usage["llm_calls"] >= run["limits"]["max_llm_calls"]:
                raise DomainError(409, "CALL_LIMIT", "达到模型尝试上限。")
            total = db.execute("SELECT COALESCE(SUM(amount),0) FROM charges").fetchone()[0]
            used = sum(usage[f"{s}_micro_cny"] for s in ("settled", "reserved", "uncertain"))
            if (
                total + amount > min(450000000, self.config.probeops_spend_cap_micro_cny)
                or used + amount > run["limits"]["max_cost_micro_cny"]
            ):
                raise DomainError(409, "BUDGET_EXHAUSTED", "剩余预算不足以预留本次请求。")
            charge_id = uid("charge")
            db.execute(
                "INSERT INTO charges(id,run_id,state,amount) VALUES(?,?,'reserved',?)",
                (charge_id, run_id, amount),
            )
            db.execute(
                "INSERT INTO charge_events(charge_id,state,amount,timestamp) "
                "VALUES(?,'reserved',?,?)",
                (charge_id, amount, now()),
            )
            usage["llm_calls"] += 1
            usage["reserved_micro_cny"] += amount
            self._event(db, run, "warning", "模型调用已预留费用并计入尝试上限。")
            return charge_id

    def settle(
        self, charge_id: str, amount: int | None, input_tokens: int = 0, output_tokens: int = 0
    ) -> None:
        with self.transaction() as db:
            charge = db.execute("SELECT * FROM charges WHERE id=?", (charge_id,)).fetchone()
            if not charge or charge["state"] != "reserved":
                return
            run = self._get(db, charge["run_id"])
            state, final = (
                ("uncertain", charge["amount"]) if amount is None else ("settled", amount)
            )
            if final < 0:
                raise ValueError("Invalid settlement")
            db.execute(
                "UPDATE charges SET state=?,amount=?,input_tokens=?,output_tokens=? WHERE id=?",
                (state, final, input_tokens, output_tokens, charge_id),
            )
            db.execute(
                "INSERT INTO charge_events(charge_id,state,amount,timestamp) VALUES(?,?,?,?)",
                (charge_id, state, final, now()),
            )
            usage = run["usage"]
            usage["reserved_micro_cny"] -= charge["amount"]
            usage[f"{state}_micro_cny"] += final
            usage["input_tokens"] += input_tokens
            usage["output_tokens"] += output_tokens
            self._event(
                db,
                run,
                "llm_finished",
                "模型请求费用已结算。" if amount is not None else "请求计费未知，保留最坏费用。",
            )

    def _uncertain(self, db: sqlite3.Connection, run: Json) -> None:
        for row in db.execute(
            "SELECT id,amount FROM charges WHERE run_id=? AND state='reserved'", (run["run_id"],)
        ).fetchall():
            db.execute("UPDATE charges SET state='uncertain' WHERE id=?", (row["id"],))
            db.execute(
                "INSERT INTO charge_events(charge_id,state,amount,timestamp) "
                "VALUES(?,'uncertain',?,?)",
                (row["id"], row["amount"], now()),
            )
            run["usage"]["reserved_micro_cny"] -= row["amount"]
            run["usage"]["uncertain_micro_cny"] += row["amount"]

    def reconcile(self, charge_id: str, actual: int, bill_reference: str) -> None:
        if actual < 0 or not bill_reference or len(bill_reference) > 120:
            raise ValueError("Invalid reconciliation")
        with self.transaction() as db:
            row = db.execute("SELECT * FROM charges WHERE id=?", (charge_id,)).fetchone()
            if not row or row["state"] != "uncertain":
                raise DomainError(409, "CHARGE_NOT_UNCERTAIN", "仅未确认费用允许对账。")
            run = self._get(db, row["run_id"])
            db.execute(
                "UPDATE charges SET state='settled',amount=? WHERE id=?", (actual, charge_id)
            )
            # Keep reference hash only. Never overwrite reservation/uncertainty history.
            state = "reconciled:" + hashlib.sha256(bill_reference.encode()).hexdigest()
            db.execute(
                "INSERT INTO charge_events(charge_id,state,amount,timestamp) VALUES(?,?,?,?)",
                (charge_id, state, actual, now()),
            )
            run["usage"]["uncertain_micro_cny"] -= row["amount"]
            run["usage"]["settled_micro_cny"] += actual
            self._event(db, run, "warning", "依据账单完成费用对账；原始流水保留。")
