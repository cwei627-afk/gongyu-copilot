"""Entirely fictional small enterprise fixtures; never overwrite existing rows."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

from app.analysis.seed_demo import seed_demo as seed_mes
from app.db import data_directory


def seed_demo(directory, now=None):
    now = now or datetime.now(timezone.utc)
    seed_mes(directory, now)
    # Two extra MES examples cover inventory quantities, not new process ranges.
    with sqlite3.connect(directory / "mes.db") as db:
        for heat_id in ("DEMO-SHORTAGE", "DEMO-ZERO"):
            if db.execute("SELECT 1 FROM heats WHERE heat_id=?", (heat_id,)).fetchone(): continue
            db.execute("INSERT INTO heats VALUES (?, 'DEMO-A', 'in_progress', ?)", (heat_id, now.isoformat()))
            db.execute("INSERT INTO temperatures VALUES (?, 1610, ?)", (heat_id, now.isoformat()))
            db.execute("INSERT INTO chemistry VALUES (?, .18, .25, .65, ?)", (heat_id, now.isoformat()))
            db.execute("INSERT INTO heat_process_context VALUES (?, 'review', 'DEMO-LINE-A', ?)",
                       (heat_id, (now-timedelta(hours=8)).isoformat()))
    tables = {"mes": ("heat_task_links", "heat_id"), "erp": ("production_orders", "production_order_id"),
              "wms": ("inventory_batches", "batch_id")}
    records = {system: [] for system in tables}
    examples = ("DEMO-NORMAL", "DEMO-HIGH-TEMP", "DEMO-HIGH-CARBON", "DEMO-BOTH", "DEMO-SHORTAGE", "DEMO-ZERO")
    for heat_id in examples:
        order_id, batch_id = "PO-"+heat_id, "BATCH-"+heat_id
        common = {"source_updated_at": now.isoformat(), "revision": 1}
        link = {"heat_id": heat_id, "production_order_id": order_id, "steel_grade": "DEMO-A",
                "material_code": "DEMO-ALLOY", "batch_id": batch_id,
                "expected_erp_revision": 1, "expected_wms_revision": 1, **common}
        order = {"production_order_id": order_id, "heat_ids": [heat_id], "steel_grade": "DEMO-A",
                 "planned_quantity": 20.0, "completed_quantity": 5.0, "quantity_unit": "t",
                 "due_date": (now+timedelta(days=1)).isoformat(), "status": "released",
                 "material_code": "DEMO-ALLOY", "batch_id": batch_id,
                 "required_quantity": 100.0, "material_unit": "kg", **common}
        batch = {"batch_id": batch_id, "material_code": "DEMO-ALLOY", "material_name": "虚构演示合金",
                 "production_order_id": order_id,
                 "available_quantity": 0.0 if heat_id == "DEMO-ZERO" else 50.0 if heat_id == "DEMO-SHORTAGE" else 150.0,
                 "unit": "kg", "warehouse": "DEMO-WH", "location": "DEMO-A01", "status": "available", **common}
        for system, values in (("mes", link), ("erp", order), ("wms", batch)):
            table, key = tables[system]
            records[system].append((values[key], json.dumps(values, ensure_ascii=False, allow_nan=False)))
    # One transaction per mock backend; fixture seeding does not overwrite rows.
    for system, (table, key) in tables.items():
        with sqlite3.connect(directory / f"{system}.db") as db:
            db.execute(f"CREATE TABLE IF NOT EXISTS {table} ({key} TEXT PRIMARY KEY, record_json TEXT NOT NULL)")
            db.executemany(f"INSERT OR IGNORE INTO {table} VALUES (?, ?)", records[system])


if __name__ == "__main__":
    seed_demo(data_directory())
    print("Fictional MES/ERP/WMS Stage C fixtures added; existing rows preserved.")
