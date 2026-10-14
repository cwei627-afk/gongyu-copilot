from fastapi import APIRouter, Request

from app.db import connect, read_record
from app.parameters import MaterialCode
from app.api_docs import error_responses
from app.schemas import Inventory

router = APIRouter(prefix="/api/wms", tags=["WMS"])


@router.get("/inventory/{material_code}", response_model=Inventory, operation_id="get_wms_inventory",
            summary="查询 WMS 物料库存",
            description="已知 material_code，需要查询该物料汇总库存时调用。每物料一条库存记录，不提供库位明细或 ERP 申请状态。零库存是有效业务事实。404 表示库存对象不存在，不能当作库存为零；409 表示数据不可用，422 表示参数错误，5xx 表示系统失败、事实状态未知；不作生产异常判断。",
            response_description="物料编码、名称、汇总库存数量、单位及更新时间；quantity=0 是有效结果。",
            responses=error_responses("WMS 库存对象", "material_code", "quantity"))
def get_inventory(material_code: MaterialCode, request: Request):
    with connect(request.app.state.data_dir, "wms") as connection:
        return read_record(connection, "SELECT * FROM inventory WHERE material_code = ?",
                           material_code, Inventory)
