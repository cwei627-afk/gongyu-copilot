BEGIN;
CREATE TABLE material_requests (
    request_id TEXT PRIMARY KEY,
    material_code TEXT,
    quantity REAL,
    unit TEXT,
    status TEXT,
    updated_at TEXT
);
INSERT INTO material_requests VALUES
('MR001', 'MAT001', 500.0, 'kg', 'approved', '2026-09-28T08:00:00+00:00'),
('MR002', 'MAT001', NULL, 'kg', 'pending', '2026-09-28T08:00:00+00:00');
COMMIT;
