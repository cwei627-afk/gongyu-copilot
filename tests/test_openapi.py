import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.export_openapi import export_openapi
from app.init_db import initialize
from app.main import create_app
from app.schemas import ErrorResponse

OPERATIONS = [
    ("/api/mes/heats/{heat_id}", "get_mes_heat", "Heat", "MES", "H001"),
    ("/api/mes/heats/{heat_id}/temperature", "get_mes_heat_temperature", "Temperature", "MES", "H001"),
    ("/api/mes/heats/{heat_id}/chemistry", "get_mes_heat_chemistry", "Chemistry", "MES", "H001"),
    ("/api/erp/material-requests/{request_id}", "get_erp_material_request", "MaterialRequest", "ERP", "MR001"),
    ("/api/wms/inventory/{material_code}", "get_wms_inventory", "Inventory", "WMS", "MAT001"),
]


@pytest.fixture(scope="module")
def schema():
    return create_app().openapi()


@pytest.mark.parametrize("path,operation_id,model,tag,sample", OPERATIONS)
def test_operation_contract(schema, path, operation_id, model, tag, sample):
    operation = schema["paths"][path]["get"]
    assert operation["operationId"] == operation_id
    assert operation["tags"] == [tag]
    assert operation["summary"] and operation["description"]
    assert "404" in operation["description"] and "5xx" in operation["description"]
    assert "requestBody" not in operation
    parameter, = operation["parameters"]
    assert parameter["in"] == "path" and parameter["required"] is True
    assert "{" + parameter["name"] + "}" in path
    assert parameter["description"]
    assert parameter["schema"]["type"] == "string"
    assert parameter["schema"]["minLength"] == 1
    assert parameter["schema"]["maxLength"] == 128
    assert parameter["schema"]["pattern"]
    assert sample in parameter["schema"]["examples"]
    assert "enum" not in parameter["schema"]
    success = operation["responses"]["200"]
    assert success["description"] != "Successful Response"
    assert success["content"]["application/json"]["schema"]["$ref"] == f"#/components/schemas/{model}"
    for status, category in [(404, "data"), (409, "data"), (422, "request"),
                             (500, "system"), (502, "system"), (503, "system"), (504, "system")]:
        response = operation["responses"][str(status)]
        media = response["content"]["application/json"]
        assert media["schema"]["$ref"] == "#/components/schemas/ErrorResponse"
        for example in media["examples"].values():
            error = ErrorResponse.model_validate(example["value"]).error
            assert error.category == category
            assert error.code in response["description"]


def test_export_matches_live_schema_without_database_access(schema, tmp_path, monkeypatch):
    monkeypatch.setenv("MOCK_DATA_DIR", str(tmp_path / "not-created"))
    output = tmp_path / "openapi.json"
    export_openapi(output)
    assert json.loads(output.read_text(encoding="utf-8")) == schema
    committed = Path(__file__).resolve().parents[1] / "docs" / "openapi.json"
    assert json.loads(committed.read_text(encoding="utf-8")) == schema
    with TestClient(create_app()) as client:
        assert client.get("/openapi.json").json() == schema
    assert not (tmp_path / "not-created").exists()


def test_export_custom_server(tmp_path):
    output = tmp_path / "custom.json"
    export_openapi(output, "https://api.example.com/backend/")
    schema = json.loads(output.read_text(encoding="utf-8"))
    assert schema["servers"][0]["url"] == "https://api.example.com/backend"


@pytest.mark.parametrize("url", ["relative", "ftp://example.com", "https://user:secret@example.com", "http://example.com?token=x"])
def test_export_rejects_invalid_server(tmp_path, url):
    with pytest.raises(ValueError):
        export_openapi(tmp_path / "out.json", url)
    assert not (tmp_path / "out.json").exists()


def test_all_references_resolve_and_fields_are_described(schema):
    def visit(value):
        if isinstance(value, dict):
            if "$ref" in value:
                assert value["$ref"].startswith("#/")
                target = schema
                for part in value["$ref"][2:].split("/"):
                    target = target[part]
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(schema)
    for model in schema["components"]["schemas"].values():
        for field in model.get("properties", {}).values():
            assert field["description"]
    ids = [entry["get"]["operationId"] for entry in schema["paths"].values()]
    assert len(ids) == len(set(ids)) == 10


@pytest.mark.parametrize("path,operation_id,model,tag,sample", OPERATIONS)
def test_documented_errors_match_real_responses(tmp_path, schema, path, operation_id, model, tag, sample):
    initialize(tmp_path)
    with TestClient(create_app(tmp_path)) as client:
        for value, status in [(sample, 200), ("UNKNOWN", 404), ("%20", 422)]:
            url = path.replace("{heat_id}", value).replace("{request_id}", value).replace("{material_code}", value)
            response = client.get(url)
            assert response.status_code == status
            if status != 200:
                examples = schema["paths"][path]["get"]["responses"][str(status)]["content"]["application/json"]["examples"]
                assert any(response.json()["error"]["code"] == e["value"]["error"]["code"]
                           for e in examples.values())
