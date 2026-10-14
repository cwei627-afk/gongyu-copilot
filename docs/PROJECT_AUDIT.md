# 最终技术审计 · Stage E2 · 2026-10-02

当前范围内：P0 **0**、P1 **0**、blocker **0**；P2 **4项**记录如下。READY仅指本机PoC Demo和交付验收，既不表示生产就绪，也不表示已公开发布。原始发现及各阶段修复记录保留在下方与私有审计包。

| 能力 | 状态 | 当前证据与边界 |
|---|---|---|
| C跨系统确定性分析与正常/缺失/无SOP/冲突失败 | VERIFIED | 本轮14个实际发布API与原生Trace，规则Code比较，模型不设范围 |
| D独立只读Agent、四工具和六种不同动态路径 | VERIFIED | 本轮19实际发布运行；模型选择日志与真实HTTP账本逐条核对 |
| E1有限单轮QA、Qwen检索、DeepSeek、拒答 | VERIFIED | 本轮11实际发布运行；5回答/6拒答；不支持开放行业问答 |
| Citation/事实覆盖、Evidence First、provenance分离 | VERIFIED | 实际hit、hash与后验重验；13原probe、34独立安全边界验证及全量回归 |
| 冻结源码/原tests/schema/DSL/知识身份与三App图 | STATICALLY_VERIFIED + VERIFIED | 修改前1431文件基线；平台draft/publish图及发布ID前后核对；测试通过 |
| Windows本机启动与C/D停止后恢复 | VERIFIED | start/check/stop/restart实际日志；Live三入口成功 |
| 七幅实际架构图 | VERIFIED | Mermaid CLI渲染SVG，XML核验，整体图视觉检查；不新增运行依赖 |
| 新机器/新实例部署及完整Windows重启 | DOCUMENTED_ONLY | 手工重新索引/来源身份登记/secret/provider绑定步骤已写，尚未实测 |
| 生产系统接入、真实权限/负载/审批 | NOT_IMPLEMENTED | 本项目只使用虚构数据，HITL为明确人工提醒，没有审批平台 |
| 多轮、统一前端、任意语义蕴含、设备控制 | NOT_IMPLEMENTED | 明确不做，不以计划冒充完成 |
| 阻塞验收项 | 无BLOCKED | 包内容与凭证扫描证据由最终ZIP收据单独记录 |

## P2记录与限制

1. **有限语义与表达**：E1人工评审别名与原文句子映射保守；生成后逐字覆盖不是开放式自然语言蕴含证明。未知问题按abstain处理，不为展示扩大语料。
2. **跨源并发原子性**：当前目录多次检查、hash及健康探针不能形成全局原子事务；来源在检查间变化、并发行政修改仍需真实接入时设计正式快照。可信管理员/后端是信任假设，hash是完整性校验，不是签名。
3. **PoC运维与初始化**：三个SQLite初始化不是跨库原子事务，失败保留现场并换新run；21600秒为演示有效期，非企业SLA。没有生产认证/高可用/负载或统一自动审批；跨机器和整机重启尚未验证。

4. **Agent失败后的额外规划尝试**：本轮ERP身份冲突、版本、时效3个失败Trace中，模型各尝试了一次后续WMS工具；适配层返回同一终止错误，没有发出额外HTTP，最终facts/provenance/citations为空。不能宣传模型总会立即停止，约束来自确定性门禁。

上述不阻塞当前限定PoC验收，不改变既有错误语义。真实远端Provider故障未主动制造，不声称其本轮实测；本地故障/确定性重放和实际正式Trace明确分开。

## 外部依赖与交付

需要自己的Dify1.17.1实例及原生插件、DeepSeek凭证、Ollama Qwen模型、现有Weaviate/平台依赖；新实例必须重新生成dataset/document/segment/provider/app身份并严格登记，不能复用旧向量混合或仅改Prompt。API keys与Agent control secret仅在本地忽略配置中。

仓库存在真实无密钥Workflow/Agent DSL，不是只有计划；三应用保持独立，无统一聊天产品。对外源码包不携带Dify、模型权重或任何真实企业数据。当前没有Git仓库或正式LICENSE，仓库名、授权许可证、公开范围和个人贡献表述需用户确认。



## 续跑冷启动修复与验证 · 2026-10-02

完整回归完成后再次续跑时，Docker/Ollama已停止，旧演示数据超过21600秒有效期。没有刷新旧记录；恢复后用`start_demo.ps1 -NewData`新增独立虚构run。

