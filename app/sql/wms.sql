BEGIN;
CREATE TABLE inventory (
    material_code TEXT PRIMARY KEY,
    material_name TEXT,
    quantity REAL,
    unit TEXT,
    updated_at TEXT
);
INSERT INTO inventory VALUES
('MAT001', '模拟合金料 A', 1200.0, 'kg', '2026-09-28T08:00:00+00:00'),
('MAT002', '模拟合金料 B', NULL, 'kg', '2026-09-28T08:00:00+00:00'),
('MAT003', '模拟合金料 C', 0.0, 'kg', '2026-09-28T08:00:00+00:00');
COMMIT;
