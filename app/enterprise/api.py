"""Three minimal queries; storage remains in each simulated enterprise backend."""
import hashlib
import json
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Header, Request
from pydantic import ValidationError

from app.api_docs import error_responses
from app.db import connect, require_heat
from app.errors import data_error
from app.parameters import HeatId, ObjectId
from app.enterprise.models import HeatTaskLink, InventoryBatch, ProductionOrder, SourceResponse

router = APIRouter()
RequestId = Annotated[str | None, Header(alias="X-Request-ID", min_length=1, max_length=128,
                                       pattern=r"^[^\s\x00-\x1f\x7f/]+$",
                                       description="本次调用身份；Dify 使用 sys.workflow_run_id。缺省服务端生成 UUID。")]


def source_response(request, system, table, key, entity_id, model, request_id):
    # Table/key are route constants; only the entity ID is supplied by a caller.
    with connect(request.app.state.data_dir, system) as connection:
        if system == "mes": require_heat(connection, entity_id)
        row = connection.execute(f"SELECT record_json FROM {table} WHERE {key} = ?", (entity_id,)).fetchone()
    if row is None:
        raise data_error("UNVERIFIED_CROSS_SYSTEM_RELATION" if system == "mes" else "OBJECT_NOT_FOUND",
                         "源系统没有该对象/正式关联，不能猜测关系")
    try:
        entity = model.model_validate_json(row["record_json"])
        if getattr(entity, key) != entity_id: raise ValueError("entity identity mismatch")
        values = entity.model_dump(mode="json")
        if any(isinstance(value, str) and not value.strip() for value in values.values()):
            raise ValueError("empty source field")
        for field in ("source_updated_at", "due_date"):
            if field in model.model_fields and getattr(entity, field).tzinfo is None:
                raise ValueError("timezone required")
    except (ValidationError, ValueError, TypeError) as exc:
        raise data_error("INVALID_DATA", "源系统字段/身份格式无效，不进行联合推断") from exc
    canonical = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return SourceResponse[model](request_id=request_id or str(uuid4()), data=entity,
                                 content_sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest())


link_errors = error_responses("MES 任务关联", "heat_id", "production_order_id")
link_errors[409]["description"] += " UNVERIFIED_CROSS_SYSTEM_RELATION：缺少正式关联键，不得猜测订单或批次。"


@router.get("/api/mes/heats/{heat_id}/enterprise-links", tags=["MES"],
            response_model=SourceResponse[HeatTaskLink], operation_id="get_mes_heat_enterprise_links",
            summary="查询 MES 炉次的正式跨系统关联",
            description="先由 MES 确认炉次，再返回生产订单、物料、批次关联。404 炉次不存在即停止；409 无关联或数据无效；422 参数错误；5xx 系统失败。不得根据文本猜测关系。",
            response_description="MES 正式关联和请求绑定摘要，不是文档出处。", responses=link_errors)
def get_links(heat_id: HeatId, request: Request, request_id: RequestId = None):
    return source_response(request, "mes", "heat_task_links", "heat_id", heat_id, HeatTaskLink, request_id)


@router.get("/api/erp/production-orders/{production_order_id}", tags=["ERP"],
            response_model=SourceResponse[ProductionOrder], operation_id="get_erp_production_order",
            summary="查询 ERP 生产订单及明确物料需求",
            description="使用 MES 返回的 production_order_id 查询。404 订单不存在；409 数据不可用；422 非法参数；5xx 系统失败。返回关联炉次、钢种、计划/完成量、交期及指定物料批次需求，全部只读。",
            response_description="ERP 生产任务事实及请求绑定摘要；不提供财务或采购功能。",
            responses=error_responses("ERP 生产订单", "production_order_id", "steel_grade"))
def get_order(production_order_id: ObjectId, request: Request, request_id: RequestId = None):
    return source_response(request, "erp", "production_orders", "production_order_id", production_order_id, ProductionOrder, request_id)


@router.get("/api/wms/batches/{batch_id}", tags=["WMS"],
            response_model=SourceResponse[InventoryBatch], operation_id="get_wms_inventory_batch",
            summary="查询 WMS 指定批次可用库存",
            description="使用正式关联 batch_id 查询物料、预留订单、可用量和仓位。404 批次不存在，不能补零；409 数据不可用；422 参数错误；5xx 系统失败。quantity=0 是事实，无库存扣减。",
            response_description="WMS 批次只读事实及请求绑定摘要，不是知识库 citation。",
            responses=error_responses("WMS 批次", "batch_id", "available_quantity"))
def get_batch(batch_id: ObjectId, request: Request, request_id: RequestId = None):
    return source_response(request, "wms", "inventory_batches", "batch_id", batch_id, InventoryBatch, request_id)
