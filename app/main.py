import logging
import sqlite3
from contextlib import closing
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException

from app.db import data_directory
from app.api_docs import API_DESCRIPTION
from app.analysis.mes_context import router as analysis_context_router, utc_now
from app.errors import BackendError, UpstreamServiceError
from app.routers import erp, mes, wms
from app.schemas import ErrorDetail, ErrorResponse
from app.enterprise.api import router as enterprise_router

logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    status: str = Field(description="全部 Mock 系统数据库可读时为 ok")
    backends: dict[str, str] = Field(description="SQLite 模拟后端连通状态")


def error_response(status: int, category: str, code: str, message: str,
                   fields: list[str] | None = None) -> JSONResponse:
    body = ErrorResponse(error=ErrorDetail(
        category=category, code=code, message=message, fields=fields or []
    ))
    return JSONResponse(status_code=status, content=body.model_dump())


def create_app(data_dir: Path | None = None, *, server_url: str = "http://127.0.0.1:8000", analysis_clock=None) -> FastAPI:
    application = FastAPI(
        title="制造业 Copilot · Mock 企业系统 API", version="0.1.0",
        description=API_DESCRIPTION,
        servers=[{"url": server_url, "description": "业务 API 地址；导入前替换为 Dify 执行环境可访问的地址"}],
        openapi_tags=[
            {"name": "MES", "description": "炉次基础信息、温度及化学成分事实查询"},
            {"name": "ERP", "description": "物料申请与最小生产订单事实查询"},
            {"name": "WMS", "description": "物料汇总库存与指定批次只读事实查询"},
        ],
    )
    application.state.data_dir = Path(data_dir) if data_dir is not None else data_directory()
    application.state.analysis_clock = analysis_clock or utc_now

    @application.get(
        "/health",
        operation_id="get_health",
        summary="检查 Mock 后端就绪状态",
        description="以只读连接检查 MES、ERP、WMS SQLite 模拟后端。任一后端不可读返回 503/system；不检查 Dify 或外部生产系统。",
        response_model=HealthResponse,
        responses={503: {"model": ErrorResponse, "description": "至少一个模拟后端不可用"}},
        tags=["Health"],
    )
    def health():
        for system in ("mes", "erp", "wms"):
            with closing(sqlite3.connect(
                (application.state.data_dir / f"{system}.db").resolve().as_uri() + "?mode=ro",
                uri=True,
                timeout=2,
            )) as connection:
                connection.execute("SELECT 1").fetchone()
        return {"status": "ok", "backends": {name: "ok" for name in ("mes", "erp", "wms")}}

    @application.exception_handler(BackendError)
    async def handle_backend_error(request: Request, exc: BackendError):
        body = ErrorResponse(error=exc.detail)
        return JSONResponse(status_code=exc.status_code, content=body.model_dump())

    @application.exception_handler(sqlite3.Error)
    async def handle_database_error(request: Request, exc: sqlite3.Error):
        logger.error("Mock database query failed", exc_info=exc)
        body = ErrorResponse(error=ErrorDetail(
            category="system", code="BACKEND_UNAVAILABLE", message="模拟业务系统数据库不可用"
        ))
        return JSONResponse(status_code=503, content=body.model_dump())

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError):
        fields = sorted({".".join(str(part) for part in error["loc"])
                         for error in exc.errors()})
        return error_response(422, "request", "INVALID_PARAMETER", "请求参数格式非法", fields)

    @application.exception_handler(TimeoutError)
    async def handle_timeout(request: Request, exc: TimeoutError):
        logger.error("Backend timed out", exc_info=exc)
        return error_response(504, "system", "UPSTREAM_TIMEOUT", "业务系统调用超时，事实状态未知")

    @application.exception_handler(UpstreamServiceError)
    async def handle_upstream_error(request: Request, exc: UpstreamServiceError):
        logger.error("Upstream service failed", exc_info=exc)
        return error_response(502, "system", "UPSTREAM_ERROR", "上游服务失败，事实状态未知")

    @application.exception_handler(HTTPException)
    async def handle_http_error(request: Request, exc: HTTPException):
        # A missing route is not evidence that a business object is absent.
        if exc.status_code >= 500:
            response = error_response(exc.status_code, "system", "INTERNAL_ERROR", "系统请求失败")
        else:
            code = {404: "ROUTE_NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(
                exc.status_code, "HTTP_REQUEST_ERROR")
            response = error_response(exc.status_code, "request", code, "请求路径、方法或权限无效")
        if exc.headers:
            response.headers.update(exc.headers)
        return response

    @application.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception):
        logger.error("Unexpected API failure", exc_info=exc)
        return error_response(500, "system", "INTERNAL_ERROR", "内部系统失败，事实状态未知")

    for router in (mes.router, erp.router, wms.router, analysis_context_router, enterprise_router):
        application.include_router(router)
    return application


app = create_app()
