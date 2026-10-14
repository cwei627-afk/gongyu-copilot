"""Stage C: real Mock HTTP contracts, identity, provenance, and generated facts."""
import copy
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.analysis import workflow_nodes as mes
from app.analysis.seed_demo import ASSETS
from app.analysis.generation_workflow import build_generation_workflow
from app.enterprise import nodes as c
from app.enterprise.seed_demo import seed_demo
from app.enterprise.workflow import build_enterprise_workflow
from app.enterprise.bundle_models import EnterpriseEvidenceBundle
from app.main import create_app
from app.errors import UpstreamServiceError

NOW = datetime(2026, 9, 30, 5, tzinfo=timezone.utc)
REQUEST = "TEST-C-REQUEST-1"
MANIFEST = json.loads((ASSETS/"knowledge_manifest.json").read_text(encoding="utf-8"))


@pytest.fixture
def backend(tmp_path):
    seed_demo(tmp_path, NOW)
    with TestClient(create_app(tmp_path, analysis_clock=lambda: NOW), raise_server_exceptions=False) as client:
        yield client, tmp_path


def collect(client, heat="DEMO-HIGH-TEMP", overrides=None):
    overrides = overrides or {}
    calls, bodies = [], {}
    def get(system, path):
        calls.append(system)
        response = client.get(path, headers={"X-Request-ID": REQUEST})
        status, text = overrides.get(system, (response.status_code, response.text))
        bodies[system] = text
        return status, text
    previous = mes.begin(heat, "all")
    previous = mes.inspect_heat(previous["result"], *get("heat", "/api/mes/heats/"+heat))
    if previous["state"] == "end": return previous, bodies, calls
    previous = mes.compare_context(previous["result"], *get("context", "/api/mes/heats/"+heat+"/analysis-context"))
    previous = c.enterprise_begin(previous["result"], bodies["context"], REQUEST)
    if previous["state"] == "end": return previous, bodies, calls
    previous = c.enterprise_accept(previous["result"], "MES", *get("MES", "/api/mes/heats/"+heat+"/enterprise-links"), REQUEST)
    if previous["state"] == "end": return previous, bodies, calls
    previous = c.enterprise_accept(previous["result"], "ERP", *get("ERP", "/api/erp/production-orders/"+previous["order_encoded"]), REQUEST)
    if previous["state"] == "end": return previous, bodies, calls
    previous = c.enterprise_accept(previous["result"], "WMS", *get("WMS", "/api/wms/batches/"+previous["batch_encoded"]), REQUEST)
    if previous["state"] != "end": previous = c.enterprise_joint(previous["result"])
    return previous, bodies, calls


def change_body(text, mutate, rehash=True):
    response = json.loads(text)
    mutate(response["data"])
    if rehash: response["content_sha256"] = c.enterprise_digest(response["data"])
    return json.dumps(response)


def prepare(client, heat="DEMO-BOTH", hits=None):
    previous, bodies, _ = collect(client, heat)
    hits = hits if hits is not None else [mes.controlled_fixture_hit(doc) for doc in MANIFEST["documents"]]
    previous = mes.evidence_decision(previous["result"], hits, MANIFEST)
    prepared = c.enterprise_prepare(previous["result"], hits, bodies["context"], bodies["MES"], bodies["ERP"], bodies["WMS"], REQUEST)
    return prepared, hits, bodies


def validate(prepared, hits, bodies, data, **kwargs):
    return json.loads(c.enterprise_validate(prepared["result"], hits,
        kwargs.pop("text", json.dumps(data, ensure_ascii=False)), kwargs.pop("native", data), kwargs.pop("finish", "stop"),
        kwargs.pop("reasoning", ""), bodies["context"], bodies["MES"], bodies["ERP"], bodies["WMS"],
        kwargs.pop("request", REQUEST))["result"])


@pytest.mark.parametrize("path", ["/api/mes/heats/DEMO-BOTH/enterprise-links", "/api/erp/production-orders/PO-DEMO-BOTH", "/api/wms/batches/BATCH-DEMO-BOTH"])
def test_new_http_contract(backend, path):
    response = backend[0].get(path, headers={"X-Request-ID": REQUEST})
    assert response.status_code == 200
    body = response.json()
    assert body["request_id"] == REQUEST and body["content_sha256"] == c.enterprise_digest(body["data"])
    assert body["data"]["revision"] == 1
    assert backend[0].post(path).status_code == 405


