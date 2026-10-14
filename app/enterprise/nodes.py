"""Stage C deterministic facts and a wrapper around frozen Stage B validation.

The marked imports are replaced with the exact frozen A/B sources in Dify Code.
API facts are separate from document citations. Hashes are integrity checks, not
signatures or protection from an administrator changing the source systems.
"""
import copy
import hashlib
import json
from urllib.parse import quote

# EMBED_IMPORTS_BEGIN
from app.analysis.workflow_nodes import packet, timestamp, finite_number
from app.analysis.generation_nodes import (GENERATION_SCHEMA, CLAIM_SCHEMA, object_schema,
    strict_json, parse_model_text, validate_schema, generation_catalog,
    validate_generation, generation_failure, GenerationError, stable_id)
# EMBED_IMPORTS_END

ENTERPRISE_MODEL_SCHEMA = object_schema({
    "mes_report": GENERATION_SCHEMA,
    "enterprise_summary": {"type": "array", "items": CLAIM_SCHEMA, "minItems": 1, "maxItems": 8},
})

ENTITY_FIELDS = {
    "MES": {"heat_id", "production_order_id", "steel_grade", "material_code", "batch_id", "source_updated_at", "revision",
            "expected_erp_revision", "expected_wms_revision"},
    "ERP": {"production_order_id", "heat_ids", "steel_grade", "planned_quantity", "completed_quantity", "quantity_unit",
            "due_date", "status", "material_code", "batch_id", "required_quantity", "material_unit", "source_updated_at", "revision"},
    "WMS": {"batch_id", "material_code", "material_name", "production_order_id", "available_quantity", "unit",
            "warehouse", "location", "status", "source_updated_at", "revision"},
}


class EnterpriseError(ValueError):
    def __init__(self, code, category="data"):
        super().__init__(code)
        self.category = category


def enterprise_digest(value):
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def enterprise_packet(result, state="end"):
    output = {"state": state, "result": json.dumps(result, ensure_ascii=False, allow_nan=False)}
    link = result.get("enterprise_evidence", {}).get("mes", {}).get("facts", {}).get("task_link") or {}
    output.update(order_encoded=quote(link.get("production_order_id", ""), safe=""),
                  batch_encoded=quote(link.get("batch_id", ""), safe=""))
    return output


def enterprise_stamp(result):
    bundle = result["enterprise_evidence"]
    bundle.pop("integrity_sha256", None)
    bundle["integrity_sha256"] = enterprise_digest(bundle)
    result["data_sources"] = [copy.deepcopy(p) for key in ("mes", "erp", "wms") for p in bundle[key]["provenance"]]


def enterprise_stop(result, system, code, category="data", critical=False):
    result.update(status="abstain" if category == "evidence" else category+"_error", category=category, code=code,
                  message="联合证据未完整验证；不能补全缺失订单、物料或批次，请人工确认。",
                  suggested_checks=[], sources=[], automatic_actions=[])
    result.pop("generation", None); result.pop("enterprise_generation", None)
    result["enterprise_status"] = "critical_failure" if critical else "partial_evidence"
    result["missing_sources"] = [{"system": system, "category": category, "code": code}]
    result["trace"].append("enterprise_fail_closed")
    if "enterprise_evidence" in result:
        for key in ("mes", "erp", "wms"):
            if not result["enterprise_evidence"][key]["verified"] and key.upper() != system:
                result["missing_sources"].append({"system": key.upper(), "category": "data", "code": "DEPENDENCY_NOT_VERIFIED"})
        enterprise_stamp(result)
    return enterprise_packet(result)


def enterprise_empty(entity_id=None):
    return {"verified": False, "entity_id": entity_id, "facts": {}, "provenance": []}


