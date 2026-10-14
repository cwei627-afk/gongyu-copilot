# API 失败语义

当前追加的 Stage C 三个 GET 也沿用下述错误结构；成功模型、关联与 provenance 契约见 [ENTERPRISE_WORKFLOW.md](ENTERPRISE_WORKFLOW.md)。`enterprise-links` 缺正式关联为 409/data/UNVERIFIED_CROSS_SYSTEM_RELATION；ERP 订单、WMS 批次未知为 404/data/OBJECT_NOT_FOUND；库存为零仍是 200 有效事实。三个新增接口返回 request_id/data/content_sha256，其他已交付接口保持原结构。机器可读 OpenAPI 当前共 10 个 GET（含 health）。

适用于现有五个 GET 查询接口。成功返回原有业务 Schema；失败统一返回下列结构。调用方按 `HTTP status + error.category + error.code` 判断，不依赖中文提示文本。

部署健康探测另提供 `GET /health`：只读检查三套模拟 SQLite 后端，全部可读返回 200；任一后端不可读返回 503/system。它不属于业务查询接口，也不表示生产状态。

基础机器可读契约：[openapi.json](openapi.json)，由 FastAPI 自动导出；各 operation 包含用途、必填参数、成功模型和对应错误示例。基础导出命令为 `.\.venv\Scripts\python.exe -m app.export_openapi`，服务地址配置见 [部署指南](DEPLOYMENT.md)。Stage F扩容实例的契约见本页末尾；基础导出不包含产品Gateway。固定流程优先 Workflow + HTTP Request，Swagger Tool仅用于自主选择接口的场景。

```json
{
  "error": {
    "category": "data",
    "code": "OBJECT_NOT_FOUND",
    "message": "MES 炉次不存在",
    "fields": []
  }
}
```

| 场景 | HTTP | category / code | 调用方可以得出的结论 |
| --- | --- | --- | --- |
| 查询成功 | 200 | 无 error，返回业务事实 | 当前接口数据可用；不表示工艺正常 |
| 业务对象不存在 | 404 | data / OBJECT_NOT_FOUND | 源系统成功查询后未找到该对象；不表示工艺异常 |
| 对象存在但无测量记录 | 409 | data / MEASUREMENT_MISSING | 炉次存在，对应测量数据不可用 |
| 必要字段 NULL、空串或全空白 | 409 | data / MISSING_FIELDS | 数据不可用，fields 列出缺失字段，不补零 |
| 字段格式无效或数字为 NaN/无穷值 | 409 | data / INVALID_DATA | 数据不可用，fields 列出无效字段 |
| 路径参数格式非法 | 422 | request / INVALID_PARAMETER | 请求未进入业务查询，需修正参数 |
| 模拟上游服务失败（如上游 HTTP 500） | 502 | system / UPSTREAM_ERROR | 系统失败，事实状态未知 |
| 数据库不可用、查询失败 | 503 | system / BACKEND_UNAVAILABLE | 系统失败，事实状态未知 |
| 模拟上游调用超时 | 504 | system / UPSTREAM_TIMEOUT | 系统失败，事实状态未知 |
| 本 API 未预期的内部错误 | 500 | system / INTERNAL_ERROR | 系统失败，事实状态未知 |
| 请求路径不存在（含缺少 ID 路径段） | 404 | request / ROUTE_NOT_FOUND | 路由未命中，不能据此认定业务对象不存在 |
| 请求方法不支持 | 405 | request / METHOD_NOT_ALLOWED | 修正 HTTP 方法，保留 Allow 响应头 |

## 参数与数据边界

- `heat_id`、`request_id`、`material_code`：1–128 字符，不含空白或控制字符，区分大小写，不自动修剪。ID 是一个 URL 路径段；路径分隔符不属于 ID。此为 PoC 接口格式约定，不是企业 ID 标准或合法 ID 白名单。符合格式但未知的 ID 必须查询源系统后才返回对象不存在。
- 参数错误的 `fields` 示例为 `path.heat_id`；源数据错误示例为 `temperature_c`。无字段级信息时为 `[]`。不返回原始异常、SQL、内部路径或堆栈。
- 字段完整性与类型校验不等于工艺判断。零库存是有效事实；原五个查询接口不判定工艺异常或过期。任务包 06 Workflow 仅按 analysis-context 返回的有效正式演示规则判断所选参数。
- `heat_id` 不存在 ≠ 炉次发生工艺异常。HTTP 500、timeout ≠ 业务/工艺异常。系统错误时，禁止推断对象存在、不存在或参数正常/异常。
- 调用方自身超时或网络中断时可能收不到本 API 的 JSON；同样按系统失败处理，事实状态未知，不能当作空结果。

## 模拟与验证

当前仍直接读取 SQLite，没有真实上游 HTTP 客户端。pytest 在后端访问边界用 `monkeypatch` 注入 `UpstreamServiceError`（模拟 HTTP 500）和 `TimeoutError`，验证 502/504 映射；不增加 HTTP 故障开关或特殊炉次号。真实 HTTP 集成和鉴权不在本轮范围。

