"""Pure standard-library Code node functions, shared by Dify DSL and local tests.

No HTTP, SQL, vector search or LLM execution lives here. The workflow supplies responses.
"""
import json
import hashlib
import math
import re
from datetime import datetime, timezone
from urllib.parse import quote

FIELDS = {"temperature": ["temperature_c"], "chemistry": ["carbon_pct", "silicon_pct", "manganese_pct"],
          "all": ["temperature_c", "carbon_pct", "silicon_pct", "manganese_pct"]}
UNITS = {"temperature_c": "°C", "carbon_pct": "%", "silicon_pct": "%", "manganese_pct": "%"}


def packet(result, state="end", query=""):
    context = result.get("data_used") if isinstance(result.get("data_used"), dict) else {}
    heat = context.get("heat") if isinstance(context.get("heat"), dict) else {}
    rule = context.get("rule") if isinstance(context.get("rule"), dict) else {}
    effective_at_epoch = 0.0
    try:
        if context.get("snapshot_at"):
            effective_at_epoch = timestamp(context["snapshot_at"]).timestamp()
    except (TypeError, ValueError, AttributeError, OverflowError):
        effective_at_epoch = 0.0
    return {
        "state": state,
        "result": json.dumps(result, ensure_ascii=False, allow_nan=False),
        "query": query,
        "heat_id_encoded": quote(result.get("heat_id", ""), safe=""),
        "scope": context.get("scope", ""),
        "steel_grade": heat.get("steel_grade", ""),
        "process_stage": context.get("process_stage", ""),
        "rule_id": rule.get("rule_id", ""),
        "effective_at_epoch": effective_at_epoch,
    }


def stop(result, category, code, message):
    result.update(status=category + "_error", category=category, code=code, message=message,
                  suggested_checks=[], sources=[])
    return packet(result)


def begin(heat_id, analysis_request):
    result = {"heat_id": heat_id if isinstance(heat_id, str) else "", "analysis_request": analysis_request,
              "status": "pending", "category": None, "code": None, "message": "",
              "process_anomaly_confirmed": None, "anomaly_facts": [], "data_used": {},
              "business_rules": [], "suggested_checks": [], "sources": [], "automatic_actions": [],
              "human_confirmation": "涉及生产处置必须由授权人员人工复核确认；本结果不控制 PLC 或设备。",
              "trace": ["validate_input"]}
    if (not isinstance(heat_id, str) or not 1 <= len(heat_id) <= 128
            or re.search(r"[\s\x00-\x1f\x7f/]", heat_id) or analysis_request not in FIELDS):
        return stop(result, "request", "INVALID_PARAMETER", "提供有效 heat_id，并选择 temperature、chemistry 或 all。")
    return packet(result, "continue")


def http_body(result, status_code, body):
    """Return parsed data or a terminal packet. Never infer facts from transport failure."""
    if status_code in (401, 403) or status_code >= 500 or status_code <= 0 or status_code == 429:
        return None, stop(result, "system", "UPSTREAM_TIMEOUT" if status_code == 504 else "UPSTREAM_FAILURE",
                          "业务系统调用失败，不能据此判断炉次存在性或工艺状态。")
    try:
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ValueError("not an object")
    except (ValueError, TypeError):
        return None, stop(result, "system", "INVALID_RESPONSE", "业务系统返回了无效响应。")
    if status_code != 200:
        error = data.get("error", {})
        valid = (status_code == 404 and error.get("category") == "data" and error.get("code") == "OBJECT_NOT_FOUND"
                 or status_code == 409 and error.get("category") == "data"
                 or status_code == 422 and error.get("category") == "request")
        if valid:
            return None, stop(result, error["category"], error.get("code", "INVALID_DATA"),
                              "源系统确认对象不存在或数据/参数不可用，停止工艺推断。")
        return None, stop(result, "system", "INVALID_RESPONSE", "未识别的接口失败语义，停止推断。")
    return data, None


