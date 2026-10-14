from fastapi import APIRouter, Request

from app.db import connect, read_record
from app.parameters import MaterialRequestId
from app.api_docs import error_responses
from app.schemas import MaterialRequest

router = APIRouter(prefix="/api/erp", tags=["ERP"])


@router.get("/material-requests/{request_id}", response_model=MaterialRequest, operation_id="get_erp_material_request",
            summary="查询 ERP 物料申请",
            description="已知 request_id，需要查询物料申请的物料编码、申请数量、单位或单据状态时调用。此接口不返回库存；如需库存，应使用返回的 material_code 查询 WMS。404 表示申请不存在，409 表示数据不可用，422 表示参数错误，5xx 表示系统失败、事实状态未知；均不是工艺异常结论。",
            response_description="ERP 申请单事实：申请单号、物料编码、数量、单位、单据状态及更新时间。",
            responses=error_responses("ERP 物料申请", "request_id", "quantity"))
def get_material_request(request_id: MaterialRequestId, request: Request):
    with connect(request.app.state.data_dir, "erp") as connection:
        return read_record(connection, "SELECT * FROM material_requests WHERE request_id = ?",
                           request_id, MaterialRequest)
