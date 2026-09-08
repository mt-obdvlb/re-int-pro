# 观测数据与复现

snapshots/ 为6份演示快照，benchmark/ 为80份冻结受控快照；manifest.json存哈希/split，costs.json存开发集成本校准。数据来自本项目合成结算服务，不含用户数据。只能说明受控故障现象。

Agent读取快照，不读取.runtime/evaluator/truth.jsonl。Git不提交标签和注入配置；因此新克隆可直接演示/单元测试，若要独立评分须重新采集一套自己的观测和真值，不能凭文件名猜标签。当前已提交数据的数值哈希可验证，但另一台机器重新采集不会得到相同耗时和哈希。

所有命令在仓库根目录执行，选择未存在的新目录，不覆盖已冻结数据：

```bash
uv sync --no-editable --frozen --group lab
docker compose -f lab/compose.yaml up -d --wait
uv run --no-editable python lab/capture.py --suite full --output .runtime/repro/benchmark
uv run --no-editable python evaluation/freeze.py --snapshots .runtime/repro/benchmark
PROBEOPS_DB_PATH=.runtime/repro/offline.sqlite3 uv run --no-editable python evaluation/run.py --snapshots .runtime/repro/benchmark --mode fake --split test --repeats 3 --output .runtime/repro/fake.jsonl
uv run --no-editable python evaluation/summarize.py .runtime/repro/fake.jsonl --output .runtime/repro/summary.json
```

控制器启动8011服务与独立任务进程，连接15432 PostgreSQL/16379 Redis，逐例复位自有control/jobs键；文件锁防止重叠采集。默认真值路径.runtime/evaluator/truth.jsonl追加新ID，评分会过滤当前目录存在的ID并核对哈希。freeze只允许新manifest/costs文件。

交互worker不能与同一费用库的批次worker同时运行；付费批次务必使用原费用库，不要使用上面的离线独立DB覆盖。模式bailian会消费额度；当前真实预算1元，完整主实验未运行。更多边界和结果见 [评测说明](../docs/evaluation-plan.md)。
