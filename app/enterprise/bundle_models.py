"""Reviewable bundle schema; Dify checks the stronger raw-response reconstruction."""
from datetime import datetime
from typing import Annotated, Generic, TypeVar

from pydantic import Field, model_validator

from app.analysis.models import AnalysisContext
from app.enterprise.models import ClosedModel, HeatTaskLink, InventoryBatch, ProductionOrder


class ApiProvenance(ClosedModel):
    system: str = Field(description="MES / ERP / WMS；不是文档 citation")
    operation_id: str = Field(description="固定只读 OpenAPI operation identity")
    endpoint: str = Field(description="实际查询路径，不含凭证")
    entity_id: str = Field(description="源实体身份")
    request_id: str = Field(description="本次 Workflow run identity")
    revision: int | None = Field(description="源修订号；冻结 MES context 接口没有此字段，明确 null")
    source_updated_at: datetime = Field(description="源记录更新时间或冻结 MES snapshot_at")
    content_sha256: str = Field(pattern="^[0-9a-f]{64}$", description="规范事实对象 hash")
    response_body_sha256: str = Field(pattern="^[0-9a-f]{64}$", description="原始响应正文 hash")


class MesFacts(ClosedModel):
    analysis_context: AnalysisContext = Field(description="已经 Stage A 比较验证的 MES 快照与规则")
    task_link: HeatTaskLink | None = Field(description="MES 正式关联；尚未取得/验证时 null，不猜测")


Facts = TypeVar("Facts")
EmptyFacts = Annotated[dict, Field(max_length=0)]


class VerifiedSource(ClosedModel, Generic[Facts]):
    verified: bool = Field(description="该系统事实是否验证通过")
    entity_id: str | None = Field(description="关联明确前可为 null")
    facts: Facts | EmptyFacts = Field(description="已验证结构化事实；未验证时为空对象")
    provenance: list[ApiProvenance] = Field(description="只读 API provenance，与 citation 分离")

    @model_validator(mode="after")
    def verified_state(self):
        if self.verified != bool(self.provenance) or self.verified != bool(self.facts):
            raise ValueError("verified source must have facts and provenance")
        return self


class RagSources(ClosedModel):
    verified_hits: list[dict] = Field(description="Stage A 实际 verified hit 记录；进入生成前由其来源门禁校验，不是 API 事实")


class EnterpriseEvidenceBundle(ClosedModel):
    request_id: str = Field(description="本次 Workflow run ID，跨请求不可复用")
    heat_id: str = Field(description="本次 MES 炉次身份")
    mes: VerifiedSource[MesFacts] = Field(description="MES 事实和两次只读 API provenance")
    erp: VerifiedSource[ProductionOrder] = Field(description="ERP 生产任务事实或显式未验证状态")
    wms: VerifiedSource[InventoryBatch] = Field(description="WMS 指定批次事实或显式未验证状态")
    rag: RagSources = Field(description="企业规程来源；引用链保持 Stage A/B 定义")
    integrity_sha256: str = Field(pattern="^[0-9a-f]{64}$", description="除本字段外的 canonical bundle hash；非数字签名")
