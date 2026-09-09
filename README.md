# ProbeOps

基于竞争假设与探测成本的故障诊断 Agent。React 工作台、FastAPI、独立 Python worker、四类只读观测、六种策略、百炼适配、持久化费用账本和 tracing 已实现。Agent 不使用框架。

这是考研复试项目的受控实验系统：先采集本地服务观测，再让 Agent 在同一冻结快照上选择探测；不执行修复。

**工程可运行不等于面试已准备好。** 复试按老师看简历提问、无法展示项目的场景准备；当前Agent价值、成本项效果与个人掌握仍需检验，见 [面试准备差距](docs/interview-readiness.md)。

2026-09-09补强：新增剩余候选验证探测、独立规则基线、共享真实候选的排序消融与失败审计。同为13/16定位结果时，新选择平均探测5.0→3.2；规则基线16/16更好，且模型仍有漏查反驳，不能声称LLM优于规则或模型费下降。结果和离线复算见 [机制补强](docs/strengthening-results.md)。

## 启动

需要 uv、Node.js 24、pnpm 11.5.1，所有命令从仓库根目录执行：

```bash
uv sync --no-editable --frozen
pnpm --dir frontend install --frozen-lockfile
uv run --no-editable python scripts/dev.py --mode fake
```

打开 [工作台](http://127.0.0.1:5173)，选择任务、策略与上限后创建运行，查看竞争假设、决策、证据和报告。默认 FakeLLM 无费用；内置六份真实服务采集快照，无需实验容器。旧 demo_latency 仅用于基础回归，限定 fixed 策略。

百炼读取现有 `.env` 的 `BAILIAN_API`，不要覆盖该文件。停止上一个开发进程后启动：

```bash
uv run --no-editable python scripts/dev.py --mode bailian
uv run --no-editable python scripts/budget.py
```

模型固定为 qwen-plus-2025-12-01。默认累计操作限额 **1元**，项目准入450元、总预算500元；账本包含已结算、预留、未确认费用。页面展示当前模式及每个历史运行自己的模型。Ctrl+C 停止本次启动的三个服务。SQLite、日志和报告保存在忽略的 .runtime/，不要为重跑删除费用账本。

## 实验环境和追踪

```bash
uv sync --no-editable --frozen --group lab
docker compose -f lab/compose.yaml --profile tracing up -d --wait
uv run --no-editable python scripts/dev.py --mode fake --tracing
uv run --no-editable python scripts/trace.py <trace_id>
```

[Jaeger](http://127.0.0.1:16686) 接收本地 OTLP。实验依赖 PostgreSQL/Redis 仅绑定回环端口；重新采集和离线评测见 [数据与复现](data/README.md)。停止依赖用 `docker compose -f lab/compose.yaml --profile tracing stop`。

## 验证范围

2026-09-08：后端29项测试、前端交互测试、类型检查、lint与构建通过；60测试快照×6策略×3次共1,080次 FakeLLM 管线运行，无系统失败。百炼20个开发任务中，16个已知故障定位正确13个，4个正常/缺失观测任务未误报。集成用量估算累计 **0.065529元**，尚未与供应商账单核对。

2026-09-09额外完成20个开发任务的候选采集（旧策略完整运行14/16），以及不再调用模型的共享候选消融。新批次估算 **0.061880元**，账本累计 **0.127409元**，预留与未确认费用均0；操作限额仍1元。完整运行与只保留初始候选的回放结果不能直接混比。

**百炼六策略正式配对实验尚未执行，不能声称竞争成本策略优于基线。** 开发/测试使用同一生成器、不同种子和严重程度区间，不能称跨模板或生产泛化。详见 [完整验收](docs/full-validation.md)。

```bash
uv run --no-editable pytest -q
uv run --no-editable mypy
uv run --no-editable ruff check backend scripts lab evaluation
uv run --no-editable ruff format --check backend scripts lab evaluation
pnpm --dir frontend typecheck
pnpm --dir frontend lint
pnpm --dir frontend test
pnpm --dir frontend build
pnpm --dir frontend generate:api
```

## 文档入口

- [模块交付](docs/module-delivery.md)、[项目记录](docs/project-plan.md)、[实施计划](docs/implementation-plan.md)：已按用户指令连续实现，不再逐个 P 阶段批准。
- [需求](docs/requirements.md)、[架构](docs/architecture.md)、[Agent机制](docs/agent-design.md)、[logging/tracing](docs/observability.md)、[开发配置](docs/development.md)。
- [唯一接口契约](docs/api/openapi.json)、[API语义](docs/api-contract.md)、[Apifox](docs/apifox/README.md)、[测试](docs/testing.md)。
- [评测与预算](docs/evaluation-plan.md)、[补强协议](docs/strengthening-protocol.md)、[补强结果与复算](docs/strengthening-results.md)、[简历与分层追问](docs/interview-guide.md)、[面试准备差距](docs/interview-readiness.md)。
- 历史：[候选调研](docs/topic-research.md)、[选题预演稿](docs/topic-interview-scripts.md)、[研究来源](docs/topic-evidence.md)、[P1验收](docs/p1-validation.md)。

提交仅含本项目源码、公共合成观测和脱敏汇总；不提交密钥、SQLite、隐藏标签或原始运行日志。历史预演稿不代表本人已完成经历。协作规范见 [AGENTS.md](AGENTS.md)。
