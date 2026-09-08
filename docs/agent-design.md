# Agent 机制、工具与百炼

2026-09-08：代码为 engine.py / reasoning.py / observations.py / provider.py。Agent循环由Python自写，不使用Agent框架。

## 可检验的机制

模型先提出1–4个候选，每个候选必须对全部10个probe填写high/normal/low/unknown预测，构成交叉预测矩阵。Pydantic拒绝漏项、重复项、非法组件/故障族、额外字段与不可用next_probe。分数、证据ID、结论不由模型填写。

对于尚未被反驳的候选对，如果对同一probe预测不同且都非unknown，则为D增加1。竞争策略选 U(q)=D(q)/(c(q)+0.1) 最大的probe，同分按成本和ID稳定排序。c来自开发集校准文件，公式p50网关毫秒/100+p50摘要字节/4096，最低0.1。这是本地快照访问和结果体积代理，不是实际线上调用费，也不是统计信息增益。

观测回来后重算支持+1、反驳−2，分数限制[-20,20]。unknown和非ok不打分。定位必须同时满足：至少两类工具通道提供异常匹配支持、领先分差≥2、无直接反驳、非unknown故障。正常观测匹配只加分，不能单独建立故障。两类通道不保证统计独立，同一请求的日志和trace可能相关；支持分数不是概率，也不证明因果。

原候选全部反驳时最多重建一次，重新用已有证据校验。证据充分停止；两次unknown观测、竞争候选全部D=0、无剩余probe、预算/步数/调用/时限也终止并保留unresolved。探测开始即计入次数和成本，超时不会漏计。模型不能自行宣布成功。

## 六策略的具体差异

| ID | 行为 |
| --- | --- |
| competitive_cost | D/(c+0.1)，显式候选竞争与成本 |
| no_cost | 最大D，去掉成本项的消融 |
| random_probe | seed固定、剩余probe均匀随机 |
| fixed | metrics→logs→trace→config固定顺序，最后模型提案仍需程序验证 |
| react | 首轮提案，此后每步模型根据已观察结果选择next_probe |
| graph_greedy | 根据当前最高分候选组件及预定义邻域选probe |

六策略共享模型、工具、停止验证器和预算。react/graph_greedy是受启发的简化基线，不是论文完整复现。fixed也会提前满足共同停止条件，并非强制穷尽；比较时必须注明。

[Lindley的信息价值](https://doi.org/10.1214/aoms/1177728069) 支持按信息价值选择观测的思路；由于没有校准先验/似然，此处用候选区分代理，不能声称实现精确贝叶斯或最优熵降低。[ReAct](https://arxiv.org/abs/2210.03629) 支持行动与反馈循环，[RCAgent](https://arxiv.org/abs/2310.16340) 提供诊断近邻。完整研究来源保留在 [选题证据](topic-evidence.md)，机制优势仍待同预算实验。

## 有限只读工具

| 工具 | 实际probe | 聚合 |
| --- | --- | --- |
| query_metrics | api_latency、pool_wait、queue_depth、cache_latency | 有限120点，mean超过阈值为high |
| query_logs | pool_events、queue_events、cache_events、config_events | 匹配事件存在为high，最多50条 |
| get_trace | request_trace | 第一条采集请求，不能视为平均或最慢请求 |
| read_config | timeout_config | request_timeout_ms：<100 low、100..1000 normal、>1000 high |

参数是代码拥有的probe ID，服务/指标/窗口从目录与快照派生，不让模型传任意路径、网络地址或SQL。快照≤2MB、工具结果≤32KB，较长日志摘要保留数量和前三条；真正超界标记truncated/unknown。缺少数据是empty/unknown，不伪装normal。每次运行按快照+probe哈希去重。

工具是本地只读快照读取，不存在在线网络transient重试；错误交worker记录failed，5秒工具时限受总deadline约束。故障注入、标签和评测控制器不作为Agent工具。

## 百炼与费用

实际已接通北京兼容接口，固定qwen-plus-2025-12-01、temperature=0、enable_thinking=false、JSON object、非流式httpx。提示proposal-v2要求完整交叉预测；每次尝试按UTF-8字节+256保守估计输入≤12000，输出≤2000，实际usage和模型标识回读校验。不是正式tokenizer上界证明，遇到usage超估计则标记PROVIDER_DRIFT并停止，保留已发生费用。

connect/pool5秒、read/write30秒、总wall deadline限制await。429/5xx最多总3次尝试，指数退避+jitter，Retry-After最多10秒；401等不可重试错误停止。结构错误最多一次修正，包含在总3次中。所有尝试计入调用上限；取消在途请求不能撤销供应商费用。

2026-09-07核对 [官方模型页](https://help.aliyun.com/zh/model-studio/qwen-plus) 与 [兼容接口](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope)：当前本项目价格常数为输入0.8元/百万、输出2元/百万token。每次预留13600 micro CNY，再按usage向上取整结算，失败无usage→uncertain保留。价格变更需更新冻结版本后重新验证。

默认操作限额1元；项目准入450元、总预算500元，单运行最高0.25元。SQLite事务同时检查全局与单运行限额；charge_events只追加，reconcile必须提供账单依据，仅调整uncertain，不覆盖原流水。系统仅保证本账本调用的准入，不保证共享账号其他应用费用。详见 [预算与评测](evaluation-plan.md)。
