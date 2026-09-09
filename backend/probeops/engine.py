"""Framework-free diagnosis loop shared by all six policies."""

import asyncio
import time

from .models import DomainError
from .observations import PROBES, Band, Gateway, Json
from .provider import propose
from .reasoning import falsifiable_probes, hypotheses, select, update
from .storage import Store


async def diagnose_snapshot(store: Store, run: Json, owner: str, delay: float = 0) -> None:
    rid = run["run_id"]
    frozen = store.frozen(rid)
    require_complete = frozen.get("policy_version") in {"competitive-v4", "competitive-v5"}
    allow_falsification = frozen.get("policy_version") == "competitive-v5"
    snapshot = frozen["snapshot"]
    gateway = Gateway(snapshot)
    deadline = time.monotonic() + run["limits"]["max_wall_seconds"]
    observed: list[tuple[Json, Band]] = []
    remaining = [p.probe_id for p in PROBES]
    hs: list[Json] = []
    replacements, stagnant = 0, 0
    stop = "ambiguous"

    async def model_context() -> Json:
        return {
            "incident": snapshot["incident"],
            "graph": snapshot["graph"],
            "strategy": run["strategy_id"],
            "hypotheses": hs,
            # Compact verified observations, no raw bodies or hidden provenance.
            "observations": [
                {"probe_id": e["probe_id"], "band": b, "outcome": e["outcome"]} for e, b in observed
            ],
        }

    try:
        proposal = await propose(store, rid, owner, await model_context(), remaining, deadline)
        hs = hypotheses(proposal)
        store.advance(
            rid, owner, "hypotheses_updated", "候选与可证伪预测已保存。", updates={"hypotheses": hs}
        )
        for step in range(run["limits"]["max_steps"]):
            if not remaining:
                break
            if time.monotonic() >= deadline:
                stop = "deadline"
                break
            if delay:
                await asyncio.sleep(delay)
            current = store.get(rid)
            if current["status"] != "running":
                store.advance(rid, owner, "run_finished", "取消完成。")
                return
            with store.telemetry.span("agent.step", step=step + 1, policy=run["strategy_id"]):
                if run["strategy_id"] == "react" and step > 0:
                    proposal = await propose(
                        store, rid, owner, await model_context(), remaining, deadline
                    )
                decision = select(
                    run["strategy_id"],
                    hs,
                    remaining,
                    frozen["seed"] + step,
                    proposal.next_probe,
                    frozen.get("costs"),
                    observations=observed,
                    verification=frozen.get("policy_version")
                    in {"competitive-v3", "competitive-v4", "competitive-v5"},
                    require_complete=require_complete,
                    allow_falsification=allow_falsification,
                )
                active = [h for h in hs if h["status"] != "contradicted"]
                if (
                    run["strategy_id"] in {"competitive_cost", "no_cost"}
                    and len(active) > 1
                    and decision["disagreement_pairs"] == 0
                    and not (allow_falsification and falsifiable_probes(hs, remaining))
                ):
                    break
                pid = decision["probe_id"]
                with store.telemetry.span(
                    "agent.select_probe",
                    selected_probe=pid,
                    utility=decision["utility"],
                    policy=run["strategy_id"],
                ):
                    usage = store.get(rid)["usage"]
                    usage["probe_count"] += 1
                    usage["probe_cost_units"] += decision["estimated_cost_units"]
                    result = store.advance(
                        rid,
                        owner,
                        "probe_started",
                        "选择只读探测。",
                        updates={"usage": usage},
                        decision=decision,
                    )
                if result["status"] != "running":
                    return
                probe = next(p for p in PROBES if p.probe_id == pid)
                with store.telemetry.span(f"tool.{probe.tool_name}", probe_id=pid):
                    async with asyncio.timeout(min(5.0, max(0.01, deadline - time.monotonic()))):
                        evidence, band, elapsed = await asyncio.to_thread(gateway.observe, pid)
                    # All state commits are short; there is no await inside transactions.
                    result = store.advance(
                        rid,
                        owner,
                        "probe_finished",
                        f"观测已保存，用时 {elapsed:.3f} ms。",
                        evidence=evidence,
                    )
                if result["status"] != "running":
                    return
                remaining.remove(pid)
                observed.append((evidence, band))
                hs = update(hs, observed, require_complete=require_complete)
                store.advance(
                    rid,
                    owner,
                    "hypotheses_updated",
                    "按实际观测更新支持与反驳关系。",
                    updates={"hypotheses": hs},
                )
                stagnant = stagnant + 1 if band == "unknown" else 0
                if any(h["status"] == "supported" for h in hs):
                    stop = "evidence_sufficient"
                    break
                if stagnant >= 2:
                    break
                if all(h["status"] == "contradicted" for h in hs) and replacements == 0:
                    replacements += 1
                    proposal = await propose(
                        store, rid, owner, await model_context(), remaining, deadline
                    )
                    hs = update(
                        hypotheses(proposal, replacements),
                        observed,
                        require_complete=require_complete,
                    )
                    store.advance(
                        rid,
                        owner,
                        "hypotheses_updated",
                        "replacement：原候选均有反驳，仅允许重建一次。",
                        updates={"hypotheses": hs},
                    )
                    if require_complete and any(h["status"] == "supported" for h in hs):
                        stop = "evidence_sufficient"
                        break
        else:
            stop = "step_limit"
        if run["strategy_id"] == "fixed" and stop != "deadline":
            # Same model and schema, after the fixed observations; cannot override evidence checks.
            proposal = await propose(store, rid, owner, await model_context(), remaining, deadline)
            hs = update(hypotheses(proposal, 1), observed, require_complete=require_complete)
            stop = "evidence_sufficient" if any(h["status"] == "supported" for h in hs) else stop
            store.advance(
                rid,
                owner,
                "hypotheses_updated",
                "固定流程最终候选经相同证据验证器校验。",
                updates={"hypotheses": hs},
            )
    except DomainError as exc:
        if exc.code in {"BUDGET_EXHAUSTED", "CALL_LIMIT", "CONTEXT_LIMIT"}:
            stop = "cost_limit" if exc.code == "BUDGET_EXHAUSTED" else "step_limit"
        elif exc.code == "DEADLINE":
            stop = "deadline"
        elif exc.code == "RUN_STOPPED":
            store.advance(rid, owner, "run_finished", "运行停止。")
            return
        else:
            raise
    store.advance(
        rid,
        owner,
        "run_finished",
        "诊断结束，报告由证据校验结果生成。",
        updates={"status": "completed", "stop_reason": stop},
    )
