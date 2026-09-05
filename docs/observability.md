# Logging、Tracing 与可回放记录

状态：设计要求，尚未实现。logging/tracing 覆盖所有执行分支是验收项，不是后期补丁。采用 [Python logging](https://docs.python.org/3/library/logging.html) 与 [OpenTelemetry Python](https://opentelemetry.io/docs/languages/python/instrumentation/)；不使用 Agent 框架。

## 三层记录

| 层 | 用途 | 持久性 |
| --- | --- | --- |
| JSON 运行日志 | 开发排障、错误摘要、性能 | stdout + 按大小轮转本地文件，10MB ×5，开发保留 7 天 |
| OTel spans | 跨 API、worker、工具、模型和实验服务的耗时因果链 | 本地 Jaeger OTLP；实验与演示 100% 采样，脱敏导出固定版本 |
| SQLite events/evidence/ledger | 状态回放、实验证据、账单恢复 | 业务必需、事务写入；不能采样丢弃；按实验批次归档 |

开发日志至少具有 time_utc、level、logger、event_name、request_id、run_id、trace_id、span_id、strategy_id、step、duration_ms、outcome、error_code、attempt 字段。不适用字段为 null；所有时间 UTC，耗时用单调时钟。前端展示转换本地时区。

logging 使用 dictConfig、每模块 `getLogger(__name__)`、contextvars 传递关联字段，异步/worker 中显式绑定和释放。QueueHandler/QueueListener 隔离慢日志 I/O；队列满可丢低等级日志并增加 dropped_logs 指标，ERROR 有受限 stderr 后备路径，不能无限阻塞任务。异常记录安全的类型、堆栈位置和错误码；不记录 locals 或含完整 HTTP 请求的 repr。

## 必需 span 与父子关系

| span | 重要属性 | 失败状态 |
| --- | --- | --- |
| HTTP METHOD route | route、status_code、request_id；使用路由模板，不含输入正文 | 5xx ERROR，业务 4xx 记录 error_code |
| diagnosis.run | run_id、strategy_id、dataset_version、config_hash | 失败 ERROR，取消/证据不足用 stop_reason |
| agent.step | step、active_hypotheses、candidate_probe_count | 非法提案记录 rejection |
| agent.select_probe | selected_tool、D、cost_units、policy_version | 无合法动作标注 unresolved |
| tool.query_metrics 等 | probe_id、窗口、大小、cache_hit、evidence_id | timeout/error 独立记录 |
| llm.request | model、attempt、tokens、estimated/settled_cost、provider_request_id | 429/5xx/parse_failure 可区分 |
| storage.commit / budget.reserve | operation、duration、result | busy/冲突不吞错 |
| lab.capture / lab.request | snapshot_id、service、trace_id | 实验环境故障归于实验链路 |

创建 run 时建立其逻辑 trace context 并持久化；HTTP 创建 span 与 diagnosis.run 通过 Span Link 关联。worker 领取时恢复同一 run trace 的上下文，工具和模型请求为子 span；前端轮询属于新的请求 trace，通过 run_id/link 关联，不能强行全部塞为超长 HTTP span。服务间采用 [W3C traceparent](https://www.w3.org/TR/trace-context/)，非法值丢弃并生成新 context，不接受任意 baggage。探测返回的业务 trace_id 和 Agent 自己的 trace_id 分字段保存，避免两种链路混淆。

## 脱敏、采样与存储

- 默认记录提示模板版本、参数哈希、tokens、结构化提案摘要，不保存完整 prompts/模型原文；Evidence 只含合成系统的脱敏观测。原始模型解析失败保存错误位置与长度，不回显原文。
- 白名单字段先抽取，再脱敏；Authorization、Cookie、BAILIAN_API、API key、连接串、密码、token 一律过滤。配置对象禁止整体 repr。密钥过滤必须覆盖异常路径、HTTP 客户端 debug、Apifox 导出和前端构建变量。
- 100% 采样限本地实验；不把高基数字段当指标标签。指标只用 strategy/tool/outcome：调用、失败、超时、队列深度、取消等待、费用、证据缺失、日志丢弃和 exporter 丢弃数。
- OTel exporter 队列有界，导出失败不影响诊断；通过日志/指标提示 telemetry_degraded。遵循 [OTel exporters](https://opentelemetry.io/docs/languages/python/exporters/) 的批处理方式，正常退出 flush 最多 5 秒；强制退出可能丢 span，但业务事件仍须完整。
- 真值目录和注入控制日志不进入 Agent 可读日志查询。实验者可离线关联隐藏真值评分，不能在 UI 提前显示答案。

## 可观测性验收矩阵

1. 一次正常运行：从 run_id 定位完整 run→step→probe/LLM 链，所有工具结果能关联 Evidence。
2. 429 后恢复：看见每个 attempt、退避和独立预算预留，不能只记最后成功。
3. 超时与取消：取消提交时刻、在途请求、终态和 uncertain 费用完整，取消后无新探测。
4. 杀掉 worker：过租约后 API 显示 failed/worker_lost；重启不重复已受理的模型调用；未结算预留有记录。
5. 停掉 Jaeger：Agent 继续完成、exporter 有降级计数；恢复后不谎称丢失链路全部补回。
6. 注入假密钥哨兵和恶意日志指令：输出日志、trace、API、前端、报告均不能包含哨兵值；非法工具拒绝有可审计事件。
7. 回放：仅用 events+evidence 重建候选变化和终止原因；不依赖 LLM 再生成，也不要求恢复模型隐式思维链。

搭建阶段先交付不依赖百炼的 FakeLLM 链路验收，随后获得实施批准并核对地域后再做最小真实调用。当前没有运行任何上述实验。
