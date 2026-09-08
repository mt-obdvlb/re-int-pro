import asyncio
import copy
import importlib.util
import time
from pathlib import Path

import httpx
import pytest
from probeops.config import Settings
from probeops.models import CreateRun, DomainError
from probeops.observations import PROBE_MAP
from probeops.provider import MAX_RESERVATION, propose
from probeops.reasoning import Proposal, fake_proposal
from probeops.storage import Store
from probeops.telemetry import Telemetry
from probeops.worker import execute


@pytest.fixture
def store(tmp_path):
    telemetry = Telemetry(tmp_path / "logs", "test")
    cfg = Settings(_env_file=None, probeops_db_path=tmp_path / "db")
    yield Store(cfg.probeops_db_path, telemetry, cfg)
    telemetry.close()


def create(store, **limits):
    return store.create(
        CreateRun.model_validate(
            {
                "incident_id": "inc_1875fd2c391740aa",
                "strategy_id": "competitive_cost",
                "limits": {
                    "max_steps": 12,
                    "max_llm_calls": 16,
                    "max_wall_seconds": 180,
                    "max_cost_micro_cny": 250000,
                    **limits,
                },
            }
        ),
        "boundary-test",
        "a" * 32,
        "b" * 16,
    )


def test_cross_prediction_matrix_required():
    value = fake_proposal(list(PROBE_MAP)).model_dump()
    value["candidates"][0]["predictions"] = value["candidates"][0]["predictions"][:2]
    with pytest.raises(ValueError):
        Proposal.model_validate(value)


def test_cancel_inflight_preserves_uncertain_fee(store):
    from pydantic import SecretStr

    store.config.llm_mode = "bailian"
    store.config.bailian_api = SecretStr("private-test-key")
    run = create(store)
    store.claim("owner")

    async def scenario():
        entered = asyncio.Event()

        async def respond(request):
            entered.set()
            await asyncio.sleep(10)
            return httpx.Response(200)

        task = asyncio.create_task(
            propose(
                store,
                run["run_id"],
                "owner",
                {},
                list(PROBE_MAP),
                time.monotonic() + 20,
                httpx.MockTransport(respond),
            )
        )
        await entered.wait()
        store.cancel(run["run_id"])
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        store.advance(run["run_id"], "owner", "run_finished", "Cancelled")

    asyncio.run(scenario())
    current = store.get(run["run_id"])
    assert current["status"] == "cancelled"
    assert current["usage"]["uncertain_micro_cny"] == MAX_RESERVATION
    with store.connection() as db:
        charge = db.execute("SELECT id FROM charges").fetchone()[0]
    store.reconcile(charge, 1200, "test-bill-reference")
    assert store.get(run["run_id"])["usage"]["settled_micro_cny"] == 1200
    assert store.get(run["run_id"])["usage"]["uncertain_micro_cny"] == 0
    with pytest.raises(DomainError):
        store.reconcile(charge, 0, "repeat")


def test_total_deadline_interrupts_slow_tool(store, monkeypatch):
    from probeops.observations import Gateway

    def slow(self, pid):
        time.sleep(1.2)
        raise RuntimeError("Should not escape cancelled worker")

    monkeypatch.setattr(Gateway, "observe", slow)
    run = create(store, max_wall_seconds=1)
    asyncio.run(execute(store, "owner", 0))
    assert store.get(run["run_id"])["stop_reason"] == "deadline"
    assert store.get(run["run_id"])["status"] == "completed"
    assert store.get(run["run_id"])["usage"]["probe_count"] == 1
    assert store.get(run["run_id"])["usage"]["probe_cost_units"] > 0


def test_candidate_history_is_immutable(store):
    run = create(store)
    asyncio.run(execute(store, "owner", 0))
    events = store.page("events", run["run_id"], 0, 100)["items"]
    versions = [e["hypotheses"] for e in events if "hypotheses" in e]
    assert len(versions) > 2
    assert all(h["score"] == 0 for h in versions[0])
    assert any(h["score"] > 0 for h in versions[-1])


def test_summary_rejects_incomplete_or_mixed_batches():
    spec = importlib.util.spec_from_file_location("summary", Path("evaluation/summarize.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    one = {
        "model": "FakeLLM-v2",
        "mode": "fake",
        "incident_id": "one",
        "strategy": "fixed",
        "repeat": 0,
        "snapshot_hash": "a",
    }
    two = copy.deepcopy(one)
    two.update(incident_id="two", strategy="react")
    with pytest.raises(ValueError, match="Incomplete"):
        module.summarize([one, two])
