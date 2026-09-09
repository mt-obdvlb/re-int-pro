# Logging、Tracing 与回放

2026-09-08实现：backend/probeops/telemetry.py。Python logging dictConfig、contextvars、QueueHandler/QueueListener，OTel TracerProvider与BatchSpanProcessor；不依赖Agent框架。

日志用于排障，span用于因果与耗时，SQLite事件/证据/费用流水用于不可丢的业务回放。日志队列2048、文件10MB/5备份，stdout和JSONL双输出；没有按天清理。span队列2048、批量128，默认本地JSONL；--tracing额外发送本地Jaeger OTLP，不发送第三方云。

字段白名单：time_utc、level、logger、event_name、request_id、run_id、trace_id、span_id、strategy_id、step、duration_ms、outcome、error_code、attempt。不适用字段null。第三方任意消息压为library_event，不输出请求正文、模型原文、异常message、locals、认证头或配置对象。

| 路径 | 可查证据 |
| --- | --- |
| HTTP创建/领取 | run.accept关联HTTP，trace上下文持久化，worker恢复关联 |
| 正常执行 | diagnosis.run、agent.step、agent.select_probe、llm.request、tool.*、storage.commit |
| 模型调用 | model、attempt、input_estimate，成功usage tokens/cost，非200响应码 |
| 决策与历史 | D/c/U、完整候选版本在SQLite，evidence引用tool span ID |
| 取消/超时/异常 | span ERROR保留异常类型；终态、停止原因与未确认费用持久化 |
| 崩溃恢复 | worker_lost；预留→uncertain；不伪造崩溃时丢失的span |
| 遥测失败 | dropped_logs/failed_exports计数，ERROR队列满固定stderr后备，账本独立 |

合法W3C traceparent可传播，不接收baggage。快照中的业务trace不是Agent trace。实验捕获没有完整跨服务OTel传播；Jaeger当前覆盖API/worker/模型/工具。

```bash
docker compose -f lab/compose.yaml --profile tracing up -d --wait
uv run --no-editable python scripts/dev.py --mode fake --tracing
uv run --no-editable python scripts/trace.py <trace_id>
```

Jaeger http://127.0.0.1:16686 ，按trace ID或probeops-worker查询。测试覆盖正常、取消在途调用、金额恢复/对账、工具deadline、候选历史。没有实时metrics仪表盘、告警系统或自动7天清理；不列为完成项。验收见 [完整记录](full-validation.md)。

2026-09-09回读发现本地Jaeger曾OOM退出（Docker记录OOMKilled=true、exit 137）。原256MiB容器使用默认无界内存存储，现限制最多500条trace；[1.76官方参数](https://www.jaegertracing.io/docs/1.76/deployment/cli/)与已安装镜像的`--help`均核实`--memory.max-traces`。这限制保留条数，不是严格内存上界或长期稳定性证明。Jaeger重启/淘汰会丢失其内存中的旧trace，本地JSONL与SQLite业务记录仍独立保留；不能承诺Jaeger永久保存历史。本轮运行回读见 [可靠性验证](reliability-results.md)。
