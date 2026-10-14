# 测试报告

## Stage F2 最终本轮实测 · 2026-10-06

实施与技术验证完成，等待用户UAT。本节仅使用F2实际日志，不将历史阶段结果当作本轮运行。

| 检查 | 实际结果 | 证据 |
|---|---|---|
| 最后一次完整pytest | **1066 passed / 36 skipped / 0 failed**，770.02秒，1条既有Starlette/AnyIO弃用警告 | stage_f2_full_pytest_release.txt/XML |
| 隔离Compose部署 | **36/36通过**，1.27秒 | stage_f2_compose_final.txt、stage_f2_compose_release_retry.log |
| 原C/D/E1真实发布API | **44/44**：C14、D19、E1 11 | stage_f2_original_regression.log |
| 原Citation probe | **13/13 fail closed** | stage_f2_citation_probe.log/JSON |
| 新F2真实发布知识矩阵 | **300/300**：企业200、证据不足50、公开50 | stage_f2_knowledge_metrics.json及逐题stage_f2_live_*.json |
| F2真实草稿及metadata故障 | **10/10**，5种故障全部abstain；元数据恢复后answered | stage_f2_draft_release_retry.log、stage_f2_draft_*.json、stage_f2_metadata_restore.json |
| 冻结检查 | 88原文件、3原正式应用图/发布ID及原5份知识目录不变 | stage_f2_frozen_release.log/JSON |
| 前端 | TypeScript与Vite构建成功，7.25秒 | stage_f2_frontend_release_build.txt |
| 浏览器 | 40个不同实际问题，最新预期39符合、1保守拒答；初始失败及重测均保留 | stage_f2_browser_results.json、stage_f2_browser_metrics.json |
| 桌面复查 | 9类场景×2完整复查轮×2尺寸；1366×768首页另抽查 | stage_f2_screenshot_reviews.json、stage_f2_final_screenshot_receipt.json |

最终安全扫描实际**1929文件、0项发现、0份source map**（已知密钥值与凭证模式检查，不能证明所有未知编码秘密均不存在）。范围与结果见`audit_artifacts/stage_f2_security_release.log`及`stage_f2_security_scan.json`，以实际扫描输出为准。扫描覆盖前端源码/构建、适配层、源编号模块、脚本、测试、F2知识资产、DSL、文档及F/F2文本证据；服务器本地密钥不导出。旧ZIP不是本轮交付，未重新扫描或生成。

实际命令（项目根目录）：

```powershell
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -B -m pytest -q --tb=short --junitxml=audit_artifacts/stage_f2_full_pytest_release.xml
.\.venv\Scripts\python.exe -B audit_artifacts/stage_f2_compose_run.py
.\.venv\Scripts\python.exe -B audit_artifacts/stage_f2_original_published_regression.py
.\.venv\Scripts\python.exe -B audit_artifacts/stage_f2_live.py internal --resume --workers 2
.\.venv\Scripts\python.exe -B audit_artifacts/stage_f2_live.py public --resume --workers 1
.\.venv\Scripts\python.exe -B -u audit_artifacts/stage_f2_draft_validation.py
.\.venv\Scripts\python.exe -B audit_artifacts/stage_f2_metrics.py
.\.venv\Scripts\python.exe -B audit_artifacts/stage_f2_frozen_check.py
.\.venv\Scripts\python.exe -B audit_artifacts/stage_f2_security.py
npm.cmd run build --prefix frontend
```

Citation probe使用原`citation_provenance_probe.py`代码，仅在内存改为F2报告文件名，原脚本未修改。截图转换及收据使用Codex既有依赖运行时的Pillow，不增加项目依赖。

36个普通pytest跳过项都是Compose专用检查：原11、企业10、D5、F5、F2 5；均在上面的36项隔离部署中启用。没有失败用例被改成跳过。

300题的“正确”是与编写时评审的完整检查项、预期状态及真实hit身份一致，**不是开放式问答准确率**。人工另审26份回答（20内部、6公开），见STAGE_F2_MANUAL_ANSWER_REVIEW.md。40个浏览器问题覆盖动态列表、真实跨系统查询、上下文引用、工艺分析、来源、无证据、空值、对象不存在、权限拒绝和真实网关中断。当前共享后缀改写的1项拒答是保留边界，不隐瞒为全部浏览器通过。

