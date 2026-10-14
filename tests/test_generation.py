"""Stage B regression: parser, closed schema, request-bound citations and claims."""
import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.analysis import generation_nodes as generation
from app.analysis import workflow_nodes as evidence
from app.analysis.generation_workflow import build_generation_workflow
from app.analysis.run_demo import run
from app.analysis.seed_demo import ASSETS, seed_demo
from app.main import create_app


@pytest.fixture
def verified(tmp_path):
    now = datetime(2026, 9, 30, 4, tzinfo=timezone.utc)
    manifest = json.loads((ASSETS / "knowledge_manifest.json").read_text(encoding="utf-8"))
    hits = [evidence.controlled_fixture_hit(doc) for doc in manifest["documents"]]
    seed_demo(tmp_path, now)
    with TestClient(create_app(tmp_path, analysis_clock=lambda: now)) as client:
        def get(path):
            response = client.get(path)
            return response.status_code, response.text
        result = run("DEMO-BOTH", "all", get, lambda query: hits, manifest)
    assert result["status"] == "review_required"
    previous = json.dumps(result, ensure_ascii=False)
    return previous, hits, generation.generation_catalog(previous, hits, "UNIT-REQUEST-1")


def validate(verified, output, **kwargs):
    previous, hits, _ = verified
    return json.loads(generation.validate_generation(previous, hits, output, request_id="UNIT-REQUEST-1", **kwargs)["result"])


@pytest.mark.parametrize("wrapper", ["plain", "fence", "think", "think_fence"])
def test_valid_complete_wrappers(verified, wrapper):
    text = json.dumps(verified[2], ensure_ascii=False)
    if "fence" in wrapper: text = "```json\n"+text+"\n```"
    if "think" in wrapper: text = "<think>只组织已验证事实，不补造依据。</think>"+text
    result = validate(verified, text)
    assert result["status"] == "review_required" and result["code"] == "SUPPORTED_GENERATION"
    assert result["generation"]["answer"] == verified[2]["answer"]
    assert result["sources"] == json.loads(verified[0])["sources"]
    assert "<think>" not in result["generation"]["answer"] and result["automatic_actions"] == []


def test_native_structured_output_without_text(verified):
    result = validate(verified, "", structured_output=verified[2], finish_reason="tool_calls")
    assert result["code"] == "SUPPORTED_GENERATION"


def test_safe_reordering_is_real_model_responsibility(verified):
    data = copy.deepcopy(verified[2])
    data["analysis_summary"].reverse(); data["check_recommendations"].reverse(); data["citations"].reverse()
    data["answer"] = generation.render_answer(data["analysis_summary"], data["check_recommendations"], data["human_confirmation"])
    assert validate(verified, json.dumps(data))["code"] == "SUPPORTED_GENERATION"


@pytest.mark.parametrize("kind", ["invalid_json", "trailing_text", "leading_text", "multiple_objects", "duplicate_key",
                                 "nan", "unclosed_think", "nested_think", "partial_fence", "truncated"])
def test_parser_failures_close(verified, kind):
    valid = json.dumps(verified[2])
    texts = {"invalid_json": "{bad}", "trailing_text": valid+"答案仅供参考", "leading_text": "答案如下："+valid,
             "multiple_objects": valid+valid, "duplicate_key": valid[:-1]+',"answer":"duplicate"}',
             "nan": valid.replace('"page": 1', '"page": NaN'), "unclosed_think": "<think>"+valid,
             "nested_think": "<think><think>bad</think>"+valid, "partial_fence": "```json\n"+valid,
             "truncated": valid[:-2]}
    result = validate(verified, texts[kind])
    assert result["status"] == "system_error" and "generation" not in result
    assert result["sources"] == result["suggested_checks"] == []


