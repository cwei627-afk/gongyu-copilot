# DIFY_INTEGRATION.md

## 1. 目标

本项目使用 **FastAPI + Dify** 构建“制造业生产知识与异常分析 AI Copilot”PoC。

- **FastAPI**：业务/API 层，提供 MES / ERP / WMS 模拟接口、业务字段、错误语义。
- **Dify**：RAG、Workflow/Chatflow、LLM、必要时的 Agent Tool Calling。
- 不额外自研 Agent Framework、RAG 引擎或复杂编排框架。

## 2. 总体原则

### Workflow 优先，Agent 受限使用
- 固定、可预期流程：Workflow / Chatflow。
- 调用路径依赖中间结果、无法预先确定时：Agent。
- 核心异常分析优先显式 Workflow，不让 Agent 成为总控制器。

判断标准：
- 路径可提前确定 → Workflow
- 路径不可提前确定 → Agent

## 3. FastAPI 接入 Dify

### 固定 API 查询
Workflow 已知道调用哪个接口时，优先使用 **HTTP Request Node**。

可用能力：
- GET / POST / PUT / PATCH / DELETE
- Header / Query / JSON Body
- Bearer / API Key
- Timeout
- Retry
- Fail Branch
- status / body / headers 供后续节点引用

### 动态工具选择
只有需要模型自主决定调用哪个业务接口时，才将 FastAPI OpenAPI 导入 **Swagger API Tool**。

OpenAPI 必须写清：
- operation/tool 名称
- 用途与调用条件
- 参数含义、required / optional、字段类型
- 返回值含义
- 错误语义

## 4. 当前 PoC API

```text
GET /api/mes/heats/{heat_id}
GET /api/mes/heats/{heat_id}/temperature
GET /api/mes/heats/{heat_id}/chemistry
GET /api/erp/material-requests/{request_id}
GET /api/wms/inventory/{material_code}
```

原则：
- MES / ERP / WMS 是业务事实 Source of Truth。
- AI 不复制完整生产数据作为自己的事实库。
- heat_id 等动态业务对象由业务系统查询结果确认。
- 404 / NOT_FOUND ≠ 工艺异常。
- 500 / timeout / 鉴权失败 ≠ 业务异常。

## 5. RAG 实现

使用：

```text
Knowledge Retrieval
→ result
→ LLM Context
```

尽量保留原生 citation 链路。

### Metadata
内置字段可使用：
- document_name
- uploader
- upload_date
- last_update_date
- source

建议自定义：
```text
doc_type
plant
production_line
equipment_type
steel_grade
version
effective_date
chapter
section
page
```

字段名统一 `lowercase_with_underscore`。

### Metadata Filtering
优先用 metadata 缩小候选范围，再做检索 / rerank。

如 API 返回的 steel_grade / equipment 会影响检索，则串行：

```text
HTTP Request
→ 提取 steel_grade / equipment
→ Knowledge Retrieval + Metadata Filtering
→ LLM
```

## 6. Evidence First

企业正式 SOP、工艺规程、质量标准是业务规则 Source of Truth。

1. 无充分企业证据时，不允许模型靠预训练知识补充确定性生产处置结论。
2. 标题不同但正文明确支持，可作为证据。
3. 仅语义相近但正文不能直接支持，视为证据不足。
4. 证据不足时 abstain / 请求人工确认。
5. 新旧文档冲突时优先有效版本，失效版本不得作为最终依据。

## 7. Citation / Source

### Chatflow
使用 Knowledge Retrieval → LLM Context，并保留 **Citations and Attributions**。

### 自定义前端
Chat API 可利用：
```text
metadata.retriever_resources
```

可展示 document/content/score 等检索来源。

不要假设所有 Custom Metadata 都会自动出现在 `retriever_resources`。

如前端必须稳定展示：
```text
version
chapter
section
page
steel_grade
equipment_type
```
则在 Workflow 中显式整理为输出字段。

纯 Workflow API 如需来源，也应将 source 信息显式放入 outputs。

## 8. API + RAG + LLM 编排

### API 与 RAG 互不依赖
可以并行。

### API 结果影响知识检索
必须串行：

```text
User Input
→ HTTP Request
→ 获取 steel_grade / equipment
→ Knowledge Retrieval + Metadata Filtering
→ LLM
→ Answer
```

本项目“炉次异常分析”优先采用串行模式。

## 9. 错误处理

Dify 侧使用：
- HTTP Retry
- HTTP Fail Branch
- LLM Fail Branch / Default Value
- Tool Fail Branch
- error_type
- error_message

### 系统异常
timeout / HTTP 500 / 网络失败 / 鉴权失败  
处理：提示实时业务数据暂不可用，不得解释为生产异常。

### 数据异常
heat_id 不存在 / 关键字段为空 / 数据过旧 / 无有效结果  
处理：停止工艺推断，明确提示数据问题。

### 业务/工艺异常
业务对象存在、数据有效、实际参数违反当前有效规则。  
只有这种情况进入工艺异常分析。

### Retry
可重试：429、500、network failure  
通常不原样重试：validation error、401、quota error、404 identifier error

FastAPI 需要保证必要幂等性。

## 10. 推荐主链路

```text
User Input
→ 参数提取
→ HTTP Request 查询 MES
→ 检查：系统异常 / 数据异常 / 正常
→ 获取 steel_grade / equipment / process_stage / actual data
→ 获取当前有效目标或业务规则
→ 判断是否业务异常
→ 如异常：Knowledge Retrieval + Metadata Filtering
→ 判断证据是否充分
→ 不充分：abstain + 人工确认
→ 充分：LLM 综合
→ 输出：
   - 异常事实
   - 使用的数据
   - 业务规则
   - 建议检查项
   - 文档来源
   - Human-in-the-loop 提示
```

