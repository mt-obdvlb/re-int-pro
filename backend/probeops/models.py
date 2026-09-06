from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
StrategyId = Literal[
    "fixed", "react", "graph_greedy", "competitive_cost", "no_cost", "random_probe"
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Limits(StrictModel):
    max_steps: int = Field(ge=1, le=12)
    max_llm_calls: int = Field(ge=1, le=16)
    max_wall_seconds: int = Field(ge=1, le=180)
    max_cost_micro_cny: int = Field(ge=1, le=250000)


class CreateRun(StrictModel):
    incident_id: Identifier
    strategy_id: StrategyId
    limits: Limits


class CancelRun(StrictModel):
    reason: str = Field(min_length=1, max_length=200)


class DomainError(Exception):
    def __init__(self, status: int, code: str, message: str, retryable: bool = False):
        self.status, self.code, self.message, self.retryable = status, code, message, retryable


INCIDENT = {
    "incident_id": "demo_latency",
    "title": "API 响应延迟",
    "alert": "模拟数据，用于验证运行流程。",
    "service": "checkout-api",
    "window_start": "2026-09-06T01:40:00Z",
    "window_end": "2026-09-06T01:45:00Z",
    "dataset_version": "p1-synthetic-v1",
}
STRATEGY = {
    "strategy_id": "fixed",
    "name": "固定流程演示",
    "description": "P1 FakeLLM 与一项模拟探测，不执行竞争假设算法。",
}
TERMINAL = {"completed", "cancelled", "failed"}
