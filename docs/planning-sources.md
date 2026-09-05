# 实施规划的官方依据与核查边界

核查日期：2026-09-05。后端：官方网页（Web open/search）与本机 Apifox CLI 2.2.9 的 help/schema/list/get；Apifox 客户端只读状态用于确认 Spec 模式。论文依据沿用[选题证据](topic-evidence.md)，本轮未重新宣称新颖性检索完整覆盖。

| 来源 | 支持的具体事实 | 本项目据此作出的设计决定 |
| --- | --- | --- |
| [React 从零构建](https://react.dev/learn/build-a-react-app-from-scratch) | 可选择 Vite 等构建工具 | 本地SPA采用React/TS/Vite；具体依赖版本待锁定 |
| [FastAPI Background Tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/) | 框架提供响应后后台任务功能及适用讨论 | 长诊断选独立持久化worker，是本项目可靠性要求驱动的取舍 |
| [SQLite WAL](https://www.sqlite.org/wal.html) | WAL读写并行仍有单写者限制 | 单机单worker、短事务和显式失败；不声称无限扩展 |
| [Python logging](https://docs.python.org/3/library/logging.html) | 标准logging设施 | JSON日志、上下文字段、队列和脱敏是本项目规划 |
| [OpenTelemetry Python Instrumentation](https://opentelemetry.io/docs/languages/python/instrumentation/) | Python手动埋点、context和span | 自写Agent可使用通用OTel基础库 |
| [OpenTelemetry Exporters](https://opentelemetry.io/docs/languages/python/exporters/) | OTLP与导出配置 | 本地有界批处理、降级计数，业务账本独立 |
| [W3C Trace Context](https://www.w3.org/TR/trace-context/) | 标准跨服务上下文传播格式 | 合法traceparent透传，业务run和采集业务trace分开 |
| [百炼qwen-plus模型信息](https://help.aliyun.com/zh/model-studio/qwen-plus) | 北京快照qwen-plus-2025-12-01能力与阶梯价格 | 非思考、固定快照、限制12k输入；预算按0.8/2元每百万tokens |
| [百炼兼容API](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope) | OpenAI兼容HTTP调用协议 | 通过httpx直接封装；不使用Agent框架 |
| [百炼Function Calling](https://help.aliyun.com/zh/model-studio/qwen-function-calling) | 模型发起工具调用的协议 | 已核查可选路径；首版采用JSON提案+本地受控dispatch |
| [Apifox CLI命令](https://docs.apifox.com/doc-5637756) | 项目/接口/用例、schema校验、导入导出命令 | 用本机help校对字段，写后必须回读 |
| [Apifox OpenAPI导入](https://docs.apifox.com/import-openapi-swagger) | 支持OAS3.x；维护模式影响导入行为 | 导入前后对照真实操作数量 |
| [Apifox Spec模式](https://docs.apifox.com/9330582m0) | Git托管的规范文件生成接口；Beta | 保留用户已建的Git连接，通过Spec同步，避免误用普通endpoint-create |

## 本轮实际观察

- CLI能访问项目8800905；main未保护且允许自动化写入。仅记录所需布尔状态，不保存完整项目设置或令牌。
- 初始项目只有文档模块、零接口/测试，客户端展示Specs工作区；Git连接指向同一GitHub仓库，说明接口应从规范生成。
- 一次普通导入返回成功，但回读/导出路径为0，仅19个模型与1个本地环境创建；一次普通endpoint创建404。以上为工具链排查结果，不是API实现错误。后续结果见[Apifox记录](apifox/README.md)。
- `.env`仅核验BAILIAN_API存在且非空，已被Git忽略；没有任何模型请求。报价支持不等于密钥地域/权限已验证。

## 局限与后续核验

价格、模型可用性、CLI和Spec Beta行为可能变化；开始真实调用或升级工具后重新核对。当前不会保证容器资源占用、诊断质量或UI耗时，均在实施计划安排实测。系统设计中阈值、工时、预算余量与性能目标是工程假设，官方文档并没有证明其对本项目有效。