@pytest.mark.parametrize("path", ["/api/mes/heats/UNKNOWN/enterprise-links", "/api/erp/production-orders/UNKNOWN", "/api/wms/batches/UNKNOWN", "/api/wms/inventory/UNKNOWN"])
def test_api_object_absent_is_not_zero_or_process_anomaly(backend, path):
    response = backend[0].get(path)
    assert response.status_code == 404 and response.json()["error"]["category"] == "data"


@pytest.mark.parametrize("path", ["/api/mes/heats/%20/enterprise-links", "/api/erp/production-orders/%20", "/api/wms/batches/%20"])
def test_api_invalid_id(backend, path):
    assert backend[0].get(path).status_code == 422


@pytest.mark.parametrize("system,table,key,path", [
    ("mes", "heat_task_links", "DEMO-BOTH", "/api/mes/heats/DEMO-BOTH/enterprise-links"),
    ("erp", "production_orders", "PO-DEMO-BOTH", "/api/erp/production-orders/PO-DEMO-BOTH"),
    ("wms", "inventory_batches", "BATCH-DEMO-BOTH", "/api/wms/batches/BATCH-DEMO-BOTH")])
def test_malformed_backend_records_return_data_error(backend, system, table, key, path):
    with sqlite3.connect(backend[1]/(system+".db")) as db:
        db.execute(f"UPDATE {table} SET record_json='{{bad}}'")
    response = backend[0].get(path)
    assert response.status_code == 409 and response.json()["error"]["code"] == "INVALID_DATA"


@pytest.mark.parametrize("path", ["/api/mes/heats/DEMO-BOTH/enterprise-links", "/api/erp/production-orders/PO-DEMO-BOTH", "/api/wms/batches/BATCH-DEMO-BOTH"])
@pytest.mark.parametrize("failure,status", [(TimeoutError, 504), (UpstreamServiceError, 502), (ConnectionError, 500)])
def test_backend_access_failure_is_system_error(backend, monkeypatch, path, failure, status):
    def unavailable(*args): raise failure("private backend details")
    monkeypatch.setattr("app.enterprise.api.connect", unavailable)
    response = backend[0].get(path)
    assert response.status_code == status and response.json()["error"]["category"] == "system"
    assert "private" not in response.text


@pytest.mark.parametrize("heat,inventory", [("DEMO-HIGH-TEMP", "sufficient"), ("DEMO-BOTH", "sufficient"), ("DEMO-NORMAL", "sufficient"), ("DEMO-SHORTAGE", "insufficient"), ("DEMO-ZERO", "insufficient")])
def test_joint_facts_and_quantity_without_process_invention(backend, heat, inventory):
    previous, _, calls = collect(backend[0], heat)
    result = json.loads(previous["result"])
    assert result["enterprise_status"] == "verified" and result["inventory_assessment"]["status"] == inventory
    assert len(result["data_sources"]) == 4 and {s["system"] for s in result["data_sources"]} == {"MES", "ERP", "WMS"}
    EnterpriseEvidenceBundle.model_validate_json(json.dumps(result["enterprise_evidence"]))
    assert result["sources"] == [] and result["automatic_actions"] == []
    if heat == "DEMO-NORMAL": assert result["status"] == "no_anomaly" and previous["state"] == "facts"
    assert calls == ["heat", "context", "MES", "ERP", "WMS"]


def test_unknown_heat_stops_all_downstream(backend):
    previous, _, calls = collect(backend[0], "UNKNOWN")
    assert json.loads(previous["result"])["code"] == "OBJECT_NOT_FOUND" and calls == ["heat"]


def test_missing_relation_does_not_guess(backend):
    with sqlite3.connect(backend[1]/"mes.db") as db: db.execute("DELETE FROM heat_task_links WHERE heat_id='DEMO-HIGH-TEMP'")
    previous, _, calls = collect(backend[0])
    result = json.loads(previous["result"])
    assert result["code"] == "UNVERIFIED_CROSS_SYSTEM_RELATION" and "ERP" not in calls
    assert result["enterprise_status"] == "critical_failure"


