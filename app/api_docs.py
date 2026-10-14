"""OpenAPI descriptions only; runtime error handling stays in main.py."""
from app.schemas import ErrorResponse

API_DESCRIPTION = (
    "只读 Mock MES/ERP/WMS 业务事实接口，SQLite 分别模拟各系统后端。"
    "固定流程后续优先使用 Workflow + HTTP Request；只有需要 Agent 自主选择接口时才使用 Swagger Tool。"
    "200 仅表示数据可用，不表示工艺正常；对象不存在或数据不可用时停止工艺推断。"
    "500/timeout 等系统失败表示事实状态未知，不是生产异常。"
    "本 API 不返回工艺判定、处置建议或设备控制指令。"
)


def error_responses(object_name: str, parameter: str, missing_field: str,
                    *, measurement: bool = False) -> dict:
    def example(category, code, message, fields=()):
        return {"value": {"error": {"category": category, "code": code,
                                    "message": message, "fields": list(fields)}}}

    definitions = {
        404: (f"data / OBJECT_NOT_FOUND：源系统成功查询后未找到{object_name}，不是工艺异常。", {
            "object_not_found": example("data", "OBJECT_NOT_FOUND", "业务对象不存在")}),
        409: ("数据不可用：MISSING_FIELDS（必要字段为空）或 INVALID_DATA（字段格式无效）；停止工艺推断。", {
            "missing_fields": example("data", "MISSING_FIELDS", "业务数据缺少必要字段", [missing_field]),
            "invalid_data": example("data", "INVALID_DATA", "业务字段格式无效", [missing_field])}),
        422: ("request / INVALID_PARAMETER：路径参数格式非法，未查询业务系统。", {
            "invalid_parameter": example("request", "INVALID_PARAMETER", "请求参数格式非法", [f"path.{parameter}"])}),
        500: ("system / INTERNAL_ERROR：内部系统失败，事实状态未知，不得推断生产异常。", {
            "internal_error": example("system", "INTERNAL_ERROR", "内部系统失败，事实状态未知")}),
        502: ("system / UPSTREAM_ERROR：模拟上游服务失败（例如 HTTP 500），事实状态未知。", {
            "upstream_error": example("system", "UPSTREAM_ERROR", "上游服务失败，事实状态未知")}),
        503: ("system / BACKEND_UNAVAILABLE：模拟业务数据库不可用或查询失败，事实状态未知。", {
            "backend_unavailable": example("system", "BACKEND_UNAVAILABLE", "模拟业务系统数据库不可用")}),
        504: ("system / UPSTREAM_TIMEOUT：模拟上游调用超时，事实状态未知。", {
            "upstream_timeout": example("system", "UPSTREAM_TIMEOUT", "业务系统调用超时，事实状态未知")}),
    }
    if measurement:
        description, examples = definitions[409]
        examples["measurement_missing"] = example("data", "MEASUREMENT_MISSING", "对象存在，但缺少测量记录")
        definitions[409] = (description + " MEASUREMENT_MISSING 表示炉次存在但无对应测量记录。", examples)
    return {status: {"model": ErrorResponse, "description": description,
                     "content": {"application/json": {"examples": examples}}}
            for status, (description, examples) in definitions.items()}