中间失败完整保留：旧隔离fixture过期导致Compose6失败30通过（stale_fixture_failure/diagnosis），新的独立fixture目录复测36通过；草稿驱动仅取目录第一页导致StopIteration（draft_pagination_failure），修复驱动分页后10通过且受控元数据读回一致；早期UI源编号映射/午夜时间、复合SOP路由、裸英文传输错误与健康状态错误均有原输出及修复后重测。未刷新旧业务事实或放宽时效门禁。

未自动化或本轮未验证：任意语义改写的支持判定、全新机器迁移、完整Windows重启、调整十分钟等待后的完整Dify冷启动、真实远端DeepSeek429/500、生产权限/容量/高可用、真实企业资料与设备。健康检查为入页实测并在查询传输失败时降级，恢复后刷新重新测，不是持续监控。

历史报告保留如下。

## Stage E2最终验收 · 2026-10-02

本节来自本轮真实运行，不使用历史数字代替。647项宿主机pytest：**621 passed / 26 skipped / 0 failed / 0 errors**，410.87秒；1条既有Starlette/AnyIO弃用警告。26项部署专用测试在普通pytest中按设计跳过，已在独立Compose部署完整运行：**26/26通过**，1.26秒。

三条正式发布入口：C **14/14**、D **19/19**、E1 **11/11**；均有实际workflow_id、Execution Trace和脱敏结果。原Citation probe **13/13 fail closed**。补充安全验证 **34/34**：真实发布输出后的确定性攻击重放、适配层越权检查及本地HTTP故障注入；不能把这些称为远端DeepSeek故障或攻击下的真实Dify运行。

实际命令与证据：

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider --basetemp=<临时目录>/stage-e2-final-complete --junitxml=audit_artifacts/stage_e2_pytest.xml
$env:API_PORT='18092'
docker compose --env-file .env.stage-d -p fde-stage-e2 -f docker-compose.yml -f docker-compose.stage_d.yml --profile test build e2e
docker compose --env-file .env.stage-d -p fde-stage-e2 -f docker-compose.yml -f docker-compose.stage_d.yml --profile test run --rm e2e
.\.venv\Scripts\python.exe -B audit_artifacts/stage_e2_live.py
.\.venv\Scripts\python.exe -B audit_artifacts/stage_e2_safety.py
.\start_demo.ps1
.\check_demo.ps1 -Live
.\stop_demo.ps1
```

Citation命令以原citation_provenance_probe.py原代码执行，仅将报告文件名改为E2独立文件，原脚本及历史报告不变。保存日志：stage_e2_pytest.txt/XML、stage_e2_compose_final.txt、stage_e2_citation_probe.txt、stage_e2_citation_provenance_probe.json；原生Trace/HTTP账本和逐项矩阵见[本轮验证](../audit_artifacts/STAGE_E2_VALIDATION.md)、[矩阵](../audit_artifacts/STAGE_E2_TEST_MATRIX.md)。完整测试镜像另外在不传任何凭证的容器运行：`docker run --rm fde-stage-e2-e2e python -B -m pytest -q -p no:cacheprovider`，实际621 passed /26 skipped /0 failed，534.72秒，见stage_e2_clean_container_pytest.txt。首次容器缺少docs/workflows失败3项的原日志保留；补齐test COPY后全量复测。

新增11项tests/test_delivery.py验证当前虚构数据、命名run幂等、不刷新旧记录、关键字段、库存150/50/0和跨run规则隔离。原A/B/C/D/E1测试均未修改或删除。

公开白名单目录另作独立构建/复现：在release_public运行`docker build --target test -t fde-e2-public-tests .`，然后`docker run --rm fde-e2-public-tests python -B -m pytest -q -p no:cacheprovider`，**621 passed /26 skipped /0 failed**，466.33秒，1条同类弃用警告；没有传入任何外部凭证。日志stage_e2_public_build.txt、stage_e2_public_reproduction.txt。文档路径脱敏与摘要变化不影响业务源码/schema/测试/DSL语义；新Dify实例的全链路仍需人工绑定且未实测。

未自动化/本轮未验证：全新机器/第二Dify实例迁移、完整Windows重启、生产认证与授权/负载/灾备、真实企业系统、真实远端DeepSeek429/500、多轮/开放语义问答。E1历史服务停止实验保留，不当作E2再次执行；首次启动/停止复测针对C/D Mock，后续Docker/Ollama停机后的冷启动与原Dify API恢复另见下方续跑记录。



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

# 测试报告

## Stage E1 本轮最终结果（2026-10-02）

以下是本轮实际运行记录，Stage A/B/C/D 后文保留为历史。

| 本轮验证 | 实际结果 | 证据 |
|---|---|---|
| 全量 pytest | 636 项：610 passed / 26 skipped / 0 failed / 0 errors；420.39 秒 | stage_e1_pytest.txt / .xml |
| 新增 E1 离线单元回归 | 84 项，包含于上述全量结果；原测试不变 | tests/test_knowledge_qa.py |
| 原有 Compose E2E，当前独立虚构数据 | 26 passed / 0 failed；最终重建后1.55秒 | stage_e1_compose_final.txt |
| E1 真实草稿测试 | 50/50：40项矩阵 + 2项真实索引停止/恢复 + 8项最终草稿 | stage_e1_results_matrix.json / stage_e1_index_health_results.json / stage_e1_results_final_draft.json |
| E1 实际发布 API | 11/11，均使用本轮发布 ID | stage_e1_published_results.json |
| 原 Stage C/D 实际发布 API 回归 | 10/10，包含2项旧数据过期拒绝；其余使用新增独立虚构对象 | stage_e1_regression_results.json |
| 原 Citation provenance probe | 13/13 fail closed | stage_e1_citation_provenance_probe.json |
| 冻结与来源交叉核验 | 963个原文件不变；C/D草稿/发布图及ID不变；5文档/5片段身份、metadata、正文hash不变；13个成功草稿输出、17条Citation重建一致 | stage_e1_final_checks.json |

实际命令（仓库根目录；Docker build 使用仅含 ASCII 字符的本地路径 junction）：

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider --basetemp=<临时目录>/stage-e1-final --junitxml=audit_artifacts/stage_e1_pytest.xml
$env:API_PORT='18091'
docker compose --env-file .env.stage-d -p fde-stage-e1 -f docker-compose.yml -f docker-compose.stage_d.yml --profile test build
docker compose --env-file .env.stage-d -p fde-stage-e1 -f docker-compose.yml -f docker-compose.stage_d.yml --profile test run --rm e2e
.\.venv\Scripts\python.exe -B audit_artifacts/stage_e1_matrix.py
.\.venv\Scripts\python.exe -B audit_artifacts/stage_e1_index_health.py
.\.venv\Scripts\python.exe -B audit_artifacts/stage_e1_regression.py
.\.venv\Scripts\python.exe -B audit_artifacts/stage_e1_publish.py
.\.venv\Scripts\python.exe -B audit_artifacts/stage_e1_final_checks.py
```

