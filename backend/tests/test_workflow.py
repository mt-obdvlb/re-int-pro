import asyncio
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft7Validator, FormatChecker
from probeops.agent import FakeMetrics
from probeops.api import create_app
from probeops.config import ROOT, Settings
from probeops.models import CreateRun, DomainError
from probeops.storage import Store
from probeops.telemetry import context
from probeops.worker import execute

SPEC = json.loads((ROOT / "docs/api/openapi.json").read_text())
BODY = {
    "incident_id": "demo_latency",
    "strategy_id": "fixed",
    "limits": {
        "max_steps": 12,
        "max_llm_calls": 16,
        "max_wall_seconds": 180,
        "max_cost_micro_cny": 250000,
    },
}


@pytest.fixture
def client(tmp_path):
    cfg = Settings(
        _env_file=None,
        probeops_db_path=tmp_path / "test.db",
        probeops_telemetry_dir=tmp_path / "telemetry",
        fake_delay_seconds=0,
    )
    with TestClient(create_app(cfg)) as client:
        yield client


def create(client, key="test-key-0001", body=None):
    response = client.post("/api/v1/runs", json=body or BODY, headers={"Idempotency-Key": key})
    assert response.status_code == 202, response.text
    return response.json()


def validate(response, schema):
    value = response.json()
    root = {"$ref": f"#/components/schemas/{schema}", "components": SPEC["components"]}
    Draft7Validator(root, format_checker=FormatChecker()).validate(value)
    assert response.headers["X-Request-ID"]
    return value


def test_end_to_end_contract_and_persistence(client):
    validate(client.get("/healthz"), "Health")
    validate(client.get("/api/v1/incidents"), "IncidentList")
    validate(client.get("/api/v1/incidents/demo_latency"), "Incident")
    assert (
        validate(client.get("/api/v1/strategies"), "StrategyList")["items"][0]["strategy_id"]
        == "fixed"
    )
    validate(client.get("/api/v1/budget"), "Budget")
    run = create(client)
    store = client.app.state.store

    async def verify_context_cleanup():
        before = context.get()
        assert await execute(store, "test-worker", 0)
        assert context.get() == before

    asyncio.run(verify_context_cleanup())
    actual = validate(client.get(f"/api/v1/runs/{run['run_id']}"), "Run")
    assert actual["status"] == "completed" and actual["usage"]["settled_micro_cny"] == 0
    assert actual["usage"]["probe_count"] == 1 and actual["usage"]["llm_calls"] == 1
    events = validate(client.get(f"/api/v1/runs/{run['run_id']}/events"), "EventPage")["items"]
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    evidence = validate(client.get(f"/api/v1/runs/{run['run_id']}/evidence"), "EvidencePage")[
        "items"
    ]
    report = validate(client.get(f"/api/v1/runs/{run['run_id']}/report"), "Report")
    assert report["conclusion"] == "unresolved"
    assert report["evidence_ids"] == [evidence[0]["evidence_id"]]
    validate(client.get("/api/v1/runs"), "RunPage")
    assert Store(store.path, store.telemetry).get(run["run_id"]) == actual
    # A terminal cancellation is idempotent and cannot replace its state.
    response = client.post(f"/api/v1/runs/{run['run_id']}/cancel", json={"reason": "done"})
    assert validate(response, "Run")["status"] == "completed"


def test_atomic_idempotency_and_claim(client):
    store = client.app.state.store
    body = CreateRun.model_validate(BODY)
    with ThreadPoolExecutor(max_workers=4) as pool:
        runs = list(
            pool.map(lambda _: store.create(body, "concurrent-key", "a" * 32, "b" * 16), range(4))
        )
    assert len({r["run_id"] for r in runs}) == 1
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(store.claim, ["worker-a", "worker-b"]))
    assert sum(c is not None for c in claims) == 1
    conflict = client.post(
        "/api/v1/runs",
        json={**BODY, "limits": {**BODY["limits"], "max_steps": 1}},
        headers={"Idempotency-Key": "concurrent-key"},
    )
    assert conflict.status_code == 409
    validate(conflict, "Error")


def test_cancel_queued_and_running(client):
    queued = create(client)
    response = client.post(f"/api/v1/runs/{queued['run_id']}/cancel", json={"reason": "stop"})
    assert response.json()["status"] == "cancelled"
    run = create(client, "test-key-0002")
    store = client.app.state.store

    async def race():
        task = asyncio.create_task(execute(store, "worker", 0.2))
        await asyncio.sleep(0.05)
        store.cancel(run["run_id"])
        await task

    asyncio.run(race())
    actual = store.get(run["run_id"])
    assert actual["status"] == "cancelled"
    assert actual["usage"]["probe_count"] == 0
    assert client.get(f"/api/v1/runs/{run['run_id']}/report").status_code == 409


