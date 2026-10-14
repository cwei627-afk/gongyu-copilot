# 最终技术架构

本项目是**基于虚构制造业数据的企业AI集成、可信检索与跨系统分析PoC**。当前统一中文入口为工域 Copilot，Dify作为内部能力后台；生成模型deepseek-flash，Embedding为本地Ollama Qwen3-Embedding-0.6B / 1024维，Dify1.17.1。原C/D/E1核心保持冻结，F2技术验证已完成、等待用户UAT，实际证据见[Stage F2记录](../audit_artifacts/STAGE_F2_ASTRA_VALIDATION.md)，历史F/E2记录保留。

原C/D/E1业务源码、Schema与DSL保持冻结；F2仅新增兼容适配层、隔离知识资产与工作流。FastAPI模拟企业只读接口；MES/ERP/WMS各自SQLite是被模拟系统的数据后端，不是AI生产数据副本。Dify原生PostgreSQL、Redis、sandbox等既有依赖与本项目业务技术栈分开，不新增队列或基础设施。

## 整体架构：一个用户入口

```mermaid
flowchart LR
  User["统一中文React页面"] --> BFF["FastAPI Gateway：同源、服务端凭证"]
  BFF --> Router["只读门禁 / 显式对象与时间 / 闭合意图分类"]
  Router --> C["原Stage C 确定性异常分析 Workflow"]
  Router --> D["原Stage D 只读 Function Calling Agent"]
  Router --> E["原E1 / 隔离扩容受控知识 / 公开参考 Workflow"]
  Router --> Lists["有界只读列表：默认10、最多20"]
  Lists --> API
  C --> API["FastAPI 只读 Mock API"]
  D --> Gate["请求权限 / 关联 / 事实门禁"]
  Gate --> API
  API --> MES["MES SQLite：炉次 / 实测 / 正式规则 / 关联"]
  API --> ERP["ERP SQLite：生产订单"]
  API --> WMS["WMS SQLite：指定批次库存"]
  C --> RAG["Dify Knowledge Retrieval"]
  E --> RAG
  RAG --> Evidence["有效版本 / 真实 hit / 直接支持"]
  Evidence --> LLM["DeepSeek：受约束组织已验证内容"]
  LLM --> Post["结构化 / 事实 / Citation 后验"]
  Post --> Human["输出与人工确认提醒"]
  Gate --> Human
  Human --> Presenter["确定性中文结果 / 来源卡片 / 技术白名单"]
  Presenter --> User
```

此前已渲染SVG是E2历史架构，当前入口关系以此图为准。

Stage F新增`app/copilot`作为兼容层，不把工艺比较交给自由Agent。六类意图为企业知识、公开行业知识、实时查询、异常分析、澄清和不支持；规则优先，只有未确定问题才调用无回答权限的结构化分类Workflow。分类结果不能创建实体或事实。

明确对象实时查询仍调用原D；异常分析仍调用原C；有限时间列表直接读取Mock后端新详情表，不增加D的工具白名单。短期追问只携带服务端签发的5分钟对象引用，每次重新查询；没有模型记忆或生产事实副本。

## 扩容知识与来源分层

F2新增隔离内部140份原创虚构资料（112现行、10历史、9撤销、9未来，14领域）和公开35份简短改述，分别真实导入与索引。原F的33/4份资料和原5文档知识库保留。生成正文→登记与hash→真实Dify文档/段落身份→结构化metadata→Qwen1024索引→原生检索→来源绑定→原文支持→DeepSeek→后验。完整知识题与桌面体验验收尚未结束。

扩容兼容层在独立命名空间复用E1和A/B校验；检索前后的完整目录、唯一现行版本、正文hash、scope、source_type、URL等保持绑定。公共资料不能作为公司制度，历史/未来/撤销版本不能支持现行结论。page没有可靠信息保持空。健康探针始终不能补用户问题证据。

F2桌面兼容层位于`app/copilot/workspace.py`；前端调用`/api/workspace/*`，原`/api/copilot/*`契约保留。展示短编号由各模拟源系统登记并通过只读接口解析，不能用来绕过MES存在性查询；原始身份及返回出处保留在技术详情。单系统列表不核验跨系统关系，完整对象查询和异常分析仍分别经过D/C门禁。状态面板显示真实服务探针的检查时间，不能据此判断某炉次正常。

