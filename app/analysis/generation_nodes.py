"""Stage B: bounded DeepSeek synthesis after the unchanged Stage A evidence gate.

Standard-library only, so the same parser/schema/coverage checks run in Dify Code.
No free-text entailment claim: output sentences must equal allowed MES/rule facts
or pre-reviewed checks. Sources are copied from verified hits, never from the LLM.
"""
import copy
import hashlib
import json
import re


def object_schema(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


TEXT = {"type": "string", "minLength": 1, "maxLength": 16000}
ID = {"type": "string", "minLength": 1, "maxLength": 128}
SOURCE_SCHEMA = object_schema({
    "citation_id": ID, "dataset_id": ID, "document_id": ID, "segment_id": ID,
    "document_name": TEXT, "version": ID, "effective_date": ID, "scope": ID,
    "chapter": TEXT, "section": TEXT,
    "page": {"type": ["integer", "null"], "minimum": 1},
    "content_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
})
CLAIM_SCHEMA = object_schema({"claim_id": ID, "text": TEXT})
CHECK_SCHEMA = object_schema({"check_id": ID, "text": TEXT,
                             "citation_ids": {"type": "array", "items": ID, "minItems": 1, "maxItems": 8}})
GENERATION_SCHEMA = object_schema({
    "answer": TEXT,
    "analysis_summary": {"type": "array", "items": CLAIM_SCHEMA, "minItems": 1, "maxItems": 8},
    "check_recommendations": {"type": "array", "items": CHECK_SCHEMA, "minItems": 1, "maxItems": 32},
    "citations": {"type": "array", "items": SOURCE_SCHEMA, "minItems": 1, "maxItems": 8},
    "human_confirmation": TEXT,
})
FINAL_GENERATION_SCHEMA = object_schema({
    "schema_version": {"type": "string", "pattern": "^1\\.0$"},
    "model": {"type": "string", "pattern": "^deepseek-flash$"},
    "request_id": ID,
    **GENERATION_SCHEMA["properties"],
})


class GenerationError(ValueError):
    pass


def validate_schema(value, schema):
    """Validate the exact closed JSON Schema subset above; no type coercion.

    This validator is deliberately limited to our checked schema keywords, not
    a replacement for a general-purpose JSON Schema library.
    """
    known = {"type", "properties", "required", "additionalProperties", "items", "minItems", "maxItems",
             "minLength", "maxLength", "minimum", "pattern"}
    if set(schema) - known: raise GenerationError("UNSUPPORTED_SCHEMA")
    types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
    kinds = {"object": dict, "array": list, "string": str, "integer": int, "null": type(None)}
    if not any(type(value) is kinds[k] for k in types): raise GenerationError("SCHEMA_TYPE")
    if value is None: return
    if isinstance(value, dict):
        if set(value) != set(schema["required"]): raise GenerationError("SCHEMA_FIELDS")
        for key, item in value.items(): validate_schema(item, schema["properties"][key])
    elif isinstance(value, list):
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", 100):
            raise GenerationError("SCHEMA_ARRAY_LENGTH")
        for item in value: validate_schema(item, schema["items"])
    elif isinstance(value, str):
        if not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", 16000):
            raise GenerationError("SCHEMA_STRING_LENGTH")
        if "pattern" in schema and not re.fullmatch(schema["pattern"], value): raise GenerationError("SCHEMA_PATTERN")
    elif type(value) is int and value < schema.get("minimum", value): raise GenerationError("SCHEMA_MINIMUM")


def no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise GenerationError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def strict_json(text):
    return json.loads(text, object_pairs_hook=no_duplicate_keys,
                      parse_constant=lambda value: (_ for _ in ()).throw(GenerationError("NONFINITE_JSON")))


def parse_model_text(text):
    """Recognize complete wrappers only, then consume one complete JSON object.

    Never search for the first/last brace or repair malformed/truncated JSON.
    Arbitrary prose, multiple objects, incomplete/nested reasoning tags fail.
    """
    if not isinstance(text, str) or len(text) > 100000: raise GenerationError("INVALID_MODEL_TEXT")
    text, reasoning = text.strip(), ""
    if text.startswith("<think>"):
        end = text.find("</think>", len("<think>"))
        if end < 0: raise GenerationError("UNCLOSED_THINK")
        reasoning = text[len("<think>"):end]
        if "<think>" in reasoning: raise GenerationError("NESTED_THINK")
        text = text[end + len("</think>"):].strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) < 3 or lines[0] not in ("```", "```json") or lines[-1] != "```":
            raise GenerationError("INVALID_CODE_FENCE")
        text = "\n".join(lines[1:-1])
    try:
        value = strict_json(text)
    except (ValueError, TypeError, RecursionError) as exc:
        raise GenerationError("INVALID_JSON") from exc
    return value, reasoning