def enterprise_provenance(system, operation, endpoint, entity_id, request_id, body, facts):
    return {"system": system, "operation_id": operation, "endpoint": endpoint, "entity_id": entity_id,
            "request_id": request_id, "revision": facts.get("revision"),
            "source_updated_at": facts.get("source_updated_at", facts.get("snapshot_at")),
            "content_sha256": enterprise_digest(facts),
            "response_body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest()}


def enterprise_begin(previous, context_body, request_id):
    result = strict_json(previous)
    if result["status"] not in ("process_anomaly", "no_anomaly"): return enterprise_packet(result)
    try:
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
            raise EnterpriseError("MISSING_ENTERPRISE_REQUEST_ID", "system")
        context = strict_json(context_body)
        if context != result["data_used"]: raise EnterpriseError("MES_CONTEXT_CHANGED")
        heat = result["heat_id"]
        provenance = enterprise_provenance("MES", "get_mes_heat_analysis_context",
            "/api/mes/heats/"+quote(heat, safe="")+"/analysis-context", heat, request_id, context_body, context)
        result["enterprise_evidence"] = {"request_id": request_id, "heat_id": heat,
            "mes": {"verified": True, "entity_id": heat, "facts": {"analysis_context": context, "task_link": None}, "provenance": [provenance]},
            "erp": enterprise_empty(), "wms": enterprise_empty(), "rag": {"verified_hits": []}}
        result.update(data_sources=[], missing_sources=[], enterprise_status="collecting")
        enterprise_stamp(result)
        return enterprise_packet(result, "continue")
    except (KeyError, ValueError, TypeError, AttributeError):
        return enterprise_stop(result, "MES", "MES_CONTEXT_CHANGED", critical=True)


def enterprise_decode(result, system, status_code, body, request_id):
    if status_code <= 0 or status_code >= 500 or status_code in (401, 403, 429):
        raise EnterpriseError("UPSTREAM_TIMEOUT" if status_code == 504 else "UPSTREAM_FAILURE", "system")
    try:
        if not isinstance(body, str) or len(body) > 100000: raise ValueError("body")
        response = strict_json(body)
        if status_code != 200:
            error = response["error"]
            if (status_code in (404, 409) and error["category"] == "data"
                    and isinstance(error["code"], str)):
                raise EnterpriseError(error["code"])
            raise EnterpriseError("INVALID_RESPONSE", "system")
        if set(response) != {"request_id", "data", "content_sha256"}: raise ValueError("envelope")
        if response["request_id"] != request_id or result["enterprise_evidence"]["request_id"] != request_id:
            raise EnterpriseError("CROSS_REQUEST_EVIDENCE_REPLAY")
        data = response["data"]
        if not isinstance(data, dict) or set(data) != ENTITY_FIELDS[system]: raise ValueError("fields")
        if response["content_sha256"] != enterprise_digest(data): raise EnterpriseError("API_CONTENT_HASH_MISMATCH")
        if type(data["revision"]) is not int or data["revision"] < 1: raise ValueError("revision")
        for name, value in data.items():
            if name in ("revision", "expected_erp_revision", "expected_wms_revision"):
                if type(value) is not int or value < 1: raise ValueError("revision")
                continue
            if name == "heat_ids":
                if (not isinstance(value, list) or not value or len(value) != len(set(value))
                        or any(not isinstance(v, str) or not v.strip() for v in value)): raise ValueError("heat_ids")
            elif name in {"planned_quantity", "completed_quantity", "required_quantity", "available_quantity"}:
                if finite_number(value) < 0: raise ValueError("quantity")
            elif not isinstance(value, str) or not value.strip(): raise ValueError("text")
        as_of = timestamp(result["data_used"]["snapshot_at"])
        age = (as_of-timestamp(data["source_updated_at"])).total_seconds()
        # Reuse the explicit current MES rule freshness assumption, not an LLM range.
        if not 0 <= age <= result["data_used"]["rule"]["max_age_seconds"]:
            raise EnterpriseError("STALE_SOURCE_RESPONSE")
        if system == "ERP":
            timestamp(data["due_date"])
            if data["completed_quantity"] > data["planned_quantity"]: raise ValueError("progress")
        return data
    except EnterpriseError: raise
    except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
        raise EnterpriseError("INVALID_RESPONSE", "system")


def enterprise_accept(previous, system, status_code, body, request_id):
    result = strict_json(previous)
    result["trace"].append("verify_"+system.lower()+"_enterprise_facts")
    try:
        facts = enterprise_decode(result, system, status_code, body, request_id)
        heat_id = result["heat_id"]
        if system == "MES":
            if facts["heat_id"] != heat_id or facts["steel_grade"] != result["data_used"]["heat"]["steel_grade"]:
                raise EnterpriseError("CROSS_SYSTEM_IDENTITY_CONFLICT")
            bundle = result["enterprise_evidence"]
            bundle["mes"]["facts"]["task_link"] = facts
            operation, endpoint, entity_id = "get_mes_heat_enterprise_links", "/api/mes/heats/"+quote(heat_id, safe="")+"/enterprise-links", heat_id
            bundle["mes"]["provenance"].append(enterprise_provenance(system, operation, endpoint, entity_id, request_id, body, facts))
            bundle["erp"]["entity_id"] = facts["production_order_id"]
            bundle["wms"]["entity_id"] = facts["batch_id"]
        else:
            link = result["enterprise_evidence"]["mes"]["facts"]["task_link"]
            if facts["revision"] < link["expected_"+system.lower()+"_revision"]:
                raise EnterpriseError("SOURCE_REVISION_MISMATCH")
            if system == "ERP":
                if (facts["production_order_id"] != link["production_order_id"] or heat_id not in facts["heat_ids"]
                        or facts["steel_grade"] != link["steel_grade"] or facts["material_code"] != link["material_code"]
                        or facts["batch_id"] != link["batch_id"]): raise EnterpriseError("CROSS_SYSTEM_IDENTITY_CONFLICT")
                operation, endpoint, entity_id = "get_erp_production_order", "/api/erp/production-orders/"+quote(link["production_order_id"], safe=""), link["production_order_id"]
            else:
                order = result["enterprise_evidence"]["erp"]["facts"]
                if any(facts[k] != link[k] for k in ("production_order_id", "material_code", "batch_id")):
                    raise EnterpriseError("CROSS_SYSTEM_IDENTITY_CONFLICT")
                if facts["unit"] != order["material_unit"]: raise EnterpriseError("UNIT_MISMATCH")
                if facts["status"] != "available": raise EnterpriseError("BATCH_NOT_AVAILABLE")
                operation, endpoint, entity_id = "get_wms_inventory_batch", "/api/wms/batches/"+quote(link["batch_id"], safe=""), link["batch_id"]
            result["enterprise_evidence"][system.lower()] = {"verified": True, "entity_id": entity_id,
                "facts": facts, "provenance": [enterprise_provenance(system, operation, endpoint, entity_id, request_id, body, facts)]}
        enterprise_stamp(result)
        return enterprise_packet(result, "continue")
    except EnterpriseError as exc:
        return enterprise_stop(result, system, str(exc), exc.category,
                               critical=system == "MES" or str(exc) in ("CROSS_SYSTEM_IDENTITY_CONFLICT", "CROSS_REQUEST_EVIDENCE_REPLAY", "API_CONTENT_HASH_MISMATCH"))
    except (KeyError, ValueError, TypeError, AttributeError):
        return enterprise_stop(result, system, "UNVERIFIED_CROSS_SYSTEM_RELATION", critical=True)


def enterprise_joint(previous):
    result = strict_json(previous)
    bundle = result["enterprise_evidence"]
    if not all(bundle[key]["verified"] for key in ("mes", "erp", "wms")):
        return enterprise_stop(result, "ENTERPRISE", "UNVERIFIED_CROSS_SYSTEM_RELATION", critical=True)
    order, batch = bundle["erp"]["facts"], bundle["wms"]["facts"]
    result["inventory_assessment"] = {"required_quantity": order["required_quantity"],
        "available_quantity": batch["available_quantity"], "unit": batch["unit"],
        "status": "sufficient" if batch["available_quantity"] >= order["required_quantity"] else "insufficient"}
    result["enterprise_status"] = "verified"
    result["trace"].append("validate_cross_system_identity")
    enterprise_stamp(result)
    return enterprise_packet(result, "retrieve" if result["process_anomaly_confirmed"] else "facts")


def enterprise_rebuild(previous, context_body, link_body, erp_body, wms_body, request_id, attach_rag=False):
    """Re-derive from original immutable HTTP outputs, not the model or bundle hash alone."""
    result = strict_json(previous)
    # Reuse the already validated MES context; collection should not consume RAG.
    seed = copy.deepcopy(result)
    seed["status"] = "process_anomaly" if result["process_anomaly_confirmed"] else "no_anomaly"
    seed.pop("enterprise_evidence", None)
    p = enterprise_begin(json.dumps(seed), context_body, request_id)
    for system, body in (("MES", link_body), ("ERP", erp_body), ("WMS", wms_body)):
        if p["state"] != "continue": raise EnterpriseError("ENTERPRISE_BUNDLE_INVALID")
        p = enterprise_accept(p["result"], system, 200, body, request_id)
    if p["state"] != "continue": raise EnterpriseError("ENTERPRISE_BUNDLE_INVALID")
    rebuilt = strict_json(enterprise_joint(p["result"])["result"])
    expected = rebuilt["enterprise_evidence"]
    incoming = copy.deepcopy(result["enterprise_evidence"])
    if attach_rag:
        if incoming["rag"] != {"verified_hits": []}: raise EnterpriseError("ENTERPRISE_BUNDLE_INVALID")
    else:
        expected["rag"]["verified_hits"] = copy.deepcopy(result["sources"])
        expected.pop("integrity_sha256", None); expected["integrity_sha256"] = enterprise_digest(expected)
    if incoming != expected or result["inventory_assessment"] != rebuilt["inventory_assessment"]:
        raise EnterpriseError("ENTERPRISE_BUNDLE_INVALID")
    result["enterprise_evidence"]["rag"]["verified_hits"] = copy.deepcopy(result["sources"])
    enterprise_stamp(result)
    return result


def enterprise_summary(result, request_id):
    bundle = result["enterprise_evidence"]
    order, batch = bundle["erp"]["facts"], bundle["wms"]["facts"]
    inventory = result["inventory_assessment"]
    sentences = [
        f"ERP 订单 {order['production_order_id']} 明确关联炉次 {result['heat_id']}，钢种 {order['steel_grade']}，状态 {order['status']}。",
        f"ERP 计划 {order['planned_quantity']} {order['quantity_unit']}，完成 {order['completed_quantity']} {order['quantity_unit']}，交期 {order['due_date']}。",
        f"WMS 物料 {batch['material_code']}（{batch['material_name']}），批次 {batch['batch_id']}，可用 {batch['available_quantity']} {batch['unit']}，仓库 {batch['warehouse']} / 仓位 {batch['location']}。",
        f"ERP 指定需求 {inventory['required_quantity']} {inventory['unit']}，WMS 指定批次可用 {inventory['available_quantity']} {inventory['unit']}；确定性比较：{'足够' if inventory['status']=='sufficient' else '不足'}。仅为该任务该批次事实，不是工艺处置授权。",
    ]
    # API text belongs to business facts, never the document-citation namespace.
    if any("[cite:" in text for text in sentences):
        raise EnterpriseError("API_FACT_CITATION_MARKER", "evidence")
    return [{"claim_id": stable_id("api_fact_", [request_id, bundle["integrity_sha256"], text]), "text": text} for text in sentences]


def enterprise_prepare(previous, retrieval_result, context_body, link_body, erp_body, wms_body, request_id):
    result = strict_json(previous)
    if result["status"] != "review_required": return {"state": "end", "result": previous, "payload": ""}
    try:
        mes = generation_catalog(previous, retrieval_result, request_id)
        result = enterprise_rebuild(previous, context_body, link_body, erp_body, wms_body, request_id, attach_rag=True)
        payload = {"mes_report": mes, "enterprise_summary": enterprise_summary(result, request_id)}
        validate_schema(payload, ENTERPRISE_MODEL_SCHEMA)
        return {"state": "generate", "result": json.dumps(result, ensure_ascii=False), "payload": json.dumps(payload, ensure_ascii=False)}
    except EnterpriseError as exc:
        stopped = enterprise_stop(result, "ENTERPRISE", str(exc), exc.category, critical=True)
        return {"state": "end", "result": stopped["result"], "payload": ""}
    except (KeyError, ValueError, TypeError, AttributeError):
        failure = enterprise_stop(result, "ENTERPRISE", "ENTERPRISE_BUNDLE_INVALID", critical=True)
        return {"state": "end", "result": failure["result"], "payload": ""}


def enterprise_validate(previous, retrieval_result, text, structured_output, finish_reason, reasoning_content,
                        context_body, link_body, erp_body, wms_body, request_id):
    try:
        result = enterprise_rebuild(previous, context_body, link_body, erp_body, wms_body, request_id)
        parsed, tagged = parse_model_text(text) if text else (None, "")
        if structured_output is not None:
            validate_schema(structured_output, ENTERPRISE_MODEL_SCHEMA)
            if parsed is not None and parsed != structured_output: raise GenerationError("NATIVE_TEXT_MISMATCH")
            parsed = structured_output
        validate_schema(parsed, ENTERPRISE_MODEL_SCHEMA)
        validated = validate_generation(previous, retrieval_result, json.dumps(parsed["mes_report"], ensure_ascii=False),
            parsed["mes_report"], finish_reason, (reasoning_content or "")+tagged, request_id)
        checked = strict_json(validated["result"])
        if checked["status"] != "review_required": return validated
        expected = {item["claim_id"]: item for item in enterprise_summary(result, request_id)}
        actual = parsed["enterprise_summary"]
        identifiers = [item["claim_id"] for item in actual]
        if len(set(identifiers)) != len(identifiers) or set(identifiers) != set(expected):
            raise EnterpriseError("ENTERPRISE_FACT_COVERAGE", "evidence")
        if any(item != expected[item["claim_id"]] for item in actual): raise EnterpriseError("UNVERIFIED_GENERATED_API_FACT", "evidence")
        # Provenance remains authoritative Code output; model has no such field.
        checked["enterprise_generation"] = {"schema_version": "1.0", "request_id": request_id,
            "facts_summary": copy.deepcopy(actual),
            "answer": checked["generation"]["answer"]+"\n"+"\n".join(item["text"] for item in actual)}
        checked["code"] = "SUPPORTED_ENTERPRISE_GENERATION"
        checked["trace"].append("validate_enterprise_fact_coverage")
        return {"state": "end", "result": json.dumps(checked, ensure_ascii=False, allow_nan=False)}
    except EnterpriseError as exc:
        failure = enterprise_stop(strict_json(previous), "ENTERPRISE", str(exc), exc.category, critical=True)
        return {"state": failure["state"], "result": failure["result"]}
    except (GenerationError, KeyError, ValueError, TypeError, AttributeError, RecursionError):
        return generation_failure(previous, "ENTERPRISE_GENERATION_INVALID_OUTPUT")