def inspect_heat(previous, status_code, body):
    result = json.loads(previous)
    result["trace"].append("query_heat")
    heat, terminal = http_body(result, status_code, body)
    if terminal:
        return terminal
    if (heat.get("heat_id") != result["heat_id"]
            or any(not isinstance(heat.get(k), str) or not heat[k].strip()
                   for k in ("steel_grade", "status", "updated_at"))):
        return stop(result, "data", "INVALID_HEAT", "炉次身份或必要字段无效，停止推断。")
    result["data_used"]["initial_heat"] = heat
    return packet(result, "continue")


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone required")
    return parsed


def finite_number(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError("finite numeric value required")
    return value


def compare_context(previous, status_code, body):
    result = json.loads(previous)
    result["trace"].append("query_context_and_rule")
    context, terminal = http_body(result, status_code, body)
    if terminal:
        return terminal
    try:
        heat, rule = context["heat"], context["rule"]
        if heat != result["data_used"]["initial_heat"]:
            return stop(result, "data", "SNAPSHOT_CHANGED", "两次查询之间炉次状态发生变化，请重新查询。")
        now, start = timestamp(context["snapshot_at"]), timestamp(context["stage_started_at"])
        if not timestamp(rule["effective_from"]) <= now < timestamp(rule["effective_until"]):
            return stop(result, "data", "RULE_NOT_EFFECTIVE", "目标规则不在有效期内。")
        for key in ("scope", "process_stage"):
            if not context[key] or context[key] != rule[key]:
                return stop(result, "data", "RULE_MISMATCH", "阶段或适用范围与规则不匹配。")
        if heat["steel_grade"] != rule["steel_grade"] or heat["status"] != rule["required_status"]:
            return stop(result, "data", "RULE_MISMATCH", "钢种或状态与规则不匹配。")
        age_limit = finite_number(rule["max_age_seconds"])
        if age_limit <= 0 or start > now:
            raise ValueError("invalid freshness rule")
        if not 0 <= (now - timestamp(heat["updated_at"])).total_seconds() <= age_limit:
            return stop(result, "data", "STALE_DATA", "炉次状态时间无效或已过期。")
        values = {}
        for kind in ("temperature", "chemistry"):
            measured = context[kind]
            when = timestamp(measured["measured_at"])
            if measured["heat_id"] != heat["heat_id"]:
                return stop(result, "data", "HEAT_MISMATCH", "测量记录不属于该炉次。")
            if when < start or not 0 <= (now - when).total_seconds() <= age_limit:
                return stop(result, "data", "STALE_DATA", "测量来自前一阶段、未来或已过期。")
            for field in FIELDS[kind]:
                values[field] = finite_number(measured[field])
        # Validate every configured bound before any abnormality is emitted.
        for field in FIELDS["all"]:
            limit = rule["limits"][field]
            if (finite_number(limit["minimum"]) > finite_number(limit["maximum"])
                    or limit["unit"] != UNITS[field]):
                raise ValueError("invalid limits or units")
        if any(not rule["source"].get(k) for k in
               ("document_name", "version", "effective_date", "chapter", "section", "page")):
            raise ValueError("rule provenance missing")
    except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
        return stop(result, "data", "INVALID_CONTEXT", "实际数据或规则结构不完整/无效，停止工艺推断。")

    result["data_used"] = context
    result["business_rules"] = [rule]
    result["trace"].append("compare_effective_limits")
    for field in FIELDS[result["analysis_request"]]:
        value, limit = values[field], rule["limits"][field]
        direction = "low" if value < limit["minimum"] else "high" if value > limit["maximum"] else None
        if direction:
            result["anomaly_facts"].append({"parameter": field, "actual": value, "unit": limit["unit"],
                                            "minimum": limit["minimum"], "maximum": limit["maximum"],
                                            "direction": direction, "rule_id": rule["rule_id"]})
    result["process_anomaly_confirmed"] = bool(result["anomaly_facts"])
    if not result["anomaly_facts"]:
        result.update(status="no_anomaly", category=None, code="WITHIN_EFFECTIVE_RULE",
                      message="本次所选参数在当前有效规则范围内；仅陈述已检查参数，不代表整炉质量合格。")
        return packet(result)
    result.update(status="process_anomaly", category="process", code="RULE_VIOLATION",
                  message="已确认所选实测参数违反当前有效规则；尚未获得生产处置证据。")
    query = " ".join([heat["steel_grade"], context["scope"], context["process_stage"],
                       "异常检查项", *[a["parameter"] + " " + a["direction"] for a in result["anomaly_facts"]]])
    return packet(result, "retrieve", query)


def sha256_text(value):
    if not isinstance(value, str):
        raise ValueError("text required")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def metadata_epoch(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("metadata epoch required")
    return float(value)


def same_epoch(value, expected):
    return abs(metadata_epoch(value) - timestamp(expected).timestamp()) < 0.001


def verify_controlled_hit(hit, document):
    """Validate one Dify hit against the provisioned controlled-source registry.

    The returned citation is built only from the validated hit. Registry values are
    used as equality constraints and never copied into a citation.
    """
    required_registry = (
        "dataset_id", "document_id", "segment_id", "source_file_name", "document_name",
        "version", "effective_date", "effective_from", "effective_until", "status", "scope",
        "steel_grade", "process_stage", "rule_id", "chapter", "section", "chunk_id",
        "content", "content_sha256", "checks", "parameters", "directions",
    )
    if any(key not in document or document[key] in (None, "") for key in required_registry):
        return None, "MISSING_CONTROLLED_IDENTITY"
    if not isinstance(hit, dict) or not isinstance(hit.get("content"), str):
        return None, "MISSING_SOURCE_IDENTITY"
    metadata = hit.get("metadata")
    if not isinstance(metadata, dict) or not isinstance(metadata.get("doc_metadata"), dict):
        return None, "MISSING_SOURCE_IDENTITY"
    doc_metadata = metadata["doc_metadata"]
    required_hit = ("dataset_id", "document_id", "segment_id", "document_name")
    required_doc_metadata = (
        "document_name", "document_id", "controlled_document_name", "source_key", "version",
        "effective_date", "effective_from", "effective_until", "status", "scope", "steel_grade",
        "process_stage", "rule_id", "chapter", "section", "parameters", "directions", "content_sha256",
    )
    if any(metadata.get(key) in (None, "") for key in required_hit):
        return None, "MISSING_SOURCE_IDENTITY"
    if any(doc_metadata.get(key) in (None, "") for key in required_doc_metadata):
        return None, "MISSING_METADATA"
    if any(key in metadata and metadata[key] != doc_metadata[key]
           for key in ("version", "status", "scope", "effective_date")):
        return None, "METADATA_MISMATCH"
    if (metadata["dataset_id"] != document["dataset_id"]
            or metadata["document_id"] != document["document_id"]
            or metadata["segment_id"] != document["segment_id"]
            or metadata["document_name"] != document["source_file_name"]
            or doc_metadata["document_name"] != metadata["document_name"]
            or doc_metadata["document_id"] != metadata["document_id"]
            or doc_metadata["controlled_document_name"] != document["document_name"]
            or doc_metadata["source_key"] != document["chunk_id"]):
        return None, "SOURCE_IDENTITY_MISMATCH"
    try:
        expected_page = document.get("page")
        if (doc_metadata["version"] != document["version"]
                or doc_metadata["status"] != document["status"]
                or doc_metadata["scope"] != document["scope"]
                or doc_metadata["steel_grade"] != document["steel_grade"]
                or doc_metadata["process_stage"] != document["process_stage"]
                or doc_metadata["rule_id"] != document["rule_id"]
                or doc_metadata["chapter"] != document["chapter"]
                or doc_metadata["section"] != document["section"]
                or doc_metadata["parameters"] != ",".join(document["parameters"])
                or doc_metadata["directions"] != ",".join(document["directions"])
                or doc_metadata.get("page") != expected_page
                or not same_epoch(doc_metadata["effective_date"], document["effective_date"] + "T00:00:00+00:00")
                or not same_epoch(doc_metadata["effective_from"], document["effective_from"])
                or not same_epoch(doc_metadata["effective_until"], document["effective_until"])):
            return None, "METADATA_MISMATCH"
    except (TypeError, ValueError, AttributeError, OverflowError):
        return None, "INVALID_METADATA"
    content_hash = sha256_text(hit["content"])
    if (content_hash != document["content_sha256"]
            or doc_metadata["content_sha256"] != content_hash
            or document["content"] not in hit["content"]):
        return None, "CONTENT_HASH_MISMATCH"
    citation = {
        "dataset_id": metadata["dataset_id"],
        "document_id": metadata["document_id"],
        "segment_id": metadata["segment_id"],
        "document_name": metadata["document_name"],
        "display_name": doc_metadata["controlled_document_name"],
        "version": doc_metadata["version"],
        "effective_date": datetime.fromtimestamp(
            metadata_epoch(doc_metadata["effective_date"]), timezone.utc
        ).date().isoformat(),
        "chapter": doc_metadata["chapter"],
        "section": doc_metadata["section"],
        "page": doc_metadata.get("page"),
        "chunk_id": doc_metadata["source_key"],
        "content_sha256": content_hash,
        "quote": hit["content"],
    }
    return citation, None


def controlled_fixture_hit(document):
    """Create an explicit local-test hit; production Workflow receives Dify hits."""
    content = document["content"]
    return {
        "title": document["source_file_name"],
        "content": content,
        "metadata": {
            "dataset_id": document["dataset_id"],
            "document_id": document["document_id"],
            "segment_id": document["segment_id"],
            "document_name": document["source_file_name"],
            "doc_metadata": {
                "document_name": document["source_file_name"],
                "document_id": document["document_id"],
                "controlled_document_name": document["document_name"],
                "source_key": document["chunk_id"],
                "version": document["version"],
                "effective_date": timestamp(document["effective_date"] + "T00:00:00+00:00").timestamp(),
                "effective_from": timestamp(document["effective_from"]).timestamp(),
                "effective_until": timestamp(document["effective_until"]).timestamp(),
                "status": document["status"],
                "scope": document["scope"],
                "steel_grade": document["steel_grade"],
                "process_stage": document["process_stage"],
                "rule_id": document["rule_id"],
                "chapter": document["chapter"],
                "section": document["section"],
                "page": document.get("page"),
                "parameters": ",".join(document["parameters"]),
                "directions": ",".join(document["directions"]),
                "content_sha256": document["content_sha256"],
            },
        },
    }


def evidence_decision(previous, retrieval_result, manifest, retrieval_failed=False):
    """Finite, pre-reviewed demo checklist mapping, NOT arbitrary semantic entailment.

    Only exact controlled passages that support each confirmed deviation can pass.
    User input and retrieval score cannot supply rules, quotes or equipment commands.
    """
    result = json.loads(previous)
    result["trace"].append("retrieve_and_validate_evidence")
    if result.get("status") != "process_anomaly":
        return stop(result, "system", "INVALID_TRANSITION", "无已确认工艺异常，不得进入建议分支。")
    if retrieval_failed:
        return stop(result, "system", "RETRIEVAL_FAILED", "已确认异常事实，但知识检索失败；不能生成处置建议，请人工确认。")
    missing, sources, checks = [], [], []
    try:
        if not isinstance(retrieval_result, list):
            raise ValueError("invalid retrieval result")
        context = result["data_used"]
        as_of = timestamp(context["snapshot_at"])
        # Every returned hit must have a verifiable current source, including
        # extra hits that do not support this particular deviation.
        for hit in retrieval_result:
            metadata = hit.get("metadata", {}) if isinstance(hit, dict) else {}
            document_id = metadata.get("document_id") if isinstance(metadata, dict) else None
            registered = [d for d in manifest["documents"] if d.get("document_id") == document_id]
            if len(registered) != 1:
                missing.append("UNVERIFIED_RETRIEVAL_SOURCE")
                continue
            document = registered[0]
            citation, reason = verify_controlled_hit(hit, document)
            if reason:
                missing.append(reason)
            elif (document["status"] != "active"
                  or not timestamp(document["effective_from"]) <= as_of < timestamp(document["effective_until"])
                  or document["scope"] != context["scope"]
                  or document["steel_grade"] != context["heat"]["steel_grade"]
                  or document["process_stage"] != context["process_stage"]
                  or document["rule_id"] != context["rule"]["rule_id"]):
                missing.append("INAPPLICABLE_RETRIEVAL_SOURCE")
        for anomaly in result["anomaly_facts"]:
            relevant = [d for d in manifest["documents"]
                        if d.get("scope") == context["scope"]
                        and d.get("steel_grade") == context["heat"]["steel_grade"]
                        and d.get("process_stage") == context["process_stage"]
                        and anomaly["parameter"] in d.get("parameters", [])
                        and anomaly["direction"] in d.get("directions", [])
                        and d.get("rule_id") == anomaly["rule_id"]]
            malformed = [d for d in relevant if d.get("status") == "active"
                         and any(d.get(key) in (None, "") for key in
                                 ("version", "effective_date", "effective_from", "effective_until"))]
            if malformed:
                missing.append("MISSING_METADATA")
                continue
            matches = [d for d in relevant if d.get("status") == "active"
                       and timestamp(d["effective_from"]) <= as_of < timestamp(d["effective_until"])]
            if len(matches) != 1:
                missing.append("VERSION_CONFLICT" if len(matches) > 1 else "NO_APPLICABLE_EVIDENCE")
                continue
            doc = matches[0]
            verified = []
            rejected = []
            for hit in retrieval_result:
                citation, reason = verify_controlled_hit(hit, doc)
                if citation:
                    verified.append(citation)
                elif reason:
                    rejected.append(reason)
                    if isinstance(hit, dict):
                        metadata = hit.get("metadata") or {}
                        doc_metadata = metadata.get("doc_metadata") or {} if isinstance(metadata, dict) else {}
                        claims_source = (isinstance(metadata, dict) and (
                            metadata.get("document_id") == doc.get("document_id")
                            or isinstance(doc_metadata, dict) and doc_metadata.get("source_key") == doc.get("chunk_id")))
                        contains_passage = isinstance(hit.get("content"), str) and doc["content"] in hit["content"]
                        if claims_source or contains_passage:
                            missing.append(reason)
            if len(verified) != 1:
                missing.extend(rejected or ["NO_DIRECT_SUPPORT"])
                continue
            if not doc["checks"] or any(check not in doc["content"] for check in doc["checks"]):
                missing.append("INVALID_CHECKLIST")
                continue
            source = verified[0]
            if source not in sources:
                sources.append(source)
            for check in doc["checks"]:
                item = {"text": check, "chunk_id": source["chunk_id"], "segment_id": source["segment_id"]}
                if item not in checks:
                    checks.append(item)
    except (KeyError, TypeError, ValueError, AttributeError):
        missing.append("INVALID_EVIDENCE")
    if missing:
        result.update(status="abstain", code="INSUFFICIENT_EVIDENCE", evidence_reason_codes=sorted(set(missing)),
                      message="异常事实已确认，但正式规程证据不足。拒绝生成确定性处置建议，请人工确认。",
                      suggested_checks=[], sources=[])
        return packet(result)
    result.update(status="review_required", code="SUPPORTED_CHECKLIST",
                  message="异常事实和对应规则已核对；下列检查项摘自有效正式演示规程，须人工确认。",
                  suggested_checks=checks, sources=sources)
    result["trace"].append("compose_six_part_report")
    return packet(result)


def evidence_abstain(result, reasons):
    result.update(status="abstain", code="INSUFFICIENT_EVIDENCE",
                  evidence_reason_codes=sorted(set(reasons)),
                  message="异常事实已确认，但受控来源或当前版本不可验证；停止建议并请求人工确认。",
                  suggested_checks=[], sources=[])
    return packet(result)


def inspect_catalog(previous, status_code, body, manifest):
    """Check the whole live Dify catalog, so top-k cannot hide version conflicts."""
    result = json.loads(previous)
    result["trace"].append("validate_live_source_catalog")
    if result.get("status") != "process_anomaly":
        return stop(result, "system", "INVALID_TRANSITION", "没有确认的异常事实，停止证据流程。")
    if status_code != 200:
        return stop(result, "system", "KNOWLEDGE_CATALOG_FAILURE", "知识目录接口失败，停止建议并请求人工确认。")
    reasons = []
    try:
        catalog = json.loads(body)
        documents = catalog["data"]
        if (not isinstance(documents, list) or catalog.get("has_more") is not False
                or catalog.get("page") != 1 or catalog.get("total") != len(documents)):
            raise ValueError("incomplete catalog")
        context = result["data_used"]
        as_of = timestamp(context["snapshot_at"]).timestamp()
        current = []
        seen = set()
        controlled = {doc["document_id"]: doc for doc in manifest["documents"]}
        if len(controlled) != len(manifest["documents"]):
            raise ValueError("duplicate controlled document identity")
        for entry in documents:
            if entry["id"] in seen:
                raise ValueError("duplicate catalog identity")
            seen.add(entry["id"])
            if entry.get("enabled") is not True or entry.get("archived") is not False:
                continue
            metadata_list = entry["doc_metadata"]
            if not isinstance(metadata_list, list):
                raise ValueError("structured catalog metadata required")
            metadata = {item["name"]: item["value"] for item in metadata_list}
            if len(metadata) != len(metadata_list):
                raise ValueError("duplicate metadata")
            if metadata.get("status") in ("expired", "revoked", "inactive", "future"):
                continue
            required = ("status", "scope", "steel_grade", "process_stage", "rule_id", "version",
                        "effective_date", "effective_from", "effective_until", "parameters", "directions")
            if any(metadata.get(key) in (None, "") for key in required):
                reasons.append("MISSING_METADATA")
                continue
            if metadata["status"] != "active":
                reasons.append("INVALID_METADATA")
                continue
            start, end = metadata_epoch(metadata["effective_from"]), metadata_epoch(metadata["effective_until"])
            effective_date = metadata_epoch(metadata["effective_date"])
            if start >= end or effective_date != start:
                reasons.append("INVALID_METADATA")
                continue
            if not start <= as_of < end:
                continue
            if (metadata["scope"] != context["scope"]
                    or metadata["steel_grade"] != context["heat"]["steel_grade"]
                    or metadata["process_stage"] != context["process_stage"]
                    or metadata["rule_id"] != context["rule"]["rule_id"]):
                continue
            current.append(metadata)
            doc = controlled.get(entry["id"])
            if not doc or entry.get("indexing_status") != "completed":
                reasons.append("UNCONTROLLED_CURRENT_SOURCE")
                continue
            expected = controlled_fixture_hit(doc)["metadata"]["doc_metadata"]
            if entry.get("name") != doc["source_file_name"] or any(
                    metadata.get(key) != value for key, value in expected.items()):
                reasons.append("CATALOG_METADATA_MISMATCH")
        for anomaly in result["anomaly_facts"]:
            matches = [meta for meta in current if anomaly["parameter"] in meta["parameters"].split(",")
                       and anomaly["direction"] in meta["directions"].split(",")]
            if len(matches) != 1:
                reasons.append("VERSION_CONFLICT" if len(matches) > 1 else "NO_APPLICABLE_EVIDENCE")
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        reasons.append("INVALID_SOURCE_CATALOG")
    return evidence_abstain(result, reasons) if reasons else packet(result, "retrieve")


def evidence_with_catalog(previous, retrieval_result, status_code, body, manifest):
    catalog = inspect_catalog(previous, status_code, body, manifest)
    if catalog["state"] != "retrieve":
        return catalog
    return evidence_decision(catalog["result"], retrieval_result, manifest)


def transport_failure(previous, stage):
    result = json.loads(previous)
    result["trace"].append(stage + "_transport_failure")
    return stop(result, "system", "TRANSPORT_FAILURE", "系统调用失败，停止后续推断或建议，提示人工确认。")
