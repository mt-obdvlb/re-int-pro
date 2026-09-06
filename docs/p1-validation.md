# P1 基础搭建验收

日期：2026-09-06。用户明确要求“真正搭建项目”，本轮执行 P1；**P2 尚待批准**。

## 当前可以运行的内容

- React/TypeScript/Vite 工作台：真实空态、新建限制表单、运行分页与筛选、详情、事件、证据、未知结论报告、取消、错误重试、主题切换、移动布局与使用说明。
- FastAPI 提供契约中的 12 个 HTTP 操作；P1 strategies 只列出 fixed，其他已规划策略创建返回503。OpenAPI仍以 `docs/api/openapi.json` 为唯一源，前端类型从它生成。
- 自写 Python FakeLLM→模拟 metrics 流程，无 Agent 框架，无网络模型调用；完整报告始终 unresolved。
- SQLite WAL，显式事务、幂等创建、单 worker 原子领取、5秒心跳/20秒租约、单调事件与证据序号；取消后不启动新探测，过期 worker 标记失败且不重放。
- logging dictConfig/contextvars/有界队列/轮转；OTel API→run Link、worker→step→LLM/tool/storage 子链；本地 JSONL exporter，失败计数与受控日志。
- 根 uv.lock、前端 pnpm-lock.yaml、最小 GitHub Actions；`.env.example`、三进程启动与 trace 查询脚本。

## 验证证据

| 检查 | 命令/方法 | 结果与边界 |
| --- | --- | --- |
| 后端集成 | `uv run pytest -q` | 9项通过：正常闭环与12操作响应/路径契约、并发幂等与领取、排队/执行取消、deadline/租约恢复、分页/错误/脱敏、trace父子关系、工具失败、路由覆盖、exporter失败不阻断 |
| Python 类型/规范 | `uv run mypy`；`uv run ruff check backend scripts`；`uv run ruff format --check backend scripts` | 通过 |
| 前端行为 | `pnpm --dir frontend test` | 1项通过：网络结果不明确时重试复用相同幂等键和正文，成功后清除待确认请求 |
| 前端工程 | typecheck、lint、format:check、generate:api、build | 通过；不使用运行时手写假记录替代API |
| Apifox真实请求 | project8800905/main，case411147565，environment48818912 | 1请求/3断言/0失败；本机FastAPI，未使用Mock，未上传报告 |
| 浏览器 | Codex IAB，现有默认视口、1536×1024、390×844 | 空态→新建→完成→证据/报告、刷新回读、取消→已取消、筛选空态、说明页、弹窗返回、深浅主题通过 |
| 移动溢出 | 浏览器只读 DOM 测量 | viewport390，clientWidth=scrollWidth=375（滚动条占15px）；表格内部横向滚动，不撑开页面 |
| 脱敏 | 哨兵异常/非法请求、源码与本地产物检查 | 不回显哨兵原文；`.env`未修改、未跟踪，前端未接入BAILIAN_API |

Python依赖当前有2条上游弃用警告（Starlette TestClient/httpx、AnyIO BlockingPortal），不影响断言；没有用过滤配置掩盖警告。CI配置已落地；远程执行结果以Actions页面为准，本地通过不冒充云端通过。

Apifox最终原始报告：`.runtime/apifox/p1-health-final.json`（忽略，不提交）；1次请求13ms，只是单次测量，不能声称满足整体性能目标。其他14个既有单接口用例未执行；真实完整API场景在P3/P4验收。

浏览器真实运行例：`run_c06dd02275684d37` 为 completed/unresolved；`run_bc0ee1637ce74add` 为 cancelled，取消后probe_count=0。记录位于本地数据库，不作为分发fixture，也不填入正式面试效果数据。

租约恢复测试通过显式设置过期租约模拟失联，不声称已经做过所有SIGKILL/文件系统故障组合。测试使用独立临时库；本地演示数据跨服务重启回读已确认。

## 视觉对照

内置 Image Gen 生成 [设计稿](design/p1-workspace-concept.png)，再实现代码原生组件。IAB 的高层截图在移动视口被缩小到98×211，因此使用同一个IAB页的CDP `Page.captureScreenshot` 保存原分辨率；没有转到外部浏览器或改造截图。使用 `view_image` 查看概念图和最终桌面截图，并单独检查移动截图。

- [最终桌面](design/p1-workspace-actual.png)：1536×1024，scrollY=0。
- [移动深色](design/p1-mobile-actual.png)：390×844。

| 对照项 | 实现与设计稿 |
| --- | --- |
| 容器结构 | 左导航、开放中央工作区、右上下文；无营销hero与卡片拼贴 |
| 颜色 | 冷灰底、深色正文、青绿色唯一强调；深色采用同一层级 |
| 字体 | Geist本地字体/系统中文；正文与表格14–16px，ID等宽；比生成稿的部分大字更紧凑，适配真实长ID |
| 导航与标题 | 三项导航、工作空间面包屑、诊断工作台、告警场景、新建按钮保持位置和语义 |
| 列表 | 四列与淡青选中行、状态图标、零费用；增加真实创建时间帮助区分记录 |
| 详情 | 过程/证据/报告保留；真实7条事件比概念4条多，允许页面纵向滚动，不删除持久化事件配合截图 |
| 右栏 | FakeLLM与三项上限按实际选中运行显示；说明当前不提供真实根因判断 |
| 交互 | 新建、取消、筛选、分页、错误、复制、主题均为真实控件；移动表格局部滚动，导航改横排 |

文案差异为具体功能需求：模拟数据标签、未知报告、真实时间和ID、worker排队提示、取消与连接错误，不增加营销文案。概念中的820ms以明确“模拟观测”放在证据页，不在未探测前显示。没有为了达到三条记录预置假API响应。

## 当前限制与下一关

P1验证的是架构闭环，不是竞争假设机制的有效性。真实观测环境/四类工具（P2）、百炼HTTP适配/成本账本/机制与六种策略（P3）、完整用例和产品验收（P4）、实验和正式面试材料（P5/P6）尚未完成。
目前OTel只导出本地JSONL；Jaeger/OTLP、provider429重试与uncertain费用、按天日志清理和指标面板仍待后续。服务只绑定本机，无多用户鉴权或公共部署。本轮百炼调用0次、API费用0元；内置设计图生成不是百炼调用。

当前在现有Git工作区安装editable包时曾遇到自动路径推断遗漏backend，已显式设置Hatch `dev-mode-dirs=["backend"]`并重装、连续uv运行验证；不依赖临时PYTHONPATH。pnpm按本机版本固定11.5.1，仅放行esbuild构建脚本。

## 官方依据（2026-09-06核查）

- [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/)：API资源生命周期与后台恢复任务。
- [OpenTelemetry Python instrumentation](https://opentelemetry.io/docs/languages/python/instrumentation/)：显式tracer、context、span与异常边界。
- [Vite guide](https://vite.dev/guide/)：本地SPA开发和生产构建。
- [pnpm settings](https://pnpm.io/settings)：构建脚本allowBuilds配置；实际命令表面以11.5.1验证。
- [Apifox CLI官方文档](https://docs.apifox.com/apifox-cli)：配合本机2.2.9的run/environment help、schema与回读。

完成本轮提交/推送后停止，等待用户验收批准P2，不自动搭建故障实验环境。
