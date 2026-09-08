# 开发配置（当前版）

从仓库根目录运行；使用uv --no-editable，pnpm保留原锁文件。见 [启动命令](../README.md)。不要覆盖.env；BAILIAN_API仅后端SecretStr读取。配置对象与凭据不能输出到日志。

| 配置 | 默认/约束 |
| --- | --- |
| LLM_MODE | fake 或 bailian，默认fake |
| BAILIAN_MODEL | qwen-plus-2025-12-01固定快照 |
| BAILIAN_BASE_URL | 北京兼容接口白名单 |
| PROBEOPS_SNAPSHOT_DIR | data/snapshots |
| PROBEOPS_DB_PATH | .runtime/probeops.sqlite3；真实调用共用账本 |
| PROBEOPS_TELEMETRY_DIR | .runtime/telemetry |
| PROBEOPS_SPEND_CAP_MICRO_CNY | 默认1000000；最大450000000 |
| OTLP_ENDPOINT | 空或http://127.0.0.1:4318/v1/traces |
| LOG_LEVEL | DEBUG/INFO/WARNING/ERROR，默认INFO |
| FAKE_DELAY_SECONDS | 默认0.8，范围0..5 |

scripts/dev.py --mode选择模式，--tracing启用本地OTLP。不会改写.env。API/worker重启后加载新wheel；源码变化后uv会按cache-keys重新构建包，运行中的进程不会自动重新导入后端。前端Vite热更新。

## 本机 editable 包兼容性

2026-09-07确认：本机 `_probeops.pth` 被反复设置macOS `UF_HIDDEN`，Python3.12.13的`site.addpackage`会跳过隐藏`.pth`。清除属性后暂时恢复，但下一次检查又出现；设置属性的程序尚未确认，因此没有更改全局隐藏文件行为或Python安全检查。

项目采用 `uv sync --no-editable --frozen` 与 `uv run --no-editable ...` 进行普通wheel安装，避免依赖editable路径文件。`pyproject.toml` 的uv cache-keys追踪backend下Python源码，修改后自动重新构建。配置与契约从仓库根目录解析，不从site-packages位置推断；所有README命令须在仓库根目录执行。CI通过 `UV_NO_EDITABLE=1` 验证同一路径。

依据：[uv同步与非editable安装](https://docs.astral.sh/uv/concepts/projects/sync/#editable-installation)、[uv缓存依赖规则](https://docs.astral.sh/uv/concepts/cache/#dynamic-metadata)；实际参数已通过本机`uv help sync/run`和真实安装核验。

直接运行不带参数的 `uv run` 可能把项目重新同步为editable；请遵循README命令。依赖锁与包管理器没有更换，不需要反复chflags或临时PYTHONPATH。

## Git 与贡献记录

用户授权按模块连续实现、统一验收和合理推送。仅暂存当前任务具体路径。原始日志、SQLite、真值、.env不提交。AI辅助代码不自动等于本人已掌握；讲稿中的本人贡献必须逐项核对。

北京模型权限和usage已通过真实开发集调用验证；当前测试结果见 [验收](full-validation.md)。正式配对实验、供应商账单对账、生产运行仍未验证。
