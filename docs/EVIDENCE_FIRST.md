# RAG / Evidence First 项目资产与校验

本轮提供完全虚构的知识资料、离线验收问题、结构化契约和证据校验函数。企业正式 SOP、工艺规程、质量标准才是业务规则 Source of Truth；这里的资料仅在虚构教学场景中模拟正式发布文档，不是实际生产依据。

## 文件与运行

- `assets/rag_demo/documents/`：5 份可读 Markdown 文档，全部原创虚构，无真实企业名称、内部资料或生产参数标准。
- `assets/rag_demo/corpus.json`：演示受控文档目录及完整正文片段，保留元数据；不是生产数据库、向量库或检索器。
- `assets/rag_demo/questions.json`：11 个问题、模拟检索结果、人工编写的语义审查标注和预期输出。**仅作测试，不得导入知识库或供检索时偷看答案。**
- `app/evidence/`：Pydantic 契约、纯函数 `evaluate(corpus_data, request_data)` 和离线验证入口。无网络、LLM、embedding、检索索引或新 API。
- `assets/rag_demo/evidence_review.md`：后续正文审查规范；不是已接入的 Dify 节点。

```powershell
.\.venv\Scripts\python.exe -m app.evidence.validate_demo
.\.venv\Scripts\python.exe -m pytest -q
```

## 演示问题与预期

默认评估日期固定为 2026-09-28，适用范围为虚构的 `DEMO-LINE-A`，不依赖运行当天日期。

| 问题 | 检索证据情况 | 预期 |
| --- | --- | --- |
| Q01 温度记录包含哪些字段 | 现行工艺规程正文直接列出 | supported，仅允许依据原文回答字段 |
| Q02 温度偏高如何调整设备 | 标题相近、分数 0.99，但正文没有处置步骤 | abstain / NO_DIRECT_SUPPORT |
| Q03 差旅报销额度 | 无相关资料 | abstain / NO_EVIDENCE |
| Q04 温度记录缺失由谁确认、填什么 | 标题为“交接记录规程”，正文直接支持 | supported，不要求标题匹配 |
| Q05 同 Q04，仅命中旧版 | v1 已失效 | abstain / INACTIVE_VERSION |
| Q06 同 Q04，新旧版同时命中 | v1 失效、v2 当前有效 | supported，只引用 v2 |
| Q07 同 Q04，仅命中未来版 | v3 尚未生效 | abstain / INACTIVE_VERSION |
| Q08 碳字段为空的记录完整性标记 | 质量标准正文直接规定“待补全” | supported，不能推断成分超标或材料不合格 |
| Q09 同时询问记录字段及设备调整 | 只覆盖字段部分 | abstain / INCOMPLETE_SUPPORT |
| Q10 有命中但无正文审查 | 未经审查不能放行 | abstain / UNREVIEWED_EVIDENCE |
| Q11 检索服务失败 | 不是成功检索后的空结果 | abstain / RETRIEVAL_FAILED |

## Metadata 与版本

| 字段 | 来源与约定 |
| --- | --- |
| document_name、version、effective_date | 受控文档发布信息，必填；不得由 LLM 猜测 |
| document_id、document_family | 唯一版本标识与版本系列标识；关联旧版、新版 |
| effective_until | 失效日期，不含该日；无结束日期为 null |
| status | published / draft / withdrawn；只有 published 且日期有效可引用 |
| doc_type、scope | SOP / 工艺规程 / 质量标准，以及适用范围；范围需匹配 |
| chunk_id | 稳定片段标识，不由检索排名决定 |
| chapter、section、page | 片段原始位置；真实缺失时保存 null，不编造 |
| fictional | 本套演示资产固定 true，防止误当真实资料 |

Markdown 中的 `page=1` 是资产明确标注的“演示逻辑页 1”，不是 PDF 排版页码；真实导入时须保留真实可用页码，不套用本演示值。每份文档只有一个正文片段，便于本轮说明 metadata 与正文的对应关系。

有效期按 `[effective_date, effective_until)` 判断，不按版本号字符串大小或语义分数选新版本。受控目录必须提供完整版本信息：同一系列、同一适用范围在评估日有多个有效版本，则 `VERSION_CONFLICT` 并要求人工确认，即使检索仅命中其中一个。只命中过期版本不会自动从目录补出新版“检索结果”。未来发布版本到生效日才可用；撤回、草稿版本始终不可引用。

