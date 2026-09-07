# 开发约定与环境准备

当前 P1 已搭建：Python3.12/uv、React/TypeScript/Vite/pnpm、FastAPI、SQLite worker 与本地 OTel。未调用百炼。实际安装、启动、测试命令见 [README](../README.md)，验证边界见 [P1记录](p1-validation.md)。Apifox CLI 2.2.9。

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

P1 已创建 `.env.example`，没有修改现有 `.env`。通过路径定位读取项目配置，不在 shell 中 `source .env` 执行内容。配置失败只返回固定安全提示，不打印配置对象或密钥值。uv 管理 Python，pnpm 管理前端，两个锁文件随提交维护。

## 日常开发顺序

先读阶段记录→本阶段需求/契约→当前Git差异；用小提交完成单一可验证行为。接口变更先更改Spec源和Apifox测试设计，后改FastAPI和前端类型。没有依据不引入Agent框架、消息中间件、云服务或训练工具。

`uv run --no-editable python scripts/dev.py` 启停本次启动的三项本地服务；端口 5173/8000。`FAKE_DELAY_SECONDS=5 uv run --no-editable python scripts/dev.py` 可放慢演示便于取消观察，默认0.8秒。`scripts/trace.py` 查询链路。pytest 使用独立临时目录，不删除真实运行。P1 不需要实验依赖，容器启停在 P2 落地；不提供模糊清库命令。

## 本机 editable 包兼容性

2026-09-07确认：本机 `_probeops.pth` 被反复设置macOS `UF_HIDDEN`，Python3.12.13的`site.addpackage`会跳过隐藏`.pth`。清除属性后暂时恢复，但下一次检查又出现；设置属性的程序尚未确认，因此没有更改全局隐藏文件行为或Python安全检查。

项目采用 `uv sync --no-editable --frozen` 与 `uv run --no-editable ...` 进行普通wheel安装，避免依赖editable路径文件。`pyproject.toml` 的uv cache-keys追踪backend下Python源码，修改后自动重新构建。配置与契约从仓库根目录解析，不从site-packages位置推断；所有README命令须在仓库根目录执行。CI通过 `UV_NO_EDITABLE=1` 验证同一路径。

依据：[uv同步与非editable安装](https://docs.astral.sh/uv/concepts/projects/sync/#editable-installation)、[uv缓存依赖规则](https://docs.astral.sh/uv/concepts/cache/#dynamic-metadata)；实际参数已通过本机`uv help sync/run`和真实安装核验。

直接运行不带参数的 `uv run` 可能把项目重新同步为editable；请遵循README命令。依赖锁与包管理器没有更换，不需要反复chflags或临时PYTHONPATH。

## Git 与贡献记录

- 提交仅当前任务具体路径，commit采用docs/feat/fix/test等；推送已获用户授权，但每阶段仍需用户验收才继续。
- 原始日志、SQLite、运行报告、trace导出、`.env`、token文件不提交。P1补齐对应忽略规则，不因路径被忽略就免除凭据检查。
- 每个机制实现记录“问题→方案→对照→测量→结论”，保存关键代码链接和自己解释得清楚的设计；AI辅助内容不能自动算成本人已经掌握。
- 比较实验配置、提示模板版本与Git提交对应。修复影响实验行为时新开批次，不覆盖旧结果。

## 搭建前仍需确认的事实

地区/模型权限、实际 usage、模型 JSON 输出稳定性、容器资源占用仍为 **Unverified**，按 P2/P3 核验。Apifox health 已有真实后端报告；其他接口、测试矩阵和性能承诺不能据此一并宣布通过。