运行：`python -m pytest -q`（使用项目 `.venv`）。保留原 13 项回归测试，同时以 pytest 参数化用例覆盖五个接口的成功、对象不存在、空字段、非法参数和系统失败，另覆盖无效数字、缺少测量、路由错误与 OpenAPI 错误 Schema。

## 任务包 06：MES 分析上下文

`GET /api/mes/heats/{heat_id}/analysis-context`：返回同一只读事务中的 `heat`、`process_stage`、`scope`、`stage_started_at`、`temperature`、`chemistry`、`rule`、`snapshot_at`。规则含范围、单位、有效期、数据年龄上限及正式文档出处。接口不判断工艺异常；Workflow 用这些事实确定性比较，见 [ANOMALY_WORKFLOW.md](ANOMALY_WORKFLOW.md)。

| 新增情况 | HTTP | category / code | 含义 |
| --- | --- | --- | --- |
| 缺少阶段上下文记录 | 409 | data / PROCESS_CONTEXT_MISSING | 炉次存在，分析所需事实不可用 |
| 无当前有效匹配规则 | 409 | data / RULE_NOT_FOUND | 不能使用默认范围或 LLM 知识兜底 |
| 存在多个当前有效规则 | 409 | data / RULE_CONFLICT | 需人工确认规则版本，不选“最相似”一条 |

其他 404/409/422/5xx 沿用上述结构。仅运行原 init_db 而未执行 `python -m app.analysis.seed_demo` 时缺少扩展表，属于 503 后端未就绪；不悄悄创建表或补齐数据。当前接口要求温度和成分快照均完整，即使本次只选其中一类分析，也采取保守停止策略。

Dify 调用方还必须区分 Workflow 执行失败与正常 End 输出：HTTP 连接失败/超时可能没有 `analysis_result`，必须映射为系统失败。参考 `app/analysis/dify_result.py`；不能把缺少输出解释为对象不存在或正常。

## Stage F：扩容源列表与产品接口

原 `openapi.json` 是基础查询接口导出；扩容 Mock 的当前完整契约由运行实例 `http://127.0.0.1:18090/openapi.json` 提供。新增列表不加入原 Stage D Agent 工具白名单，由 Gateway 按限定参数直查业务源。

| 只读路径 | 支持的查询参数 |
|---|---|
| GET /api/mes/heats | limit、date、start_time/end_time、furnace_id、steel_grade、status、review_only |
| GET /api/erp/production-orders | limit、date、start_time/end_time、status |
| GET /api/wms/inventory | limit、status |
| GET /api/demo/summary | 无；当前虚构数据规模、时间范围、实际示例编号 |

列表只查最近一次独立扩容 run，默认10、最多20。日期和完整时间范围二选一，范围必须带时区、递增且不超过60天，结束时刻不包含在内；生产日期按源记录的当地生产时间。未知参数、非法范围或超限返回422。未知筛选值可返回200空列表，不能推断库存为零或炉次异常。未初始化返回409 `DEMO_DATA_NOT_READY`；身份/源记录不完整返回409 `INVALID_DATA`；后端故障仍按系统错误停止。

列表模型包含 `request_id`、`system`、`operation_id`、`rows`、`returned_count`、`total_matching`、`limit`、`truncated`、`source_snapshot_at`、`content_sha256` 和 `fictional`。`total_matching` 只是条数，不返回全库；历史待复核标记不是当前工艺判定。

产品 `POST /api/copilot/query` 只接受 `question` 与可选的短期 `context_token`，不接受模型指定URL、实体来源或后端引擎。返回固定产品模型：中文 `title/summary/facts/analysis/sources/next_actions/human_confirmation/process_steps`，技术字段放在 `technical_meta` 白名单中。业务失败和调用槽繁忙用HTTP200承载明确的 `data_error/system_error/abstain`；请求Schema错误为422，跨源请求为403，已声明的过长请求为413。页面必须检查语义结果，不能将200直接当作生产正常。健康/演示摘要接口不可用时为503。

## F2 桌面有限复合结果（2026-10-08）

仅 `POST /api/workspace/query`：同一明确炉次同时要求订单/库存和工艺判断，且原分析返回 `RULE_NOT_FOUND` 或 `RULE_CONFLICT` 时，可独立补调原只读查询。其他失败不触发该分支。

新增可选 `sub_results: [{label, result}]`；每个result为原桌面子结果，独立保留状态、来源和执行元数据。只读查询完成而工艺判断未完成时父状态为 `partial`；查询失败时为对应失败状态，不能把HTTP200或partial当作工艺正常。父结果不合并citation/API provenance，不签发或延长context；引用及来源只属于各自子结果。原 `/api/copilot/query` 契约与原C/D接口不变。
