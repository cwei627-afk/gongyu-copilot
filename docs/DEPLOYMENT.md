# 本地部署与跨环境复现

基础版本记录来自E2：Windows/Docker Desktop、Python3.12.10、Docker Engine29.5.3、Compose5.1.4、Dify1.17.1、plugin-daemon0.6.10、sandbox0.2.15、Weaviate1.27.0、Ollama0.34.0。Stage F沿用现有平台与模型，不是所有版本兼容性保证。Dify已有依赖保留，不新建平台基础设施。

## 1. 无外部凭证的本地验证

按README创建.venv并安装requirements-dev.txt，运行完整pytest。只部署Mock可用默认Compose/.env.example；API_BIND_ADDRESS默认0.0.0.0便于Dify容器访问，不是生产鉴权。网络不可对不可信用户开放。

需要全部26项部署E2E时，生成本地.env.stage-d（不要提交）：

```powershell
.\.venv\Scripts\python.exe -c "import secrets,pathlib; p=pathlib.Path('.env.stage-d'); assert not p.exists(); p.write_text('API_PORT=18090\nAGENT_CONTROL_SECRET='+secrets.token_urlsafe(40)+'\n',encoding='utf-8')"
$env:API_PORT='18092'
docker compose --env-file .env.stage-d -p fde-demo-test -f docker-compose.yml -f docker-compose.stage_d.yml --profile test run --build --rm e2e
```

新project生成独立虚构卷；不要使用down -v或prune --volumes。端口环境变量优先于env-file，执行每个项目时显式设置API_PORT，避免覆盖18089/18090。容器内端口8000不变。Docker中文build上下文如果出现sharedkey ASCII错误，可在已验证ASCII junction执行同一命令；不要复制修改业务代码或删除旧卷。

## 2. Dify与模型

