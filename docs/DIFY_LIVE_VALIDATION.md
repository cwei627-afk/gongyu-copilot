# 任务包 06：Dify 实例联调记录

以下 2026-09-28 内容保留为历史联调记录；当前绑定见文末阶段 A。

联调对象：用户现有自部署 Dify 1.17.1。项目使用专用的虚构规程知识库（ID `f1fe6d08-5bae-45eb-a985-4f3ac28f12b8`）和独立 Workflow 草稿（App ID `c9ccd056-00db-44fc-a07e-d4f385c07400`）。两份 `DEMO-CHECK-*.md` 文档在原生 economy 关键词索引中完成处理。此处记录的是本机演示，不证明真实企业规程或生产数据适用性。

## 2026-09-28 已保存的真实运行结果

下表依据当时 Dify `workflow_finished` 事件核对，原始事件保存在本机被忽略的 `data/dify-run-*.json`。测试时临时关闭的规程、临时故障地址和错误检索节点，均已在 `finally` 中恢复；正常草稿重新导入。部分错误场景使用了临时故障服务，只验证 Dify 分类，不在业务 API 中加入故障开关。

| 场景 | Dify 执行 | 业务输出 | 停止/证据约束 |
| --- | --- | --- | --- |
| `DEMO-NORMAL` | succeeded | `no_anomaly / WITHIN_EFFECTIVE_RULE` | 未进入检索 |
| `UNKNOWN` | succeeded | `data_error / OBJECT_NOT_FOUND` | 仅执行炉次查询；无上下文查询或检索 |
| `DEMO-MISSING` | succeeded | `data_error / MISSING_FIELDS` | 无工艺推断 |
| `DEMO-NO-RULE` | succeeded | `data_error / RULE_NOT_FOUND` | 不使用默认阈值 |
| `DEMO-STALE` | succeeded | `data_error / STALE_DATA` | 已过期数据停止 |
| `DEMO-HIGH-TEMP` | succeeded | `review_required / SUPPORTED_CHECKLIST` | 1 项异常、1 份出处、3 条原文检查项 |
| `DEMO-HIGH-CARBON` | succeeded | `review_required / SUPPORTED_CHECKLIST` | 成分规程检索成功 |
| `DEMO-BOTH` | succeeded | `review_required / SUPPORTED_CHECKLIST` | 2 项异常、2 份出处、6 条原文检查项 |
| `DEMO-BOTH`，临时关闭温度规程 | succeeded | `abstain / INSUFFICIENT_EVIDENCE` | 2 项异常仍保留；0 出处、0 检查项 |
| 模拟 HTTP 500 | succeeded | `system_error / UPSTREAM_FAILURE` | 工艺状态未知 |
| 模拟 HTTP 超时 / 后端断连 | failed | 无 End 输出 | 调用方按 `normalize_finished` 映射为 `system_error / WORKFLOW_EXECUTION_FAILED` |
| 临时损坏检索节点输入 | partial-succeeded | `system_error / TRANSPORT_FAILURE` | 已确认 2 项异常仍保留；0 检查项 |

`review_required` 是辅助分析待人工复核，不是执行授权；输出的 `automatic_actions` 在成功、abstain 与结构化失败路径均为空。六项输出为异常事实、使用的数据、对应规则、建议检查项、文档出处、人工确认提醒。检查项来自预审查规程的原文，模型没有自行生成范围或处置动作。

## 2026-09-29 恢复后复验

复用同一知识库和 Workflow 草稿，用新的 `data/task06-20260929` 模拟 MES 数据目录运行 FastAPI，避免覆盖昨日炉次。Dify PostgreSQL 启动恢复完成后，API 健康检查通过；两份专用规程的索引状态均为 `completed`。全量 `pytest -q --tb=short`：**216 passed，1 warning**；警告来自测试依赖 Starlette 的 `anyio.abc.BlockingPortal` 弃用提示。

| 当日输入 | Dify 输出 | 检索与停止行为 |
| --- | --- | --- |
| `DEMO-NORMAL` | `no_anomaly / WITHIN_EFFECTIVE_RULE` | 不检索 |
| `UNKNOWN` | `data_error / OBJECT_NOT_FOUND` | 炉次查询后停止 |
| `DEMO-HIGH-TEMP` | `review_required / SUPPORTED_CHECKLIST` | 检索成功，1 份出处 |
| `DEMO-BOTH` | `review_required / SUPPORTED_CHECKLIST` | 检索成功，2 份出处 |
| `DEMO-BOTH`，暂时停用温度规程 | `abstain / INSUFFICIENT_EVIDENCE` | 0 出处、0 检查项；测试结束已重新启用该文档 |

