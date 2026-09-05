# 选题证据与检索记录

> 阶段更新（2026-09-05）：用户已选择T1。本文保留选题时的调研/预演记录；实施栈、百炼预算与后续范围以[当前阶段记录](project-plan.md)及其链接文档为准。所有未实测成果仍为待验证假设。

检索与核验日期：2026-09-05（Asia/Shanghai）。服务于第 2 步选题，不代表完成创新性证明、软件复现或效果实验。

阅读入口：[候选分析](topic-research.md) · [逐题面试稿](topic-interview-scripts.md)。

## 1. 来源与覆盖边界

本次使用 `paper-search` 多源检索、Academic Research 的 OpenAlex 检索、Exa 语义搜索、普通网页检索、Agent Reach 路由的 Jina Reader 正文提取，以及 `gh` 核查官方仓库。学术记录最终以 arXiv、论文出版方和 Crossref 元数据为准；工程事实以官方 README、数据卡和许可证为准。

`paper-search` 的 Semantic Scholar 返回 429，DBLP 返回 503，未把这两路视为成功覆盖。多源结果存在跑题记录，OpenAlex 返回的一条 LongMemEval 摘要还混入其他项目内容，已用 arXiv 正文纠正。Jina 提取 ALCE 时出现 SSL EOF，改用直接网页读取成功。RCAgent 的 ACM DOI 落地页在自动链接检查中返回 403，已通过 Crossref 核对题名和 CIKM 出版信息，并提供可访问的 arXiv 版本。搜索命中只用来定位，未将博客、聚合页和搜索摘要作为核心结论的唯一依据。

覆盖经典方法及截至检索日找到的 2025–2026 年近邻工作。不是系统综述，没有穷尽全部论文、代码或非英语材料；尤其不证明任何候选“全球首创”。未下载大规模数据、运行第三方项目、调用付费模型或检查用户账号额度。

### 实际查询与筛选轨迹

| 方向 | 使用过的查询表达 | 结果如何影响选题 |
| --- | --- | --- |
| 云诊断 | `LLM agent active diagnosis information gain root cause AIOpsLab`；`2025 2026 research root cause analysis agent active probing information gain tool selection`；`根因 Agent 主动探测 论文` | 确认 RCAgent、AIOpsLab 和 2026 年图引导诊断/轨迹评价；排除“首次用 Agent 查日志”的表述 |
| SQL | `text to SQL agent ambiguity clarification CHESS BIRD`；`text to SQL ambiguity clarification execution results counterexample information gain 2026`；`SQL Agent 澄清 反例` | 发现 AmbiSQL、EIG-SQL、SOMA-SQL，放弃把澄清、信息增益或执行探针单独包装为新方法 |
| 记忆 | `LongMemEval memory update temporal reasoning agents`；`agent memory invalidation dependency provenance temporal Zep Mem0 2025 2026`；`智能体 记忆 依赖 失效` | 发现 Zep、MemState，并从官方仓库追到 LongMemEval-V2；缩小到有预算约束的受影响计划修订 |
| 修复 | `2025 2026 software repair agent discriminative test generation overfitting patch validation SWE agent research`；`SWE agent SWE bench EvalPlus arxiv` | 发现修复与复现测试协同生成已有工作；聚焦测试预算分配并保留独立判定器 |
| 文献 | `ALCE SciFact PaperQA2 language model evidence research agent paper`；`Language Agents Achieve Superhuman Synthesis arxiv` | 确认引用核查、矛盾发现均已有工作；进一步纳入 2026 年验证器可靠性研究 |
| 其他方向 | `agent benchmarks data analysis InfiAgent DABench browser WebArena travel TravelPlanner OSWorld`；`TravelPlanner WebArena OSWorld AgentBench official benchmark GitHub` | 用数据分析、旅行规划与通用环境的公开资料辅助初筛；未将未深入检索的方向认定为没有创新空间 |
| 理论与价格 | `Lindley On a Measure of the Information Provided by an Experiment 1956 10.1214`；百炼模型定价；DeepSeek 官方价格页 | Crossref 校验经典信息量论文；最终预算采用有人民币表格、支持工具调用的 DeepSeek 官方报价 |

