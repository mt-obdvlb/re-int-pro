# 开发约定与环境准备

当前是文档阶段；下列内容是后续搭建约定，尚未安装依赖、创建应用或调用百炼。已检查本机为 Apple Silicon/16GB，uv、node、pnpm、Apifox CLI 可用；CLI版本2.2.9。实际应用兼容性待P1。

## 配置约定

| 配置 | 默认/来源 | 边界 |
| --- | --- | --- |
| BAILIAN_API | 用户现有根目录 `.env`，非空已确认 | 仅后端读取，绝不输出、复制到Apifox或VITE变量 |
| BAILIAN_BASE_URL | https://dashscope.aliyuncs.com/compatible-mode/v1 | 默认北京；密钥地域尚未验证，不从key字符串推断 |
| BAILIAN_MODEL | qwen-plus-2025-12-01 | 不用latest漂移；切模型重新冻结实验 |
| LLM_MODE | fake（P1/CI默认） | live仅在实施获批、预算和地域核验后启用 |
| PROBEOPS_DB_PATH | 本地运行目录下SQLite文件 | 不跟踪真实库；测试使用独立临时库 |
| PROBEOPS_SNAPSHOT_ROOT | 脱敏观测目录 | 不包含或挂载隐藏真值 |
| LOG_LEVEL | INFO | DEBUG也不得记录密钥/原始正文 |
| OTEL_EXPORTER_OTLP_ENDPOINT | 本地collector/Jaeger地址 | 本地开发；不把观测发到第三方云 |

P1创建`.env.example`时只写占位符并解释变量，不改现有`.env`。通过路径定位读取项目配置，不在shell中 `source .env` 执行其中内容。启动失败仅报缺哪个变量，不打印配置对象或密钥值。uv管理Python，pnpm管理前端，安装后提交对应锁文件。

## 日常开发顺序

先读阶段记录→本阶段需求/契约→当前Git差异；用小提交完成单一可验证行为。接口变更先更改Spec源和Apifox测试设计，后改FastAPI和前端类型。没有依据不引入Agent框架、消息中间件、云服务或训练工具。

运行命令随实际脚本落地补充，不写不存在的“开箱即用”。P1应提供：前后端启动、worker启动、实验依赖启停、FakeLLM smoke、OTel查看、Apifox本地测试、清理测试数据的独立命令。清理默认只作用于临时测试目录，正式观测归档不可被一条模糊命令删除。

## Git 与贡献记录

- 提交仅当前任务具体路径，commit采用docs/feat/fix/test等；推送已获用户授权，但每阶段仍需用户验收才继续。
- 原始日志、SQLite、运行报告、trace导出、`.env`、token文件不提交。P1补齐对应忽略规则，不因路径被忽略就免除凭据检查。
- 每个机制实现记录“问题→方案→对照→测量→结论”，保存关键代码链接和自己解释得清楚的设计；AI辅助内容不能自动算成本人已经掌握。
- 比较实验配置、提示模板版本与Git提交对应。修复影响实验行为时新开批次，不覆盖旧结果。

## 搭建前仍需确认的事实

地区/模型权限、实际usage字段、SDK无关的JSON格式输出稳定性、容器资源占用和Apifox runner的真实后端报告均为 **Unverified**。这些有明确P1/P2验收路径，不阻止规划交付，也不能在面试稿中写成已经通过。
