# Apifox 设计资产与同步记录

项目 `re-int-pro` / 8800905，main / 8592769；CLI 2.2.9；核查日期2026-09-05。

2026-09-06收尾复核：`test-case list` 返回15项。`project get` 的统计摘要仍显示接口/用例0，未能反映本次Spec生成接口与单接口用例；本记录的数量依据专用endpoint/test-case list、逐项get和OpenAPI导出，不使用项目摘要推断资源不存在。

现有项目是Git托管Spec模式，连接2190指向 `mt-obdvlb/re-int-pro`。契约源为 [docs/api/openapi.json](../api/openapi.json)。直接CLI导入曾保存19个数据模型和1个本地环境但未生成接口；直接endpoint创建404。已查明应通过Git同步Spec，未创建替代项目、未更改权限。

契约提交 `4a302a6` 推送后，现有 Git 同步生成 **12 个操作、19 个模型**。已通过 CLI 建立 **15 个独立 API 测试用例**；每个都经过 schema validate 和 get 回读，验证绑定ID、分类、正文、参数、前置脚本（如有）及断言。实际费用为本轮模型调用0元。

- [资源映射](resource-index.json)：12个endpoint ID、15个case ID和逐项验证状态。
- [用例设计快照](test-cases.json)：按operationId记录输入/预期，便于评审；不是直接导入的CLI payload。后续用例在Apifox维护后同步此快照，不能在两处独立修改。
- 将Apifox导出与仓库源规范化对照：19模型一致；12操作的方法/路径/operationId/参数required与schema/请求体/响应状态与schema一致。忽略UI扩展和描述性字段。

后端尚未搭建，**15个用例均未运行**；保存和回读不等于后端断言通过。本轮不启用云Mock或公开文档站点。API-16～24场景在P1/P4有真实fixture后创建，当前没有空场景/空套件。

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