## 11. Agent 使用边界

只在“根据中间结果，自主决定下一步查 MES / ERP / WMS 哪个接口，且调用顺序事先无法确定”时使用 Agent。

要求：
- Tool Description 写清调用条件
- 限制可用工具范围
- 设置 Max Iterations
- 不允许 Agent 直接操作 PLC / 设备
- 不允许绕过 Source of Truth 或 Evidence First
- 核心 PoC 不依赖 New Agent Beta 才能运行

## 12. 明确不做

- 不自研 RAG backend
- 不自研 Agent Framework
- 不以 LangGraph 为核心
- 不做知识图谱
- 不做多 Agent
- 不做 Kubernetes
- 不做复杂微服务
- 不做复杂前端
- 不让 LLM 直接控制生产设备

## 13. 后续实施顺序

1. 完善 FastAPI OpenAPI
2. 导入必要 Swagger API Tools
3. 创建 Dify Knowledge Base
4. 建立 metadata schema
5. 配置 Knowledge Retrieval / filtering / rerank
6. 创建主 Workflow / Chatflow
7. 固定业务查询使用 HTTP Request
8. 必要位置增加 Agent
9. 配置 retry / fail branch / fallback
10. 配置 citation / source 输出
11. 完成端到端异常分析 PoC

## 任务包 06 实现补充

固定异常分析已采用显式 Workflow + HTTP Request + 原生 Knowledge Retrieval，未引入自由 Agent。对应 DSL、有限证据审查边界、Dify 1.17.1 HTTP 失败语义及演示步骤见 [ANOMALY_WORKFLOW.md](ANOMALY_WORKFLOW.md)，实测记录见 [DIFY_LIVE_VALIDATION.md](DIFY_LIVE_VALIDATION.md)。上述既定原则继续有效。


## 阶段 A：受控来源与正式索引（2026-09-30）

任务06的原旗舰 App 已迁移到新正式 Qwen 数据集；固定流程仍使用 Workflow + HTTP Request，不增加 Agent 或 LLM 综合节点。来源登记 `assets/analysis_demo/dify_source_registry.json` 与真实 Dify document/segment ID、正文 SHA-256 绑定。两份 `workflows/heat_analysis*.yml` 为本机正式配置的无密钥导出。

Dify metadata 为真实结构化字段，见 ADR-013；内建 document_name 是实际文件名，controlled_document_name 是受控标题。检索使用 manual AND filter（active、scope、钢种、阶段、rule_id、有效期及字段非空），且检索前后核对完整目录；冲突/缺字段/未知来源 fail closed。所有返回 hit 都验证来源；夹带无身份或篡改片段不能被其他有效命中掩盖。正式 Markdown 无可靠分页，page=null。

Citation 仅从验证后的 hit 复制 ID、实际文件名、版本、有效日期、章节/节、页码、正文 quote/hash；不从 manifest 补造。受控目录只提供预审查映射及身份约束，不维护 MES 事实。KNOWLEDGE_API_KEY 使用仅授权正式数据集的 Dify secret 环境变量，导出值留空。环境迁移时重新索引、采集真实 ID/hash 和配置密钥，禁止复用旧向量或来源登记。

联调与实际草稿/发布 trace 见 [DIFY_LIVE_VALIDATION.md](DIFY_LIVE_VALIDATION.md) 及阶段 A 验证报告。不代表在线开放知识问答、LLM 综合或 Agent 已完成。

## Stage B 当前旗舰配置（2026-09-30）

上文“无 LLM”的说明为 Stage A 快照。正式旗舰现在增加证据后的 DeepSeek 受约束报告组织，仍优先 Workflow + HTTP Request，不增加 Agent。Qwen 正式数据集、metadata 和来源校验保持冻结。

当前导入文件为 `workflows/heat_analysis.stage_b.yml`；旧两份 DSL 为历史基线，重新导入会回退 Stage A。DeepSeek Provider 由现有 Dify 配置，模型 deepseek-flash；thinking=false、json_object、原生 structured_output、reasoning separated。导出不包含 Provider/知识 API 密钥。

不能只依赖原生 schema 或 prompt：Dify 1.17.1 thinking 曾误选 reasoning 内的 JSON 片段，项目 Code 再验证完整 JSON、schema、引用与正文，失败关闭。新环境配置真实来源登记与 secret 后，运行草稿及发布版本测试。契约见 GENERATION_CONTRACT.md；原始验证见 audit_artifacts/STAGE_B_VALIDATION.md。

## Stage C 联合旗舰配置（2026-10-01）

当前导入文件为 `workflows/heat_analysis.stage_c.yml`，正式 App 和 Qwen 数据集不更换。MES enterprise-links → ERP production-orders → WMS batches 使用原生 HTTP Request；X-Request-ID 绑定 sys.workflow_run_id，Code 校验正式关联、版本、单位、hash。成功才进入既有检索/evidence；无工艺异常直接返回结构化联合事实。

DeepSeek 在既有门禁之后，最外层输出 mes_report + enterprise_summary；冻结的 Stage B MES schema/引用/正文校验继续执行，新增 API 事实覆盖与原始 HTTP 重建校验。API provenance 是 Code 输出，不授予模型创建数据来源的权限。失败停止并明确缺失源；真实 HTTP timeout 无 End 仍系统失败。

本机使用独立 Mock 18089，旧 DSL 仅历史基线；跨环境必须重新配置真实来源、secret 和 Provider。部署、教学假设及样例见 ENTERPRISE_WORKFLOW.md；实际草稿/发布证据见 audit_artifacts/STAGE_C_VALIDATION.md。
