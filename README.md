# re-int-pro

用于计算机考研与复旦复试面试准备的 Agent 项目。用户已选择 **T1：基于竞争假设与探测成本的故障诊断 Agent（ProbeOps）**。当前交付 P1：React 工作台、FastAPI、独立 Python worker、SQLite 和 FakeLLM 可运行链路；真实故障环境和竞争策略尚未实现。

## 项目目标

围绕一个明确问题，完成可演示、可复现、可解释的 Agent 系统，并积累适合简历和面试讲述的设计与实验材料。

- **Agent 是项目核心**：需要围绕任务目标进行决策、调用工具、利用反馈并判断何时结束；具体机制在选题后确定。
- **AI 亮点与难点可讲述**：能够解释问题、设计选择、替代方案、失败案例与改进过程。
- **创新点可验证**：与已有方法和项目比较，区分工程改进、场景创新与研究贡献，避免未经验证的首创声明。
- **理论依据可追溯**：关键机制关联论文、算法或其他可靠的一手资料，说明理论与实际实现的对应关系。
- **效果有证据**：后续通过基线、评价指标和必要的消融实验检验方案，保留成本与局限记录。

以上为项目要求，不代表系统已实现或实验已完成。此仓库不提供复旦招生政策或复试形式的官方结论。

## 阶段与审批

| 步骤 | 内容 | 当前状态 |
| --- | --- | --- |
| 1 | 初始化 Git、README、协作规范与项目记录 | 已完成，用户已批准进入第 2 步 |
| 2 | 候选题目调研及完整面试预演稿 | 已交付，用户已继续选题 |
| 3 | 用户确定题目 | 已明确选择 T1 |
| 4 / P0 | 整体规划、技术设计、文档与 Apifox 设计资产 | 已完成，用户已批准 P1 |
| P1 | 基础搭建与 FakeLLM 端到端 | 本轮交付，等待验收 |
| P2–P6 | 环境、Agent、完整前端、实验、面试 | 已规划，尚未实施 |

**每一步完成后，必须获得用户明确批准，才能进入下一步。** 不根据文档齐全、提交成功或候选题目评分自动推进。

## 当前方案与文档入口

React + TypeScript + Vite 前端；Python FastAPI 后端；Agent 由纯 Python 状态机实现，不使用 Agent 框架。LLM 使用阿里云百炼，配置来自未跟踪的 `.env` 中 `BAILIAN_API`；logging + OpenTelemetry tracing 覆盖整个执行链。Apifox 沿用 `re-int-pro` 的 Git Spec 模式，以 OpenAPI 文件生成接口，CLI 维护测试。

- [完整实施计划](docs/implementation-plan.md)：280 小时目标、P0–P6 关卡、验收和风险。
- [需求与前端流程](docs/requirements.md)：演示场景、功能范围、可验收标准。
- [系统架构与决策](docs/architecture.md)：模块、数据流、worker、持久化和并发。
- [Agent 机制与百炼](docs/agent-design.md)：竞争假设、成本排序、工具边界、重试和费用账本。
- [日志与追踪](docs/observability.md)：字段、span、脱敏、故障验收。
- [API 契约](docs/api-contract.md) / [OpenAPI](docs/api/openapi.json) / [Apifox 记录](docs/apifox/README.md)：12 个操作与维护流程。
- [测试设计](docs/testing.md)：24 项 API 测试矩阵、内部测试和验收分工。
- [实验与预算](docs/evaluation-plan.md)：80 个计划任务、六配置、统计和百炼费用。
- [开发约定](docs/development.md)：环境、安全配置和后续搭建要求。
- [P1 验收记录](docs/p1-validation.md) / [工作台设计](docs/design/p1-design.md)：实际运行、测试与视觉对照。
- [规划来源](docs/planning-sources.md) / [本轮验证记录](docs/planning-validation.md)：官方依据、验证证据与未执行边界。

## 历史选题材料与阶段记录

- [五个候选题目与对比](docs/topic-research.md)：十二方向初筛、理论与近邻、机制假设、系统设计、评测和成本。
- [逐题完整面试预演稿](docs/topic-interview-scripts.md)：每题三分钟稿、八分钟稿、五组追问回答与两条简历草案。
- [来源与检索记录](docs/topic-evidence.md)：论文、官方实现、数据许可、报价及核验局限。
- [AGENTS.md](AGENTS.md)：范围、审批、研究证据与代码协作规则。
- [项目阶段记录](docs/project-plan.md)：各步骤交付内容、验收要求和批准记录。
- [.gitignore](.gitignore)：系统杂项、本地凭据和常见临时产物的忽略规则。

第 2 步按总投入 150–300 小时、单个最终项目 API 预算不超过 500 元设计，不以训练或微调为前提。用户已决定选择 ProbeOps。历史候选报价和备选方案保留作调研记录，当前实施以选题后的设计文档为准。讲稿全部为尚未实现时的预演稿，不能直接作为已完成项目经历使用。

## 本地使用

需要 uv、Node.js 24、pnpm 11.5.1。Python 3.12 由 uv 管理。所有命令从仓库根目录执行：

```bash
uv sync --frozen
pnpm --dir frontend install --frozen-lockfile
uv run python scripts/dev.py
```

打开 [本地工作台](http://127.0.0.1:5173)，点击“新建运行”。Ctrl+C 关闭本次启动的前端、API 与 worker。也可以分别启动：

```bash
uv run uvicorn probeops.api:app --host 127.0.0.1 --port 8000 --no-access-log
uv run python -m probeops.worker
pnpm --dir frontend dev
```

默认 `LLM_MODE=fake`，无需密钥或实验容器。不要覆盖已有 `.env`；新环境可参考 [.env.example](.env.example)。P1 拒绝 live 模式，不消费百炼额度。SQLite 与本地脱敏遥测保存在忽略的 `.runtime/`。目前支持固定流程模拟、创建/列表/详情/取消、事件与证据回读、未知结论报告；服务仅绑定本机。

```bash
uv run pytest -q
uv run mypy
uv run ruff check backend scripts
uv run ruff format --check backend scripts
pnpm --dir frontend typecheck
pnpm --dir frontend lint
pnpm --dir frontend test
pnpm --dir frontend build
# 接口变动后从唯一契约源重新生成 TS 类型
pnpm --dir frontend generate:api
```

从运行详情复制链路 ID：`uv run python scripts/trace.py <trace_id>`，查看 API 创建关联、worker、step、FakeLLM、tool 和 storage spans。P1 使用本地 JSONL exporter；Jaeger/OTLP、真实模型重试与预算账本在后续阶段验收。

Apifox 的真实健康测试（先启动后端，CLI 已登录）：

```bash
apifox run --project 8800905 --branch main --test-case 411147565 --environment 48818912 --reporters cli,json --out-dir .runtime/apifox --out-file p1-health --upload-report false
```

该命令实际请求本地后端，不是 Mock。原始报告留在 `.runtime`，脱敏摘要见验收文档。请勿把模拟流程通过当作故障诊断有效或面试实验提升。

## 提交与公开材料

- 按阶段创建内容明确的 Git 提交；用户已授权合理安排提交与推送。
- 只提交本项目相关变更，不覆盖已有工作，不重写远程历史。
- 提交前检查差异与暂存区；推送后核对远程提交。
- 不提交 API 密钥、访问令牌、含个人信息的简历或私有数据；使用凭据时通过未跟踪的本地环境文件配置。