@pytest.mark.parametrize("kind", ["missing", "extra", "wrong_type", "null", "bool_page", "bad_hash", "empty_array"])
def test_schema_failures_close(verified, kind):
    data = copy.deepcopy(verified[2])
    if kind == "missing": del data["analysis_summary"]
    elif kind == "extra": data["automatic_action"] = "PLC write"
    elif kind == "wrong_type": data["citations"] = "not array"
    elif kind == "null": data["answer"] = None
    elif kind == "bool_page": data["citations"][0]["page"] = True
    elif kind == "bad_hash": data["citations"][0]["content_sha256"] = "invalid"
    else: data["analysis_summary"] = []
    result = validate(verified, json.dumps(data))
    assert result["status"] == "system_error" and result["sources"] == []


@pytest.mark.parametrize("field", ["citation_id", "document_id", "segment_id", "dataset_id", "document_name", "version",
                                  "effective_date", "scope", "page", "chapter", "section", "content_sha256"])
def test_citation_identity_and_metadata_are_immutable(verified, field):
    data = copy.deepcopy(verified[2])
    data["citations"][0][field] = 999 if field == "page" else "f"*64 if field == "content_sha256" else "FORGED"
    result = validate(verified, json.dumps(data))
    assert result["status"] == "abstain" and result["sources"] == result["suggested_checks"] == []


@pytest.mark.parametrize("kind", ["unhit_real_document", "old_version", "mixed_versions", "another_request",
                                 "unsupported_claim", "answer_outside_evidence", "answer_citation_mismatch", "wrong_check_source",
                                 "missing_citation", "duplicate_citation", "missing_fact", "human_removed"])
def test_generation_coverage_attacks_close(verified, kind):
    data = copy.deepcopy(verified[2])
    if kind == "unhit_real_document": data["citations"][0]["document_id"] = "HISTORICAL-REAL-ID-NOT-HIT"
    elif kind == "old_version": data["citations"][0]["version"] = "0.8"
    elif kind == "mixed_versions": data["citations"].append({**data["citations"][0], "version": "0.8"})
    elif kind == "another_request":
        prior = json.loads(verified[0]); prior["data_used"]["snapshot_at"] = "2026-09-30T04:00:01Z"
        data["citations"] = generation.generation_catalog(json.dumps(prior), verified[1], "UNIT-REQUEST-2")["citations"]
    elif kind == "unsupported_claim": data["check_recommendations"][0]["text"] += "将设备调到9999度。"
    elif kind == "answer_outside_evidence": data["answer"] += "可直接升温操作。"
    elif kind == "answer_citation_mismatch": data["answer"] = data["answer"].replace("[cite:", "[untrusted:")
    elif kind == "wrong_check_source": data["check_recommendations"][0]["citation_ids"] = [data["citations"][1]["citation_id"]]
    elif kind == "missing_citation": data["citations"].pop()
    elif kind == "duplicate_citation": data["citations"].append(data["citations"][0])
    elif kind == "missing_fact": data["analysis_summary"].pop()
    else: data["human_confirmation"] = "可自动执行"
    result = validate(verified, json.dumps(data))
    assert result["status"] == "abstain" and result["sources"] == [] and "generation" not in result


@pytest.mark.parametrize("reasoning", ["[cite:FORGED]", '{"citation_id":"FORGED"}', "cite_"+"f"*32])
def test_forged_thinking_citation_rejected(verified, reasoning):
    result = validate(verified, "<think>"+reasoning+"</think>"+json.dumps(verified[2]))
    assert result["status"] == "abstain" and result["code"] == "UNAUTHORIZED_REASONING_CITATION"


def test_known_reasoning_reference_is_not_rendered(verified):
    reasoning = "思考但不输出："+verified[2]["citations"][0]["citation_id"]
    result = validate(verified, json.dumps(verified[2]), reasoning_content=reasoning)
    assert result["code"] == "SUPPORTED_GENERATION"
    assert "思考但不输出" not in result["generation"]["answer"]


