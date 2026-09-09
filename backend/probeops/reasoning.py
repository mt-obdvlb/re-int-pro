"""Validated model proposals and deterministic, inspectable policy decisions."""

import itertools
import math
import random
from typing import Literal

from pydantic import Field, model_validator

from .models import StrictModel
from .observations import GRAPH, PROBE_MAP, PROBES, Band, Json

Fault = Literal["pool_exhaustion", "queue_backlog", "cache_latency", "config_error", "unknown"]
POLICY_VERSION = "competitive-v5"


class Prediction(StrictModel):
    probe_id: str
    expected: Band

    @model_validator(mode="after")
    def valid_probe(self) -> "Prediction":
        if self.probe_id not in PROBE_MAP:
            raise ValueError("Unknown observation")
        return self


class Candidate(StrictModel):
    component: Literal["checkout-api", "task-worker", "cache", "database"]
    fault_type: Fault
    predictions: list[Prediction] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def unique_predictions(self) -> "Candidate":
        if len({p.probe_id for p in self.predictions}) != len(self.predictions):
            raise ValueError("Duplicate prediction")
        if {p.probe_id for p in self.predictions} != set(PROBE_MAP):
            raise ValueError("Every candidate must predict the same complete probe catalog")
        return self


class Proposal(StrictModel):
    candidates: list[Candidate] = Field(min_length=1, max_length=4)
    next_probe: str = ""

    @model_validator(mode="after")
    def validate_plan(self) -> "Proposal":
        if self.next_probe and self.next_probe not in PROBE_MAP:
            raise ValueError("Unknown tool request")
        if len({(h.component, h.fault_type) for h in self.candidates}) != len(self.candidates):
            raise ValueError("Duplicate hypothesis")
        return self


def hypotheses(proposal: Proposal, generation: int = 0) -> list[Json]:
    return [
        {
            "hypothesis_id": f"h_{generation}_{i}",
            "component": h.component,
            "fault_type": h.fault_type,
            "status": "active",
            "score": 0,
            "evidence_ids": [],
            "predictions": [
                {
                    "tool_name": PROBE_MAP[p.probe_id].tool_name,
                    "observation": p.probe_id,
                    "expected": p.expected,
                }
                for p in h.predictions
            ],
        }
        for i, h in enumerate(proposal.candidates)
    ]


def expected(h: Json, probe_id: str) -> str:
    return next(
        (p["expected"] for p in h["predictions"] if p["observation"] == probe_id), "unknown"
    )


def falsifiable_probes(hs: list[Json], remaining: list[str]) -> dict[str, int]:
    """Known predictions can be refuted even when other candidates say unknown."""
    active = [h for h in hs if h["status"] != "contradicted"]
    counts = {pid: sum(expected(h, pid) != "unknown" for h in active) for pid in remaining}
    return {pid: n for pid, n in counts.items() if 0 < n < len(active)}


