"""P1's explicit Python workflow; no inference, agent SDK, or network access."""

import asyncio
import hashlib
import time
from typing import Any

from .models import INCIDENT, TERMINAL
from .storage import Store, uid
from .telemetry import now, span_id


class FakeLLM:
    async def propose(self) -> list[dict[str, Any]]:
        return [
            {
                "hypothesis_id": "h_demo",
                "component": "checkout-api",
                "fault_type": "模拟延迟候选",
                "status": "unresolved",
                "score": 0,
                "evidence_ids": [],
                "predictions": [],
            }
        ]


class FakeMetrics:
    async def observe(self) -> dict[str, Any]:
        summary = "模拟观测：checkout-api 示例响应时间 820 ms。"
        return {
            "evidence_id": uid("ev"),
            "probe_id": "p_demo",
            "tool_name": "query_metrics",
            "observed_at": now(),
            "window_start": INCIDENT["window_start"],
            "window_end": INCIDENT["window_end"],
            "summary": summary,
            "content_hash": hashlib.sha256(summary.encode()).hexdigest(),
            "outcome": "ok",
            "source": "synthetic://p1/metrics",
            "span_id": span_id(),
        }


async def diagnose(
    store: Store,
    run: dict[str, Any],
    owner: str,
    delay: float,
    llm: FakeLLM | None = None,
    probe: FakeMetrics | None = None,
) -> None:
    telemetry = store.telemetry
    run_id = run["run_id"]
    started = time.monotonic()

    async def checkpoint() -> bool:
        # Responsive cancellation/deadline while deliberately slowing the demo.
        until = time.monotonic() + delay
        while True:
            current = store.get(run_id)
            if current["status"] in TERMINAL:
                return False
            if current["status"] == "cancel_requested":
                store.advance(run_id, owner, "run_finished", "取消完成。")
                return False
            if time.monotonic() - started >= run["limits"]["max_wall_seconds"]:
                store.advance(
                    run_id,
                    owner,
                    "run_finished",
                    "达到运行时间上限。",
                    updates={"status": "completed", "stop_reason": "deadline"},
                )
                return False
            remaining = until - time.monotonic()
            if remaining <= 0:
                return True
            await asyncio.sleep(min(0.1, remaining))

    with telemetry.span("agent.step", step=1, policy="p1-fixed"):
        if not await checkpoint():
            return
        with telemetry.span("llm.request", model="FakeLLM-v1", attempt=1, cost_micro_cny=0):
            hypotheses = await (llm or FakeLLM()).propose()
            usage = {**run["usage"], "llm_calls": 1}
            result = store.advance(
                run_id,
                owner,
                "llm_finished",
                "FakeLLM 返回模拟假设，费用为零。",
                updates={"usage": usage},
            )
            if result["status"] in TERMINAL:
                return
        result = store.advance(
            run_id,
            owner,
            "hypotheses_updated",
            "生成模拟假设。",
            updates={"hypotheses": hypotheses},
        )
        if result["status"] in TERMINAL or not await checkpoint():
            return
        with telemetry.span("agent.select_probe", selected_tool="query_metrics", policy="p1-fixed"):
            result = store.advance(run_id, owner, "probe_started", "读取模拟指标快照。")
        if result["status"] in TERMINAL:
            return
        with telemetry.span("tool.query_metrics", probe_id="p_demo", synthetic=True):
            evidence = await (probe or FakeMetrics()).observe()
            usage.update(probe_count=1, probe_cost_units=1)
            result = store.advance(
                run_id,
                owner,
                "probe_finished",
                "模拟快照已持久化。",
                updates={"usage": usage},
                evidence=evidence,
            )
        if result["status"] in TERMINAL or not await checkpoint():
            return
        store.advance(
            run_id,
            owner,
            "run_finished",
            "流程完成；模拟数据不支持真实诊断结论。",
            updates={"status": "completed", "stop_reason": "ambiguous"},
        )