@pytest.mark.parametrize("system", ["ERP", "WMS"])
@pytest.mark.parametrize("failure", ["not_found", "timeout", "connection", "malformed", "route404", "auth", "500"])
def test_missing_and_failed_source_never_fills_facts(backend, system, failure):
    status, body = {"not_found": (404, '{"error":{"category":"data","code":"OBJECT_NOT_FOUND"}}'),
        "timeout": (504, '{}'), "connection": (0, ''), "malformed": (200, '{bad}'),
        "route404": (404, '{"error":{"category":"request","code":"ROUTE_NOT_FOUND"}}'),
        "auth": (401, '{}'), "500": (500, '{}')}[failure]
    previous, _, calls = collect(backend[0], overrides={system: (status, body)})
    result = json.loads(previous["result"])
    assert result["status"] == ("data_error" if failure == "not_found" else "system_error")
    assert result["enterprise_evidence"][system.lower()]["facts"] == {}
    assert result["sources"] == result["suggested_checks"] == [] and "generation" not in result
    assert result["process_anomaly_confirmed"] is True  # Already established by MES, never by the API failure.
    assert result["enterprise_status"] == "partial_evidence"
    if system == "ERP": assert "WMS" not in calls


@pytest.mark.parametrize("system,field", [("MES", "heat_id"), ("MES", "steel_grade"), ("ERP", "production_order_id"), ("ERP", "steel_grade"),
    ("ERP", "material_code"), ("ERP", "batch_id"), ("ERP", "heat_ids"), ("WMS", "production_order_id"), ("WMS", "material_code"), ("WMS", "batch_id")])
def test_real_entity_identity_must_match_even_with_valid_hash(backend, system, field):
    _, bodies, _ = collect(backend[0])
    changed = change_body(bodies[system], lambda d: d.update({field: ["OTHER"] if field == "heat_ids" else "OTHER"}))
    previous, _, _ = collect(backend[0], overrides={system: (200, changed)})
    result = json.loads(previous["result"])
    assert result["code"] == "CROSS_SYSTEM_IDENTITY_CONFLICT" and result["enterprise_status"] == "critical_failure"


@pytest.mark.parametrize("system", ["MES", "ERP", "WMS"])
@pytest.mark.parametrize("failure", ["stale", "future", "replay", "hash", "missing_field", "bool_revision"])
def test_provenance_and_response_integrity(backend, system, failure):
    _, bodies, _ = collect(backend[0])
    response = json.loads(bodies[system])
    if failure == "replay": response["request_id"] = "OLD-REQUEST"
    elif failure == "hash": response["data"]["revision"] = 999
    else:
        if failure == "stale": response["data"]["source_updated_at"] = "2020-01-01T00:00:00Z"
        if failure == "future": response["data"]["source_updated_at"] = "2099-01-01T00:00:00Z"
        if failure == "missing_field": response["data"].pop("revision")
        if failure == "bool_revision": response["data"]["revision"] = True
        response["content_sha256"] = c.enterprise_digest(response["data"])
    previous, _, _ = collect(backend[0], overrides={system: (200, json.dumps(response))})
    result = json.loads(previous["result"])
    assert result["status"] in ("data_error", "system_error")
    if system == "MES": assert result["enterprise_evidence"]["mes"]["facts"]["task_link"] is None
    else: assert result["enterprise_evidence"][system.lower()]["facts"] == {}
    assert result["sources"] == [] and "generation" not in result


@pytest.mark.parametrize("unit,status", [("t", "available"), ("kg", "quarantined")])
def test_wms_units_and_status_not_guessed(backend, unit, status):
    _, bodies, _ = collect(backend[0])
    body = change_body(bodies["WMS"], lambda d: d.update(unit=unit, status=status))
    previous, _, _ = collect(backend[0], overrides={"WMS": (200, body)})
    assert json.loads(previous["result"])["code"] in ("UNIT_MISMATCH", "BATCH_NOT_AVAILABLE")


