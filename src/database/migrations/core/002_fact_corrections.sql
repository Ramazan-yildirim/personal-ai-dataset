CREATE TABLE IF NOT EXISTS fact_corrections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fact_id INTEGER NOT NULL,
    changed_fields TEXT NOT NULL,
    before_values TEXT NOT NULL,
    after_values TEXT NOT NULL,
    correction_note TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (fact_id)
        REFERENCES facts(id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_fact_corrections_fact
ON fact_corrections(fact_id);
