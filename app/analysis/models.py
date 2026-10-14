from datetime import datetime

from pydantic import BaseModel, Field, FiniteFloat, model_validator

from app.schemas import Chemistry, Heat, Temperature


class Limit(BaseModel):
    minimum: FiniteFloat = Field(description="有效标准规定的下限，包含边界")
    maximum: FiniteFloat = Field(description="有效标准规定的上限，包含边界")
    unit: str = Field(min_length=1, description="与实际参数一致的单位")

    @model_validator(mode="after")
    def ordered(self):
        if self.minimum > self.maximum:
            raise ValueError("minimum exceeds maximum")
        return self


class RuleSource(BaseModel):
    document_name: str = Field(min_length=1, description="正式演示标准名称")
    version: str = Field(min_length=1, description="标准版本")
    effective_date: str = Field(min_length=1, description="标准生效日期")
    chapter: str = Field(min_length=1, description="章")
    section: str = Field(min_length=1, description="节")
    page: int = Field(ge=1, description="演示逻辑页码")


class ProcessRule(BaseModel):
    rule_id: str = Field(min_length=1, description="MES 受控规则标识，不由 LLM 决定")
    steel_grade: str = Field(min_length=1, description="适用钢种")
    process_stage: str = Field(min_length=1, description="适用工艺阶段")
    scope: str = Field(min_length=1, description="适用产线")
    required_status: str = Field(min_length=1, description="适用生产状态")
    effective_from: datetime = Field(description="生效时刻，含边界，带时区")
    effective_until: datetime = Field(description="失效时刻，不含边界，带时区")
    max_age_seconds: int = Field(gt=0, description="正式演示标准规定的数据有效期秒数")
    limits: dict[str, Limit] = Field(description="温度和碳硅锰有效上下限；纯虚构教学值")
    source: RuleSource = Field(description="规则的正式文档出处")

    @model_validator(mode="after")
    def valid_rule(self):
        if (self.effective_from.tzinfo is None or self.effective_until.tzinfo is None
                or self.effective_from >= self.effective_until):
            raise ValueError("invalid rule effective interval")
        expected = {"temperature_c": "°C", "carbon_pct": "%", "silicon_pct": "%", "manganese_pct": "%"}
        if set(self.limits) != set(expected) or any(self.limits[k].unit != v for k, v in expected.items()):
            raise ValueError("incomplete limits or invalid units")
        return self


class AnalysisContext(BaseModel):
    heat: Heat = Field(description="MES 炉次基础事实")
    process_stage: str = Field(min_length=1, description="MES 当前工艺阶段")
    scope: str = Field(min_length=1, description="MES 当前产线")
    stage_started_at: datetime = Field(description="当前阶段开始时刻；拒绝沿用之前阶段的测量")
    temperature: Temperature = Field(description="MES 保存的温度实测记录")
    chemistry: Chemistry = Field(description="MES 保存的成分实测记录")
    rule: ProcessRule = Field(description="匹配当前钢种、阶段、状态、产线和时刻的唯一有效规则")
    snapshot_at: datetime = Field(description="MES 服务端本次只读事务快照时刻")