@pytest.mark.parametrize("system", ["ERP", "WMS"])
def test_older_revision_than_mes_task_requirement_stops(backend, system):
    with sqlite3.connect(backend[1]/"mes.db") as db:
        row = db.execute("SELECT record_json FROM heat_task_links WHERE heat_id='DEMO-HIGH-TEMP'").fetchone()
        link = json.loads(row[0]); link["expected_"+system.lower()+"_revision"] = 2
        db.execute("UPDATE heat_task_links SET record_json=? WHERE heat_id='DEMO-HIGH-TEMP'", (json.dumps(link),))
    previous, _, _ = collect(backend[0])
    assert json.loads(previous["result"])["code"] == "SOURCE_REVISION_MISMATCH"


def test_successful_enterprise_generation_keeps_citations_separate(backend):
    prepared, hits, bodies = prepare(backend[0])
    assert prepared["state"] == "generate"
    model = json.loads(prepared["payload"])
    result = validate(prepared, hits, bodies, model)
    assert result["code"] == "SUPPORTED_ENTERPRISE_GENERATION"
    assert len(result["generation"]["citations"]) == 2
    assert all("system" not in cite for cite in result["generation"]["citations"])
    assert "WMS" in result["enterprise_generation"]["answer"] and result["automatic_actions"] == []
    EnterpriseEvidenceBundle.model_validate_json(json.dumps(result["enterprise_evidence"]))


@pytest.mark.parametrize("wrapper", ["think", "fence", "forged-think"])
def test_enterprise_structured_wrappers_keep_stage_b_guards(backend, wrapper):
    prepared, hits, bodies = prepare(backend[0])
    data = json.loads(prepared["payload"])
    text = json.dumps(data, ensure_ascii=False)
    if wrapper == "fence": text = "```json\n"+text+"\n```"
    else: text = "<think>"+("[cite:FORGED]" if wrapper == "forged-think" else "只整理已验证企业事实。")+"</think>"+text
    result = validate(prepared, hits, bodies, data, text=text, native=None)
    assert result["status"] == ("abstain" if wrapper == "forged-think" else "review_required")


@pytest.mark.parametrize("attack", ["erp_fact", "wms_fact", "timeout_fact", "extra_provenance", "fake_cite", "old_version", "unhit_doc", "metadata", "other_request", "malformed", "extra_text", "provider_truncation", "bundle_tamper", "bundle_rehash", "raw_body_tamper"])
def test_enterprise_generation_attack_regression(backend, attack):
    prepared, hits, bodies = prepare(backend[0])
    data = json.loads(prepared["payload"]); kwargs = {}
    if attack in ("erp_fact", "wms_fact", "timeout_fact"):
        data["enterprise_summary"][0]["text"] += {"erp_fact": "订单完成999吨。", "wms_fact": "库存999公斤。", "timeout_fact": "API 超时证明库存为零。"}[attack]
    elif attack == "extra_provenance": data["data_sources"] = [{"system": "ERP", "verified": True}]
    elif attack == "fake_cite": data["mes_report"]["citations"][0]["citation_id"] = "FORGED"
    elif attack == "old_version": data["mes_report"]["citations"][0]["version"] = "0.1"
    elif attack == "unhit_doc": data["mes_report"]["citations"][0]["document_id"] = "REAL-BUT-UNHIT"
    elif attack == "metadata": data["mes_report"]["citations"][0]["content_sha256"] = "a"*64
    elif attack == "other_request": kwargs["request"] = "ANOTHER-REQUEST"
    elif attack == "malformed": kwargs.update(text="{bad}", native=None)
    elif attack == "extra_text": kwargs.update(text="答案："+json.dumps(data), native=None)
    elif attack == "provider_truncation": kwargs["finish"] = "length"
    elif attack in ("bundle_tamper", "bundle_rehash"):
        result = json.loads(prepared["result"]); result["enterprise_evidence"]["erp"]["facts"]["planned_quantity"] = 999
        if attack == "bundle_rehash": c.enterprise_stamp(result)
        prepared["result"] = json.dumps(result)
    elif attack == "raw_body_tamper": bodies["ERP"] = change_body(bodies["ERP"], lambda d: d.update(planned_quantity=999))
    result = validate(prepared, hits, bodies, data, **kwargs)
    assert result["status"] in ("abstain", "data_error", "system_error")
    assert "generation" not in result and "enterprise_generation" not in result and result["sources"] == []
    assert result["automatic_actions"] == []