当日事件记录在被忽略的 `data/dify-run-20260929-*.json`，不会成为交付时必须存在的依赖。HTTP 500、超时与检索节点错误使用上一节保存的真实 Dify 执行记录及当日全量自动测试核对，没有在业务 API 加入故障开关。

## 复现步骤

1. 启动现有 Dify 1.17.1 实例。保持原有数据卷；本项目不要求重建 Dify。专用知识库应启用上述两份演示检查规程。
2. 在仓库根目录使用新的 `MOCK_DATA_DIR` 显式执行 `python -m app.analysis.seed_demo`，然后在相同环境启动 `python -m uvicorn app.main:app --host 0.0.0.0 --port 18086`。演示数据由种子时间生成且不会覆盖已存在记录；超过虚构标准中的 6 小时后应换新目录，不要刷新历史事实。
3. 在 Dify 打开 App ID 上述草稿，确认 HTTP 基础地址为 `http://host.docker.internal:18086`，检索节点绑定专用知识库。若迁移实例，运行 `python -m app.analysis.export_workflow --dataset-id <新知识库ID> --base-url <Dify可访问的API地址>` 并导入新草稿。
4. 分别输入 `UNKNOWN`、`DEMO-NORMAL`、`DEMO-HIGH-TEMP`、`DEMO-BOTH`，`analysis_request=all`。按上表检查执行分支及 `analysis_result` JSON 字符串。特别检查未知炉次不进入上下文和检索、正常炉次不进入检索。
5. 错误场景可用本地 pytest 和已有 Dify 事件记录核对；临时故障注入完成后必须恢复专用知识库文档状态和正常 Workflow 草稿。Dify 1.17.1 的 HTTP 节点配置限制见 [ANOMALY_WORKFLOW.md](ANOMALY_WORKFLOW.md)。

规则和值、规程与炉次均完全虚构。当前草稿没有自由 LLM 节点或实际审批节点；人工复核由输出提醒和流程边界要求承担，任何生产处置均需授权人员另行确认。


## 2026-09-30：阶段 A 正式受控 Qwen 迁移

原旗舰 App ID 保持 `c9ccd056-00db-44fc-a07e-d4f385c07400`，迁移到新正式数据集 `553a2ee9-b37e-4d0f-b3de-0251267d2f59`。旧 economy 数据集与审计 clone 不再承担旗舰检索。5 份虚构文档重新索引为 5 个受控片段；真实 Embedding 为 Qwen3-Embedding-0.6B / Local Ollama / 1024 维，见 `stage_a_dataset.json`、`stage_a_index_status.json`、`stage_a_embedding.json`。

Dify 文档具备真实结构化 metadata，手动过滤在原生检索前执行；全文目录在检索前后验证版本唯一性。绑定登记为 `assets/analysis_demo/dify_source_registry.json`。来源文件名、document/segment ID、metadata 与正文 hash 不一致则 abstain，无 citation/检查项。当前 Markdown 无可靠页码，page=null。目录请求使用内部 nginx，与宿主机 API 查询分开。

真实草稿 trace 场景：正常、未知炉次、缺数据、无规则、温度异常、双参数异常、业务规则冲突、历史/撤销/不活动/未来规程、缺 version/effective_date/metadata、无 SOP、两个当前版本、错误 document/segment、revoked version、篡改正文、缺 hit 身份、错误 scope、原始三字段 Citation 攻击、MES 500、timeout，以及恢复后的正例。逐项状态与路径见 `audit_artifacts/stage_a_dify_results.json`；原始事件为 `STAGE-A-TRACE-*.json`。故障地址、metadata 和演示规则已恢复。

本轮仍未添加 LLM 综合/开放知识问答/Agent。版本判断与 Citation 来源由代码及 metadata 确定，不交给模型。本机 Mock 使用独立 `fde-stage-a` Compose 项目（18088），不覆盖原卷；数据仍受 6 小时新鲜度限制。

最终草稿 28/28 PASS；原旗舰已发布相同受控图（版本名 Stage A Qwen），发布 API 异常/正常/未知炉次 3/3 PASS，证据为 `stage_a_publish.json`、`stage_a_published_workflow.json`、`stage_a_published_results.json` 与 `STAGE-A-PUBLISHED-*.json`。

## Stage B 实测追加（2026-09-30）

原旗舰 App ID 和正式数据集不变；新增证据后 DeepSeek 报告组织和生成后独立校验。最终草稿 32/32、发布 API 4/4；发布 Workflow ID 为 `1b890b35-eae4-4284-8382-9427e9fba73c`，每次真实 API workflow_id 均匹配，generation.request_id 与 run ID 一致。trace、负向输出 replay 方法、中间失败与恢复详见 [STAGE_B_VALIDATION.md](../audit_artifacts/STAGE_B_VALIDATION.md)。上文历史无 LLM 状态不代表当前旗舰。
