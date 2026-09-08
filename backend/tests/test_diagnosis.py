import asyncio
import json
import time
from pathlib import Path

import httpx
import pytest
from probeops.config import Settings
from probeops.models import CreateRun, DomainError
from probeops.observations import PROBE_MAP, Gateway, SnapshotCatalog
from probeops.provider import MAX_RESERVATION, propose
from probeops.reasoning import fake_proposal, hypotheses, select, update
from probeops.storage import Store
from probeops.telemetry import Telemetry
from probeops.worker import execute

SNAPSHOTS = Path("data/snapshots").resolve()
POOL = "inc_1875fd2c391740aa"
NORMAL = "inc_233acaee38074eff"
UNKNOWN = "inc_d357a43615e543b8"


@pytest.fixture
def store(tmp_path):
    telemetry = Telemetry(tmp_path / "logs", "test")
    cfg = Settings(
        _env_file=None, probeops_db_path=tmp_path / "db", probeops_snapshot_dir=SNAPSHOTS
    )
    yield Store(cfg.probeops_db_path, telemetry, cfg)
    telemetry.close()


def create(store, incident=POOL, strategy="competitive_cost", **limits):
    body = CreateRun.model_validate(
        {
            "incident_id": incident,
            "strategy_id": strategy,
            "limits": {
                "max_steps": 12,
                "max_llm_calls": 16,
                "max_wall_seconds": 180,
                "max_cost_micro_cny": 250000,
                **limits,
            },
        }
    )
    from uuid import uuid4

    return store.create(body, uuid4().hex, "a" * 32, "b" * 16)


@pytest.mark.parametrize(
    "strategy", ["fixed", "react", "graph_greedy", "competitive_cost", "no_cost", "random_probe"]
)
def test_real_snapshot_all_strategies(store, strategy):
    run = create(store, strategy=strategy)
    assert asyncio.run(execute(store, "test", 0))
    final = store.get(run["run_id"])
    assert final["status"] == "completed"
    assert 0 < final["usage"]["probe_count"] <= 12
    assert final["usage"]["settled_micro_cny"] == 0
    events = store.page("events", run["run_id"], 0, 100)["items"]
    decisions = [e["decision"] for e in events if "decision" in e]
    assert len(decisions) == final["usage"]["probe_count"]
    assert len({d["probe_id"] for d in decisions}) == len(decisions)
    report = store.report(run["run_id"])
    if report["conclusion"] == "located":
        assert (report["component"], report["fault_type"]) == ("database", "pool_exhaustion")
    if strategy == "competitive_cost":
        assert report["conclusion"] == "located"


@pytest.mark.parametrize("incident", [NORMAL, UNKNOWN])
def test_normal_and_missing_do_not_establish_fault(store, incident):
    run = create(store, incident)
    asyncio.run(execute(store, "test", 0))
    assert store.report(run["run_id"])["conclusion"] == "unresolved"


def test_selection_ablation_and_independent_evidence():
    hs = hypotheses(fake_proposal(list(PROBE_MAP)))
    costs = dict.fromkeys(PROBE_MAP, 1.0)
    costs["cache_latency"] = 100.0
    remaining = ["cache_latency", "pool_wait"]
    assert select("competitive_cost", hs, remaining, 42, costs=costs)["probe_id"] == "pool_wait"
    assert select("no_cost", hs, remaining, 42, costs=costs)["probe_id"] == "cache_latency"
    assert select("random_probe", hs, remaining, 42) == select("random_probe", hs, remaining, 42)
    gateway = Gateway(SnapshotCatalog(SNAPSHOTS).load(POOL))
    ev, band, _ = gateway.observe("pool_wait")
    assert all(h["status"] != "supported" for h in update(hs, [(ev, band)]))
    with pytest.raises(DomainError, match="不可重复"):
        gateway.observe("pool_wait")
    with pytest.raises(DomainError, match="白名单"):
        gateway.observe("../../.env")


def test_budget_reservation_cancel_and_recovery(store):
    run = create(store, max_cost_micro_cny=15000)
    store.claim("owner")
    charge = store.reserve(run["run_id"], "owner", MAX_RESERVATION)
    with pytest.raises(DomainError, match="预算"):
        store.reserve(run["run_id"], "owner", MAX_RESERVATION)
    store.settle(charge, 100, 50, 30)
    assert store.budget()["settled_micro_cny"] == 100
    store.settle(charge, 999)  # Idempotent settlement.
    pending = store.reserve(run["run_id"], "owner", MAX_RESERVATION)
    with store.connection() as db:
        db.execute("UPDATE runs SET lease_until=0 WHERE id=?", (run["run_id"],))
        db.commit()
    store.recover()
    final = store.get(run["run_id"])
    assert final["status"] == "failed" and final["stop_reason"] == "worker_lost"
    assert final["usage"]["uncertain_micro_cny"] == MAX_RESERVATION
    assert final["usage"]["reserved_micro_cny"] == 0
    store.settle(pending, 0)  # Recovery cannot silently refund an unknown charge.
    assert store.budget()["uncertain_micro_cny"] == MAX_RESERVATION


@pytest.mark.parametrize("behavior", ["success", "invalid", "timeout", "unauthorized"])
def test_provider_protocol_and_charges(store, behavior):
    store.config.llm_mode = "bailian"
    from pydantic import SecretStr

    store.config.bailian_api = SecretStr("test-secret-not-for-export")
    run = create(store)
    store.claim("owner")
    calls = []

    async def respond(request):
        data = json.loads(request.content)
        calls.append(data)
        assert data["enable_thinking"] is False and data["max_tokens"] == 2000
        if behavior == "timeout":
            raise httpx.ReadTimeout("test-secret-not-for-export")
        if behavior == "unauthorized":
            return httpx.Response(401, json={"error": "test-secret-not-for-export"})
        value = fake_proposal(list(PROBE_MAP)).model_dump_json() if behavior == "success" else "{}"
        return httpx.Response(
            200,
            json={
                "model": store.config.bailian_model,
                "usage": {"prompt_tokens": 100, "completion_tokens": 200},
                "choices": [{"message": {"content": value}}],
            },
        )

    async def run_provider():
        return await propose(
            store,
            run["run_id"],
            "owner",
            {},
            list(PROBE_MAP),
            time.monotonic() + 20,
            httpx.MockTransport(respond),
        )

    if behavior == "success":
        assert len(asyncio.run(run_provider()).candidates) == 4
        assert store.get(run["run_id"])["usage"]["settled_micro_cny"] == 480
    else:
        with pytest.raises(DomainError):
            asyncio.run(run_provider())
    assert len(calls) <= 3
    if behavior == "unauthorized":
        assert len(calls) == 1
    if behavior in {"timeout", "unauthorized"}:
        assert (
            store.get(run["run_id"])["usage"]["uncertain_micro_cny"] == len(calls) * MAX_RESERVATION
        )


def test_snapshot_is_frozen_in_run_and_rejects_tampering(store, tmp_path):
    run = create(store)
    frozen = store.frozen(run["run_id"])
    original = frozen["snapshot"]["content_hash"]
    assert original == SnapshotCatalog(SNAPSHOTS).load(POOL)["content_hash"]
    value = frozen["snapshot"]
    value["metrics"] = {}
    (tmp_path / f"{POOL}.json").write_text(json.dumps(value))
    with pytest.raises(DomainError, match="哈希"):
        SnapshotCatalog(tmp_path).load(POOL)
    assert store.frozen(run["run_id"])["snapshot"]["content_hash"] == original