def stable_id(prefix, payload):
    value = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False)
    return prefix + hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def render_answer(summary, checks, human):
    return "\n".join([item["text"] for item in summary] +
                     [item["text"] + " " + " ".join("[cite:" + key + "]" for key in item["citation_ids"])
                      for item in checks] + [human])


def generation_catalog(previous, retrieval_result, request_id=None):
    """Bind this generation request to Stage A verified sources and native hits."""
    result = strict_json(previous)
    if result.get("status") != "review_required" or not result.get("sources"):
        raise GenerationError("UNVERIFIED_GENERATION_INPUT")
    if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
        raise GenerationError("MISSING_GENERATION_REQUEST_ID")
    binding = [request_id, result["heat_id"], result["analysis_request"], result["data_used"]["snapshot_at"]]
    citations, by_segment = [], {}
    for source in result["sources"]:
        matches = [hit for hit in retrieval_result if isinstance(hit, dict) and isinstance(hit.get("metadata"), dict)
                   and all(hit["metadata"].get(k) == source[k] for k in ("dataset_id", "document_id", "segment_id"))]
        if len(matches) != 1: raise GenerationError("VERIFIED_HIT_NOT_AVAILABLE")
        hit = matches[0]; metadata = hit["metadata"].get("doc_metadata", {})
        if (hit.get("content") != source["quote"]
                or hashlib.sha256(hit["content"].encode("utf-8")).hexdigest() != source["content_sha256"]
                or metadata.get("scope") != result["data_used"]["scope"]
                or any(metadata.get(k) != source[k] for k in ("version", "chapter", "section", "page", "content_sha256"))):
            raise GenerationError("VERIFIED_HIT_CHANGED")
        citation = {key: source[key] for key in SOURCE_SCHEMA["properties"] if key not in ("citation_id", "scope")}
        citation["scope"] = metadata["scope"]
        citation["citation_id"] = stable_id("cite_", [binding, citation])
        citations.append(citation)
        by_segment[source["segment_id"]] = citation["citation_id"]
    summary = []
    for fact in result["anomaly_facts"]:
        direction = "低于下限" if fact["direction"] == "low" else "高于上限"
        text = (f"{fact['parameter']} 实测 {fact['actual']} {fact['unit']}；MES 当前规则 {fact['rule_id']} "
                f"范围 [{fact['minimum']}, {fact['maximum']}] {fact['unit']}；{direction}。")
        summary.append({"claim_id": stable_id("fact_", [binding, fact]), "text": text})
    checks = [{"check_id": stable_id("check_", [binding, item]), "text": item["text"],
               "citation_ids": [by_segment[item["segment_id"]]]} for item in result["suggested_checks"]]
    catalog = {"answer": render_answer(summary, checks, result["human_confirmation"]), "analysis_summary": summary,
               "check_recommendations": checks, "citations": citations, "human_confirmation": result["human_confirmation"]}
    validate_schema(catalog, GENERATION_SCHEMA)
    return catalog


def generation_failure(previous, code="LLM_PROVIDER_FAILURE", category="system"):
    result = strict_json(previous)
    result.update(status="abstain" if category == "evidence" else "system_error", category=category, code=code,
                  message="生成或引用校验未通过，无法确认处置建议；请人工核对原始事实与企业规程。",
                  sources=[], suggested_checks=[], automatic_actions=[])
    result.pop("generation", None)
    result["trace"].append("generation_fail_closed")
    return {"state": "end", "result": json.dumps(result, ensure_ascii=False, allow_nan=False)}


def prepare_generation(previous, retrieval_result, request_id=None):
    result = strict_json(previous)
    if result.get("status") != "review_required":
        return {"state": "end", "result": previous, "payload": ""}
    try:
        catalog = generation_catalog(previous, retrieval_result, request_id)
        return {"state": "generate", "result": previous,
                "payload": json.dumps(catalog, ensure_ascii=False, allow_nan=False)}
    except (KeyError, ValueError, TypeError, AttributeError):
        failure = generation_failure(previous, "UNVERIFIED_GENERATION_INPUT", "evidence")
        return {**failure, "payload": ""}