**E2-START-001 / P1 / FIXED（2026-10-02）**：启动脚本此前没有使用配置中的Dify Compose项目名，曾在安装目录误启动默认`docker`项目，遇到已有`dify`插件端口5003冲突。仅停止本次误启动且工作目录匹配的`docker-*`容器，保留容器/卷/失败日志，未删除或重置原Dify数据。修复为启动/共享停止均显式指定配置项目，并先验证该项目已有API容器；未知项目在执行Compose前拒绝。另支持显式Docker Desktop路径及根据现有CLI定位非标准安装。

Desktop遗留socket错误通过备份重命名用户目录下两个明确的运行时socket目录恢复；未清空数据卷、重建知识库或改变模型。恢复记录为`stage_e2_resume_runtime_recovery.json`；首次路径失败及默认项目端口冲突分别保留在`stage_e2_final_demo_start.initial.txt`、`stage_e2_final_demo_start.duplicate_project_failure.txt`，没有改写为成功。

| 补充验证 | 实际结果 | 证据文件 |
|---|---|---|
| 停止原Dify API后执行修复版启动，强制覆盖原项目冷启动分支 | 正确恢复原`dify`项目及Mock/Ollama | stage_e2_resume_api_stop.txt、stage_e2_final_demo_start.txt |
| 当前独立数据上真实发布API/服务健康检查 | C/D/E1 **3/3**，全部服务PASS | stage_e2_final_demo_health.txt |
| 与交付相关pytest | **11 passed /0 failed**，38.02秒，1条既有警告 | stage_e2_resume_delivery_pytest.txt |
| 未知Compose项目的启动/停止保护 | **2/2 PASS**，明确为模拟Docker/HTTP的负向脚本测试 | stage_e2_resume_script_guards.txt、tests/test_demo_scripts.ps1 |
| 三正式图、发布ID、知识身份/hash与冻结文件复查 | PASS，未重发或迁移知识库 | stage_e2_resume_checks.txt、stage_e2_checks.json |
| 公开ZIP逐成员保护回归 | **7/7 PASS**，6项合成负向拒绝，1项完整安全ZIP通过 | stage_e2_package_probe.json/txt |

补充执行命令（工作目录为项目根目录）：

```powershell
docker stop dify-api-1
.\start_demo.ps1 -NewData
.\check_demo.ps1 -Live
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/test_delivery.py
.\tests\test_demo_scripts.ps1
.\.venv\Scripts\python.exe -B audit_artifacts/stage_e2_checks.py
.\.venv\Scripts\python.exe -B audit_artifacts/stage_e2_package_probe.py
```

**E2-PACK-001 / P1 / FIXED（2026-10-02）**：公开ZIP的个人路径、原始Trace排除和Markdown链接检查原先缩进在成员循环外，仅检查最后一项。已移入循环，对每个实际成员检查；密钥/路径排除/CRC/manifest hash检查本来就在逐成员执行。新增真实ZIP字节变异回归：不在最后位置的个人路径、偏好、私有Trace、失效链接以及合成密钥模式/.env均拒绝，完整安全ZIP通过。两份最终包在修复后重新生成并扫描，结果见外部stage_e2_zip_verification.json；早先收据不作为修复后扫描证据。

本次补充只修改E2启动/停止脚本、配置模板、打包校验、文档及独立测试；冻结业务实现未改。全量621/26、Compose26与正式发布44项仍是本轮先前真实完整运行，未把补充3次调用或11项复测重复计入。清洁/公开容器全量验证也早于本次PowerShell修复；未声称修复后重新运行这些完整矩阵。完整Windows重启、新机器迁移仍未验证。当前未解决P0=0、P1=0、P2=4、blocker=0。


## 用户要求的最终复核 · 2026-10-02

**E2-TEST-001 / P1 / FIXED（2026-10-02）**：最终交付目录生成后，根目录默认pytest会递归收集release_public/tests与release_review/tests，导致28项import file mismatch收集错误。这是原交付验收的真实遗漏；此前全量通过发生在生成交付目录之前，不能用于证明最终目录状态可直接重跑。失败日志/XML原样保留为stage_e2_recheck_pytest.collection-failure.txt/XML。

最小修复为新增pytest.ini，默认testpaths=tests；不删除任何旧测试、交付副本或失败记录。Dockerfile仅测试阶段复制配置，两个包明确包含该文件。README说明测试收集范围，并与DEPLOYMENT一起明确仅首次创建.env.demo.local，避免覆盖现有凭证。

