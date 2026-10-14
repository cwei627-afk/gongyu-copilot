"""Product contracts expose only verified facts and an explicit technical allowlist."""
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field


class Intent(str, Enum):
    INTERNAL_KNOWLEDGE = 'INTERNAL_KNOWLEDGE'
    GENERAL_INDUSTRY_KNOWLEDGE = 'GENERAL_INDUSTRY_KNOWLEDGE'
    LIVE_ENTERPRISE_QUERY = 'LIVE_ENTERPRISE_QUERY'
    ANOMALY_ANALYSIS = 'ANOMALY_ANALYSIS'
    CLARIFICATION = 'CLARIFICATION'
    UNSUPPORTED = 'UNSUPPORTED'


class Closed(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Query(Closed):
    question: str = Field(min_length=1, max_length=2000)
    context_token: str | None = Field(default=None, max_length=2000)


class Route(Closed):
    intent: Intent
    entity_kind: str | None = None
    entity_id: str | None = None
    canonical_query: str = ''
    collection: str | None = None
    filters: dict = Field(default_factory=dict)
    reason: str = ''


class Fact(Closed):
    label: str
    value: str
    system: str


class Source(Closed):
    source_type: str
    label: str
    document_name: str | None = None
    version: str | None = None
    chapter: str | None = None
    section: str | None = None
    page: int | None = None
    effective_date: str | None = None
    scope: str | None = None
    citation_id: str | None = None
    document_id: str | None = None
    segment_id: str | None = None
    content_sha256: str | None = None
    url: str | None = None
    entity_id: str | None = None


class ProductResponse(Closed):
    request_id: str
    status: str
    intent: Intent
    title: str
    summary: str
    facts: list[Fact] = Field(default_factory=list)
    analysis: list[str] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    human_confirmation: str
    process_steps: list[str] = Field(default_factory=list)
    technical_meta: dict = Field(default_factory=dict)
    context_token: str | None = None
