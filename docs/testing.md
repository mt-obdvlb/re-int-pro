# 测试设计与验收清单

本轮交付测试设计和 Apifox 资源，**当前没有真实后端**；未执行接口业务测试，不能以 Mock 或 schema validate 声称服务通过。运行测试等到 P1/P4，具体资源状态见 [Apifox 记录](apifox/README.md)。

## API 用例矩阵

| ID | 接口/情形 | 请求/前置 | 预期 |
| --- | --- | --- | --- |
| API-01 | health | 无正文 | 200；status=ok；version存在 |
| API-02 | incidents | 演示数据已加载 | 200；items数组；无 truth/fault_label |
| API-03 | incident 不存在 | incident_id=missing_incident | 404；code=NOT_FOUND |
| API-04 | strategies | 配置可读 | 200；六种 ID；含 competitive_cost |
| API-05 | 创建成功 | demo_001、合法limits、唯一幂等键 | 202；run_id存在；首次status=queued |
| API-06 | 创建缺字段 | 缺 incident_id | 422；code=VALIDATION_ERROR |
| API-07 | 上限越界 | max_steps=13 | 422；不创建运行、不调用LLM |
| API-08 | 非法策略 | strategy_id=arbitrary | 422；不透传给模型 |
| API-09 | 运行列表 | limit=20 | 200；items/next_cursor；排序符合契约 |
| API-10 | 运行不存在 | run_id=missing_run | 404；code=NOT_FOUND |
| API-11 | 取消不存在运行 | missing_run、reason | 404；code=NOT_FOUND |
| API-12 | 事件非法游标 | after_seq=-1 | 422；code=VALIDATION_ERROR |
| API-13 | 证据不存在运行 | missing_run | 404；code=NOT_FOUND |
| API-14 | 报告不存在运行 | missing_run | 404；code=NOT_FOUND |
| API-15 | 项目预算 | 本地账本 | 200；currency=CNY；cap=500000000；admission=450000000 |
| API-16 | 未完成报告 | 已排队 run_id | 409；code=REPORT_NOT_READY |
| API-17 | 创建幂等重复 | 相同key、相同body连续两次 | 两次202、同一run_id、账本仅创建一次 |
| API-18 | 幂等冲突 | 相同key、不同limits | 第二次409；IDEMPOTENCY_CONFLICT |
| API-19 | 并发/费用准入 | 隔离测试账本耗尽或队列满 | 429；BUDGET_EXHAUSTED/QUEUE_FULL；无额外预留 |
| API-20 | 增量事件 | 两页同run，使用第一页next_cursor | 严格递增、无重复；空页cursor不倒退 |
| API-21 | 取消竞争/重复取消 | 运行中取消两次，另测终态取消 | 202返回实际状态；终态不回退；取消成功后无新探测 |
| API-22 | 完整诊断报告 | FakeLLM确定性fixture运行完成 | located/正确fixture或unresolved；引用证据全部存在 |
| API-23 | 非法正文属性/注入 | 传 tool_url、shell、model、api_key 等额外字段 | 422；不执行、不回显内容 |
| API-24 | 错误与观测脱敏 | 假密钥哨兵及错误路径 | 错误仅标准字段；所有输出无哨兵值 |

单接口资源已保存 API-01～15 的独立状态码与关键字段断言；排序、标签泄漏、无额外调用等深层行为按上表在P4继续补全实测，不能仅凭当前初始断言宣称整行验收通过。API-16～24 需要应用 fixture 和跨请求状态，作为 P1/P4 场景清单，不提前创建空场景冒充可运行用例。后续场景用 `import-steps --source test-case` 绑定现有用例，再编辑变量与断言。步骤顺序依 number；run_id 从创建响应传入，轮询≤180次且每秒一次，退出条件是终态。失败清理在隔离测试夹具完成，Agent 不持有重置接口。

每个保存的单接口用例至少有 HTTP 状态和关键 JSONPath 断言，绑定当前项目真实分类/endpoint ID；JSON 请求体以 `requestBody.data` 字符串保存。场景的变量表达式不要放进无法获得上游步骤的独立 case。schema validate 仅证明结构合法，get 仅证明已保存，runner 报告才证明实际断言执行。

## 内部与集成测试

| 层 | 必需故障或边界 | 原因 |
| --- | --- | --- |
| 决策单元 | 四候选上限、unknown预测、D=0、并列、一候选、重复证据、候选替换 | 防止评分实现自证和无限循环 |
| 策略消融 | no_cost只改排序、random只改选取 | 证明实验隔离了机制差异 |
| 工具网关 | 越窗、越权、路径/URL注入、空/截断/超时 | LLM建议不能越过程序边界 |
| LLM适配 | 401、429、5xx、超时、非法JSON、缺usage、取消 | 错误分类、费用预留和限额正确 |
| 存储/worker | 并发领取、事务冲突、取消先后顺序、杀进程/租约过期 | 不重复执行、不出现两个终态 |
| 预算 | 小数向上取整、未知计费、重试二次预留、450元边界 | 本地可做确定性断言，无需付费 |
| 观测 | trace上下文跨worker、exporter停机、敏感哨兵 | 完整关联和脱敏都覆盖失败路径 |
| 前端 | 重复点击、刷新、断网恢复、空页/404/409/429、未知结论 | UI不能将HTTP成功当诊断成功 |

FakeLLM 预置响应序列而不是联网模型，用实际解析器和预算代码执行；测试只模拟外部依赖，不绕过状态机。核心风险写行为断言，不追求机械100%覆盖。接口端到端以Apifox维护，内部pytest可覆盖事务和故障注入，但不复制整份API用例矩阵。

## 阶段验证与产物

- P0：文档相对链接、JSON及引用解析、OpenAPI标准验证、Apifox真实资源回读、差异/凭据检查；未搭建后端的运行项标为未执行。
- P1：静态检查+FakeLLM接口闭环+health Apifox本地报告；实际命令写入README后再执行。
- P3：边界、故障恢复、预算和trace验收；最多1元百炼接入烟测须在实施范围内进行。
- P4：API-01～24真实执行记录，创建→观察→报告和创建→取消两条UI流程；不做与任务无关的大规模测试。
- P5/P6：冻结配置、数据hash、聚合结果CSV、绘图源、失败摘要、复现指南、脱敏报告。仅提交可公开的合成数据和小结果，原始输出默认忽略。

阻塞按实现、配置、供应商、数据、工具链分类；失败后保留失败记录，修复后只重跑受影响范围。接口测试不调用故障生产环境；Apifox不保存BAILIAN_API。