26个本地跳过是原部署测试，随后在Compose全部执行。没有失败或error；有1条既有Starlette/AnyIO弃用警告。新增84项覆盖来源/版本/正文篡改、目录冲突、范围/部分支持、请求级Citation、严格JSON/schema/截断/think、越权内容、人工边界及Embedding/检索健康检查。

真实Dify矩阵区分正常实际检索/生成、实际检索后的来源变异、实际DeepSeek后的生成变异和配置故障。QA-22实际停止本地Ollama；另实际停止/恢复Weaviate。QA-24为Provider拒绝非法max_tokens配置，不是声称制造远端DeepSeek429/500。HTTP transport无成功End时，调用方归类WORKFLOW_EXECUTION_FAILED系统失败，不把缺输出当作知识不存在。

旧18090数据卷直接运行为20 passed / 6 failed（stage_e1_compose_expired.txt）；6项正向Demo因源数据超过有效时限而被正确拒绝。保留旧失败及时间戳，用新18091独立虚构卷重跑原26项。C/D原正式API另检查旧对象过期拒绝，再新增当前独立虚构对象完成真实回归，不改旧对象/预期。初期模型合并原文换行和Ollama失效被原生检索吞为[]的失败记录均保留，根因与修复见STAGE_E1_VALIDATION.md。

未验证：任意开放中文蕴含、生产鉴权/权限/并发、远端真实DeepSeek429/500、全局原子知识快照、完整Windows重启、跨实例自动迁移。E1只覆盖已评审问题与既有虚构DEMO-A/review规程；转炉终点及温度记录缺失专门流程没有证据，必须abstain。