新演示详情表位于MES/ERP/WMS模拟源数据库，固定seed与显式as-of生成；它们属于Mock系统。列表中的历史待复核标记是源字段，不是LLM或Gateway对当前工艺作出的判断。

## 模型与平台部署

```mermaid
flowchart TD
  Windows["Windows 本地 PoC / Docker Desktop"] --> Docker["现有 Docker Engine"]
  Docker --> Dify["现有 Dify 1.17.1：Web / API / Worker / Agent backend"]
  Dify --> Infra["既有 PostgreSQL / Redis / plugin daemon / sandbox / SSRF proxy"]
  Dify --> Vector["既有 Weaviate：正式 Qwen 索引"]
  Windows --> Ollama["宿主机 Ollama：Qwen3-Embedding-0.6B / 1024维"]
  Dify -->|"host.docker.internal:11434"| Ollama
  Docker --> CMock["Stage C Mock：18089 / 独立业务数据卷"]
  Docker --> DMock["Stage D Mock与权限适配：18090 / 独立数据卷"]
  Dify -->|"host.docker.internal"| CMock
  Dify -->|"host.docker.internal"| DMock
  Dify -->|"Provider HTTPS API"| Cloud["DeepSeek deepseek-flash"]
```

[已渲染SVG](../assets/diagrams/02-deployment.svg)

## Stage C确定性异常分析

```mermaid
flowchart TD
  S["heat_id + analysis_request"] --> H["MES存在性 / 当前快照"]
  H --> Rule["唯一有效规则 / 当前数据与时间"]
  Rule --> Compare["Code比较真实参数与有效范围"]
  Compare --> Links["MES正式关联 → ERP → WMS"]
  Links --> Identity["身份 / 钢种 / 物料 / 批次 / 单位 / 版本 / 时效"]
  Identity --> Joint["Enterprise Evidence Bundle与库存比较"]
  Joint -->|"无工艺异常"| Facts["联合事实；不检索、不调用LLM"]
  Joint -->|"确认工艺异常"| Retrieval["Qwen原生检索 + 目录版本过滤"]
  Retrieval --> Evidence["Stage A身份 / hash / 直接支持门禁"]
  Evidence -->|"不足"| Abstain["abstain / 无确定性处置"]
  Evidence -->|"充分"| Generate["Stage B/C DeepSeek结构化生成"]
  Generate --> Check["从原始HTTP与hit重建 / 事实与引用覆盖"]
  Check --> Review["review_required / 人工复核 / automatic_actions空"]
  H -->|"不存在或接口失败"| Stop["数据或系统错误；停止"]
  Rule -->|"缺失或冲突"| Stop
  Identity -->|"不匹配"| Stop
```

[已渲染SVG](../assets/diagrams/03-stage-c.svg)

## Stage D动态只读工具调用

```mermaid
flowchart TD
  Q["单轮明确业务ID查询"] --> Begin["有限意图 / 服务端请求权限与capability"]
  Begin -->|"范围不明或工艺请求"| Stop["澄清 / 拒绝 / 转Stage C入口"]
  Begin --> Agent["唯一官方 Function Calling Agent / DeepSeek"]
  Agent --> Choose["模型按需选择允许工具子集"]
  Choose --> Tools["mes_heat / mes_links / erp_order / wms_batch：仅GET"]
  Tools --> Gate["固定后端 / 前置事实 / 同一请求关联 / 调用预算"]
  Gate --> Source["真实MES / ERP / WMS HTTP"]
  Source --> Check["格式 / 身份 / 单位 / revision / 时效 / hash"]
  Check --> Agent
  Agent --> Terminal["原生日志最后无工具轮次"]
  Terminal --> Finish["完整JSON / 全量原文事实覆盖"]
  Finish --> Output["服务端 facts与API provenance / citations空"]
  Gate -->|"越权 / 重复 / 超限"| Fail["停止 / 清空最终事实与出处"]
  Check -->|"源失败或身份冲突"| Fail
```

[已渲染SVG](../assets/diagrams/04-stage-d.svg)

## Stage E1有限知识问答

