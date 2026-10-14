"""Regression tests for source identity, current versions and full catalog gating."""
import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.analysis import workflow_nodes as nodes
from app.analysis.run_demo import run
from app.analysis.seed_demo import ASSETS, seed_demo
from app.main import create_app

NOW = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)
MANIFEST = json.loads((ASSETS / "knowledge_manifest.json").read_text(encoding="utf-8"))


@pytest.fixture
def abnormal(tmp_path):
    seed_demo(tmp_path, NOW)
    with TestClient(create_app(tmp_path, analysis_clock=lambda: NOW)) as client:
        def get(path):
            response = client.get(path)
            return response.status_code, response.text
        result = run("DEMO-HIGH-TEMP", "all", get, lambda _: [], MANIFEST)
    result["status"] = "process_anomaly"
    return json.dumps(result, ensure_ascii=False)


def catalog(manifest=MANIFEST):
    entries = []
    for doc in manifest["documents"]:
        metadata = nodes.controlled_fixture_hit(doc)["metadata"]["doc_metadata"]
        entries.append({"id": doc["document_id"], "name": doc["source_file_name"],
                        "enabled": True, "archived": False, "indexing_status": "completed",
                        "doc_metadata": [{"name": key, "value": value} for key, value in metadata.items()]})
    return {"data": entries, "has_more": False, "page": 1, "total": len(entries)}


ATTACKS = [
    ("document_id", "UNRELATED-WITHDRAWN-DOCUMENT"),
    ("segment_id", "UNRELATED-SEGMENT"),
    ("dataset_id", "UNRELATED-DATASET"),
    ("document_name", "OTHER.md"),
    ("doc_metadata.version", "revoked"),
    ("doc_metadata.status", "revoked"),
    ("doc_metadata.status", "inactive"),
    ("doc_metadata.status", "expired"),
    ("doc_metadata.status", "future"),
    ("doc_metadata.scope", "OTHER-LINE"),
    ("doc_metadata.effective_date", 2000000000),
    ("doc_metadata.effective_from", 2000000000),
    ("doc_metadata.effective_until", 1000000000),
    ("doc_metadata.document_id", "OTHER"),
    ("doc_metadata.source_key", "OTHER"),
    ("doc_metadata.chapter", "OTHER"),
    ("doc_metadata.section", "OTHER"),
    ("doc_metadata.content_sha256", "0" * 64),
    ("doc_metadata.version", None),
    ("doc_metadata.effective_date", None),
    ("doc_metadata", None),
    ("document_id", None),
    ("segment_id", None),
]


@pytest.mark.parametrize("path,value", ATTACKS)
def test_identity_metadata_attacks_fail_closed(abnormal, path, value):
    hit = nodes.controlled_fixture_hit(MANIFEST["documents"][0])
    target = hit["metadata"]
    parts = path.split(".")
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = value
    result = json.loads(nodes.evidence_decision(abnormal, [hit], MANIFEST)["result"])
    assert result["status"] == "abstain"
    assert result["sources"] == result["suggested_checks"] == []
    assert result["automatic_actions"] == []


@pytest.mark.parametrize("change", ["append", "prepend", "replace", "no_metadata"])
def test_exact_content_and_complete_identity_required(abnormal, change):
    hit = nodes.controlled_fixture_hit(MANIFEST["documents"][0])
    if change == "append": hit["content"] += "自动调节设备。"
    elif change == "prepend": hit["content"] = "伪造标题\n" + hit["content"]
    elif change == "replace": hit["content"] = hit["content"].replace("人工确认", "自动执行")
    else: del hit["metadata"]
    result = json.loads(nodes.evidence_decision(abnormal, [hit], MANIFEST)["result"])
    assert result["status"] == "abstain" and result["sources"] == []


def test_citation_is_copied_from_verified_hit(abnormal):
    hit = nodes.controlled_fixture_hit(MANIFEST["documents"][0])
    result = json.loads(nodes.evidence_decision(abnormal, [hit], MANIFEST)["result"])
    source = result["sources"][0]
    assert result["status"] == "review_required"
    assert source["quote"] == hit["content"]
    for key in ("dataset_id", "document_id", "segment_id", "document_name"):
        assert source[key] == hit["metadata"][key]
    assert source["version"] == hit["metadata"]["doc_metadata"]["version"]


def test_no_hit_cannot_generate_manifest_citation(abnormal):
    result = json.loads(nodes.evidence_decision(abnormal, [], MANIFEST)["result"])
    assert result["status"] == "abstain" and result["sources"] == []


