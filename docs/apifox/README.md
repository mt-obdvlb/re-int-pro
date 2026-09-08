# Apifox维护与真实回归

2026-09-08，CLI2.2.9，沿用re-int-pro项目8800905/main、环境48818912。Git Spec源为 [OpenAPI](../api/openapi.json)，不直接改生成接口、不新建同名项目。

现有12个操作、19个数据模型；20个接口测试用例均经过schema校验、写入及CLI回读，真实本地runner共20请求、45断言，0失败。原始报告留在.runtime/apifox，不上传；[资源索引](resource-index.json)保留逐项路径与SHA256。[用例快照](test-cases.json)是设计记录，不是直接导入payload。

真实回归曾发现旧错误码预期NOT_FOUND与实现细分不符、操作限额不应固定等于450元，以及新增用例复制模板后路径未更新、事件没有run_id字段。现已校正并重跑；旧失败报告保留。服务启动前/重启中产生的连接失败也保留，最终结果来自ready后执行。

先启动FakeLLM后端和worker。执行API-05创建真实快照任务，再从输出中取得run_id，等到completed后将其作为fixture运行17–20；示例：

```bash
apifox run --project 8800905 --branch main --test-case 411147578 --environment 48818912 --reporters cli,json --out-dir .runtime/apifox --out-file create-fixture --upload-report false
# FIXTURE_RUN_ID 取自上一步真实返回，等待completed；不得用不存在的占位ID
apifox run --project 8800905 --branch main --test-case 411733979 --environment 48818912 --env-var "fixture_run_id=$FIXTURE_RUN_ID" --reporters cli,json --out-dir .runtime/apifox --out-file report-fixture --upload-report false
```

维护流程：help→cli-schema get→get原资源/真实category→完整payload→validate→create/update→get回读→runner。category正向13341829、负向13341830；参数与绑定endpoint ID见索引。CLI创建输出可能含提示文本，不能盲目当纯JSON解析；不确定写入结果先list确认，避免重复创建。

[官方CLI文档](https://docs.apifox.com/apifox-cli) 于2026-09-07核对。升级后以安装版本help/schema为准；令牌不写入命令参数、仓库或环境导出。项目总览计数曾不反映Spec资源，以专用endpoint/test-case list和回读为准。

变更Spec后提交推送，再export核对新增可选字段和12操作。不能用源规范与自己返回的/openapi.json相等代替后端响应验收。历史P0/P1仅health通过的记录已被本轮20用例真实回归更新。