完整输入/预期/实际输出/执行层级/trace、性能和文件清单见 [Stage E1验证](../audit_artifacts/STAGE_E1_VALIDATION.md)。

## Stage D 最终本轮结果（2026-10-01）

以下数字来自本轮真实执行；后面的 Stage A/B/C 数字保留为历史，不能替代本轮结果。

| 验证 | 本轮结果 | 原始记录 |
|---|---|---|
| 全量 pytest | 552 项：526 passed / 26 skipped / 0 failed / 0 errors；263.16 秒 | stage_d_final_pytest.txt / .xml |
| Stage D Compose：原 21 项 + 新 5 项 | 26 passed / 0 failed；0.92 秒 | stage_d_final_compose.txt |
| 原 Stage C Compose 测试，使用独立当前有效 Mock HTTP | 原 21 项 21 passed / 0 failed；1.89 秒 | stage_d_stage_c_fresh_compose.txt |
| 正式 Stage D 原生 Agent 草稿 | 68/68 验证记录，包括标注的 HTTP 夹具和生成边界注入 | 见 STAGE_D_VALIDATION.md 的六组记录 |
| 最终生产配置草稿六条不同路径 | 6/6（包含在上述 68 中） | stage_d_final_draft_results.json |
| 新发布 Agent API | 6/6，实际 workflow_id 与当前发布一致 | stage_d_published_results.json |
| 原 Stage C 正式 App | 草稿 6/6、原发布 API 4/4 | stage_d_stage_c_*_results.json |
| 原 Citation 攻击 probe | 13/13 abstain / fail closed | stage_d_citation_provenance_probe.json |
| 冻结与来源交叉核验 | 457 个原文件不变，Stage C 原草稿/发布图及 ID 不变；35 条 API provenance 重建一致，17 条成功草稿原生工具参数与 HTTP 一致 | stage_d_final_checks.json |