def test_reasoning_syntax_templates_are_not_trusted_citations(verified):
    reasoning = "格式是 [cite:citation_id] 或 [cite:...]，不是实际引用。"
    result = validate(verified, json.dumps(verified[2]), reasoning_content=reasoning)
    assert result["code"] == "SUPPORTED_GENERATION"
    assert "格式是" not in result["generation"]["answer"]
    forged = copy.deepcopy(verified[2]); forged["citations"][0]["citation_id"] = "citation_id"
    assert validate(verified, json.dumps(forged))["status"] == "abstain"


@pytest.mark.parametrize("reason", ["length", "content_filter", None, "error"])
def test_finish_reason_required_even_when_json_is_complete(verified, reason):
    result = validate(verified, json.dumps(verified[2]), finish_reason=reason)
    assert result["status"] == "system_error" and result["sources"] == []


def test_native_output_and_text_disagree(verified):
    native = copy.deepcopy(verified[2]); native["answer"] += "伪造"
    result = validate(verified, json.dumps(verified[2]), structured_output=native)
    assert result["status"] == "system_error" and result["code"] == "NATIVE_TEXT_MISMATCH"


def test_no_hit_model_attempt_does_not_become_supported(verified):
    previous = json.loads(verified[0]); previous.update(status="abstain", sources=[], suggested_checks=[])
    result = json.loads(generation.validate_generation(json.dumps(previous), [], json.dumps(verified[2]))["result"])
    assert result["status"] == "abstain" and result["sources"] == []
    assert generation.prepare_generation(json.dumps(previous), [])["state"] == "end"


def test_identical_snapshot_citations_are_bound_to_distinct_requests(verified):
    other = generation.generation_catalog(verified[0], verified[1], "UNIT-REQUEST-2")
    assert other["citations"] != verified[2]["citations"]
    assert validate(verified, json.dumps(other))["status"] == "abstain"


def test_missing_request_id_fails_closed(verified):
    result = json.loads(generation.validate_generation(verified[0], verified[1], json.dumps(verified[2]))["result"])
    assert result["status"] == "abstain" and result["code"] == "MISSING_GENERATION_REQUEST_ID"


def test_provider_failure_preserves_only_confirmed_facts(verified):
    result = json.loads(generation.generation_failure(verified[0])["result"])
    assert result["status"] == "system_error" and result["process_anomaly_confirmed"] is True
    assert result["anomaly_facts"] and not result["sources"] and not result["suggested_checks"]


def test_stage_b_graph_reuses_stage_a_core_and_gates_llm():
    registry = json.loads((ASSETS / "dify_source_registry.json").read_text(encoding="utf-8"))
    dsl = build_generation_workflow("formal", "http://api:8000", registry)
    nodes = {n["id"]: n["data"] for n in dsl["workflow"]["graph"]["nodes"]}
    assert nodes["deepseek"]["structured_output_enabled"] and nodes["deepseek"]["reasoning_format"] == "separated"
    assert nodes["deepseek"]["model"]["completion_params"]["thinking"] is False
    assert not any(n["type"] == "agent" for n in nodes.values())
    assert nodes["generation_validate"]["variables"][0]["value_selector"] == ["evidence", "result"]
    assert nodes["retrieval"]["metadata_filtering_mode"] == "manual"
    assert nodes["deepseek"]["error_strategy"] == "fail-branch"
    assert json.loads((ASSETS / "generation.schema.json").read_text(encoding="utf-8")) == generation.GENERATION_SCHEMA
    assert json.loads((ASSETS / "generation.result.schema.json").read_text(encoding="utf-8")) == generation.FINAL_GENERATION_SCHEMA
    from app.analysis.export_workflow import build_workflow
    original = {n["id"]: n["data"] for n in build_workflow("formal", "http://api:8000", registry)["workflow"]["graph"]["nodes"]}
    assert all(nodes[name] == value for name, value in original.items() if name != "report_end")
