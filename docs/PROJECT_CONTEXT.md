# 当前项目上下文 · F2技术验证完成，等待用户UAT

当前产品入口为**工域 Copilot — 生产知识与业务数据辅助系统**，统一桌面页面与FastAPI兼容层连接已冻结的C/D/E1能力。F2新增隔离的140份虚构内部资料及35份有出处的公开短摘要索引，保留所有原知识库和审计记录。F2只完善产品表达、展示编号、数据体验及知识覆盖，不新增业务控制或自由Agent能力。

本轮完整pytest、Compose、300题真实知识矩阵、40个不同浏览器问题及两轮桌面复查已完成；有限自然语言改写仍有保守拒答边界。结果以[Stage F2验证记录](../audit_artifacts/STAGE_F2_ASTRA_VALIDATION.md)为准。下方E2状态为历史快照，不能作为当前功能或本轮测试结果。

## 以下为E2历史快照

现有产品为三个独立正式Dify应用：Stage C确定性MES/ERP/WMS/RAG辅助分析、Stage D四只读工具动态Agent、Stage E1有限单轮企业规程QA。三个入口无统一前端、无共享多轮记忆。全部企业数据/规程为虚构演示，底层业务规则和来源门禁冻结；E2只增加交付脚本、文档、验证和包内容。

下方早期上下文中的“后续”“未接入”是当时状态；当前状态以PROJECT_AUDIT与STAGE_E2_VALIDATION为准。Source of Truth、Evidence First、三类异常、Citation/HITL边界不变。


---

## 以下为原阶段记录（历史结果，不代表E2本轮）

# 项目背景：制造业生产知识与异常分析 AI Copilot

## 目标与定位

本项目是面向制造企业生产现场的教学型旗舰 PoC，在已有 MES、ERP、WMS 和企业知识文档之上增加 AI 智能交互与编排层。项目不替代业务系统，也不直接控制生产设备。

以结构清楚、代码容易理解、架构边界可解释为原则，不追求过度工程化。任务包 01 已实现五个 Mock 查询接口；任务包 06 增加 MES 分析快照与 Dify 显式异常分析流程。启动方式与当前接口约定见 [README](../README.md)。

任务包 05 的虚构规程、离线问题集和校验逻辑见 [EVIDENCE_FIRST.md](EVIDENCE_FIRST.md)。任务包 06 的真实 Dify 检索、确定性规则比较、六项报告及人工边界见 [ANOMALY_WORKFLOW.md](ANOMALY_WORKFLOW.md)；Stage B 已在证据门禁后接入 DeepSeek，按本次 MES 事实和预审查原文组织报告，生成后独立验证 JSON、引用和正文支持范围；不允许任意改写或新增结论，未接自由 Agent。契约见 [GENERATION_CONTRACT.md](GENERATION_CONTRACT.md)。独立的开放式知识问答与自主选工具场景尚未实现。

## 三个展示场景

| 场景 | 方式 | 依据与边界 |
| --- | --- | --- |
| 企业生产知识查询 | RAG | 根据企业正式文档回答，并返回可追溯出处；证据不足时明确说明 |
| MES/ERP/WMS 实时业务数据查询 | Agent / Tool Calling | 通过业务系统正式接口查询动态事实，不由模型猜测或用 AI 数据副本代替 |
| 生产异常辅助分析 | 业务系统事实 + 企业正式规程 + Workflow + LLM | 区分系统、数据、工艺异常，依据当前有效规则综合生成分析，生产处置由人工复核与决策 |

## 计划架构与技术职责

- **AI 交互与编排层：** 后续使用 Dify 承担 RAG、Agent、Workflow、Tool Calling，组织事实与证据并生成回答。
- **模拟业务系统接口：** 使用 Python、FastAPI 提供 MES/ERP/WMS 查询接口。
- **模拟业务系统后端：** `mes.db`、`erp.db`、`wms.db` 分别模拟三个系统的数据存储，不是 AI 自己维护的业务数据库。
- **企业知识来源：** 正式 SOP、操作规程与质量标准提供业务规则和可引用证据。
- **部署：** Dockerfile / Docker Compose 仅部署 FastAPI Mock API；既有 Dify 1.17.1 单独运行。启动和端到端验证见 [DEPLOYMENT.md](DEPLOYMENT.md)。

真实生产环境应通过 MES/ERP/WMS 提供的 API、数据库视图或其他正式接口查询动态数据。PoC 的模拟数据源不改变这一职责边界。

