from fastapi import APIRouter, Request

from app.db import connect, read_record, require_heat
from app.parameters import HeatId
from app.api_docs import error_responses
from app.schemas import Chemistry, Heat, Temperature

router = APIRouter(prefix="/api/mes", tags=["MES"])


@router.get("/heats/{heat_id}", response_model=Heat, operation_id="get_mes_heat",
            summary="查询 MES 炉次基础信息",
            description="已知 heat_id，需要确认炉次是否存在或读取钢种、生产状态、更新时间时调用。只返回 MES 基础事实；温度和化学成分使用各自专用接口。404 表示炉次不存在，不是工艺异常；409 表示数据不可用；422 表示参数错误；5xx 表示系统失败、事实状态未知。",
            response_description="炉次基础事实：炉次号、钢种、生产状态及更新时间；不包含工艺正常/异常结论。",
            responses=error_responses("MES 炉次", "heat_id", "steel_grade"))
def get_heat(heat_id: HeatId, request: Request):
    with connect(request.app.state.data_dir, "mes") as connection:
        return read_record(connection, "SELECT * FROM heats WHERE heat_id = ?", heat_id, Heat)


@router.get("/heats/{heat_id}/temperature", response_model=Temperature, operation_id="get_mes_heat_temperature",
            summary="查询 MES 炉次温度",
            description="已知 heat_id，需要该炉次温度实测值时调用。返回当前保存的一条温度记录（摄氏度）及测量时间，不提供历史序列、目标温度或工艺判定。404 表示炉次不存在，不是工艺异常；409 表示炉次存在但测量缺失或数据无效；422 表示参数错误；5xx 表示事实状态未知。",
            response_description="炉次号、温度实测值 temperature_c（°C）及 measured_at；200 不代表温度符合工艺要求。",
            responses=error_responses("MES 炉次", "heat_id", "temperature_c", measurement=True))
def get_temperature(heat_id: HeatId, request: Request):
    with connect(request.app.state.data_dir, "mes") as connection:
        require_heat(connection, heat_id)
        return read_record(connection, "SELECT * FROM temperatures WHERE heat_id = ?",
                           heat_id, Temperature, missing_code="MEASUREMENT_MISSING")


@router.get("/heats/{heat_id}/chemistry", response_model=Chemistry, operation_id="get_mes_heat_chemistry",
            summary="查询 MES 炉次化学成分",
            description="已知 heat_id，需要碳、硅、锰实测成分时调用。返回当前保存的一条成分记录及测量时间，单位为质量百分比，不提供成分标准或合格判定。404 表示炉次不存在，不是工艺异常；409 表示测量缺失或数据无效；422 表示参数错误；5xx 表示事实状态未知。",
            response_description="炉次号、碳/硅/锰质量百分比及 measured_at；0.18 表示 0.18%，200 不代表成分合格。",
            responses=error_responses("MES 炉次", "heat_id", "carbon_pct", measurement=True))
def get_chemistry(heat_id: HeatId, request: Request):
    with connect(request.app.state.data_dir, "mes") as connection:
        require_heat(connection, heat_id)
        return read_record(connection, "SELECT * FROM chemistry WHERE heat_id = ?",
                           heat_id, Chemistry, missing_code="MEASUREMENT_MISSING")
