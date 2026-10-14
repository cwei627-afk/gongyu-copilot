# Agent与固定Workflow：E2当前复核

本轮仍使用同一冻结入口。C固定执行MES基础/当前规则快照/正式links/ERP/WMS共5个业务HTTP；正常路径不检索、不调用LLM。D由原生Function Calling动态选择工具，不是预定工具流水线；六条实际路径如下，均核对原生ROUND与HTTP账本。

| E2用例 | 实际工具顺序 | 总秒数 |
|---|---|---|
| mes | ['mes_heat'] | 4.127 |
| erp | ['erp_order'] | 4.811 |
| wms | ['wms_batch'] | 3.908 |
| mes-erp | ['mes_heat', 'mes_links', 'erp_order'] | 6.402 |
| joint | ['mes_heat', 'mes_links', 'erp_order', 'wms_batch'] | 7.003 |
| order-wms | ['erp_order', 'wms_batch'] | 5.827 |

本轮C正常发布运行耗时6.216秒，仅一个样本。与D六种不同范围样本不作统计性能优劣结论。模型、调度、冷/热服务和输出范围都会影响耗时。下方Stage D三次同对象比较为**历史2026-10-01测量**，不是本轮性能数字。

C负责必须完整执行的工艺规则/证据/人工复核闭环，D适合显式对象的按需只读查询；D不承担工艺判断，工艺请求引导C，四工具禁止任意URL/SQL/写入。双方API失败停止并不补事实，Citation与API provenance分离。E2三条失败Trace仍有被适配层阻止的后续WMS规划尝试；未发送额外HTTP，不能把业务HTTP数当成全部模型尝试数。


---

## 以下为原阶段记录（历史结果，不代表E2本轮）

# Stage D：Agent 与固定 Workflow 的实际对比

对比日期为 2026-10-01；固定入口是已发布 Stage C，动态入口是独立 Stage D。两者使用同一份当前有效的虚构 MES/ERP/WMS HTTP 数据，未调整旧记录更新时间。对比对象为 `STAGE-D-C-COMP-20261001082403`，正式关联返回 `ORDER-1393cf489c` 和 `LOT-92f0c84944`，这些键不能由炉次号拼接得到。

| 项目 | Stage C 固定 Workflow | Stage D 只读 Agent |
|---|---|---|
| 输入 | heat_id + all | 查询炉次的 ERP 订单和 WMS 库存 |
| 本次业务路径 | MES 基础、分析快照、MES links、ERP、WMS | 原生 Agent 动态调用 MES 基础、MES links、ERP、WMS |
| 业务 HTTP 次数 | 每次 5 | 联合查询每次 4；仅 MES 查询 1 |
| 正常路径模型使用 | 无异常时不检索、不调用 LLM | DeepSeek 选择工具、组织受约束事实句 |
| 三次联合耗时（秒） | 3.606 / 3.728 / 3.647 | 5.507 / 6.126 / 6.008 |
| 中位数（秒） | 3.647 | 6.008 |
| 事实一致性 | 与源对象核对 3/3 | 与同一源对象核对 3/3 |
| 输出约束 | 有效规则、异常门禁、证据门禁、生成覆盖 | 本次 API 事实和 claim 全量覆盖；不作工艺结论 |
| 关联与权限 | Code 固定核对源关系与版本 | Code 核对源关系、版本及请求级工具权限；模型不能放宽 |
| 失败 | 系统/数据/工艺分流，证据不足 abstain | request/data/system error；失败最终无可信事实或出处 |

另一条只查 MES 的真实 Agent 路径耗时 3.510 秒，调用 1 个工具，没有多余 ERP/WMS HTTP。所有结果来自实际 Dify 与实际 Mock HTTP；不是本地模型桩。数据和逐次 trace 见 `audit_artifacts/stage_d_comparison.json`，执行脚本为 `stage_d_comparison.py`。

这只有三次联合测量，没有并发或统计显著性验证。两者输出范围也不同：Stage C 还检查工艺规则，Stage D 只解释事实。不能由此断言 Agent 更好或通用性能结论。Agent 本次联合路径较慢，固定正常路径也更少依赖模型。

固定 Workflow 适合必须完整执行、可审查的异常分析：存在性、当前规则、确定性比较、正式 SOP、Evidence First 和人工确认不能交给自由规划。Agent 适合明确对象和有限范围的临时查询，按需选择不同工具子集；它增加 Provider、终止输出、调用预算等失败面，因此所有业务关联和最终事实仍由确定性门禁控制。

本轮没有复制异常 Workflow 到 Agent，也没有暴露它为工具。工艺请求返回 `USE_STAGE_C_WORKFLOW`，提示从原入口分析。双方文档 Citation 与 API provenance 独立，均不产生设备自动动作。
