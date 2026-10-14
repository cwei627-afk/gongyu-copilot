-- Synthetic fixtures, not enterprise standards or a whitelist of valid heat IDs.
BEGIN;
CREATE TABLE heats (
    heat_id TEXT PRIMARY KEY,
    steel_grade TEXT,
    status TEXT,
    updated_at TEXT
);
CREATE TABLE temperatures (
    heat_id TEXT PRIMARY KEY REFERENCES heats(heat_id),
    temperature_c REAL,
    measured_at TEXT
);
CREATE TABLE chemistry (
    heat_id TEXT PRIMARY KEY REFERENCES heats(heat_id),
    carbon_pct REAL,
    silicon_pct REAL,
    manganese_pct REAL,
    measured_at TEXT
);
INSERT INTO heats VALUES
('H001', 'DEMO-A', 'in_progress', '2026-09-28T08:00:00+00:00'),
('H002', NULL, 'in_progress', '2026-09-28T08:00:00+00:00'),
('H003', 'DEMO-A', 'in_progress', '2026-09-28T08:00:00+00:00');
INSERT INTO temperatures VALUES
('H001', 1580.0, '2026-09-28T08:00:00+00:00'),
('H002', NULL, '2026-09-28T08:00:00+00:00');
INSERT INTO chemistry VALUES
('H001', 0.18, 0.25, 0.65, '2026-09-28T08:00:00+00:00'),
('H002', NULL, 0.25, 0.65, '2026-09-28T08:00:00+00:00');
COMMIT;