def test_deadline_and_lease_recovery(client):
    run = create(client, body={**BODY, "limits": {**BODY["limits"], "max_wall_seconds": 1}})
    store = client.app.state.store
    asyncio.run(execute(store, "worker", 0.6))
    assert store.get(run["run_id"])["stop_reason"] == "deadline"
    lost = create(client, "worker-lost-key")
    store.claim("lost")
    with store.connection() as db:
        db.execute("UPDATE runs SET lease_until=? WHERE id=?", (time.time() - 1, lost["run_id"]))
        db.commit()
    assert store.recover() == 1
    assert store.get(lost["run_id"])["stop_reason"] == "worker_lost"
    assert store.claim("new") is None
    with pytest.raises(DomainError):
        store.advance(lost["run_id"], "lost", "probe_finished", "late")


def test_pagination_invalid_parameters_and_secret_boundary(client):
    for n in range(3):
        create(client, f"pagination-{n}")
    first = client.get("/api/v1/runs?limit=2").json()
    second = client.get(f"/api/v1/runs?limit=2&cursor={first['next_cursor']}").json()
    assert len(first["items"]) == 2 and len(second["items"]) == 1
    assert not ({r["run_id"] for r in first["items"]} & {r["run_id"] for r in second["items"]})
    for path in [
        "/api/v1/runs?cursor=-1",
        "/api/v1/runs?limit=0",
        "/api/v1/runs/missing/events?after_seq=-1",
    ]:
        result = client.get(path)
        assert result.status_code == 422
        validate(result, "Error")
    secret = "sentinel-secret-never-export"
    invalid = client.post(
        "/api/v1/runs", json={**BODY, "secret": secret}, headers={"Idempotency-Key": "invalid-key"}
    )
    assert invalid.status_code == 422 and secret not in invalid.text
    unavailable = client.post(
        "/api/v1/runs",
        json={**BODY, "strategy_id": "competitive_cost"},
        headers={"Idempotency-Key": "unsupported-key"},
    )
    assert unavailable.status_code == 503
    validate(unavailable, "Error")


def test_trace_causality_failure_and_redaction(client):
    run = create(client)
    store = client.app.state.store
    asyncio.run(execute(store, "worker", 0))
    telemetry = store.telemetry
    secret = "sentinel-secret-never-export"
    try:
        with telemetry.span("test.failure"):
            raise RuntimeError(secret)
    except RuntimeError:
        logging.getLogger("httpx").exception(secret)
    telemetry.provider.force_flush()
    telemetry.queue.join()
    files = list(telemetry.exporter.handler.baseFilename.rsplit("/", 1)[:1])
    from pathlib import Path

    directory = Path(files[0])
    text = "".join(p.read_text() for p in directory.glob("*.jsonl"))
    assert secret not in text
    spans = [json.loads(line) for line in (directory / "api-spans.jsonl").read_text().splitlines()]
    relevant = [span for span in spans if span["trace_id"] == run["trace_id"]]
    by_name = {span["name"]: span for span in relevant}
    assert by_name["diagnosis.run"]["parent_span_id"] == by_name["run.accept"]["span_id"]
    assert by_name["llm.request"]["parent_span_id"] == by_name["agent.step"]["span_id"]
    assert by_name["tool.query_metrics"]["parent_span_id"] == by_name["agent.step"]["span_id"]
    assert any(span["name"] == "test.failure" and span["status"] == "ERROR" for span in spans)


def test_tool_failure_never_emits_raw_exception(client, monkeypatch):
    class BrokenProbe(FakeMetrics):
        async def observe(self):
            raise RuntimeError("secret-in-provider-error")

    monkeypatch.setattr("probeops.agent.FakeMetrics", BrokenProbe)
    run = create(client)
    store = client.app.state.store
    asyncio.run(execute(store, "worker", 0))
    assert store.get(run["run_id"])["status"] == "failed"
    assert store.get(run["run_id"])["stop_reason"] == "dependency_error"
    assert store.page("evidence", run["run_id"], 0, 100)["items"] == []


def test_runtime_route_coverage(client):
    routes = {
        (route.path, method.lower())
        for route in client.app.routes
        for method in getattr(route, "methods", [])
        if route.path != "/openapi.json"
    }
    expected = {
        (path, method)
        for path, definition in SPEC["paths"].items()
        for method in definition
        if method in {"get", "post"}
    }
    assert routes == expected


def test_export_failure_does_not_break_workflow(client, monkeypatch):
    telemetry = client.app.state.telemetry

    def broken_write(_record):
        raise OSError("fake-disk-failure-secret")

    monkeypatch.setattr(telemetry.exporter.handler, "emit", broken_write)
    run = create(client)
    asyncio.run(execute(client.app.state.store, "worker", 0))
    telemetry.provider.force_flush()
    assert telemetry.exporter.failed_exports >= 1
    assert client.app.state.store.get(run["run_id"])["status"] == "completed"
