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
STRATEGIES = [
    {"strategy_id": key, "name": name, "description": description}
    for key, name, description in [
        ("fixed", "固定流程", "固定指标→日志→trace→配置，统一模型与验证器。"),
        ("react", "ReAct", "模型根据已有观测选择下一项探测。"),
        ("graph_greedy", "图贪心", "优先验证领先候选组件及其邻接依赖。"),
        ("competitive_cost", "竞争假设与成本", "按候选对区分度 D/(c+0.1) 选择探测。"),
        ("no_cost", "去成本消融", "仅按区分度 D 排序，字典序破同分。"),
        ("random_probe", "随机探测消融", "保存种子，均匀选择合法未执行探测。"),
    ]
]