## Source of Truth

### 业务事实

MES/ERP/WMS 是业务事实的 Source of Truth。炉次号 `heat_id` 动态产生，炉次是否存在应由 MES 查询结果确认，不能依赖预生成的合法炉次全集，也不能由 AI 层维护完整生产数据副本来判断。

MES 查询不到炉次属于对象不存在或数据异常问题，不等于发生工艺异常。接口调用失败不能用来证明炉次不存在或生产参数异常。

### 业务规则

企业正式 SOP、操作规程、质量标准是业务规则的 Source of Truth。工艺异常必须依据当前炉次真实数据，以及与其对应的当前有效工艺参数/标准判断。LLM 不得凭训练知识自行决定正常范围。

## Evidence First

- 先取得足以直接支持答案的企业证据，再生成结论。
- 检索结果仅语义相近，而正文不能直接支持答案时，视为证据不足。
- 缺少充分企业证据时，拒绝生成确定性的生产处置结论，说明证据不足。
- 答案尽可能返回 `document_name`、`version`、`chapter`、`section`、`page` 等出处 metadata；未提供的 metadata 不得编造。
- 涉及生产处置的建议必须保留 Human-in-the-loop，由人工复核与决策。

## 异常分类

| 分类 | 典型情况 | 判断边界 |
| --- | --- | --- |
| 系统异常 | 接口 timeout、500、鉴权失败 | 表示系统调用失败，不能解释成生产异常或炉次不存在 |
| 数据异常 | 炉次不存在、关键字段为空、数据过期 | 表示对象或数据存在问题，不能直接认定为工艺异常 |
| 业务/工艺异常 | 当前炉次真实生产参数违反对应的当前有效规则 | 必须同时有业务事实和有效规则作为依据，不能由 LLM 自定阈值 |

## 第一版计划接口

以下路径已在任务包 01 实现；字段及测试样例见 README 和应用生成的 OpenAPI 文档，统一失败语义见 [API_CONTRACT.md](API_CONTRACT.md)。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/mes/heats/{heat_id}` | 查询炉次信息 |
| GET | `/api/mes/heats/{heat_id}/temperature` | 查询炉次温度数据 |
| GET | `/api/mes/heats/{heat_id}/chemistry` | 查询炉次成分数据 |
| GET | `/api/erp/material-requests/{request_id}` | 查询物料申请 |
| GET | `/api/wms/inventory/{material_code}` | 查询物料库存 |
| GET | `/api/mes/heats/{heat_id}/analysis-context` | 同一 MES 只读快照中的当前阶段、实测值及有效规则 |

## 明确不做

Stage C 已授权最小 MES 正式关联、ERP 生产任务、WMS 指定批次的只读联合 Workflow；不是完整 ERP/WMS。关联与有效性由 Code 校验，API provenance 与 RAG citation 分离，DeepSeek 仅组织经验证内容。具体契约及保守的演示新鲜度假设见 [ENTERPRISE_WORKFLOW.md](ENTERPRISE_WORKFLOW.md)。Stage A/B 原始记录继续保留。

- 不替代 MES/ERP/WMS，不把 AI 层变成生产业务数据的权威来源。
- 不建立 AI 完整生产数据副本，不预生成全部合法炉次号用于存在性判断。
- 不混淆系统异常、数据异常和工艺异常，不凭模型训练知识设定工艺范围。
- 不在企业证据不足时输出确定性的生产处置结论。
- 不直接向 PLC、控制系统或生产设备发送控制指令，不跳过人工复核与决策。
- 第一阶段不引入 React、LangGraph、知识图谱、多 Agent、Kafka、Redis、Kubernetes 或复杂微服务。
- 不擅自扩充技术栈或需求；复用用户现有 Dify 1.17.1。项目 Compose 只负责 Mock API，不封装 Dify。

## Stage F已授权扩展（2026-10-04）

统一中文React/TypeScript/Vite入口、FastAPI Gateway/Router/Presenter由本轮用户明确授权，原C/D/E1保持内部能力与冻结核心。新增Mock源详情和有界只读列表，400炉次、100订单、200批次；33份虚构内部资料和4份登记公开摘要分层隔离、真实Qwen索引。不是AI生产副本、不是生产系统认证、不是复杂多轮或新的Agent系统。实际验证及边界见Stage F报告，第一阶段禁用前端不适用于本轮明确授权。