```mermaid
flowchart TD
  Q["question：无需heat_id"] --> Input["有限已评审别名 / 输入边界"]
  Input --> Catalog["官方完整目录 / 当前版本与范围"]
  Catalog --> Health["真实Ollama调用：模型 / 1024维 / 有限数值"]
  Health --> Canary["原生检索健康探针：不作为答案证据"]
  Canary --> Retrieval["用户问题原生Knowledge Retrieval"]
  Retrieval --> Gate["目录复核 / 真实hit身份hash / 原文直接支持"]
  Gate -->|"无或部分证据"| Abstain["abstain / 不调用正常生成"]
  Gate -->|"充分"| LLM["DeepSeek原生结构化组织"]
  LLM --> Check["目录再复核 / 完整schema / 原句与Citation覆盖 / HITL"]
  Check --> Output["answered：真实引用、适用边界、人工提醒"]
  Health -->|"失败"| Error["系统失败；无正常结论"]
  Canary -->|"失败"| Error
  LLM -->|"失败"| Error
```

[已渲染SVG](../assets/diagrams/05-stage-e1.svg)

## 事实、Evidence Bundle、API provenance与Citation

```mermaid
flowchart LR
  MES["MES / ERP / WMS：业务事实权威"] --> HTTP["本次可信HTTP执行与响应"]
  HTTP --> API["Code验证事实 / API provenance"]
  Rules["MES正式有效规则：参数判断依据"] --> Compare["确定性工艺比较"]
  HTTP --> Compare
  Docs["虚构正式企业文档：规程权威"] --> Hit["本次用户真实Retrieval Hit"]
  Registry["受控登记：约束身份 / 版本 / hash"] --> Verify["验证hit与直接支持"]
  Hit --> Verify
  Verify --> Cite["Code创建请求绑定Citation"]
  API --> Bundle["Enterprise Evidence Bundle"]
  Compare --> Bundle
  Cite --> Bundle
  Bundle --> LLM["LLM只组织允许的事实和原句"]
  LLM --> Post["从原始HTTP / hit再校验"]
  Post --> Human["人工确认；无自动控制"]
```

[已渲染SVG](../assets/diagrams/06-trust.svg)

## 三类异常与停止分支

```mermaid
flowchart TD
  Query["查询与验证"] --> Kind{"来源结果"}
  Kind -->|"500 / timeout / 鉴权或协议失败"| System["system_error：事实未知"]
  Kind -->|"404 / 空字段 / 过期 / 版本或身份冲突"| Data["data_error：对象或数据不可用"]
  Kind -->|"有效事实 + 唯一有效规则"| Compare["Code参数比较"]
  Compare -->|"未违反规则"| Normal["no_anomaly：返回事实"]
  Compare -->|"违反有效规则"| Anomaly["真实业务或工艺异常"]
  Anomaly --> Evidence{"有效企业证据充分?"}
  Evidence -->|"否"| Abstain["abstain：无确定性处置"]
  Evidence -->|"是"| Generate["受约束生成 + 后验 + 人工复核"]
  System --> Stop["停止正常推断 / 不补造事实或出处"]
  Data --> Stop
```

[已渲染SVG](../assets/diagrams/07-errors.svg)

## 可信边界与适用范围

- 企业事实由实际只读HTTP取得；对象存在性以MES查询为准，不枚举合法炉次。参数范围来自MES的唯一有效规则，与实测值分离，Code比较而非模型设阈值。
- 文档Citation只能来自本次已验证用户hit：dataset/document/segment、版本、日期、范围、章节/page、正文hash保持一致。Registry只是约束，不能补Citation；健康canary不能补用户证据。
- API provenance由可信执行与Code产生，保留operation、endpoint、entity、request、revision、时间和hash，不转为文档Citation。SHA-256用于完整性，并非来源签名；PoC信任本机后端和Dify管理环境。
- 有充分证据后才生成；schema合法仍须检查原句、事实、引用和适用条件。LLM输出不授予来源权威。确定性500/timeout、模型/协议失败与证据不足分别处理；无成功End的Workflow按系统失败。
- Stage D最多4次业务调用、每工具一次、6轮Agent、5秒源timeout；关系必须来自已验证上游返回。同一请求能力短期保存响应，不是业务数据副本。
- E1的QA_ALIASES/qa_plan是有限人工评审映射，拒绝未评审表达和缺条件的开放问题。没有通用自然语言蕴含证明。
- 生产建议需人工确认，automatic_actions=[]。没有审批系统、设备控制、生产鉴权、多轮记忆或原子跨系统快照。

固定工艺分析优先Workflow，显式顺序和停止条件可检查；Agent只承担用户明确对象的按需只读查询，不替代工艺判断。两者不预设性能优劣，实际历史比较见[AGENT_VS_WORKFLOW](AGENT_VS_WORKFLOW.md)。