实际命令（在仓库根目录；Docker build 可在仅含 ASCII 字符的本地路径 junction 执行）：

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider --basetemp=<临时目录>/stage-d-final --junitxml=audit_artifacts/stage_d_final_pytest.xml
$env:API_PORT='18090'
docker compose --env-file .env.stage-d -p fde-stage-d -f docker-compose.yml -f docker-compose.stage_d.yml --profile test run --rm e2e
$env:API_PORT='18089'
docker compose -p fde-stage-c -f docker-compose.yml -f docker-compose.stage_c.yml --profile test run --rm --no-deps -e API_BASE_URL=http://host.docker.internal:18090 e2e
.\.venv\Scripts\python.exe -B audit_artifacts/stage_d_publish.py
.\.venv\Scripts\python.exe -B audit_artifacts/stage_d_final_checks.py
```

26 项本地跳过是 21 个既有部署测试和 5 个新增部署测试；它们在 Compose 中实际执行。新增本地门禁回归为 92 项，覆盖参数/权限、身份/版本/单位/时效、每个工具失败、恶意源、JSON/think/事实覆盖、原生终止日志、预算、能力隔离和只读路由。所有原测试文件未改，完整测试有一条既有 Starlette/AnyIO 弃用警告。

中间失败没有删除：旧 Stage C 卷直接执行为 19 passed / 2 failed，两条工艺 Demo 的源数据已超 6 小时，被正确拒绝为 data_error；没有修改其时间戳，改用独立新数据源重跑原 21 项。原 Stage C App 回归则在原 18089 后端新增当前虚构对象，不覆盖旧行。两次端口环境变量错误导致部署重建失败/暂时不可达，已恢复 18089/18090 并重新验证。Agent 原生 text 聚合中间说明导致初次输出解析失败，改为验证结构化终止 ROUND；第一次发布标记超过平台 20 字符限制、两项版本故障夹具命中错误对象也均修正后重跑，旧日志保留。

外部边界：真实 DeepSeek 由原生 Agent 使用，但 500/timeout 是本地业务 HTTP 故障夹具；生成攻击是实际 DeepSeek 之后的边界注入。Provider 错误测试是实际 Dify 拒绝非法模型配置，没有声称实际制造远端 DeepSeek 429/500。未测试生产认证、负载/并发、任意中文表达、多轮记忆、全局原子快照和跨实例自动导入；它们不属于本轮验收范围。全部输入、输出、证据链接和 A–V 对照见 `audit_artifacts/STAGE_D_VALIDATION.md`。

## 历史记录：任务包 07

- **测试日期：** 2026-09-29（Asia/Shanghai）
- **本地完整测试命令：** $env:PYTHONDONTWRITEBYTECODE='1'; .\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider
- **本地结果：** 218 passed，11 skipped，0 failed；运行约 64.77 秒。
- **Compose 部署 E2E 命令：** docker compose --env-file .env.example --profile test run --build --rm e2e
- **Compose 结果：** 11 passed，0 failed；Compose 构建 FastAPI / E2E 镜像，等待 API health check 通过后执行。
- **pytest 警告：** 1 条 Starlette TestClient 对 anyio.abc.BlockingPortal 别名的 DeprecationWarning；不是测试失败。

## 跳过与失败

本地完整测试中的 11 项部署端到端测试受 RUN_DEPLOYMENT_E2E 环境标记控制，未配置时跳过；随后由上述 Compose profile 运行并全部通过。失败数为 0，因此没有失败原因。

## 已覆盖场景

自动化测试覆盖 API 正常查询、参数错误、对象不存在、数据缺失/不可用、结构化错误；OpenAPI 契约；MES 分析的正常状态、有效规则违规、无效/缺失规则停止、缺失数据、MES 404、系统失败停止；离线 Evidence gate 的支持/证据不足判断；部署健康检查和 API 部署端到端访问。

## 未由自动化测试验证的场景

- 本轮没有通过 Dify UI 新导入并运行 Workflow；Compose E2E 只测试 FastAPI。
- 无在线开放式知识问答、LLM 综合生成、自然语言 entailment / hallucination 评测或 Agent Tool Calling 自动化测试，因为这些能力未实现。
- ERP 与 WMS 的端点分别受 API 测试覆盖，但两者 AI 自动编排与答案生成未实现，故无该链路测试。
- 没有真实企业 MES / ERP / WMS 网络或鉴权联调；上游错误采用测试桩覆盖。
- 没有独立人工审批系统测试。
- Dify 检索 hit 的 document_id / segment_id 与引用来源身份绑定缺少负向回归测试；审计确认当前实现仍有 P0 风险，见 PROJECT_AUDIT.md。


## 2026-09-30 阶段 A 最终回归

命令：`.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider --junitxml=audit_artifacts/stage_a_pytest.xml`。实际 283 次执行：**272 passed / 11 skipped / 0 failed / 0 errors**，140.63s，1 条既有弃用警告。11 项部署测试另以 `docker compose -p fde-stage-a --profile test run --rm e2e` 运行，**11 passed**（0.34s）。

新增来源回归测试 54 项；Citation probe 13/13 fail closed；原旗舰实际 Dify 草稿 28/28、发布 API 3/3 PASS。执行命令、失败中间记录和原始证据见 [阶段 A 验证记录](../audit_artifacts/STAGE_A_VALIDATION.md)。本阶段未验证或实现下一阶段 LLM 综合、开放式 QA、Agent、多轮及 ERP+WMS AI 编排，不把它们计为通过。

## 2026-09-30 Stage B 最终回归

实际命令：`.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider --junitxml=audit_artifacts/stage_b_pytest.xml`。

345 次执行：**334 passed / 11 skipped / 0 failed / 0 errors**，175.58s；1 条既有 Starlette/AnyIO 警告。新增 `tests/test_generation.py` 62 项，原测试无回归。原始日志与 JUnit：stage_b_pytest.txt/xml。

Compose：`$env:API_PORT='18088'`，`docker compose -p fde-stage-a --profile test build` 后 `docker compose -p fde-stage-a --profile test run --rm e2e`；**11 passed / 0 failed**，0.39s，宿主机跳过的部署测试实际执行。目录使用指向本仓库的 ASCII junction，见 Stage B 记录。Citation provenance probe 13/13 fail closed。

真实 Dify 最终草稿 **32/32 PASS**，发布 API **4/4 PASS**。输出攻击 replay 保留真实 Retrieval/LLM，再在校验前变异；不声称 Provider 自发产生全部攻击。中间一个 MES timeout 正确系统失败，稳定后单项重跑通过，原证据保留。强制 thinking 曾产生 native schema 误解析，独立校验拒绝；生产关闭 thinking。无效平台 native schema 的补充探索未触发平台拒绝，其原始预期失败记录保留，不计为安全验收成功。

仍未自动化验证远端 Provider 实际 429/500、开放式 QA、任意文本语义审查、多轮/Agent、ERP+WMS AI 综合或独立人工审批系统；不得把这些计为已完成。详细场景、命令与原始证据见 [STAGE_B_VALIDATION.md](../audit_artifacts/STAGE_B_VALIDATION.md)。

## 2026-10-01 Stage C 初次完整回归（API 引用标记门禁前）

命令：`.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider --basetemp=<临时目录>/stage-c-final-pytest --junitxml=audit_artifacts/stage_c_pytest.xml`。

实际 **452 次执行：431 passed / 21 skipped / 0 failed / 0 errors**，600.33s；1 条既有 Starlette/AnyIO 弃用警告。该次日志及 JUnit 保留为 `stage_c_pytest.pre_marker.txt/xml`。新增 Stage C 本地 97 项与部署 10 项；21 跳过项为原 11 与新增 10 项 opt-in HTTP 部署测试。之后新增三项 API 文本引用标记回归并修复，最新最终结果另列。

第一次全量执行是 428 passed / 21 skipped / 3 failed，保留在 `stage_c_pytest.first_run.txt/xml`。原因是两个旧 OpenAPI 数量断言仍预期 7（新增三个只读接口后为 10），以及导出与标签更新发生在该次测试运行期间。修改三处数量断言并在代码/导出稳定后重跑，最终无失败；未削弱原错误或引用校验。

Compose 实际执行：设置 `API_PORT=18089`，在仅含 ASCII 字符的本地路径 junction 下运行 `docker compose -p fde-stage-c -f docker-compose.yml -f docker-compose.stage_c.yml --profile test build`、`up -d api`、`--profile test run --rm e2e`。最新镜像 **21 passed / 0 failed**，1.12s，见 `stage_c_compose_final_build.txt`、`stage_c_compose_final_up.txt`、`stage_c_compose_final_e2e.txt`。

Stage A 原 citation probe 源码原样执行，仅在内存替换输出文件名为 `stage_c_citation_provenance_probe.json`，**13/13 fail closed**；不覆盖原 probe 或历史验收。新增测试覆盖跨系统身份、最小源版本、陈旧/未来响应、单位、hash/request replay、API 故障、JSON/think/schema、伪造 API 事实/来源、引用越权及嵌入 Code 输出契约。

真实 Dify 草稿、发布 API、原始失败与重跑证据另见 [STAGE_C_VALIDATION.md](../audit_artifacts/STAGE_C_VALIDATION.md)。Compose 仍只部署 Mock API，不等同于 Dify 测试。未验证真实企业网络、远端 Provider 实际 429/500、任意文本蕴含或独立审批系统；不新增 Agent/多轮/开放式 QA。

## Stage C 最终回归：API 文本引用标记修复后

额外三项负向测试复现 API 自由文本 `[cite:FORGED]` 被拼入最终回答的缺口（`stage_c_api_marker_before.txt`：3 failed），修复 C 生成前/后 namespace 门禁后（`stage_c_api_marker_after.txt`：3 passed）再运行全部测试。

最终命令：`.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider --basetemp=<临时目录>/stage-c-final-marker --junitxml=audit_artifacts/stage_c_pytest.xml`。

**455 次执行：434 passed / 21 skipped / 0 failed / 0 errors**，710.02s，1 条既有弃用警告。新增 Stage C 本地总数 **100**，部署 **10**；旧 Stage A/B 核心不变。最终 JUnit/日志为 `stage_c_pytest.xml/txt`。

修复后再次构建部署，原命令相同：**Compose 21 passed / 0 failed**，1.07s；21 项本地跳过的部署测试全部执行。正式 Dify 完整矩阵也从头重跑，新增 API 文本引用标记的真实 HTTP fixture；草稿和新发布 API 最终结果及 run/version 身份见 STAGE_C_VALIDATION.md。

## Stage F / F-Data最终实测（2026-10-04）

本机最终命令：`.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider --basetemp=<临时目录>/stage-f-final-stable-20261004 --junitxml=audit_artifacts/stage_f_final_stable_pytest.xml`。

**756项：725 passed / 31 skipped / 0 failed / 0 errors，423.31s，1条既有弃用警告**。31项跳过为显式启用的部署E2E，随后以隔离新卷Compose **31 passed / 0 failed**实跑，没有未执行的部署项冒充通过。新增F本地104项、部署5项；原源码/测试/DSL冻结88文件校验通过。

Compose实际命令在指向本仓库、仅含 ASCII 字符的路径 junction 下执行：`docker compose --env-file .env.stage-d -p fde-stage-f-20261004-validation -f docker-compose.yml -f docker-compose.stage_d.yml -f docker-compose.stage_f_test.yml --profile test run --build --rm e2e`；API_PORT=18096，已先up并build api。旧卷过期的6失败/25通过及中文context错误现场保留，最终独立新卷通过；未刷新旧fixture。

本轮真实原Published回归：**C14/14、D19/19、E1 11/11**；额外冒烟8/8。新数据随机20炉次+10订单+20批次 **50/50**；扩容RAG **53/53**（31内部、11公开、11无证据/非现行）；新草稿 **11/11**；metadata恢复后Published **3/3**。Citation probe **13/13 fail closed**；真实浏览器 **13/13**（含移动公开参考、列表、实体追问）；前端`npm run build --prefix frontend`成功。

最终健康 **22/22**。凭证扫描PASS，详细文件数量/范围见`stage_f_security_scan.json`；桌面/手机几何无横向溢出，captured console warn/error为空。UI系统失败是实际停止Mock C，随后已恢复，不宣称真实远端DeepSeek500/429。

日志/XML/逐请求inputs、outputs、run/version、node/HTTP trace与旧失败尝试保存在[audit_artifacts/STAGE_F_VALIDATION.md](../audit_artifacts/STAGE_F_VALIDATION.md)及[STAGE_F_TEST_MATRIX.md](../audit_artifacts/STAGE_F_TEST_MATRIX.md)。最初中间pytest数字716/26与724/31仍留证，但不计最终结果。

仍未自动化或未本轮实测：全新跨机器配置、完整Windows重启、远端Provider真实故障、真实企业权限/网络/生产数据、负载/SLA、全部浏览器与辅助技术、任意自然语言蕴含、独立审批平台。QA有限评审集合与本机PoC边界未放宽。现有E2 ZIP为历史快照，未因Stage F重生成。

## F2 用户实体语序缺陷修复（2026-10-08）

新增41项桌面HTTP入口及错误呈现回归；专项41通过，F/F2相关486通过。全量本轮命令：`.venv\Scripts\python.exe -B -m pytest -q --tb=short --junitxml=audit_artifacts/f2_user_uat_full_pytest.xml`。

**1107 passed / 36 skipped / 0 failed，460.14秒，1项既有弃用警告。** 36项部署/在线测试未设置opt-in，不能称为本轮Compose通过。日志/XML保存在`audit_artifacts/f2_user_uat_full_pytest.txt/xml`。

真实桌面API及Dify发布C/D调用6/6符合预期，额外5项停止路径通过，三个用户原始问法在独立真实浏览器页面通过。不是模拟业务成功；测试桩仅用于自动化路由及失败边界。88个原核心文件摘要未变。原始复现、限定修复、真实节点记录、截图及环境边界见 [F2_USER_UAT_ROUTING_FIX.md](../audit_artifacts/F2_USER_UAT_ROUTING_FIX.md)。本轮没有重跑全部10项UAT、重建知识库、修改DSL或重发正式应用。

## F2 复合请求遗漏修复（2026-10-08，后续用户UAT）

新增23项专项；实际相关回归命令：`.venv\Scripts\python.exe -B -m pytest tests/test_stage_f2_compound_query.py tests/test_stage_f2_uat_language.py tests/test_stage_f2_workspace.py tests/test_stage_f_router.py tests/test_stage_f_gateway.py -q --tb=short --junitxml=audit_artifacts/f2_compound_query_pytest.xml`。

**159 passed / 0 failed / 0 skipped**，29.68秒，1项既有弃用警告。`npm run build --prefix frontend` 成功（TypeScript/Vite，1.47秒）。本次未重跑全量，上一节1107/36为先前语序修复结果。实际发布调用3/3及真实浏览器原句均符合预期，复制回答包含两个子结果；88个冻结核心文件未改。记录见 [F2_COMPOUND_QUERY_FIX.md](../audit_artifacts/F2_COMPOUND_QUERY_FIX.md)。
