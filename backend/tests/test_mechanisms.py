import asyncio
import copy
import importlib.util
from pathlib import Path

import pytest
from probeops.config import Settings
from probeops.models import CreateRun
from probeops.observations import PROBE_MAP, Gateway, SnapshotCatalog
from probeops.reasoning import fake_proposal, hypotheses, select, update
from probeops.storage import Store
from probeops.telemetry import Telemetry
from probeops.worker import execute

spec = importlib.util.spec_from_file_location("mechanisms", Path("evaluation/mechanisms.py"))
mechanisms = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mechanisms)
CATALOG = SnapshotCatalog(Path("data/snapshots"))
POOL = "inc_1875fd2c391740aa"
COSTS = dict.fromkeys(PROBE_MAP, 0.1)


def test_lone_candidate_seeks_missing_channel_without_granting_support():
    hs = hypotheses(fake_proposal(list(PROBE_MAP)))
    gateway = Gateway(CATALOG.load(POOL))
    e, band, _ = gateway.observe("pool_events")
    observed = [(e, band)]
    update(hs, observed)
    assert sum(h["status"] == "active" for h in hs) == 1
    assert not any(h["status"] == "supported" for h in hs)
    remaining = [p for p in PROBE_MAP if p != "pool_events"]
    old = select("competitive_cost", hs, remaining, 42, costs=COSTS, verification=False)
    new = select("competitive_cost", hs, remaining, 42, costs=COSTS, observations=observed)
    assert old["probe_id"] == "api_latency"  # Same D=0 and cost: irrelevant alphabetical tie.
    assert new["probe_id"] == "pool_wait" and new["disagreement_pairs"] == 0
    assert not any(h["status"] == "supported" for h in hs)  # A prediction is not evidence.
    evidence, actual, _ = gateway.observe(new["probe_id"])
    update(hs, [*observed, (evidence, actual)])
    assert [h["fault_type"] for h in hs if h["status"] == "supported"] == ["pool_exhaustion"]


def test_verification_still_refutes_mismatches():
    hs = hypotheses(fake_proposal(list(PROBE_MAP)))[:1]
    gateway = Gateway(CATALOG.load("inc_233acaee38074eff"))
    observed = [gateway.observe(pid)[:2] for pid in ("pool_events", "pool_wait")]
    assert update(hs, observed)[0]["status"] == "contradicted"


@pytest.mark.parametrize("smoothing", [-1, float("nan"), float("inf")])
def test_bad_smoothing_rejected(smoothing):
    with pytest.raises(ValueError, match="smoothing"):
        select("competitive_cost", [], list(PROBE_MAP), 42, smoothing=smoothing)


def test_unknown_and_identical_predictions_do_not_create_evidence():
    hs = hypotheses(fake_proposal(list(PROBE_MAP)))[:2]
    hs[1]["predictions"] = copy.deepcopy(hs[0]["predictions"])
    for name in ("legacy_cost", "verification_cost"):
        value = mechanisms.replay(CATALOG.load(POOL), hs, COSTS, name)
        assert value["stop"] == "indistinguishable"
        assert value["diagnosis"] is None and value["probe_count"] == 0