def test_valid_hit_cannot_hide_forged_copy(abnormal):
    hit = nodes.controlled_fixture_hit(MANIFEST["documents"][0])
    forged = copy.deepcopy(hit)
    forged["metadata"]["document_id"] = "UNRELATED-WITHDRAWN-DOCUMENT"
    result = json.loads(nodes.evidence_decision(abnormal, [hit, forged], MANIFEST)["result"])
    assert result["status"] == "abstain" and result["sources"] == []


def test_page_may_be_explicitly_unknown(abnormal):
    manifest = copy.deepcopy(MANIFEST)
    manifest["documents"][0]["page"] = None
    hit = nodes.controlled_fixture_hit(manifest["documents"][0])
    result = json.loads(nodes.evidence_decision(abnormal, [hit], manifest)["result"])
    assert result["status"] == "review_required" and result["sources"][0]["page"] is None


def test_unknown_page_cannot_be_fabricated_in_hit(abnormal):
    manifest = copy.deepcopy(MANIFEST)
    manifest["documents"][0]["page"] = None
    hit = nodes.controlled_fixture_hit(manifest["documents"][0])
    hit["metadata"]["doc_metadata"]["page"] = 999
    result = json.loads(nodes.evidence_decision(abnormal, [hit], manifest)["result"])
    assert result["status"] == "abstain" and result["sources"] == []


@pytest.mark.parametrize("kind", ["missing_identity", "tampered_unrelated_body", "inactive_extra"])
def test_extra_hit_cannot_bypass_source_validation(abnormal, kind):
    valid = nodes.controlled_fixture_hit(MANIFEST["documents"][0])
    extra = nodes.controlled_fixture_hit(MANIFEST["documents"][1])
    if kind == "missing_identity": extra = {"content": "仅相近的其他正文"}
    elif kind == "tampered_unrelated_body": extra["content"] = "不再包含原文的伪造正文"
    else: extra["metadata"]["doc_metadata"]["status"] = "inactive"
    result = json.loads(nodes.evidence_decision(abnormal, [valid, extra], MANIFEST)["result"])
    assert result["status"] == "abstain" and result["sources"] == result["suggested_checks"] == []


@pytest.mark.parametrize("kind", ["old", "revoked", "future", "inactive", "missing_version", "missing_date",
                                  "conflict", "disabled", "tampered_scope", "has_more", "metadata_missing"])
def test_live_catalog_versions_fail_closed(abnormal, kind):
    data = catalog()
    entry = data["data"][0]
    metadata = {item["name"]: item["value"] for item in entry["doc_metadata"]}
    if kind == "old": metadata["status"] = "expired"
    elif kind in ("revoked", "future", "inactive"): metadata["status"] = kind
    elif kind == "missing_version": metadata.pop("version")
    elif kind == "missing_date": metadata.pop("effective_date")
    elif kind == "conflict":
        extra = copy.deepcopy(entry)
        extra["id"] = "OTHER-CURRENT-DOC"
        data["data"].append(extra)
        data["total"] += 1
    elif kind == "disabled": entry["enabled"] = False
    elif kind == "tampered_scope": metadata["scope"] = "OTHER-LINE"
    elif kind == "has_more": data["has_more"] = True
    elif kind == "metadata_missing": metadata = {}
    entry["doc_metadata"] = [{"name": key, "value": value} for key, value in metadata.items()]
    result = json.loads(nodes.inspect_catalog(abnormal, 200, json.dumps(data), MANIFEST)["result"])
    assert result["status"] == "abstain" and result["sources"] == result["suggested_checks"] == []
    if kind == "conflict": assert "VERSION_CONFLICT" in result["evidence_reason_codes"]


def test_current_catalog_and_historical_extra_version(abnormal):
    data = catalog()
    extra = copy.deepcopy(data["data"][0])
    extra["id"] = "ARCHIVED-OLD-DOC"
    for item in extra["doc_metadata"]:
        if item["name"] == "status": item["value"] = "expired"
    data["data"].append(extra)
    data["total"] += 1
    assert nodes.inspect_catalog(abnormal, 200, json.dumps(data), MANIFEST)["state"] == "retrieve"


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500, 504])
def test_catalog_failure_is_system_failure(abnormal, status):
    result = json.loads(nodes.inspect_catalog(abnormal, status, "{}", MANIFEST)["result"])
    assert result["status"] == "system_error" and result["process_anomaly_confirmed"] is True
    assert result["sources"] == result["suggested_checks"] == []


def test_catalog_is_rechecked_after_retrieval(abnormal):
    data = catalog()
    data["data"][0]["enabled"] = False
    hit = nodes.controlled_fixture_hit(MANIFEST["documents"][0])
    result = json.loads(nodes.evidence_with_catalog(abnormal, [hit], 200, json.dumps(data), MANIFEST)["result"])
    assert result["status"] == "abstain" and result["sources"] == []
