# Apifox 设计资产与同步记录

项目 `re-int-pro` / 8800905，main / 8592769；CLI 2.2.9；核查日期2026-09-05。

2026-09-06收尾复核：`test-case list` 返回15项。`project get` 的统计摘要仍显示接口/用例0，未能反映本次Spec生成接口与单接口用例；本记录的数量依据专用endpoint/test-case list、逐项get和OpenAPI导出，不使用项目摘要推断资源不存在。

现有项目是Git托管Spec模式，连接2190指向 `mt-obdvlb/re-int-pro`。契约源为 [docs/api/openapi.json](../api/openapi.json)。直接CLI导入曾保存19个数据模型和1个本地环境但未生成接口；直接endpoint创建404。已查明应通过Git同步Spec，未创建替代项目、未更改权限。

契约提交 `4a302a6` 推送后，现有 Git 同步生成 **12 个操作、19 个模型**。已通过 CLI 建立 **15 个独立 API 测试用例**；每个都经过 schema validate 和 get 回读，验证绑定ID、分类、正文、参数、前置脚本（如有）及断言。实际费用为本轮模型调用0元。

- [资源映射](resource-index.json)：12个endpoint ID、15个case ID和逐项验证状态。
- [用例设计快照](test-cases.json)：按operationId记录输入/预期，便于评审；不是直接导入的CLI payload。后续用例在Apifox维护后同步此快照，不能在两处独立修改。
- 将Apifox导出与仓库源规范化对照：19模型一致；12操作的方法/路径/operationId/参数required与schema/请求体/响应状态与schema一致。忽略UI扩展和描述性字段。

P0 时15个用例均未运行。P1 已启动真实 FastAPI 后端，并执行 API-01（411147565）：1次HTTP请求、3条断言、0失败；最终请求耗时13ms只是单次观测，不是性能基准。环境48818912指向127.0.0.1:8000，名称经CLI schema validate→update→get改为“本地开发后端（P1 FakeLLM）”。原始报告 `.runtime/apifox/p1-health-final.json` 仅本地保存，没有上传云端。其余14个用例仍未运行，API-16～24完整业务场景留到P3/P4。无空场景/空套件。

```bash
apifox run --project 8800905 --branch main --test-case 411147565 --environment 48818912 --reporters cli,json --out-dir .runtime/apifox --out-file p1-health-final --upload-report false
```

Spec解析默认将接口显示为released，源文件已补`x-apifox-status: developing`，以表达待开发状态。该标签仅为设计工作状态，不能代替运行验收。

## 可复查命令

```bash
apifox endpoint list --project 8800905 --branch main --page-size 100
apifox test-case category --project 8800905
# ENDPOINT_ID 来自实际list；不要猜ID
apifox test-case list --project 8800905 --branch main --endpoint "$ENDPOINT_ID"
apifox export --project 8800905 --branch main --format openapi --output /tmp/probeops-apifox-openapi.json
```

更多工作流见 [API契约](../api-contract.md)；覆盖计划见 [测试矩阵](../testing.md)。请求/响应必须包含实际断言，不用空场景或空套件代替测试资产。
