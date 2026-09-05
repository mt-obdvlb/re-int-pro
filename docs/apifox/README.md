# Apifox 设计资产与同步记录

项目 `re-int-pro` / 8800905，main / 8592769；CLI 2.2.9；核查日期2026-09-05。

现有项目是Git托管Spec模式，连接2190指向 `mt-obdvlb/re-int-pro`。契约源为 [docs/api/openapi.json](../api/openapi.json)。直接CLI导入曾保存19个数据模型和1个本地环境但未生成接口；直接endpoint创建404。已查明应通过Git同步Spec，未创建替代项目、未更改权限。

本轮将契约推送到已连接仓库后，核对生成的12个操作，并据真实endpointId通过CLI建立API测试用例。后端尚未搭建，本轮不运行业务接口测试；不使用云Mock冒充后端验收。最终资源数量和校验结果将回填本记录。

## 可复查命令

```bash
apifox endpoint list --project 8800905 --branch main --page-size 100
apifox test-case category --project 8800905
# ENDPOINT_ID 来自实际list；不要猜ID
apifox test-case list --project 8800905 --branch main --endpoint "$ENDPOINT_ID"
apifox export --project 8800905 --branch main --format openapi --output /tmp/probeops-apifox-openapi.json
```

更多工作流见 [API契约](../api-contract.md)；覆盖计划见 [测试矩阵](../testing.md)。请求/响应必须包含实际断言，不用空场景或空套件代替测试资产。