本项目Compose不部署Dify。[官方Compose步骤](https://docs.dify.ai/en/self-host/deploy/quick-start/docker-compose)用于首次安装；已有实例只启动其原Compose和原overlay，保留全部volumes。当前经典Agent使用官方langgenius/agent0.0.50 Function Calling strategy，不切换文档中的beta新Agent。

在自己的Dify Provider中配置DeepSeek API key及deepseek-flash，使用已验证的structured输出配置；不要把key写入业务Python、DSL或公开包。Ollama安装/模型来源按[官方文档](https://docs.ollama.com/api/embed)及[Qwen模型卡](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B)核对：

```powershell
ollama pull qwen3-embedding:0.6b
ollama serve
```

本机已安装模型不重复下载。Dify容器访问Windows宿主Ollama使用http://host.docker.internal:11434；宿主检查用127.0.0.1。原安装OLLAMA_HOST=127.0.0.1:11434、OLLAMA_MODELS是本机自己的模型目录，应在忽略配置中设置。不同Docker/防火墙环境必须实际测试容器可达性，不假定Linux也同样可用。

预热使用POST /api/embed，model=qwen3-embedding:0.6b、input=企业演示规程；应取得一条1024维向量。本轮冷加载与各节点实测时延见最终报告；不承诺首次加载或生产SLA。

## 3. 知识库与来源迁移（必须人工配置）

1. 安装原DeepSeek/Ollama Provider及官方Agent strategy；不重用其他模型旧向量。
2. 用assets/analysis_demo真实虚构文档和受控版本正文建立正式KB，选high_quality、Qwen3-Embedding-0.6B / 1024维。历史/撤销/未来文档与当前2份文档需保留明确metadata。
3. 按受控目录设置结构化document_name/controlled_document_name、document_id、version、effective_date/from/until、status、scope、steel_grade、process_stage、rule_id、chapter、section、parameters、directions、content_sha256。page无可靠信息保持null。
4. 等索引completed，读取新实例真实document_id/segment_id和实际segment正文，用UTF-8 SHA-256登记。重新分段会改变hash，必须同步评审原句及登记后重验，不填伪造旧ID。assets/analysis_demo/dify_source_registry.json是**当前原实例绑定**，不能直接迁移。
5. 用app.enterprise.workflow/build_enterprise_workflow及app.knowledge_qa.workflow/build_qa_workflow生成新实例绑定DSL，传入新dataset和受控登记。保留原过滤/身份/正文/版本冲突门禁；不要手工删检验以便导入。
6. 在Dify secret KNOWLEDGE_API_KEY填新实例的知识API key。校对官方完整目录可读及metadata filter有效，旧/撤销/未来文档不能被当前问答采用。

正式原实例5文档/5chunk只是已绑定实例的事实，不能声称另一机器配置完一定有同一ID。不同文档切分也不能把manifest里句子变成本次真实hit引用。

## 4. Mock与Agent工具绑定

Stage C访问host.docker.internal:18089；Stage D控制/工具与业务后端使用18090。Dify三应用相互独立。

仅首次且.env.demo.local不存在时复制.env.demo.example，再填写DIFY_COMPOSE_DIR、OLLAMA_EXE/MODELS、三应用APP_ID/API_KEY、DATASET_ID、知识API key；已有本地配置直接复用，不用模板覆盖。Dify服务凭证不在模板中。

新Stage D control secret在.env.stage-d生成一次；与Dify secret AGENT_CONTROL_SECRET必须相同，不能每次启动旋转导致既有App失配。控制接口仅用于本地请求能力，属于PoC权限边界，不是生产认证中心。

在Dify Custom Tool Provider导入docs/agent_openapi.json，服务地址指向只读适配层。只能4个GET工具mes_heat/mes_links/erp_order/wms_batch；capability参数必须auto=0/variable绑定begin_check，不允许模型生成；entity_id才由模型选择且后端核验。设置新的provider ID到app.readonly_agent.workflow/build_agent_workflow。原生导出dependencies为空不能自动安装Swagger Provider；按AGENT_DESIGN步骤人工绑定strategy与四工具，不导入任意URL/SQL或控制接口。

导入当前正式C/D/E1无密钥DSL后：绑定自身知识库/Provider/secret/API地址，草稿实测，再发布并检查API返回workflow_id等于实际新发布ID。当前仓库旧Stage A/B/heat_analysis.local.yml是历史资产，不回退或覆盖正式应用。

## 5. 本机启动、健康、停止

```powershell
./start_demo.ps1 -NewData
./check_demo.ps1 -Live
./stop_demo.ps1
```

start_demo在Engine未启动时使用DOCKER_DESKTOP_EXE、标准安装路径或已安装Docker CLI旁的Desktop可执行文件；特殊路径仍可先自行启动Desktop。DIFY_COMPOSE_PROJECT必须来自docker compose ls的已有项目名。原Dify不可达时先确认该项目已有API容器，再显式-p启动原Compose；没有已存在项目则停止，不能默认创建另一个实例。原自定义fde-net若要求fde_shared网络，先核对它存在；脚本不猜测或重建原网络。Ollama未启动时用配置的现有可执行文件Hidden启动，不下载新供应商。

默认stop仅停止C/D Mock API，保留数据卷与Dify/Ollama共享服务；需要停止共享服务时显式StopDify/StopOllama并指向原Dify目录与已有DifyComposeProject（或本地配置中的项目名）。共享stop同样核对已存在API并显式-p，不操作默认项目。整机重启后完整链路本轮未执行，不能把当前停止/恢复当成Windows重启验收。

健康检查仅输出服务名、PASS/FAIL及必要非敏感诊断。quick检查容器运行/已有health、数据库、实际Embedding、索引completed和scope API key；-Live另外实跑C正常、D只读MES、E1有证据生成，消耗少量自身API额度，E1验证真实检索与DeepSeek。容器running本身不等于业务健康。

## 6. 演示数据与幂等性

scripts/prepare_demo.py只向Mock后端新增完全虚构对象，不刷新历史行或放宽21600秒时效。run_label限定ASCII安全字符；同一run已完成则读取同一清单，超过6小时明确fresh=false，不修旧时间。-NewData或新run_label才创建新的当前对象；初始化失败保留现场，使用新run_label而不覆盖旧半完成对象。

data/demo-state.json是演示准备生成的系统对象索引，不用于Agent判断对象存在；真实查询仍访问MES。ORDER-/LOT-是随机不透明键，模型不能按炉次拼接。温度缺失属于Stage C分析缺字段，Stage D仅身份/订单查询不读取温度；MES身份字段缺失则两者均停止。NO-SOP独立虚构钢种采用已有参数标准复制，仅为“有有效规则、无对应SOP”拒答测试，不新增真实工艺知识。

## 7. 常见失败与恢复

| 现象 | 处理 |
|---|---|
| Docker Windows runtime socket故障 | 关闭Docker相关进程、核对并备份既有runtime目录后恢复；不要factory reset或删volumes。详细旧现场在私有审计记录 |
| Dify仅Web正常/API不通 | 检查API与nginx真实HTTP，已有nginx上游过期时仅重启nginx；不重建数据库 |
| Ollama冷加载或检索canary失败 | 检查原模型、容器宿主网络并预热；先恢复服务，不把系统故障当NO_EVIDENCE |
| 旧对象data_error | 看更新时间/版本，使用新虚构run；不要回写旧时间戳 |
| secret不匹配 | 私下核对Dify环境与本地控制secret；不要输出值 |
| 4xx/5xx或无End | 分类request/data/system并停止，不调用模型补事实 |
| JSON/引用门禁拒绝 | 检查脱敏trace中的契约原因；不删字段、不放宽来源校验 |

跨实例流程当前是DOCUMENTED_ONLY，尚未在第二台全新机器实测。真实企业API鉴权、网络、各源正式有效性契约、权限/安全审计、负载与人工审批均是接入真实系统前的另外工作。

## 8. Stage F统一入口（当前用户默认入口）

需要额外准备Node.js/npm以构建React/TypeScript/Vite页面；Python后端依赖不增加新框架。

```powershell
Set-Location frontend
npm ci --no-audit --no-fund
npm run build
Set-Location ..
.\start_demo.ps1 -NewData
```

页面 **http://127.0.0.1:18095**；独立FastAPI静态托管与BFF，不开Vite开发服务器作为最终入口。启动脚本只在无构建时自动构建；改前端后需先重新build，再刷新浏览器。原C/D/E1 Dify运行页仍留作调试，不自动作为主Demo打开。

服务端忽略配置为`.env.demo.local`与`.env.stage-f.local`，模板`.env.copilot.example`不含真实凭证。环境变量优先；不要创建任何带密钥的VITE_*变量。

| 变量 | 用途 |
|---|---|
| DIFY_BASE_URL | 既有Dify Published API地址 |
| DIFY_C_API_KEY / DIFY_D_API_KEY / DIFY_E1_API_KEY | 原发布能力的限定应用密钥 |
| DIFY_F_INTERNAL_API_KEY / DIFY_F_PUBLIC_API_KEY | 两个隔离扩容知识应用的限定密钥 |
| DIFY_F_ROUTER_API_KEY | 可选闭合意图分类；缺失或非法输出则澄清 |
| COPILOT_SOURCE_BASE | 默认127.0.0.1:18090，固定只读源 |

DeepSeek凭证留在Dify Provider；各知识库访问凭证绑定相应Workflow secret，不进入浏览器。无生产登录/多用户鉴权，Gateway仅绑定本机127.0.0.1，不建议公开访问。

新增知识索引由`audit_artifacts/stage_f_dify.py`在授权的现有实例配置，读取已存在状态以复用**新增**索引；它包含管理操作，不能当作一般启动脚本。原C/D/E1和原5文档KB不重建。迁移另一实例仍需要管理员读取新document/segment/hash、metadata和Provider身份，人工核对后生成/导入绑定DSL。新扩容文档使用保持完整正文的UTF-8纯文本载体，Markdown作者文件保留；不能忽略分段/hash不一致以便导入。

`start_demo -NewData`用Python字节管道新增原演示run及400/100/200扩容run到C/D两套源实例；固定seed、显式UTC as-of、幂等，不覆盖旧fixture。原D工具白名单不扩大，列表由Gateway直接按限定参数读取Mock。

健康检查新增Unified Frontend、Copilot Gateway、Intent Router。快速健康不等同全部知识问题可回答；真实业务/知识结果见Stage F在线验证。

Stage F隔离部署测试使用新项目与新卷，避免复用过期fixture：

```powershell
$env:API_PORT='18096'
# 项目名换成此次验收的唯一名字；已有同端口实例先仅stop。
docker compose --env-file .env.stage-d -p fde-stage-f-20261004-validation -f docker-compose.yml -f docker-compose.stage_d.yml -f docker-compose.stage_f_test.yml --profile test run --build --rm e2e
```

中文上下文出现sharedkey非ASCII错误时，在已验证指向同一仓库的ASCII junction运行相同命令；不删除卷。正常源有6小时时效，不能反复重用昨日测试卷并期望成功。保留失败现场，使用新的隔离项目重建虚构测试源。

此次Docker socket恢复只将两处已核对的runtime目录改名备份，保留volumes；随后PostgreSQL执行了真实崩溃恢复。数据库ready后恢复API/worker，未重置或重建知识库。证据见`stage_f_docker_resume_recovery.json`与启动日志。此恢复不等于整机Windows重启或通用Docker修复保证。

此前E2 ZIP是历史快照，不包含统一页面/扩容，当前产品请使用本仓库及Stage F说明。
