# API 契约与 Apifox 维护

接口字段的机器可读定义见 [openapi.json](api/openapi.json)：OpenAPI 3.0.3，11 条路径、12 个操作、19 个数据模型。P1 已实现这些路由的 FakeLLM 基础行为，策略仅 fixed 可用；真实机制与费用账本待 P3。本文描述全项目目标语义，当前验收子集见 [P1记录](p1-validation.md)。

## 接口清单

| 方法与路径 | 成功 | 关键约定 |
| --- | --- | --- |
| GET /healthz | 200 Health | 存活检查；模型不可达也不伪装进程已死 |
| GET /api/v1/incidents | 200 IncidentList | 仅预登记公开演示任务，不提供隐藏测试标签 |
| GET /api/v1/incidents/{incident_id} | 200 Incident | 告警、服务、窗口、数据版本；未知 ID 404 |
| GET /api/v1/strategies | 200 StrategyList | 六种冻结策略及说明 |
| POST /api/v1/runs | 202 Run | 必填 Idempotency-Key；incident、strategy、limits；准入后排队 |
| GET /api/v1/runs | 200 RunPage | limit 默认20最大100，按 created_at+run_id 降序的 opaque cursor |
| GET /api/v1/runs/{run_id} | 200 Run | 状态、假设、usage、最后事件序号 |
| POST /api/v1/runs/{run_id}/cancel | 202 Run | 原因长度1–200；重复/终态取消返回实际状态，不重启任务 |
| GET /api/v1/runs/{run_id}/events | 200 EventPage | after_seq 默认0、limit默认50最大100；增量查询 |
| GET /api/v1/runs/{run_id}/evidence | 200 EvidencePage | 独立递增证据游标，同样上限；内容不可变 |
| GET /api/v1/runs/{run_id}/report | 200 Report | 仅 completed 可取；其它状态409，未知运行404 |
| GET /api/v1/budget | 200 Budget | 项目账本，不返回账号余额、密钥或供应商控制台信息 |

所有路径参数为最多64字符的字母、数字、下划线、连字符；时间 RFC3339 UTC，金额 micro_cny 非负整数；拒绝未声明正文属性。缺少或不合法字段统一422，不能泄漏 Pydantic 原始 input。正常错误结构为 code、message、request_id、retryable。业务状态与 HTTP 成功严格分开。

固定错误码：NOT_FOUND(404)、IDEMPOTENCY_CONFLICT/REPORT_NOT_READY(409)、VALIDATION_ERROR(422)、QUEUE_FULL/BUDGET_EXHAUSTED(429)、DEPENDENCY_UNAVAILABLE(503)、INTERNAL_ERROR(500)。所有响应都带 X-Request-ID，包括错误；500 文本不包含堆栈。429 的 retryable 取决于预算是否可释放，预算用尽不鼓励无限重试。

事件只返回 seq>after_seq，按 seq 升序；next_cursor 是本页最后序号，空页保持原输入，has_more 表示当次快照仍有剩余。证据页使用单独内部序号，不与 event seq 混用；目前不对外返回 raw 文件路径。运行列表 cursor 解析失败422；分页期间新增运行不要求出现在旧页链中。

创建队列事务和实际模型预算预留分开：创建时预算不足则429；排队后预算被其他任务耗尽，可以 completed/unresolved + cost_limit，没有调用不得记作模型错误。Report 位于已完成的 immutable run 下；unresolved 时 component/fault_type 为空字符串，不能胡填最高分候选为答案。

## Apifox 现有配置与权威来源

2026-09-05 读取确认：项目 `re-int-pro`（8800905），main（8592769），Git 连接 2190 指向 `mt-obdvlb/re-int-pro`。客户端为 **Spec 模式**，接口定义来自 Git 中的 OpenAPI 文件。保留现有模式，不新建替代项目、不修改连接权限。

[官方 Spec 文档](https://docs.apifox.com/9330582m0) 说明规范文件生成接口结构；Git 托管项目通过仓库同步，普通项目导入不替代 Git 源文件。因此本项目唯一契约源为仓库 `docs/api/openapi.json`，在 Apifox Specs 中查看/编辑（其修改也必须提交回同一仓库），CLI 用于读取、核对、测试资源维护与执行。FastAPI 的 `/openapi.json` 是实现产物，只用于比较，不能覆盖设计。

首次排查：CLI 2.2.9 的 `import --format openapi` 只新增19个模型和1个本地环境、接口计数0；`endpoint create` 返回404。客户端与 Git 连接确认后停止沿普通可视化项目路径重试。最终同步与用例状态以 [Apifox 交付记录](apifox/README.md) 为准，不把导入成功作为接口落地证据。

## 后续变更流程

1. 修改契约源或 Apifox Specs 中同一文件，先核对 diff、字段 required/enum/响应码和所有 $ref；同一变更只选一个编辑入口。
2. 提交并按授权推送；在 Apifox 同步 main，CLI list/get 验证12个操作及新增/变更 DTO。不能手工编辑被 Spec 生成的接口资源。
3. 维护绑定真实 endpointId 的 API 测试用例；先 `cli-schema get`、`validate`，再 create/update、get 回读。同分支查询，分类 ID 来自 category。
4. 实现 FastAPI DTO/路由；对 `/openapi.json` 做规范化差异检查：路径/方法、参数 required、类型/约束、请求体、响应码和 schema 结构必须相同。忽略 title、description、顺序与 UI 扩展；3.0/3.1 nullable 表达先语义归一，不只比较原始 JSON 文本。
5. Apifox 测试指向本地隔离后端，报告写临时目录，不上传密钥/原始日志。复核报告后保存脱敏用例映射与结果摘要。

命令与 CLI 2.2.9 帮助、[官方 CLI 文档](https://docs.apifox.com/doc-5637756) 核对；升级后仍先读取对应帮助。不要把访问令牌放到命令行、Git 文件、共享环境或示例请求中。

```bash
apifox project get 8800905
apifox endpoint list --project 8800905 --branch main --page-size 100
apifox cli-schema get test-case-create
apifox test-case category --project 8800905
# CASE_FILE 是已填写真实 endpointId 并校验的本地用例文件
apifox cli-schema validate test-case-create --file "$CASE_FILE"
apifox test-case create --project 8800905 --branch main --file "$CASE_FILE"
apifox export --project 8800905 --branch main --format openapi --output /tmp/probeops-apifox-openapi.json
```

GET 的全量响应与环境导出可能包含配置；自动核验仅输出选定字段和计数。不要直接打印项目完整设置或 Git 连接配置。
