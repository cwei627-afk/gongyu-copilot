from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Document(Contract):
    document_id: Text
    document_name: Text
    document_family: Text
    doc_type: Literal["sop", "process_procedure", "quality_standard"]
    version: Text
    effective_date: date
    effective_until: date | None = None  # Exclusive; version strings are never sorted.
    status: Literal["published", "withdrawn", "draft"]
    scope: Text
    fictional: Literal[True]

    @model_validator(mode="after")
    def valid_interval(self):
        if self.effective_until is not None and self.effective_until <= self.effective_date:
            raise ValueError("effective_until must be later than effective_date")
        return self

    def is_effective(self, as_of: date) -> bool:
        return (self.status == "published" and self.effective_date <= as_of
                and (self.effective_until is None or as_of < self.effective_until))


class Chunk(Contract):
    chunk_id: Text
    document_id: Text
    chapter: Text | None = None
    section: Text | None = None
    page: int | None = Field(default=None, ge=1)
    content: Text


class Corpus(Contract):
    notice: Text
    documents: list[Document]
    chunks: list[Chunk]

    @model_validator(mode="after")
    def valid_references(self):
        ids = [document.document_id for document in self.documents]
        chunk_ids = [chunk.chunk_id for chunk in self.chunks]
        if len(ids) != len(set(ids)) or len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("duplicate document_id or chunk_id")
        if any(chunk.document_id not in ids for chunk in self.chunks):
            raise ValueError("chunk references an unknown document")
        return self


class Question(Contract):
    question_id: Text
    question: Text
    scope: Text
    as_of: date
    required_points: list[Text] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_points(self):
        if len(set(self.required_points)) != len(self.required_points):
            raise ValueError("required_points must be unique")
        return self


class Candidate(Contract):
    chunk_id: Text
    content: Text
    similarity_score: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)


class Assessment(Contract):
    """Explicit review input, not an automatic claim of semantic understanding."""
    chunk_id: Text
    question_id: Text
    question: Text
    reviewer: Text
    verdict: Literal["direct", "related_only", "irrelevant", "uncertain"]
    quote: str = ""
    covered_points: list[Text] = Field(default_factory=list)
    rationale: Text


class GateRequest(Contract):
    question: Question
    retrieval_status: Literal["ok", "failed"]
    candidates: list[Candidate]
    assessments: list[Assessment] = Field(default_factory=list)


class Citation(Contract):
    chunk_id: str
    document_id: str
    document_name: str
    version: str
    effective_date: date
    chapter: str | None
    section: str | None
    page: int | None
    quote: str
    covered_points: list[str]


class Rejection(Contract):
    chunk_id: str
    code: str


class GateResult(Contract):
    decision: Literal["supported", "abstain"]
    reason_codes: list[str]
    message: str
    human_confirmation_required: Literal[True] = True
    production_conclusion: None = None
    evidence: list[Citation] = Field(default_factory=list)
    rejected: list[Rejection] = Field(default_factory=list)
