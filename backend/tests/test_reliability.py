import asyncio
import copy
import time
from pathlib import Path

import httpx
import pytest
from probeops.config import Settings
from probeops.models import CreateRun
from probeops.observations import PROBE_MAP, Gateway, SnapshotCatalog
from probeops.prompts import SERVICE_SEMANTICS, SYSTEM_V2
from probeops.provider import propose
from probeops.reasoning import fake_proposal, falsifiable_probes, hypotheses, select, update
from probeops.storage import Store
from probeops.telemetry import Telemetry
from probeops.worker import execute
from pydantic import SecretStr

POOL = "inc_1875fd2c391740aa"


def test_complete_check_detects_a_late_counterexample():
    hs = hypotheses(fake_proposal(list(PROBE_MAP)))[:1]
    hs[0]["predictions"][-1]["expected"] = "low"  # False prediction about normal config.
    gateway = Gateway(SnapshotCatalog(Path("data/snapshots")).load(POOL))
    first = [gateway.observe(pid)[:2] for pid in ("pool_events", "pool_wait")]
    assert update(copy.deepcopy(hs), first)[0]["status"] == "supported"
    assert update(copy.deepcopy(hs), first, require_complete=True)[0]["status"] == "active"
    rest = [
        gateway.observe(pid)[:2] for pid in PROBE_MAP if pid not in {"pool_events", "pool_wait"}
    ]
    assert update(hs, [*first, *rest], require_complete=True)[0]["status"] == "contradicted"


def test_missing_expected_observation_cannot_complete_verification():
    snapshot = SnapshotCatalog(Path("data/snapshots")).load(POOL)
    snapshot["metrics"]["task-worker"] = {}
    gateway = Gateway(snapshot)
    observed = [gateway.observe(pid)[:2] for pid in PROBE_MAP]
    hs = hypotheses(fake_proposal(list(PROBE_MAP)))[:1]
    assert update(hs, observed, require_complete=True)[0]["status"] == "active"


def test_closing_selection_skips_unknown_predictions():
    snapshot = SnapshotCatalog(Path("data/snapshots")).load(POOL)
    gateway = Gateway(snapshot)
    observed = [gateway.observe(pid)[:2] for pid in ("pool_events", "pool_wait")]
    hs = update(hypotheses(fake_proposal(list(PROBE_MAP)))[:1], observed, require_complete=True)
    choice = select(
        "competitive_cost",
        hs,
        ["api_latency", "cache_events"],
        42,
        costs=dict.fromkeys(PROBE_MAP, 0.1),
        observations=observed,
        require_complete=True,
    )
    assert choice["probe_id"] == "cache_events"
    assert "完整预测核对" in choice["reason"]


def test_unknown_predictions_still_allow_refuting_a_candidate():
    hs = hypotheses(fake_proposal(list(PROBE_MAP)))[:2]
    for h in hs:
        for p in h["predictions"]:
            if p["expected"] == "normal":
                p["expected"] = "unknown"
    remaining = ["pool_wait", "queue_depth"]
    assert falsifiable_probes(hs, remaining) == {"pool_wait": 1, "queue_depth": 1}
    selected = select("competitive_cost", hs, remaining, 42, allow_falsification=True)
    assert selected["disagreement_pairs"] == 0 and "unknown补查" in selected["reason"]
    gateway = Gateway(SnapshotCatalog(Path("data/snapshots")).load(POOL))
    observed = [gateway.observe("queue_depth")[:2]]
    update(hs, observed, require_complete=True)
    assert hs[1]["status"] == "contradicted" and hs[0]["score"] == 0
    assert falsifiable_probes(hs, remaining) == {}


def test_identical_or_all_unknown_candidates_do_not_get_fallback():
    hs = hypotheses(fake_proposal(list(PROBE_MAP)))[:2]
    hs[1]["predictions"] = copy.deepcopy(hs[0]["predictions"])
    assert falsifiable_probes(hs, list(PROBE_MAP)) == {}
    for h in hs:
        for p in h["predictions"]:
            p["expected"] = "unknown"
    assert falsifiable_probes(hs, list(PROBE_MAP)) == {}


