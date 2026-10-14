"""Deterministic checks around reviewed evidence; does not judge natural-language entailment."""
from pydantic import ValidationError

from app.evidence.models import Citation, Corpus, GateRequest, GateResult, Rejection


def abstain(codes: list[str], rejected: list[Rejection] | None = None) -> GateResult:
    return GateResult(
        decision="abstain", reason_codes=codes,
        message="没有充分且有效的企业证据，无法给出确定性生产处置结论。请人工确认或补充有效规程与直接支持问题的正文。",
        rejected=rejected or [],
    )


def evaluate(corpus_data: dict, request_data: dict) -> GateResult:
    # Invalid metadata or review input must not become a permissive default.
    try:
        corpus = Corpus.model_validate(corpus_data)
        request = GateRequest.model_validate(request_data)
    except ValidationError:
        return abstain(["INVALID_INPUT"])

    if request.retrieval_status != "ok":
        return abstain(["RETRIEVAL_FAILED"])
    if not request.candidates:
        return abstain(["NO_EVIDENCE"])

    candidate_ids = [candidate.chunk_id for candidate in request.candidates]
    review_ids = [review.chunk_id for review in request.assessments]
    if (len(candidate_ids) != len(set(candidate_ids))
            or len(review_ids) != len(set(review_ids))
            or not set(review_ids).issubset(candidate_ids)):
        return abstain(["INVALID_INPUT"])

    question = request.question
    documents = {document.document_id: document for document in corpus.documents}
    chunks = {chunk.chunk_id: chunk for chunk in corpus.chunks}
    reviews = {review.chunk_id: review for review in request.assessments}
    rejected = []
    evidence = []
    covered = set()
    version_conflict = False

    for candidate in request.candidates:
        code = None
        chunk = chunks.get(candidate.chunk_id)
        if chunk is None:
            code = "UNKNOWN_SOURCE"
        elif candidate.content != chunk.content:
            code = "CONTENT_MISMATCH"
        else:
            document = documents[chunk.document_id]
            if document.scope != question.scope:
                code = "SCOPE_MISMATCH"
            elif not document.is_effective(question.as_of):
                code = "INACTIVE_VERSION"
            else:
                # Consult the whole controlled catalog, not only retrieved versions.
                active_versions = [d for d in corpus.documents
                                   if d.document_family == document.document_family
                                   and d.scope == document.scope and d.is_effective(question.as_of)]
                if len(active_versions) != 1:
                    code = "VERSION_CONFLICT"
                    version_conflict = True

        review = reviews.get(candidate.chunk_id)
        if code is None:
            if review is None:
                code = "UNREVIEWED_EVIDENCE"
            elif review.question_id != question.question_id or review.question != question.question:
                code = "REVIEW_QUESTION_MISMATCH"
            elif review.verdict != "direct":
                code = "NO_DIRECT_SUPPORT"
            elif not review.quote.strip() or review.quote not in chunk.content:
                code = "INVALID_QUOTE"
            elif (not review.covered_points
                  or not set(review.covered_points).issubset(question.required_points)):
                code = "INVALID_COVERAGE"

        if code is not None:
            rejected.append(Rejection(chunk_id=candidate.chunk_id, code=code))
            continue

        covered.update(review.covered_points)
        evidence.append(Citation(
            chunk_id=chunk.chunk_id, document_id=document.document_id,
            document_name=document.document_name, version=document.version,
            effective_date=document.effective_date, chapter=chunk.chapter,
            section=chunk.section, page=chunk.page, quote=review.quote,
            covered_points=review.covered_points,
        ))

    if version_conflict:
        return abstain(["VERSION_CONFLICT"], rejected)
    if not evidence:
        return abstain(list(dict.fromkeys(r.code for r in rejected)), rejected)
    if not set(question.required_points).issubset(covered):
        return abstain(["INCOMPLETE_SUPPORT"], rejected)
    return GateResult(
        decision="supported", reason_codes=["DIRECT_EVIDENCE"],
        message="经审查的有效正文覆盖本问题所需要点；仅可依据所列原文作答，生产处置仍须人工确认。",
        evidence=evidence, rejected=rejected,
    )
