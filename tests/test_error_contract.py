import sqlite3
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from app.errors import UpstreamServiceError
from app.init_db import initialize
from app.main import create_app
from app.routers import erp, mes, wms
from app.schemas import ErrorResponse

# One matrix exercises the same contract on every existing business endpoint.
ROUTES = [
    (mes, "/api/mes/heats/{id}", "H001", "H002", "heat_id", "steel_grade"),
    (mes, "/api/mes/heats/{id}/temperature", "H001", "H002", "heat_id", "temperature_c"),
    (mes, "/api/mes/heats/{id}/chemistry", "H001", "H002", "heat_id", "carbon_pct"),
    (erp, "/api/erp/material-requests/{id}", "MR001", "MR002", "request_id", "quantity"),
    (wms, "/api/wms/inventory/{id}", "MAT001", "MAT002", "material_code", "quantity"),
]


@pytest.fixture
def client(tmp_path):
    initialize(tmp_path)
    # Exercise the real 500 response instead of re-raising the application exception.
    with TestClient(create_app(tmp_path), raise_server_exceptions=False) as client:
        yield client


def assert_error(response, status, category, code, fields=()):
    assert response.status_code == status, response.text
    assert response.headers["content-type"] == "application/json"
    payload = response.json()
    ErrorResponse.model_validate(payload)
    assert set(payload) == {"error"}
    assert set(payload["error"]) == {"category", "code", "message", "fields"}
    assert payload["error"]["category"] == category
    assert payload["error"]["code"] == code
    assert payload["error"]["fields"] == list(fields)
    assert payload["error"]["message"]
    assert "secret-diagnostic" not in response.text


@pytest.mark.parametrize("route", ROUTES)
def test_normal_facts(client, route):
    _, path, good_id, _, id_field, _ = route
    response = client.get(path.format(id=good_id))
    assert response.status_code == 200
    assert response.json()[id_field] == good_id
    assert "error" not in response.json()


@pytest.mark.parametrize("route", ROUTES)
def test_object_absent(client, route):
    assert_error(client.get(route[1].format(id="NOT-IN-SYSTEM")),
                 404, "data", "OBJECT_NOT_FOUND")


@pytest.mark.parametrize("route", ROUTES)
def test_null_fields_are_unavailable_data(client, route):
    _, path, _, missing_id, _, field = route
    assert_error(client.get(path.format(id=missing_id)),
                 409, "data", "MISSING_FIELDS", [field])


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("invalid_id", [" ", "H 001", "H\t001", "H\x00001", "X" * 129])
def test_invalid_parameters_do_not_query_backend(client, monkeypatch, route, invalid_id):
    module, path, _, _, id_field, _ = route

    def forbidden_query(*args, **kwargs):
        pytest.fail("Invalid parameters must be rejected before accessing the backend")

    monkeypatch.setattr(module, "connect", forbidden_query)
    assert_error(client.get(path.format(id=quote(invalid_id, safe=""))),
                 422, "request", "INVALID_PARAMETER", [f"path.{id_field}"])


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("exception,status,code", [
    (UpstreamServiceError("HTTP 500: secret-diagnostic"), 502, "UPSTREAM_ERROR"),
    (TimeoutError("secret-diagnostic"), 504, "UPSTREAM_TIMEOUT"),
    (sqlite3.OperationalError("secret-diagnostic"), 503, "BACKEND_UNAVAILABLE"),
    (RuntimeError("secret-diagnostic"), 500, "INTERNAL_ERROR"),
])
def test_system_failures_never_claim_absence(client, monkeypatch, route, exception, status, code):
    def fail(*args, **kwargs):
        raise exception

    monkeypatch.setattr(route[0], "connect", fail)
    # Even an unknown ID cannot be declared absent if the source system failed.
    assert_error(client.get(route[1].format(id="UNKNOWN")), status, "system", code)


@pytest.mark.parametrize("measurement", ["temperature", "chemistry"])
def test_no_measurement_is_not_missing_heat(client, measurement):
    assert client.get("/api/mes/heats/H003").status_code == 200
    assert_error(client.get(f"/api/mes/heats/H003/{measurement}"),
                 409, "data", "MEASUREMENT_MISSING")


@pytest.mark.parametrize("value,code", [
    ("", "MISSING_FIELDS"), ("  ", "MISSING_FIELDS"),
    ("not-a-number", "INVALID_DATA"), ("NaN", "INVALID_DATA"),
    (float("inf"), "INVALID_DATA"), (float("-inf"), "INVALID_DATA"),
])
@pytest.mark.parametrize("system,table,key,object_id,field,path", [
    ("mes", "temperatures", "heat_id", "H001", "temperature_c", "/api/mes/heats/H001/temperature"),
    ("mes", "chemistry", "heat_id", "H001", "carbon_pct", "/api/mes/heats/H001/chemistry"),
    ("erp", "material_requests", "request_id", "MR001", "quantity", "/api/erp/material-requests/MR001"),
    ("wms", "inventory", "material_code", "MAT001", "quantity", "/api/wms/inventory/MAT001"),
])
def test_unusable_numeric_data(client, tmp_path, value, code,
                             system, table, key, object_id, field, path):
    connection = sqlite3.connect(tmp_path / f"{system}.db")
    try:
        with connection:
            connection.execute(f"UPDATE {table} SET {field} = ? WHERE {key} = ?", (value, object_id))
    finally:
        connection.close()
    assert_error(client.get(path), 409, "data", code, [field])


@pytest.mark.parametrize("path", ["/not-a-route", "/api/mes/heats/", "/api/mes/heats/H001/unknown"])
def test_route_absent_does_not_mean_object_absent(client, path):
    assert_error(client.get(path), 404, "request", "ROUTE_NOT_FOUND")


def test_unsupported_method(client):
    response = client.post("/api/mes/heats/H001")
    assert_error(response, 405, "request", "METHOD_NOT_ALLOWED")
    assert "GET" in response.headers["allow"]


def test_openapi_error_models_match_runtime(client):
    spec = client.get("/openapi.json").json()
    assert len(spec["paths"]) == 10
    for path in spec["paths"].values():
        for status in (404, 409, 422, 500, 502, 503, 504):
            response = path["get"]["responses"].get(str(status))
            if response is None:
                continue
            schema = response["content"]["application/json"]["schema"]
            assert schema["$ref"] == "#/components/schemas/ErrorResponse"
