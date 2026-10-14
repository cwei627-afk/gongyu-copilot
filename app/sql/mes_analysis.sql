-- Additional MES-owned tables. Existing heats/measurements are not migrated or copied.
CREATE TABLE IF NOT EXISTS heat_process_context (
    heat_id TEXT PRIMARY KEY REFERENCES heats(heat_id),
    process_stage TEXT,
    scope TEXT,
    stage_started_at TEXT
);
CREATE TABLE IF NOT EXISTS process_rules (
    rule_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    rule_json TEXT NOT NULL
);
