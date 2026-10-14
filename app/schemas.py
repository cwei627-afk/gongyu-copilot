from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, FiniteFloat


class Heat(BaseModel):
    heat_id: str = Field(description='MES 炉次号，动态业务标识；不是合法 ID 白名单')
    steel_grade: str = Field(description='MES 记录的钢种；不包含该钢种的工艺标准')
    status: str = Field(description='源系统记录的业务状态，不是工艺正常/异常判定')
    updated_at: datetime = Field(description='源系统记录的更新时间；不代表本次 API 查询时间，不自动判断过期')


class Temperature(BaseModel):
    heat_id: str = Field(description='MES 炉次号，动态业务标识；不是合法 ID 白名单')
    temperature_c: FiniteFloat = Field(description='实测温度，单位 °C；有限数值，不包含目标范围')
    measured_at: datetime = Field(description='源系统记录的测量时间；不代表本次查询时间')


class Chemistry(BaseModel):
    heat_id: str = Field(description='MES 炉次号，动态业务标识；不是合法 ID 白名单')
    carbon_pct: FiniteFloat = Field(description='碳质量百分比，0.18 表示 0.18%；不包含合格范围')
    silicon_pct: FiniteFloat = Field(description='硅质量百分比，0.25 表示 0.25%；不包含合格范围')
    manganese_pct: FiniteFloat = Field(description='锰质量百分比，0.65 表示 0.65%；不包含合格范围')
    measured_at: datetime = Field(description='源系统记录的测量时间；不代表本次查询时间')


class MaterialRequest(BaseModel):
    request_id: str = Field(description='ERP 物料申请单号')
    material_code: str = Field(description='源系统物料编码，可用于 WMS 库存查询')
    quantity: FiniteFloat = Field(description='业务数量，单位见 unit；ERP 为申请数量，WMS 为汇总库存，0 是有效值')
    unit: str = Field(description='数量单位，例如 kg')
    status: str = Field(description='源系统记录的业务状态，不是工艺正常/异常判定')
    updated_at: datetime = Field(description='源系统记录的更新时间；不代表本次 API 查询时间，不自动判断过期')


class Inventory(BaseModel):
    material_code: str = Field(description='源系统物料编码，可用于 WMS 库存查询')
    material_name: str = Field(description='WMS 记录的物料名称')
    quantity: FiniteFloat = Field(description='业务数量，单位见 unit；ERP 为申请数量，WMS 为汇总库存，0 是有效值')
    unit: str = Field(description='数量单位，例如 kg')
    updated_at: datetime = Field(description='源系统记录的更新时间；不代表本次 API 查询时间，不自动判断过期')


class ErrorDetail(BaseModel):
    category: Literal["request", "data", "system"] = Field(description='request：请求错误；data：事实不存在或数据不可用；system：系统失败、事实状态未知')
    code: str = Field(description='稳定机器错误码，与 HTTP 状态及 category 一起判断；见各响应示例')
    message: str = Field(description='可读错误提示，调用方不要依赖提示文本进行逻辑分支')
    fields: list[str] = Field(default_factory=list, description="相关字段路径；参数错误如 path.heat_id，数据错误如 temperature_c；无字段级信息时为空数组")


class ErrorResponse(BaseModel):
    error: ErrorDetail = Field(description='统一错误对象；不包含工艺判定或生产处置建议')
