# 公开验证摘要 · Stage E2 · 2026-10-02

本轮宿主机647项：621通过、26部署专用跳过、0失败/错误；Compose26/26；正式Dify发布C14/14、D19/19、E1 11/11；原Citation probe13/13 fail closed；补充安全34/34（本地后验重放/Gateway/HTTP故障夹具，非远端模型现场攻击）。原A/B/C/D/E1核心与tests/DSL未改，三正式发布图/ID/KB来源身份核对不变。

正常、无对象、缺字段、缺规则、无SOP、源身份/版本/时效冲突、有限QA拒答、只读动态工具选择通过。Source of Truth、Evidence First、Citation来源绑定、API来源分离、生成后覆盖、HITL仍生效。脚本启动/停止C/D恢复后Live三入口成功；完整Windows重启/第二全新机器/真实企业/生产权限负载/真实远端429/500未验证。

公开包不包含完整运行Trace、任何密钥或本机个人路径。需要自己的Dify/Provider/模型和手工知识身份、工具、secret、DSL绑定。有限别名/原文校验不是开放语义推理。P0/P1/blocker=0，P2=4；详情见docs/PROJECT_AUDIT.md。源码中的规程、参数、企业对象全为虚构教学样例，不能指导真实生产。

## 续跑启动补充

2026-10-02修复启动/共享停止的Compose项目作用域错误（E2-START-001，P1 FIXED），支持非标准Desktop路径。原Dify API停止后实际恢复通过，C/D/E1发布健康复测3/3、相关pytest11/11、模拟项目保护2/2；未改变冻结图/发布ID/知识身份。另修复ZIP公开路径/链接检查的循环范围（E2-PACK-001，P1 FIXED），逐成员ZIP负向回归7/7并重新扫描最终包。没有删除原数据卷或刷新过期对象。详见TEST_REPORT与STAGE_E2_VALIDATION；这些补充结果不重复计入全量621项或44项正式发布矩阵。

## 最终目录再次核查

修复交付目录导致pytest重复收集的真实遗漏（E2-TEST-001，P1 FIXED），新增pytest.ini并包含在两包及测试镜像中。最终根目录再次全量621通过/26跳过/0失败，新独立Compose26通过，正式发布健康复测3/3，Citation13/13 fail closed；失败收集日志保留。最终两包重新生成并逐成员扫描，详见TEST_REPORT与ZIP外部收据。已有本地凭证配置直接复用，不用模板覆盖。