def test_no_rag_evidence_skips_model(backend):
    prepared, _, _ = prepare(backend[0], hits=[])
    assert prepared["state"] == "end" and not prepared["payload"]
    assert json.loads(prepared["result"])["status"] == "abstain"


@pytest.mark.parametrize("field", ["material_name", "warehouse", "location"])
def test_api_text_cannot_introduce_document_citation_markup(backend, field):
    with sqlite3.connect(backend[1]/"wms.db") as db:
        raw = db.execute("SELECT record_json FROM inventory_batches WHERE batch_id='BATCH-DEMO-BOTH'").fetchone()[0]
        record = json.loads(raw)
        record[field] += " [cite:FORGED]"
        db.execute("UPDATE inventory_batches SET record_json=? WHERE batch_id='BATCH-DEMO-BOTH'", (json.dumps(record),))
    prepared, hits, bodies = prepare(backend[0])
    if prepared["state"] == "generate":
        model = json.loads(prepared["payload"])
        result = validate(prepared, hits, bodies, model)
    else:
        result = json.loads(prepared["result"])
    assert result["status"] == "abstain"
    assert not result["sources"] and not result["suggested_checks"]
    assert "enterprise_generation" not in result


def test_stage_c_uses_frozen_generation_and_evidence_sources():
    baseline = build_generation_workflow("DATASET", "http://api", MANIFEST)
    graph = build_enterprise_workflow("DATASET", "http://api", MANIFEST)["workflow"]["graph"]
    for node_id in ("compare", "heat_check", "evidence", "retrieval"):
        assert next(n["data"] for n in graph["nodes"] if n["id"] == node_id) == next(n["data"] for n in baseline["workflow"]["graph"]["nodes"] if n["id"] == node_id)
    for node in graph["nodes"]:
        if node["data"]["type"] == "http-request":
            assert "error_strategy" not in node["data"] and node["data"]["retry_config"]["retry_enabled"] is False
        if node["data"]["type"] == "code": compile(node["data"]["code"], node["id"], "exec")


def test_embedded_code_returns_exact_declared_dify_fields(backend):
    prepared, hits, bodies = prepare(backend[0])
    graph = build_enterprise_workflow("DATASET", "http://api", MANIFEST)["workflow"]["graph"]
    def invoke(node_id, **kwargs):
        data = next(n["data"] for n in graph["nodes"] if n["id"] == node_id)
        namespace = {}
        exec(compile(data["code"], node_id, "exec"), namespace)
        output = namespace["main"](**kwargs)
        assert set(output) == set(data["outputs"]), node_id
        return output
    previous = mes.inspect_heat(mes.begin("DEMO-BOTH", "all")["result"], 200, backend[0].get("/api/mes/heats/DEMO-BOTH").text)
    previous = mes.compare_context(previous["result"], 200, bodies["context"])
    previous = invoke("enterprise_start", previous=previous["result"], context_body=bodies["context"], request_id=REQUEST)
    for key, system in (("links_check", "MES"), ("erp_check", "ERP"), ("wms_check", "WMS")):
        previous = invoke(key, previous=previous["result"], status_code=200, body=bodies[system], request_id=REQUEST)
    invoke("enterprise_joint", previous=previous["result"])
    common = dict(retrieval_result=hits, context_body=bodies["context"], link_body=bodies["MES"], erp_body=bodies["ERP"], wms_body=bodies["WMS"], request_id=REQUEST)
    before_prepare = json.loads(prepared["result"])
    before_prepare["enterprise_evidence"]["rag"] = {"verified_hits": []}; c.enterprise_stamp(before_prepare)
    new_prepared = invoke("generation_prepare", previous=json.dumps(before_prepare), **common)
    assert new_prepared["state"] == "generate"
    model = json.loads(new_prepared["payload"])
    for valid in (True, False):
        payload = copy.deepcopy(model)
        if not valid: payload["enterprise_summary"][0]["text"] += "未经证据支持的建议。"
        checked = invoke("generation_validate", previous=new_prepared["result"], text=json.dumps(payload), structured_output=payload,
                         finish_reason="stop", reasoning_content="", **common)
        assert json.loads(checked["result"])["status"] == ("review_required" if valid else "abstain")
