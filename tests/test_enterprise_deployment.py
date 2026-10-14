"""Opt-in real HTTP enterprise deployment checks; no live Dify credentials."""
import os
import uuid

import httpx
import pytest

from app.enterprise.nodes import enterprise_digest

pytestmark = pytest.mark.skipif(os.environ.get("RUN_DEPLOYMENT_E2E") != "1", reason="Compose deployment profile only")
BASE = os.environ.get("API_BASE_URL", "http://localhost:18089")


@pytest.mark.parametrize("path", ["/api/mes/heats/DEMO-BOTH/enterprise-links", "/api/erp/production-orders/PO-DEMO-BOTH", "/api/wms/batches/BATCH-DEMO-BOTH"])
def test_bound_read_only_http(path):
    request_id = str(uuid.uuid4())
    response = httpx.get(BASE+path, headers={"X-Request-ID": request_id}, timeout=10)
    response.raise_for_status()
    body = response.json()
    assert body["request_id"] == request_id and body["content_sha256"] == enterprise_digest(body["data"])
    assert httpx.post(BASE+path, timeout=10).status_code == 405


@pytest.mark.parametrize("path", ["/api/mes/heats/UNKNOWN/enterprise-links", "/api/erp/production-orders/UNKNOWN", "/api/wms/batches/UNKNOWN"])
def test_http_not_found(path):
    response = httpx.get(BASE+path, timeout=10)
    assert response.status_code == 404 and response.json()["error"]["category"] == "data"


@pytest.mark.parametrize("heat,quantity", [("DEMO-HIGH-TEMP", 150), ("DEMO-SHORTAGE", 50), ("DEMO-ZERO", 0)])
def test_inventory_quantity(heat, quantity):
    response = httpx.get(BASE+"/api/wms/batches/BATCH-"+heat, timeout=10)
    assert response.status_code == 200 and response.json()["data"]["available_quantity"] == quantity


def test_new_operations_in_live_openapi():
    response = httpx.get(BASE+"/openapi.json", timeout=10)
    schema = response.json()
    assert all(path in schema["paths"] for path in ("/api/mes/heats/{heat_id}/enterprise-links", "/api/erp/production-orders/{production_order_id}", "/api/wms/batches/{batch_id}"))
