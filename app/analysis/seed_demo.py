"""Add task-06 demo records to the simulated MES, without overwriting existing rows."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.analysis.models import ProcessRule
from app.db import data_directory
from app.init_db import initialize

ASSETS = Path(__file__).resolve().parents[2] / "assets" / "analysis_demo"


def seed_demo(directory: Path, now: datetime | None = None):
    now = now or datetime.now(timezone.utc)
    initialize(directory)
    rule = ProcessRule.model_validate_json((ASSETS / "rule.json").read_text(encoding="utf-8"))
    connection = sqlite3.connect(directory / "mes.db")
    try:
        connection.executescript((Path(__file__).resolve().parents[1] / "sql" / "mes_analysis.sql").read_text(encoding="utf-8"))
        with connection:
            connection.execute("INSERT OR IGNORE INTO process_rules VALUES (?, 'published', ?)",
                               (rule.rule_id, rule.model_dump_json()))
            examples = [
                ("DEMO-NORMAL", 1580.0, 0.18, "DEMO-A", 0),
                ("DEMO-HIGH-TEMP", 1610.0, 0.18, "DEMO-A", 0),
                ("DEMO-HIGH-CARBON", 1580.0, 0.30, "DEMO-A", 0),
                ("DEMO-BOTH", 1610.0, 0.30, "DEMO-A", 0),
                ("DEMO-MISSING", None, 0.18, "DEMO-A", 0),
                ("DEMO-NO-RULE", 1580.0, 0.18, "DEMO-UNKNOWN", 0),
                ("DEMO-STALE", 1610.0, 0.18, "DEMO-A", 7),
            ]
            for heat_id, temp, carbon, grade, age in examples:
                # Treat a heat as one fixture unit: never repair/overwrite a pre-existing heat.
                if connection.execute("SELECT 1 FROM heats WHERE heat_id = ?", (heat_id,)).fetchone():
                    continue
                measured_at = (now - timedelta(hours=age)).isoformat()
                connection.execute("INSERT INTO heats VALUES (?, ?, ?, ?)",
                                   (heat_id, grade, "in_progress", now.isoformat()))
                connection.execute("INSERT INTO temperatures VALUES (?, ?, ?)", (heat_id, temp, measured_at))
                connection.execute("INSERT INTO chemistry VALUES (?, ?, ?, ?, ?)", (heat_id, carbon, 0.25, 0.65, measured_at))
                connection.execute("INSERT INTO heat_process_context VALUES (?, ?, ?, ?)",
                                   (heat_id, "review", "DEMO-LINE-A", (now - timedelta(hours=8)).isoformat()))
    finally:
        connection.close()


if __name__ == "__main__":
    seed_demo(data_directory())
    print("Task-06 MES fixtures added; existing rows preserved.")