## 校验职责与输出

处理顺序：输入结构校验 → 检索状态 → 来源及正文一致性 → 适用范围 → 有效版本及冲突 → 明确的正文支持审查 → 引用确实在正文中 → 问题全部必要要点覆盖。

`supported` 表示**显式审查结果通过了上述机械校验**，不是程序独立证明自然语言语义正确，也不是已生成答案、已完成工艺判定或获得执行授权。`similarity_score` 仅留作检索诊断，不参与放行；标题也不参与放行。

语义审查输入必须绑定当前问题，逐条标记 `direct / related_only / irrelevant / uncertain`、引用原文、覆盖要点、审查理由和审查者。`required_points` 必须完整表达问题需求。本轮标注由人工编写；未来接入时需要独立审查步骤，不能把“命中结果”直接标记为 direct。校验器不能发现伪造的审查结论、漏拆的问题要点或所有跨文档语义矛盾；这些仍须语义评估与人工复核，不能声称已由单元测试解决。

证据不足时示例：

```json
{
  "decision": "abstain",
  "reason_codes": ["NO_DIRECT_SUPPORT"],
  "message": "没有充分且有效的企业证据，无法给出确定性生产处置结论。请人工确认或补充有效规程与直接支持问题的正文。",
  "human_confirmation_required": true,
  "production_conclusion": null,
  "evidence": [],
  "rejected": [{"chunk_id": "temperature-record", "code": "NO_DIRECT_SUPPORT"}]
}
```

充分证据输出携带原文引用和 `document_name、version、effective_date、chapter、section、page`。所有分支保留 `human_confirmation_required=true`、`production_conclusion=null`。本轮只输出证据和判断结果，不生成自由文本处置结论。复合问题若仅部分覆盖，整体 abstain，清空可作答 evidence，避免将部分信息伪装成完整答案。

其他明确拒绝原因包括 `INVALID_INPUT`（必要 metadata、契约不完整等）、`UNKNOWN_SOURCE`、`CONTENT_MISMATCH`、`SCOPE_MISMATCH`、`REVIEW_QUESTION_MISMATCH`、`INVALID_QUOTE`、`INVALID_COVERAGE`。拒绝项保存在 rejected 中；无有效证据时不得依赖预训练知识兜底。

## 后续 Dify 接入约定（尚未实施）

1. 只把演示文档正文及来源信息导入知识库。`questions.json`、预期答案、测试代码和审查规范不得作为业务知识检索源。现行版与历史/未来版分开管理；历史版只用于受控回归测试，避免默认检索混用。
2. 依据 DIFY_INTEGRATION.md 使用 metadata 缩小范围。每个片段保持独立的 chunk_id、版本和位置，不跨版本合并。不要假设 Markdown 中写了 metadata 就会自动变成 Dify 自定义字段，也不要假设全部自定义字段自动出现在 citation 中。
3. 后续适配器需将检索结果映射为 Candidate，并校验返回正文与受控片段一致。受控目录来自发布资料管理，不接受模型自行声称版本有效。缺少映射或 metadata 时 abstain。代码目前只实现本项目 JSON 契约，没有声称直接兼容 Dify 的原始 result 对象。
4. 在固定 Workflow 中显式执行“检索 → 正文支持审查 → Evidence First 校验 → 分支”。abstain 分支直接输出拒答和人工确认信息，**不得再进入补充处置结论的 LLM 节点**。检索失败单独处理，不包装成无相关资料。
5. supported 分支以后如使用 LLM，只给通过审查的正文和出处，禁止添加无证据的阈值、设备指令或处置步骤。生成后的每项实质性结论仍需核对引用及支持关系；本轮未实现该生成后审查或评估真实检索质量。
6. Chatflow 尽量保留原生 citation 链路；Workflow 在 outputs 显式输出所需 metadata，不能只输出分数或文档标题。生产处置始终保留 Human-in-the-loop，不直接控制设备。

MES/ERP/WMS 实时事实仍通过既有接口查询；API 404、数据错误、timeout 不能由 RAG 填补为工艺结论。固定流程优先 Workflow + HTTP Request，本轮没有增加 Agent、向量数据库、模型依赖或业务接口。