def validate_generation(previous, retrieval_result, text, structured_output=None, finish_reason="stop", reasoning_content="", request_id=None):
    try:
        catalog = generation_catalog(previous, retrieval_result, request_id)
        allowed = {item["citation_id"]: item for item in catalog["citations"]}
        if finish_reason not in ("stop", "tool_calls"): raise GenerationError("INCOMPLETE_MODEL_OUTPUT")
        reasoning = reasoning_content or ""
        if not isinstance(reasoning, str): raise GenerationError("INVALID_REASONING")
        parsed = None
        if text:
            parsed, tagged_reasoning = parse_model_text(text)
            reasoning += tagged_reasoning
        if structured_output is not None:
            validate_schema(structured_output, GENERATION_SCHEMA)
            if parsed is not None and parsed != structured_output: raise GenerationError("NATIVE_TEXT_MISMATCH")
            parsed = structured_output
        validate_schema(parsed, GENERATION_SCHEMA)
        # Reasoning is never rendered; explicit forged references still reject.
        references = re.finditer(r"\[cite:([^\]]+)\]|\bcite_[0-9a-f]{32}\b|citation_id[\"']?\s*:\s*[\"']([^\"']+)", reasoning)
        flattened = [match.group(1) or match.group(2) or match.group(0) for match in references]
        # Syntax-only templates in private reasoning are not source identities.
        # They are never rendered, and are NOT allowed in the final citations.
        templates = {"citation_id", "...", "<citation_id>", "<id>"}
        if any(key not in allowed and key not in templates for key in flattened):
            raise GenerationError("UNAUTHORIZED_REASONING_CITATION")
        citations = parsed["citations"]
        ids = [source["citation_id"] for source in citations]
        if len(ids) != len(set(ids)) or set(ids) != set(allowed): raise GenerationError("CITATION_COVERAGE")
        if any(source != allowed[source["citation_id"]] for source in citations): raise GenerationError("CITATION_METADATA_CHANGED")
        for field, identifier in (("analysis_summary", "claim_id"), ("check_recommendations", "check_id")):
            expected = {item[identifier]: item for item in catalog[field]}
            actual_ids = [item[identifier] for item in parsed[field]]
            if len(actual_ids) != len(set(actual_ids)) or set(actual_ids) != set(expected):
                raise GenerationError("CLAIM_COVERAGE")
            if any(item != expected[item[identifier]] for item in parsed[field]): raise GenerationError("UNSUPPORTED_GENERATED_CLAIM")
        if parsed["human_confirmation"] != catalog["human_confirmation"]: raise GenerationError("HUMAN_CONFIRMATION_CHANGED")
        if parsed["answer"] != render_answer(parsed["analysis_summary"], parsed["check_recommendations"], parsed["human_confirmation"]):
            raise GenerationError("ANSWER_CITATION_MISMATCH")
        result = strict_json(previous)
        # Authoritative citations are copied from the bound hit catalog, not the model echo.
        safe = copy.deepcopy(parsed)
        safe["citations"] = [copy.deepcopy(allowed[key]) for key in ids]
        result["generation"] = {"schema_version": "1.0", "model": "deepseek-flash", "request_id": request_id, **safe}
        validate_schema(result["generation"], FINAL_GENERATION_SCHEMA)
        result["code"] = "SUPPORTED_GENERATION"
        result["trace"] += ["deepseek_synthesis", "validate_generation_schema", "validate_citation_coverage"]
        return {"state": "end", "result": json.dumps(result, ensure_ascii=False, allow_nan=False)}
    except GenerationError as exc:
        reason = str(exc)
        evidence = reason in {"UNVERIFIED_GENERATION_INPUT", "VERIFIED_HIT_NOT_AVAILABLE", "VERIFIED_HIT_CHANGED",
                              "MISSING_GENERATION_REQUEST_ID",
                              "CITATION_COVERAGE", "CITATION_METADATA_CHANGED", "CLAIM_COVERAGE",
                              "UNSUPPORTED_GENERATED_CLAIM", "UNAUTHORIZED_REASONING_CITATION",
                              "ANSWER_CITATION_MISMATCH", "HUMAN_CONFIRMATION_CHANGED"}
        return generation_failure(previous, reason, "evidence" if evidence else "system")
    except (KeyError, ValueError, TypeError, AttributeError, RecursionError):
        return generation_failure(previous, "GENERATION_INVALID_OUTPUT")
