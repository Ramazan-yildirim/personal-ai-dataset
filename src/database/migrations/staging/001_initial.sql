PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS fact_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    person_id INTEGER NOT NULL,
    source_id INTEGER,

    category TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,

    valid_from TEXT,
    valid_to TEXT,
    visibility TEXT NOT NULL DEFAULT 'public',
    confidence,
    allow_overlap INTEGER NOT NULL DEFAULT 0
        CHECK (allow_overlap IN (0, 1)),

    review_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (review_status IN ('pending', 'approved', 'rejected')),

    validation_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (validation_status IN ('pending', 'valid', 'invalid')),

    validation_report TEXT NOT NULL DEFAULT '[]',
    approved_fact_id INTEGER,
    review_note TEXT,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_candidates_review_status
ON fact_candidates(review_status);

CREATE INDEX IF NOT EXISTS idx_candidates_validation_status
ON fact_candidates(validation_status);

CREATE INDEX IF NOT EXISTS idx_candidates_person
ON fact_candidates(person_id);

CREATE INDEX IF NOT EXISTS idx_candidates_source
ON fact_candidates(source_id);
