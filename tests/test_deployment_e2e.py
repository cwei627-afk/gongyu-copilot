"""Compose-network checks for the API and existing, bounded analysis assets.

Knowledge candidates and review labels are fixtures. These tests do not claim to
exercise a live Dify retrieval or a natural-language answer generator.
"""
import json
import os
from pathlib import Path

import httpx
import pytest

from app.analysis.run_demo import run as run_analysis
from app.analysis.workflow_nodes import controlled_fixture_hit
from app.evidence.gate import evaluate

BASE_URL = os.environ.get("API_BASE_URL", "").rstrip("/")
pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DEPLOYMENT_E2E") != "1" or not BASE_URL,
    reason="仅由 Docker Compose e2e profile 设置部署测试环境",
)
ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "assets/analysis_demo/knowledge_manifest.json").read_text(encoding="utf-8"))
CORPUS = json.loads((ROOT / "assets/rag_demo/corpus.json").read_text(encoding="utf-8"))
QUESTIONS = json.loads((ROOT / "assets/rag_demo/questions.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=5) as value:
        yield value


def get_api(path):
    response = httpx.get(BASE_URL + path, timeout=5)
    return response.status_code, response.text


def gate_scenario(scenario_id):
    scenario = next(item for item in QUESTIONS if item["id"] == scenario_id)
    return evaluate(CORPUS, scenario["request"])


def test_compose_health_and_normal_mes_query(client):
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "backends": {"mes": "ok", "erp": "ok", "wms": "ok"}}

    response = client.get("/api/mes/heats/H001")
    assert response.status_code == 200
    assert response.json()["heat_id"] == "H001"


def test_heat_not_found_stops_before_context_and_retrieval():
    calls = []

    def get(path):
        calls.append(path)
        return get_api(path)

    def retrieve(_query):
        pytest.fail("unknown heat must not reach knowledge retrieval")

    result = run_analysis("UNKNOWN", "all", get, retrieve, MANIFEST)
    assert result["status"] == "data_error"
    assert result["code"] == "OBJECT_NOT_FOUND"
    assert result["process_anomaly_confirmed"] is None
    assert len(calls) == 1 and "/analysis-context" not in calls[0]


def test_missing_data_is_data_error_not_process_anomaly():
    result = run_analysis("DEMO-MISSING", "all", get_api, lambda _query: [], MANIFEST)
    assert result["status"] == "data_error"
    assert result["code"] in {"MISSING_FIELDS", "INVALID_DATA"}
    assert result["process_anomaly_confirmed"] is None


@pytest.mark.parametrize(
    "failure,expected",
    [
        (lambda _path: (500, '{"error":{"category":"system","code":"UPSTREAM_ERROR"}}'), "UPSTREAM_FAILURE"),
        (lambda _path: (_ for _ in ()).throw(TimeoutError()), "TRANSPORT_FAILURE"),
    ],
    ids=["upstream-500", "timeout"],
)
def test_upstream_failure_never_becomes_process_anomaly(failure, expected):
    result = run_analysis("DEMO-HIGH-TEMP", "all", failure, lambda _query: [], MANIFEST)
    assert result["status"] == "system_error"
    assert result["code"] == expected
    assert result["process_anomaly_confirmed"] is None
    assert result["anomaly_facts"] == []


def test_reviewed_direct_knowledge_evidence_is_supported():
    result = gate_scenario("Q01")
    assert result.decision == "supported"
    assert result.reason_codes == ["DIRECT_EVIDENCE"]
    assert result.evidence[0].document_name
    assert result.evidence[0].version
    assert result.evidence[0].quote
    assert result.production_conclusion is None


@pytest.mark.parametrize("scenario_id", ["Q02", "Q03"], ids=["related-only", "no-evidence"])
def test_insufficient_knowledge_evidence_abstains(scenario_id):
    result = gate_scenario(scenario_id)
    assert result.decision == "abstain"
    assert result.evidence == []
    assert result.production_conclusion is None
    assert result.human_confirmation_required is True


def test_process_anomaly_with_current_sop_requires_human_review():
    result = run_analysis(
        "DEMO-HIGH-TEMP", "all", get_api,
        lambda _query: [controlled_fixture_hit(doc) for doc in MANIFEST["documents"]], MANIFEST,
    )
    assert result["status"] == "review_required"
    assert result["process_anomaly_confirmed"] is True
    assert result["anomaly_facts"]
    assert result["business_rules"] and result["data_used"]
    assert result["suggested_checks"]
    assert result["sources"][0]["document_name"] and result["sources"][0]["version"]
    assert result["human_confirmation"]
    assert result["automatic_actions"] == []


def test_process_anomaly_without_current_sop_evidence_abstains():
    result = run_analysis("DEMO-HIGH-TEMP", "all", get_api, lambda _query: [], MANIFEST)
    assert result["status"] == "abstain"
    assert result["process_anomaly_confirmed"] is True
    assert result["code"] == "INSUFFICIENT_EVIDENCE"
    assert result["suggested_checks"] == [] and result["sources"] == []
    assert result["human_confirmation"]


def test_no_effective_process_rule_prevents_anomaly_and_retrieval():
    def forbidden_retrieval(_query):
        pytest.fail("without a current MES rule no process anomaly may be asserted")

    result = run_analysis("DEMO-NO-RULE", "all", get_api, forbidden_retrieval, MANIFEST)
    assert result["status"] == "data_error" and result["code"] == "RULE_NOT_FOUND"
    assert result["process_anomaly_confirmed"] is None