@pytest.fixture
def store(tmp_path):
    telemetry = Telemetry(tmp_path / "logs", "test")
    cfg = Settings(_env_file=None, probeops_db_path=tmp_path / "db")
    yield Store(cfg.probeops_db_path, telemetry, cfg)
    telemetry.close()


def create(store, max_steps=12):
    return store.create(
        CreateRun.model_validate(
            {
                "incident_id": POOL,
                "strategy_id": "competitive_cost",
                "limits": {
                    "max_steps": max_steps,
                    "max_llm_calls": 16,
                    "max_wall_seconds": 180,
                    "max_cost_micro_cny": 250000,
                },
            }
        ),
        "reliability-test",
        "a" * 32,
        "b" * 16,
    )


@pytest.mark.parametrize("version", ["proposal-v2", "proposal-v3"])
def test_provider_uses_frozen_prompt_even_after_version_changes(store, monkeypatch, version):
    monkeypatch.setattr("probeops.storage.PROMPT_VERSION", version)
    store.config.llm_mode = "bailian"
    store.config.bailian_api = SecretStr("private-test")
    run = create(store)
    store.claim("owner")
    messages = []

    async def respond(request):
        import json

        messages.append(json.loads(request.content)["messages"][0]["content"])
        return httpx.Response(
            200,
            json={
                "model": store.config.bailian_model,
                "usage": {"prompt_tokens": 100, "completion_tokens": 200},
                "choices": [
                    {"message": {"content": fake_proposal(list(PROBE_MAP)).model_dump_json()}}
                ],
            },
        )

    asyncio.run(
        propose(
            store,
            run["run_id"],
            "owner",
            {},
            list(PROBE_MAP),
            time.monotonic() + 10,
            httpx.MockTransport(respond),
        )
    )
    assert messages == [SYSTEM_V2 + (SERVICE_SEMANTICS if version == "proposal-v3" else "")]


def test_replacement_verified_on_last_step_finishes_immediately(store, monkeypatch):
    good = fake_proposal(list(PROBE_MAP))
    good.candidates = good.candidates[:1]
    bad = good.model_copy(deep=True)
    bad.candidates[0].predictions[-1].expected = "low"
    calls = []

    async def proposals(*args, **kwargs):
        calls.append(1)
        return bad if len(calls) == 1 else good

    monkeypatch.setattr("probeops.engine.propose", proposals)
    run = create(store, max_steps=8)
    asyncio.run(execute(store, "owner", 0))
    final = store.get(run["run_id"])
    assert len(calls) == 2
    assert final["usage"]["probe_count"] == 8
    assert final["stop_reason"] == "evidence_sufficient"
    assert store.report(run["run_id"])["conclusion"] == "located"


@pytest.mark.parametrize(
    ("version", "conclusion"),
    [("competitive-v4", "unresolved"), ("competitive-v5", "located")],
)
def test_frozen_v5_explores_unknowns_without_changing_v4(store, monkeypatch, version, conclusion):
    monkeypatch.setattr("probeops.storage.POLICY_VERSION", version)
    proposal = fake_proposal(list(PROBE_MAP))
    proposal.candidates = proposal.candidates[:2]
    for h in proposal.candidates:
        for p in h.predictions:
            if p.expected == "normal":
                p.expected = "unknown"

    async def propose_partial(*args, **kwargs):
        return proposal

    monkeypatch.setattr("probeops.engine.propose", propose_partial)
    run = create(store)
    asyncio.run(execute(store, "owner", 0))
    assert store.report(run["run_id"])["conclusion"] == conclusion
    events = store.page("events", run["run_id"], 0, 100)["items"]
    used_fallback = any("unknown补查" in e.get("decision", {}).get("reason", "") for e in events)
    assert used_fallback == (version == "competitive-v5")