## 2. 核心论文登记

“支持”仅指支撑问题设定或机制来源，不代表论文验证了本项目拟议改进。日期以首发年份为主；版本差异单独注明。

| ID | 年份 / 状态 | 论文与来源 | 关键词 | 支持的内容与边界 |
| --- | --- | --- | --- | --- |
| P01 | 1956，Annals of Mathematical Statistics 27(4):986–1005 | Lindley, [On a Measure of the Information Provided by an Experiment](https://doi.org/10.1214/aoms/1177728069) | 实验设计；信息量 | 信息收集应考虑预期不确定性下降。DOI、期刊和页码经 Crossref 核验；不是任意 LLM 评分的最优性证明 |
| P02 | 2022 首发，ICLR 2023 | Yao et al., [ReAct: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629) | 推理；动作；反馈 | 支撑工具交互闭环；用作共同基线，不作为本项目创新 |
| P03 | 2023 首发，CIKM 2024 | Wang et al., [RCAgent: Cloud Root Cause Analysis by Autonomous Agents with Tool-Augmented Large Language Models](https://doi.org/10.1145/3627673.3680016)；[arXiv](https://arxiv.org/abs/2310.16340) | 云诊断；工具；轨迹 | 工具增强的自主根因分析已经存在；其工业数据和内部模型不等于可直接低成本复现 |
| P04 | 2025，MLSys | Chen et al., [AIOpsLab: A Holistic Framework to Evaluate AI Agents for Enabling Autonomous Clouds](https://arxiv.org/abs/2501.06706)；[会议记录](https://proceedings.mlsys.org/paper_files/paper/2025/hash/d1f9e4a9f109b6e8b75ed362736f22ec-Abstract-Conference.html) | 故障注入；遥测；评测 | 支撑环境、任务和独立故障标签分离；本项目小型实验环境不是官方 AIOpsLab 成绩 |
| P05 | 2026，预印本 | [GALA: Graph-Augmented LLM Agents for Root Cause Analysis and Incident Response in Microservices](https://arxiv.org/abs/2608.08968) | 依赖图；诊断 | 图引导探查已有直接近邻，T1 必须比较图引导基线 |
| P06 | 2026，预印本 | [Beyond Fault Localization: A Trajectory-Level Study of LLM Agents for Microservice Root Cause Analysis](https://arxiv.org/abs/2608.21310) | 轨迹；传播路径 | 不能把记录诊断过程本身作为创新；过程证据需与最终正确率分别评价 |
| P07 | 2023，EMNLP | Bhaskar et al., [Benchmarking and Improving Text-to-SQL Generation under Ambiguity](https://arxiv.org/abs/2310.13659) | AmbiQT；多解释 | 支撑语义不同的候选集合；字符串多样性不等于解释多样性 |
| P08 | 2025 首发，2026-03 修订 v2 | Ding et al., [AmbiSQL: Interactive Ambiguity Detection and Resolution for Text-to-SQL](https://arxiv.org/abs/2508.15276) | 澄清；歧义分类 | 直接近邻：交互式多选澄清已存在；不沿用旧版摘要的性能数字 |
| P09 | 2025，预印本 | Qiu et al., [Interactive Text-to-SQL via Expected Information Gain for Disambiguation](https://arxiv.org/abs/2507.06467) | 信息增益；提问 | 按信息增益选择澄清问题已有直接研究，不是 T2 的新贡献 |
| P10 | 2026，预印本 | Somayajula et al., [SOMA-SQL: Resolving Multi-Source Ambiguity in NL-to-SQL via Synthetic Log and Execution Probing](https://arxiv.org/abs/2606.11424) | 执行探针；候选分歧 | 自动探测数据库消歧已有直接研究；T2 聚焦何时仍需问用户，不宣称发明探针 |
| P11 | 2025 首发，ICLR 2026 Oral | Huo et al., [BIRD-INTERACT: Re-imagining Text-to-SQL Evaluation for Large Language Models via Lens of Dynamic Interactions](https://arxiv.org/abs/2510.05318) | 动态交互；用户模拟 | 提供交互环境和任务资源；完整任务覆盖 CRUD，不能用只读子集冒充全榜结果 |
| P12 | 2024 首发，ICLR 2025 | Wu et al., [LongMemEval: Benchmarking Chat Assistants on Long-Term Interactive Memory](https://arxiv.org/abs/2410.10813) | 时间；更新；拒答 | 支撑记忆能力分项评估；2025 cleaned 数据替代早期版本 |
| P13 | 2025，预印本 | Rasmussen et al., [Zep: A Temporal Knowledge Graph Architecture for Agent Memory](https://arxiv.org/abs/2501.13956) | 双时态；失效 | 动态事实、来源与历史处理已有实现；不能称“记忆带时间戳”为创新 |
| P14 | 2026，预印本 | Orogat & Mansour, [Is Agent Memory a Database? Rethinking Data Foundations for Long-Term AI Agent Memory](https://arxiv.org/abs/2605.26252) | GEM；MemState；语义修订 | 直接讨论跨依赖修订；T3 不能宣称首次提出依赖传播。已读摘要及相关方法片段，未复现其原型 |
| P15 | 2024，NeurIPS | Yang et al., [SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering](https://arxiv.org/abs/2405.15793) | 修复；工具接口 | 支撑代码编辑、执行反馈与 Agent 接口设计，不能把“会运行测试”作为创新 |
| P16 | 2023，NeurIPS | Liu et al., [Is Your Code Generated by ChatGPT Really Correct? Rigorous Evaluation of Large Language Models for Code Generation](https://arxiv.org/abs/2305.01210) | EvalPlus；测试充分性 | 支撑隐藏扩展测试和变异测试；函数生成基准改造成修复任务后必须另行命名 |
| P17 | 2026，预印本，已读 v3 | Cheng et al., [Dynamic Cogeneration of Bug Reproduction Test in Agentic Program Repair](https://arxiv.org/abs/2601.19066) | 协同生成；补丁选择 | 修复与测试共同生成、测试感知补丁选择已经存在；其 Google 内部缺陷集不可作为本项目默认数据 |
| P18 | 2020，EMNLP | Wadden et al., [Fact or Fiction: Verifying Scientific Claims](https://arxiv.org/abs/2004.14974) | SciFact；支持；反驳 | 提供有人工标签的主张与证据；领域以科学文献为主，不等于通用 CS 文献事实库 |
| P19 | 2023，EMNLP | Gao et al., [Enabling Large Language Models to Generate Text with Citations](https://arxiv.org/abs/2305.14627) | ALCE；引用质量 | 区分流畅度、答案正确性与引用质量；三者不能相互替代 |
| P20 | 2024，预印本 | Skarlinski et al., [Language agents achieve superhuman synthesis of scientific knowledge](https://arxiv.org/abs/2409.13740) | PaperQA2；文献；矛盾 | 检索、证据聚合与矛盾发现已有成熟近邻；其论文标题不构成本项目能力声明 |
| P21 | 2026，预印本 | [Evaluating and Guarding Citation Faithfulness in Agentic Scientific Synthesis](https://arxiv.org/abs/2607.20527) | 验证器；校准；引用 | 引用核查器本身可能不可靠；T5 不将一个模型的判决当作真值，也不借用其统计保证 |

## 3. 官方实现与数据可获得性

已执行仓库读取和 README 检查；“可访问”不等于“本机运行通过”。许可证为检索日快照，实际引入时固定版本并保留对应声明。本轮只添加链接，不复制第三方代码或数据。

| 对象 | 核验结果 | 对选题的影响 |
| --- | --- | --- |
| [AIOpsLab](https://github.com/microsoft/AIOpsLab) | 仓库 MIT；README 要求 Python、Helm 等，提供 kind 路线；[本地部署说明](https://github.com/microsoft/AIOpsLab/blob/main/kind/README.md)列出已验证的 Ubuntu / WSL2 环境 | macOS 全套运行 **Unverified**。T1 先用小型可控服务系统，不把 Kubernetes 部署作为最小交付前提 |
| [AmbiSQL](https://github.com/JustinzjDing/AmbiSQL) | Apache-2.0；有后端、前端与 BIRD minidev 下载说明 | 可参考交互基线；本项目不直接沿用其安装命令，也不默认第三方数据继承代码许可 |
| [BIRD-Interact](https://github.com/bird-bench/BIRD-Interact) / [Lite 数据卡](https://huggingface.co/datasets/birdsql/bird-interact-lite) | 仓库代码显示 MIT，数据卡为 CC-BY-SA-4.0；官方提示 Docker 加载失败可能产生空数据库 | 评测前检查表和行数；只读子集单独报告，数据衍生物保留许可与归属 |
| [LongMemEval](https://github.com/xiaowu0162/LongMemEval) / [cleaned 数据卡](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned) | 代码和数据卡 MIT；原 S 设置每条历史约 115k tokens，仅为特定 tokenizer 下量级；oracle 文件直接提供证据会话 | T3 默认小型自建事件任务，加 20 条 cleaned 外部检查；oracle 文件不能提供给正式 Agent |
| [LongMemEval-V2](https://github.com/xiaowu0162/LongMemEval-V2) | 已读官方 README：2026 年版本、451 问、web/enterprise 域、大规模多模态轨迹 | 作为近邻和扩展入口，不声称旧版仍是最新；全量 V2 不纳入 500 元最小方案 |
| [Graphiti](https://github.com/getzep/graphiti) | Apache-2.0；README 明确历史、来源、双时态与事实失效，需图后端 | T3 的时间感知基线。适配和 API 兼容性 **Unverified**，不能声称已复现 Zep 论文 |
| [Mem0](https://github.com/mem0ai/mem0) | 仓库可访问，Apache-2.0 | 作为原子事实维护的实现参照；本轮仅元数据核查，不对其内部行为作全面断言 |
| [SWE-agent](https://github.com/SWE-agent/SWE-agent) | 仓库可访问，MIT | 修复 Agent 参照；不把全量真实仓库修复纳入 T4 最小范围 |
| [EvalPlus](https://github.com/evalplus/evalplus) | Apache-2.0；README 提供 HumanEval+ / MBPP+ 和 Docker 评测路线 | T4 可基于规范构造受控缺陷；隐藏测试必须放在 Agent 不可读的位置 |
| [PaperQA](https://github.com/Future-House/paper-qa) | Apache-2.0；README 提供检索问答接口和模型配置，历史版本对象存在兼容差异 | T5 比较其方法思想或固定版本适配，不能把当前包等同于 PaperQA2 原论文设置 |
| [SciFact](https://github.com/allenai/scifact) | [LICENSE.md](https://github.com/allenai/scifact/blob/master/LICENSE.md)：主张和证据标注 CC-BY-4.0，摘要 ODC-By-1.0，代码 Apache-2.0；train/dev 有标签、test 无公开标签 | T5 用 train 调参、dev 封存评测；不把无标签 test 当作可直接计算正确率的集合 |
| [InfiAgent-DABench](https://infiagent.github.io/) / [仓库](https://github.com/InfiAgent/InfiAgent) | 已读官方页面和 README；版本间题数有差异 | 支撑初筛中数据分析方向的可评测性，不采用未经版本固定的题目总数 |
| [TravelPlanner](https://github.com/OSU-NLP-Group/TravelPlanner) / [AgentBench](https://github.com/THUDM/AgentBench) | 检索读到官方说明：旅行约束规划、跨环境 Agent 任务均已有基准 | 初筛参照；未做全量运行和依赖审计 |

为便于追踪本次阅读版本，关键 README blob SHA：AIOpsLab `53a1921c6d9a83f9611fdbbad2942a2be329424b`；AmbiSQL `2f98ca4a64dddd35f7f4b83e64b1b9c5c79c60bc`；BIRD-Interact `eee5522a04e4ffeca22d59e9c73f9122379b8c40`；LongMemEval `3490db4f796c14903788ecb3e33f056cab438bb0`；Graphiti `a426f3482b963b0986577a96732e1896ca82b871`；EvalPlus `511e305c214578700e09e454e03581c9ccac87a5`；PaperQA `0b5639921586f03bd1f9d93445af9e0d17f37c48`；SciFact `b483bc1102536ce1e58b4a4794a567abb66d78f1`。这是文档对象指纹，不是运行版本或锁定的依赖提交。

## 4. 价格与预算依据

2026-09-05 读取 [DeepSeek 官方人民币价格页](https://api-docs.deepseek.com/zh-cn/quick_start/pricing)：`deepseek-v4-flash` 对应页面版本 DeepSeek-V4-Flash-0731，支持工具调用与 JSON 输出；高峰、缓存未命中输入 **3 元 / 百万 tokens**，输出 **9 元 / 百万 tokens**。按此较保守情形估算，不扣免费额度、不算缓存折扣和空闲折扣。此为预算参照，不是最终技术选型；未做真实 API 调用。

若输入和输出量分别为 I、O（单位百万 tokens），费用估计 `C = 3I + 9O`。统计必须包含反复发送的历史、工具结果、模型输出及实际计费的思考内容；不能只数用户问题。重试与格式修复预留 25%，另留 150 元用于开发调试、少量模型对照和演示。

| 题目 | 正式评测输入上限 I | 输出上限 O | 基础估算 | 含 25% 余量及 150 元预留 | 距 500 元余量 |
| --- | ---: | ---: | ---: | ---: | ---: |
| T1 ProbeOps | 36 | 6 | 162 元 | 352.50 元 | 147.50 元 |
| T2 ClarifySQL | 24 | 4 | 108 元 | 285.00 元 | 215.00 元 |
| T3 MemoryLedger | 40 | 6 | 174 元 | 367.50 元 | 132.50 元 |
| T4 PatchArena | 40 | 8 | 192 元 | 390.00 元 | 110.00 元 |
| T5 EvidenceTrail | 32 | 6 | 150 元 | 337.50 元 | 162.50 元 |

这是**最终选中一题**的预算，不是同时实现五题的总预算。输入上限也包含记忆写入、所有基线和消融，正式方案的次数估计见候选报告。模型表现、每步实际 token 数及价格变化仍不确定，因此先用开发集测量单任务成本，再固定正式规模。达到 400 元停止扩大实验，500 元为总支出硬上限；并发时先预留在途请求最大费用。价格超出参照时按成本缩减任务或重复数并如实更新协议，不把缩减后的结果冒充原计划。

不租 GPU，不使用付费搜索作为正式评测必需项；本地 CPU、磁盘与人工时间不算入 API 预算，但计入工时及可行性风险。硬件资源未实测，全量第三方环境部署 **Unverified**。

## 5. 结论能说到哪里

可以说：这些问题有公开理论与工程参照，存在适合本科生深入实现、对照验证的受控方案。不能说：五题的改进已被证明有效、比所有现有方法先进、能保证论文产出或复试录取。

本次没有完成论文全部定理复核、所有仓库内部代码审计和第三方数据完整下载。题目确定后的相关阶段应固定论文版本、仓库版本、数据哈希、模型标识和实际计费，并以真实实验替换占位符；这不是提前进入后续步骤的授权。
