import json
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from pydantic import ValidationError

from app.analysis.models import AnalysisContext, ProcessRule
from app.api_docs import error_responses
from app.db import connect, read_record
from app.errors import data_error
from app.parameters import HeatId
from app.schemas import Chemistry, Heat, Temperature

router = APIRouter(prefix="/api/mes", tags=["MES"])
responses = error_responses("MES 炉次", "heat_id", "process_stage", measurement=True)
responses[409]["description"] += (
    " PROCESS_CONTEXT_MISSING / MISSING_FIELDS / INVALID_DATA：上下文不可用；"
    "RULE_NOT_FOUND：无当前有效规则；RULE_CONFLICT：多个当前有效规则。不得工艺推断。"
)


@router.get("/heats/{heat_id}/analysis-context", response_model=AnalysisContext,
            operation_id="get_mes_heat_analysis_context", summary="查询 MES 炉次分析上下文及有效规则",
            description="先确认炉次存在，再读取同一只读事务中的状态、阶段、温度、成分和唯一有效规则。404 是炉次不存在，不是工艺异常；409 是事实或规则不可用；422 参数错误；5xx 系统失败。此接口不进行工艺异常判断。",
            response_description="服务端当前快照及匹配规则，规则含正式虚构文档出处；由 Workflow 确定性比较。",
            responses=responses)
def get_analysis_context(heat_id: HeatId, request: Request):
    # Test clock is supplied at app creation, never through user query parameters.
    now = request.app.state.analysis_clock()
    with connect(request.app.state.data_dir, "mes") as connection:
        connection.execute("BEGIN")
        heat = read_record(connection, "SELECT * FROM heats WHERE heat_id = ?", heat_id, Heat)
        row = connection.execute("SELECT * FROM heat_process_context WHERE heat_id = ?", (heat_id,)).fetchone()
        if row is None:
            raise data_error("PROCESS_CONTEXT_MISSING", "炉次缺少工艺阶段上下文")
        process = dict(row)
        if any(not process.get(k) or not str(process[k]).strip() for k in ("process_stage", "scope", "stage_started_at")):
            raise data_error("MISSING_FIELDS", "工艺阶段上下文缺少必要字段", ["process_stage", "scope", "stage_started_at"])
        temperature = read_record(connection, "SELECT * FROM temperatures WHERE heat_id = ?", heat_id,
                                  Temperature, missing_code="MEASUREMENT_MISSING")
        chemistry = read_record(connection, "SELECT * FROM chemistry WHERE heat_id = ?", heat_id,
                                Chemistry, missing_code="MEASUREMENT_MISSING")
        active = []
        try:
            for stored in connection.execute("SELECT rule_json FROM process_rules WHERE status = 'published'"):
                rule = ProcessRule.model_validate(json.loads(stored["rule_json"]))
                if (rule.steel_grade == heat.steel_grade and rule.process_stage == process["process_stage"]
                        and rule.scope == process["scope"] and rule.required_status == heat.status
                        and rule.effective_from <= now < rule.effective_until):
                    active.append(rule)
        except (ValidationError, ValueError, TypeError) as exc:
            raise data_error("INVALID_DATA", "受控规则数据格式无效", ["rule"]) from exc
        if not active:
            raise data_error("RULE_NOT_FOUND", "该炉次没有当前有效的匹配规则，停止工艺推断")
        if len(active) != 1:
            raise data_error("RULE_CONFLICT", "该炉次匹配多个有效规则，请人工确认")
        try:
            return AnalysisContext(heat=heat, temperature=temperature, chemistry=chemistry,
                                   rule=active[0], snapshot_at=now, **{k: process[k] for k in
                                   ("process_stage", "scope", "stage_started_at")})
        except ValidationError as exc:
            raise data_error("INVALID_DATA", "工艺上下文格式无效") from exc


def utc_now():
    return datetime.now(timezone.utc)
