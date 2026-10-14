import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.init_db import initialize
from app.main import create_app


class APITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        initialize(self.directory)
        self.client = TestClient(create_app(self.directory))
        self.addCleanup(self.client.close)

    def execute(self, system, sql, parameters=()):
        connection = sqlite3.connect(self.directory / f"{system}.db")
        try:
            with connection:
                connection.execute(sql, parameters)
        finally:
            connection.close()

    def check_error(self, path, status, category, code):
        response = self.client.get(path)
        self.assertEqual(response.status_code, status, response.text)
        error = response.json()["error"]
        self.assertEqual(error["category"], category)
        self.assertEqual(error["code"], code)
        return error

    def test_all_five_success_responses(self):
        cases = [
            ("/api/mes/heats/H001", "steel_grade", "DEMO-A"),
            ("/api/mes/heats/H001/temperature", "temperature_c", 1580.0),
            ("/api/mes/heats/H001/chemistry", "carbon_pct", 0.18),
            ("/api/erp/material-requests/MR001", "quantity", 500.0),
            ("/api/wms/inventory/MAT001", "quantity", 1200.0),
        ]
        for path, field, value in cases:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()[field], value)
                self.assertNotIn("normal", response.json())

    def test_nonexistent_objects_on_all_routes(self):
        for path in ("/api/mes/heats/UNKNOWN", "/api/mes/heats/UNKNOWN/temperature",
                     "/api/mes/heats/UNKNOWN/chemistry",
                     "/api/erp/material-requests/UNKNOWN", "/api/wms/inventory/UNKNOWN"):
            with self.subTest(path=path):
                self.check_error(path, 404, "data", "OBJECT_NOT_FOUND")

    def test_missing_fields_on_all_routes(self):
        cases = [
            ("/api/mes/heats/H002", "steel_grade"),
            ("/api/mes/heats/H002/temperature", "temperature_c"),
            ("/api/mes/heats/H002/chemistry", "carbon_pct"),
            ("/api/erp/material-requests/MR002", "quantity"),
            ("/api/wms/inventory/MAT002", "quantity"),
        ]
        for path, field in cases:
            with self.subTest(path=path):
                error = self.check_error(path, 409, "data", "MISSING_FIELDS")
                self.assertEqual(error["fields"], [field])

    def test_existing_heat_without_measurements(self):
        for measurement in ("temperature", "chemistry"):
            self.check_error(f"/api/mes/heats/H003/{measurement}", 409,
                             "data", "MEASUREMENT_MISSING")

    def test_dynamic_heat_is_read_from_mes(self):
        self.execute("mes", "INSERT INTO heats VALUES (?, ?, ?, ?)",
                     ("NEW-HEAT-99", "DEMO-B", "created", "2026-09-28T09:00:00+00:00"))
        response = self.client.get("/api/mes/heats/NEW-HEAT-99")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["steel_grade"], "DEMO-B")

    def test_zero_inventory_is_valid_data(self):
        response = self.client.get("/api/wms/inventory/MAT003")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["quantity"], 0.0)

    def test_invalid_timestamp_is_data_error(self):
        self.execute("mes", "UPDATE heats SET updated_at = 'invalid' WHERE heat_id = 'H001'")
        error = self.check_error("/api/mes/heats/H001", 409, "data", "INVALID_DATA")
        self.assertEqual(error["fields"], ["updated_at"])

    def test_blank_field_is_missing(self):
        self.execute("erp", "UPDATE material_requests SET unit = '  ' WHERE request_id = 'MR001'")
        error = self.check_error("/api/erp/material-requests/MR001", 409, "data", "MISSING_FIELDS")
        self.assertEqual(error["fields"], ["unit"])

    def test_database_failures_are_system_errors(self):
        cases = [("mes", "heats", "/api/mes/heats/H001"),
                 ("erp", "material_requests", "/api/erp/material-requests/MR001"),
                 ("wms", "inventory", "/api/wms/inventory/MAT001")]
        for system, table, path in cases:
            with self.subTest(system=system):
                self.execute(system, f"DROP TABLE {table}")
                with self.assertLogs("app.main", level="ERROR"):
                    self.check_error(path, 503, "system", "BACKEND_UNAVAILABLE")

    def test_absent_database_is_not_created_by_query(self):
        empty = self.directory / "empty"
        empty.mkdir()
        with TestClient(create_app(empty)) as client:
            with self.assertLogs("app.main", level="ERROR"):
                response = client.get("/api/mes/heats/H001")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()["error"]["category"], "system")
        self.assertEqual(list(empty.iterdir()), [])

    def test_sql_input_is_not_executed(self):
        self.check_error("/api/mes/heats/'OR'1'='1", 404, "data", "OBJECT_NOT_FOUND")
        self.assertEqual(self.client.get("/api/mes/heats/H001").status_code, 200)

    def test_initialization_preserves_existing_data(self):
        self.execute("wms", "UPDATE inventory SET quantity = 42 WHERE material_code = 'MAT001'")
        self.execute("mes", "DELETE FROM temperatures WHERE heat_id = 'H001'")
        self.assertEqual(initialize(self.directory), [])
        self.assertEqual(self.client.get("/api/wms/inventory/MAT001").json()["quantity"], 42)
        self.check_error("/api/mes/heats/H001/temperature", 409, "data", "MEASUREMENT_MISSING")

    def test_openapi_exposes_existing_and_enterprise_routes_and_schemas(self):
        spec = self.client.get("/openapi.json").json()
        self.assertEqual(len(spec["paths"]), 10)
        for name in ("Heat", "Temperature", "Chemistry", "MaterialRequest", "Inventory", "ErrorResponse"):
            self.assertIn(name, spec["components"]["schemas"])

    def test_health_reports_each_mock_backend(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "status": "ok", "backends": {"mes": "ok", "erp": "ok", "wms": "ok"}
        })

    def test_health_marks_unreadable_backend_as_system_failure(self):
        client = TestClient(create_app(self.directory / "missing"))
        self.addCleanup(client.close)
        response = client.get("/health")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["category"], "system")
        self.assertEqual(response.json()["error"]["code"], "BACKEND_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
