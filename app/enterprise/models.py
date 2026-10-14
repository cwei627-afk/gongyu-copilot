from datetime import datetime
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class HeatTaskLink(ClosedModel):
    heat_id: str = Field(description="MES 确认的炉次身份")
    production_order_id: str = Field(description="MES 正式关联的 ERP 生产订单 ID")
    steel_grade: str = Field(description="MES 关联记录钢种，必须与炉次快照一致")
    material_code: str = Field(description="MES 任务关联的物料编码")
    batch_id: str = Field(description="MES 任务关联的 WMS 指定批次")
    expected_erp_revision: int = Field(ge=1, description="MES 任务要求的 ERP 最低有效修订号，不由 AI 猜测")
    expected_wms_revision: int = Field(ge=1, description="MES 任务要求的 WMS 最低有效修订号")
    source_updated_at: datetime = Field(description="源记录更新时间，须有时区")
    revision: int = Field(ge=1, description="MES 源记录修订号")


class ProductionOrder(ClosedModel):
    production_order_id: str = Field(description="ERP 生产订单身份")
    heat_ids: list[str] = Field(min_length=1, description="ERP 明确关联的炉次列表，不由 AI 推测")
    steel_grade: str = Field(description="ERP 产品钢种要求")
    planned_quantity: Annotated[FiniteFloat, Field(ge=0)] = Field(description="订单计划数量")
    completed_quantity: Annotated[FiniteFloat, Field(ge=0)] = Field(description="订单完成数量")
    quantity_unit: str = Field(description="计划与完成数量共同单位")
    due_date: datetime = Field(description="ERP 订单交期，含时区；不据此自行推断交期风险")
    status: str = Field(description="ERP 订单状态，只读事实")
    material_code: str = Field(description="该订单本次指定物料编码")
    batch_id: str = Field(description="该订单本次指定 WMS 批次")
    required_quantity: Annotated[FiniteFloat, Field(ge=0)] = Field(description="该任务明确物料需求量，不由模型估算")
    material_unit: str = Field(description="需求量单位，只允许与 WMS 同单位比较，无隐式换算")
    source_updated_at: datetime = Field(description="ERP 源记录更新时间，含时区")
    revision: int = Field(ge=1, description="ERP 源记录修订号")


class InventoryBatch(ClosedModel):
    batch_id: str = Field(description="WMS 批次身份")
    material_code: str = Field(description="WMS 物料编码")
    material_name: str = Field(description="WMS 物料名称")
    production_order_id: str = Field(description="批次明确关联/预留的生产订单 ID")
    available_quantity: Annotated[FiniteFloat, Field(ge=0)] = Field(description="本批次可用数量，零是事实，缺失不补零")
    unit: str = Field(description="可用数量单位")
    warehouse: str = Field(description="仓库标识")
    location: str = Field(description="仓位标识")
    status: str = Field(description="WMS 批次状态；只有 available 可参与本 PoC 可用量比较")
    source_updated_at: datetime = Field(description="WMS 源记录更新时间，含时区")
    revision: int = Field(ge=1, description="WMS 源记录修订号")


Entity = TypeVar("Entity", bound=ClosedModel)


class SourceResponse(ClosedModel, Generic[Entity]):
    request_id: str = Field(description="回显 X-Request-ID；未提供则由服务端生成。Workflow 必须与本次运行身份相等")
    data: Entity = Field(description="业务系统结构化事实，不是文档 citation")
    content_sha256: str = Field(pattern="^[0-9a-f]{64}$", description="data 的 canonical JSON SHA-256；检测传输/验证后的改动，不代替鉴权或数字签名")