修复后在同时存在两个交付目录的最终根目录执行原默认命令，全量**621 passed /26 skipped /0 failed /0 errors**，实际JUnit耗时389.635秒，仍有1条既有Starlette/AnyIO警告。新独立Compose项目fde-e2-recheck-20261002使用新虚构卷，**26/26**通过（5.55秒）；原C/D服务与数据卷未替换。正式发布实时健康复测C/D/E1 **3/3**、所有服务PASS；原Citation探针再次**13/13 fail closed**。Dify当前三draft/publish图、发布ID、Qwen索引配置、5来源身份/hash、四工具与冻结业务文件复核PASS。

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider --basetemp=<临时目录>/stage-e2-recheck-20261002-fixed --junitxml=audit_artifacts/stage_e2_recheck_pytest.xml
$env:API_PORT='18093'
docker compose --env-file .env.stage-d -p fde-e2-recheck-20261002 -f docker-compose.yml -f docker-compose.stage_d.yml --profile test build api e2e
docker compose --env-file .env.stage-d -p fde-e2-recheck-20261002 -f docker-compose.yml -f docker-compose.stage_d.yml --profile test run --rm e2e
.\.venv\Scripts\python.exe -B scripts/demo_health.py --live --json-output audit_artifacts/stage_e2_recheck_health.json
.\.venv\Scripts\python.exe -B audit_artifacts/stage_e2_checks.py
```

构建在已验证ASCII junction中执行。Citation原脚本只重定向输出到stage_e2_recheck_citation_probe.json，源码未改。证据为stage_e2_recheck_pytest.txt/XML、stage_e2_recheck_compose_build.txt、stage_e2_recheck_compose.txt、stage_e2_recheck_health.txt/JSON、stage_e2_recheck_checks.txt及stage_e2_recheck_citation_probe.txt/JSON。原44项完整发布矩阵保留，本次3项实时复测不冒充重新执行44项。

两份ZIP在修复后重新生成，逐成员验证配置、当前源码hash、CRC、排除项与敏感值，最终证据仍为外部stage_e2_zip_verification.json。公开包测试收集同时复核，不用旧包的哈希替代新包。当前限定PoC状态PASS；未解决P0/P1/blocker为0，P2仍为4，原未验证生产/跨机器/整机重启边界不变。

---

## 以下为原阶段记录（历史结果，不代表E2本轮）

# 项目状态与技术审计

## 当前补充状态：Stage F / F-Data（2026-10-04）

以下早期审计正文和Stage C更新作为**历史记录保留**，其中“未接LLM/Agent/在线RAG/来源未绑定”等描述不是当前结论。当前分阶段证据以`WORK_FINAL_AUDIT.md`和各阶段VALIDATION为准；Stage F结果见[STAGE_F_VALIDATION](../audit_artifacts/STAGE_F_VALIDATION.md)。

本轮真正实现并验证：统一中文React/TypeScript页面、同源FastAPI BFF、六类意图安全路由、可信结果展示；独立虚构400炉次/100订单/200批次及有限日期列表；30现行+3非现行虚构内部规程、4公开主来源改述摘要，两个实际Qwen1024隔离索引、真实metadata、检索身份/hash及生成门禁。公开资料不替代企业标准。原88个核心源码/测试/资产/DSL、原C/D/E1草稿和发布图/ID、原5文档知识库未变。

本轮最终pytest **725 passed / 31 skipped / 0 failed**，31部署项随后Compose **31/31**。原发布C **14/14**、D **19/19**、E1 **11/11**；随机业务 **50/50**、新RAG发布 **53/53**、新草稿 **11/11**、恢复后发布 **3/3**、Citation probe **13/13 fail closed**、浏览器 **13/13**，前端构建和安全扫描通过。初期运行失败与重跑均保留，不将历史通过数当本轮结果。

未完成或未验证的边界：真实企业API/鉴权、生产权限与审批留痕、跨机器首次迁移/完整Windows重启、负载/SLA、全部浏览器/辅助技术、任意自然语言蕴含、远端Provider真实429/500。有限问法之外可保守拒答，不声称生产级。Dify、DeepSeek凭证和Provider、既有Ollama Qwen、实例专属来源ID/metadata/索引绑定仍是外部与人工配置依赖；已有本机配置可复用，但不能复制秘密到客户端或公开包。

本轮无已知P0/P1/blocker；P2与未验证范围见Stage F报告。现有E2 ZIP只扫描、未重打包，仍为历史快照，不含Stage F。以下为原审计，不覆盖原始发现。

**2026-10-01 Stage C 更新**：原始审计发现保留如下；Stage A 来源与版本修复、Stage B 受约束生成均已验证，Stage C 新增只读跨系统身份/API provenance 与事实覆盖，并修复 API 文本反射引用标记缺口。当前状态及实际 Dify 验证见 `audit_artifacts/STAGE_C_VALIDATION.md`，本地全量 434 passed / 21 skipped，最新 Compose 21 passed。历史“ERP/WMS 未编排”不代表当前状态。仍非通用语义审查或真实企业接入。

审计口径：仓库源代码、测试、部署文件、虚构资产和 Dify DSL。运行状态与验证结果仅指本报告记录的命令和范围；外部 Dify UI 配置仍需人工确认。

## 已完成并测试

- FastAPI 提供健康检查，以及 MES 炉次、温度、化学成分，ERP 物料申请、WMS 库存只读 API；SQLite 是业务系统模拟后端。基础查询、字段缺失、对象不存在及参数错误有自动化测试。
- API 使用结构化响应和错误契约，OpenAPI 有自动化验证并导出到 docs/openapi.json。
- MES 异常分析模块执行只读快照校验、有效演示规则校验和确定性实测值比较；测试覆盖正常、异常、缺失、对象不存在、系统失败等停止条件。
- 虚构规程、问题集和离线证据评审资产已提交；证据门禁结果有测试。
- Dockerfile / Compose、健康检查和部署 E2E 已运行验证。
- 2026-09-29 本轮本地完整 pytest：218 passed、11 skipped、0 failed；Compose E2E：11 passed。具体命令和警告见 docs/TEST_REPORT.md。

## 部分完成 / 存在审计问题

- Dify 异常分析 Workflow DSL 有默认版和本机绑定知识库版，仓库另有已保存的在线验证记录；但本轮未重新操作 Dify UI 验证导入后的当前状态。
- Workflow 的 Knowledge Retrieval 结果检查有限，使用受控 manifest。源码的证据判断未将 Dify hit 的 document_id / segment_id 与清单来源身份绑定。审计探针保持正文内容不变、将 hit metadata 换成无关且已撤销的来源后，仍得出受支持结果并生成清单 citation。因此当前展示引用不能证明检索结果确由所引来源产生；这是阻碍可信来源追溯的 P0。
- 离线通用 Evidence gate 消费预先提供的人工评审 verdict，不是在线检索与自然语言蕴含判定器。评审标注错误可以改变结果。它的测试不能证明任意相近段落直接支持用户问题。
- 当前演示知识库和规则完全虚构，仅用于 PoC，不可用于真实生产处置。
- 样例具有有效期/时效限制。全新 Compose 数据卷会重建种子记录；已有数据不会按时间戳自动刷新。长期运行时需重新初始化演示数据或重建独立 PoC 数据卷。

## 未完成 / 仅属设计或计划

- 自然语言企业知识问答的在线 RAG Workflow、生成答案、充分性评审和带完整来源绑定的 Citation。
- 用 LLM 根据正式证据进行综合生成；当前异常 Workflow 没有 LLM 节点。
- 自然语言参数抽取和 Agent 自主选择 Swagger API Tool。
- ERP 物料申请 + WMS 库存的自动编排和 AI 综合回答。
- 真实 MES / ERP / WMS 连接、鉴权、权限治理及生产级 SLA。
- 独立审批、人工确认记录与反馈系统。当前只提供人工确认提醒。
- 对任意企业文档进行当前版本、生效日期和权限过滤的生产级索引治理。
- P0 Citation 身份关联修复及相应的负向回归测试。
- 全链路实时在线 UI 验证（本报告的 Compose E2E 不包括 Dify UI）。

## 外部依赖与人工配置

- Dify 1.17.1：需要可运行实例、导入工作流 DSL、检查 API base URL、导入/绑定正确知识库并确认文档已索引。
- 外部业务 API：未来接真实 MES / ERP / WMS 时，需要企业正式只读接口、网络、身份认证、权限、错误映射及接口负责人。
- 当前代码与 DSL 未配置 LLM，因此当前 PoC 没有 LLM API Key 依赖。未来加入 LLM 或语义 Embedding 前，需要在 Dify UI 配置兼容的模型供应方、API Key、Embedding 模型和模型授权；这些尚未验证。
- 演示需要人工检查数据是否仍处于有效演示窗口，并在 Dify UI 复核 Workflow 输出与引用。

## DSL 资产

仓库有 Dify Workflow DSL：workflows/heat_analysis.yml 与 workflows/heat_analysis.local.yml。本机版绑定外部数据集 ID；默认版数据集列表为空。Dify workflow configuration not included in repository 指 DSL 文件根本不存在时使用；本仓库实际包含 DSL。导入后的服务端实例配置、插件状态和数据集内容不由 Git 管理。