@pytest.mark.parametrize(
    ("iid", "fault"),
    [
        (POOL, "pool_exhaustion"),
        ("inc_b87350fa819a4635", "queue_backlog"),
        ("inc_d20660077ea642f1", "cache_latency"),
        ("inc_29f7ec8ec6f74885", "config_error"),
        ("inc_233acaee38074eff", None),
        ("inc_d357a43615e543b8", None),
    ],
)
def test_rules_use_observations_without_model_or_labels(iid, fault, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Rules must not use model proposals or shared scores")

    monkeypatch.setattr(mechanisms, "select", forbidden)
    monkeypatch.setattr(mechanisms, "update", forbidden)
    snapshot = CATALOG.load(iid)
    # These annotations cannot affect diagnosis. Gateway still returns identical bands.
    snapshot["incident"]["incident_id"] = "inc_0000000000000000"
    snapshot["provenance"] = {"fault_type": "misleading-label"}
    value = mechanisms.rule_diagnose(snapshot, COSTS)
    assert (value["diagnosis"]["fault_type"] if value["diagnosis"] else None) == fault
    assert value["probe_count"] <= 5


def test_rules_abstain_on_conflicting_faults():
    snapshot = CATALOG.load(POOL)
    snapshot["metrics"]["cache"]["latency_ms"] = [1000]
    assert mechanisms.rule_diagnose(snapshot, COSTS)["diagnosis"] is None


def test_initial_history_does_not_use_a_later_replacement():
    original = hypotheses(fake_proposal(list(PROBE_MAP)))
    with pytest.raises(ValueError, match="history missing"):
        mechanisms.initial_hypotheses(
            [
                {"kind": "hypotheses_updated", "hypothesis_ids": ["h_0_0"]},
                {"kind": "hypotheses_updated", "hypotheses": original},
            ]
        )
    assert mechanisms.initial_hypotheses([]) is None
    original[0]["score"] = 1
    with pytest.raises(ValueError):
        mechanisms.initial_hypotheses([{"kind": "hypotheses_updated", "hypotheses": original}])


def test_audit_separates_candidate_coverage_and_prediction_accuracy():
    snapshot = CATALOG.load(POOL)
    hs = hypotheses(fake_proposal(list(PROBE_MAP)))
    truth = {"component": "database", "fault_type": "pool_exhaustion"}
    audit = mechanisms.audit_predictions(snapshot, hs, truth)
    assert audit["true_candidate_present"]
    assert audit["available_observations"] == 10
    assert audit["true_candidate_known_predictions"] == 8
    assert audit["true_candidate_matching_predictions"] == 8
    audit = mechanisms.audit_predictions(snapshot, hs[1:], truth)
    assert not audit["true_candidate_present"]
    assert audit["true_candidate_known_predictions"] == 0


def test_replay_uses_original_costs_and_preserves_initial_candidates():
    hs = hypotheses(fake_proposal(list(PROBE_MAP)))
    original = copy.deepcopy(hs)
    costs = {pid: c + 0.3 for pid, c in COSTS.items()}
    replay = mechanisms.replay(CATALOG.load(POOL), hs, costs, "uniform_cost")
    assert replay["probe_cost_units"] == sum(costs[pid] for pid in replay["probes"])
    assert hs == original


def test_cost_range_cannot_reverse_distinct_disagreement_scores():
    import json

    costs = json.loads(Path("data/costs.json").read_text())["costs"]
    audit = mechanisms.cost_audit(costs)
    assert audit["cost_can_only_break_disagreement_ties"]
    assert audit["at_original_floor"] == 7
    for higher in range(2, 7):
        assert higher / (max(costs.values()) + 0.1) > (higher - 1) / (min(costs.values()) + 0.1)


def test_unscored_replay_does_not_report_accuracy():
    snapshot = CATALOG.load(POOL)
    hs = hypotheses(fake_proposal(list(PROBE_MAP)))
    values = {name: mechanisms.replay(snapshot, hs, COSTS, name) for name in mechanisms.VARIANTS}
    values["rules"] = mechanisms.rule_diagnose(snapshot, COSTS)
    summary = mechanisms.unscored_summary([{"variants": values}])
    assert summary["scored"] is False
    assert all("known_correct" not in v for v in summary["variants"].values())


@pytest.mark.parametrize(
    ("version", "variant"),
    [("competitive-v2", "legacy_cost"), ("competitive-v3", "verification_cost")],
)
def test_live_engine_matches_frozen_policy_replay(tmp_path, monkeypatch, version, variant):
    monkeypatch.setattr("probeops.storage.POLICY_VERSION", version)
    telemetry = Telemetry(tmp_path / "telemetry", "test")
    cfg = Settings(_env_file=None, probeops_db_path=tmp_path / "db")
    store = Store(cfg.probeops_db_path, telemetry, cfg)
    try:
        run = store.create(
            CreateRun.model_validate(
                {
                    "incident_id": POOL,
                    "strategy_id": "competitive_cost",
                    "limits": {
                        "max_steps": 12,
                        "max_llm_calls": 16,
                        "max_wall_seconds": 180,
                        "max_cost_micro_cny": 250000,
                    },
                }
            ),
            "mechanism-integration",
            "a" * 32,
            "b" * 16,
        )
        asyncio.run(execute(store, "test", 0))
        events = store.page("events", run["run_id"], 0, 100)["items"]
        initial = mechanisms.initial_hypotheses(events)
        frozen = store.frozen(run["run_id"])
        replay = mechanisms.replay(frozen["snapshot"], initial, frozen["costs"], variant)
        assert replay["probes"] == [e["decision"]["probe_id"] for e in events if "decision" in e]
        assert store.report(run["run_id"])["conclusion"] == "located"
        assert frozen["policy_version"] == version
    finally:
        telemetry.close()