def select(
    strategy: str,
    hs: list[Json],
    remaining: list[str],
    seed: int,
    model_choice: str = "",
    costs: dict[str, float] | None = None,
    *,
    observations: list[tuple[Json, Band]] | None = None,
    verification: bool = True,
    smoothing: float = 0.1,
    require_complete: bool = False,
    allow_falsification: bool = False,
) -> Json:
    if not math.isfinite(smoothing) or smoothing < 0:
        raise ValueError("Invalid cost smoothing")
    costs = costs or {p.probe_id: p.cost for p in PROBES}
    active = [h for h in hs if h["status"] != "contradicted"]
    scored: list[Json] = []
    for pid in remaining:
        pairs = sum(
            expected(a, pid) != expected(b, pid)
            and "unknown" not in (expected(a, pid), expected(b, pid))
            for a, b in itertools.combinations(active, 2)
        )
        scored.append(
            {
                "probe_id": pid,
                "disagreement_pairs": pairs,
                "estimated_cost_units": costs[pid],
                "utility": pairs / (costs[pid] + smoothing),
            }
        )
    # Once discrimination is complete, seek a missing abnormal evidence channel.
    # This changes acquisition order only: update() still requires actual evidence.
    confirm = []
    closing = False
    fallback = {}
    if (
        allow_falsification
        and strategy in {"competitive_cost", "no_cost"}
        and not any(p["disagreement_pairs"] for p in scored)
    ):
        fallback = falsifiable_probes(hs, remaining)
    if verification and strategy in {"competitive_cost", "no_cost"} and len(active) == 1:
        candidate = active[0]
        supported_tools = {
            e["tool_name"]
            for e, band in observations or []
            if e["outcome"] == "ok"
            and band in {"high", "low"}
            and expected(candidate, e["probe_id"]) == band
        }
        if candidate["fault_type"] != "unknown" and len(supported_tools) < 2:
            confirm = [
                p
                for p in scored
                if expected(candidate, p["probe_id"]) in {"high", "low"}
                and PROBE_MAP[p["probe_id"]].tool_name not in supported_tools
            ]
        if not confirm and require_complete:
            confirm = [p for p in scored if expected(candidate, p["probe_id"]) != "unknown"]
            closing = bool(confirm)
    if confirm:
        pick = min(
            confirm,
            key=lambda p: (
                p["estimated_cost_units"] if strategy == "competitive_cost" else 0,
                p["probe_id"],
            ),
        )
    elif fallback:
        pick = min(
            [p for p in scored if p["probe_id"] in fallback],
            key=lambda p: (
                -fallback[p["probe_id"]]
                / (costs[p["probe_id"]] + smoothing if strategy == "competitive_cost" else 1),
                p["probe_id"],
            ),
        )
    elif strategy == "random_probe":
        pick = random.Random(seed).choice(scored)
    elif strategy == "react":
        pick = next((p for p in scored if p["probe_id"] == model_choice), scored[0])
    elif strategy == "fixed":
        order = [
            p.probe_id
            for tool in ("query_metrics", "query_logs", "get_trace", "read_config")
            for p in PROBES
            if p.tool_name == tool
        ]
        pick = min(scored, key=lambda p: order.index(p["probe_id"]))
    elif strategy == "graph_greedy":
        leader = max(active or hs, key=lambda h: h["score"])
        component = leader["component"]
        neighbors = GRAPH.get(component, [])
        pick = min(
            scored,
            key=lambda p: (
                0
                if PROBE_MAP[p["probe_id"]].service == component
                else 1
                if PROBE_MAP[p["probe_id"]].service in neighbors
                else 2,
                p["probe_id"],
            ),
        )
    elif strategy == "no_cost":
        pick = min(scored, key=lambda p: (-p["disagreement_pairs"], p["probe_id"]))
    else:
        pick = min(scored, key=lambda p: (-p["utility"], p["estimated_cost_units"], p["probe_id"]))
    detail = "未知预测不参与区分。"
    if confirm:
        detail = (
            "完整预测核对：检查剩余明确预测，缺失不算验证通过。"
            if closing
            else "验证剩余候选：尝试补足异常证据通道，仍须通过实际观测校验。"
        )
    elif fallback:
        count = fallback[pick["probe_id"]]
        denominator = costs[pick["probe_id"]] + smoothing if strategy == "competitive_cost" else 1
        detail = f"unknown补查：K={count}，检验分数={count / denominator:.3f}；未知预测仍不评分。"
    return {
        **pick,
        "reason": (
            f"{strategy}: D={pick['disagreement_pairs']}, "
            f"c={pick['estimated_cost_units']:.3f}; {detail}"
        ),
    }


def update(
    hs: list[Json], observations: list[tuple[Json, Band]], *, require_complete: bool = False
) -> list[Json]:
    # Recompute from immutable observations; distinct tools need not be independent.
    for h in hs:
        score, support, refute, abnormal = 0, set(), False, False
        refs = []
        compared = set()
        for evidence, band in observations:
            prediction = expected(h, evidence["probe_id"])
            if "unknown" in (band, prediction) or evidence["outcome"] != "ok":
                continue
            refs.append(evidence["evidence_id"])
            compared.add(evidence["probe_id"])
            if prediction == band:
                score += 1
                # Normal observations alone never establish a fault.
                if band != "normal":
                    support.add(evidence["tool_name"])
                    abnormal = True
            else:
                score -= 2
                refute = True
        h.update(
            score=max(-20, min(20, score)),
            evidence_ids=refs,
            status="contradicted" if refute else "active",
        )
        h["_support"] = len(support) if abnormal else 0
        h["_complete"] = not require_complete or all(
            p["expected"] == "unknown" or p["observation"] in compared for p in h["predictions"]
        )
    ranked = sorted(hs, key=lambda h: h["score"], reverse=True)
    if ranked:
        first = ranked[0]
        margin = first["score"] - (ranked[1]["score"] if len(ranked) > 1 else 0)
        if (
            first["_support"] >= 2
            and first["_complete"]
            and margin >= 2
            and first["status"] != "contradicted"
            and first["fault_type"] != "unknown"
        ):
            first["status"] = "supported"
    for h in hs:
        h.pop("_support", None)
        h.pop("_complete", None)
    return hs


def fake_proposal(remaining: list[str]) -> Proposal:
    # Deterministic test double. It receives no hidden labels or observed answers.
    pairs = [
        ("database", "pool_exhaustion", {"pool_wait", "pool_events"}),
        ("task-worker", "queue_backlog", {"queue_depth", "queue_events"}),
        ("cache", "cache_latency", {"cache_latency", "cache_events"}),
        ("checkout-api", "config_error", {"config_events", "timeout_config"}),
    ]
    return Proposal.model_validate(
        {
            "candidates": [
                {
                    "component": c,
                    "fault_type": f,
                    "predictions": [
                        {
                            "probe_id": p.probe_id,
                            "expected": (
                                "unknown"
                                if p.probe_id in {"api_latency", "request_trace"}
                                else "low"
                                if p.probe_id == "timeout_config" and p.probe_id in signal
                                else "high"
                                if p.probe_id in signal
                                else "normal"
                            ),
                        }
                        for p in PROBES
                    ],
                }
                for c, f, signal in pairs
            ],
            "next_probe": remaining[0] if remaining else "",
        }
    )
