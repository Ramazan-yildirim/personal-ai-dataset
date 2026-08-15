PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS persons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    person_id INTEGER NOT NULL,

    category TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,

    valid_from TEXT,
    valid_to TEXT,

    visibility TEXT NOT NULL DEFAULT 'public'
        CHECK (visibility IN ('public', 'private', 'internal')),

    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'deprecated', 'deleted')),

    confidence REAL NOT NULL DEFAULT 1.0
        CHECK (confidence >= 0.0 AND confidence <= 1.0),

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (person_id)
        REFERENCES persons(id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    source_type TEXT NOT NULL,
    title TEXT NOT NULL,

    file_path TEXT,
    source_date TEXT,
    file_hash TEXT,

    is_active INTEGER NOT NULL DEFAULT 1
        CHECK (is_active IN (0, 1)),

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fact_sources (
    fact_id INTEGER NOT NULL,
    source_id INTEGER NOT NULL,

    PRIMARY KEY (fact_id, source_id),

    FOREIGN KEY (fact_id)
        REFERENCES facts(id)
        ON DELETE CASCADE,

    FOREIGN KEY (source_id)
        REFERENCES sources(id)
        ON DELETE CASCADE
);

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

CREATE INDEX IF NOT EXISTS idx_facts_person
ON facts(person_id);

CREATE INDEX IF NOT EXISTS idx_facts_category
ON facts(category);

CREATE INDEX IF NOT EXISTS idx_facts_key
ON facts(key);

CREATE INDEX IF NOT EXISTS idx_facts_dates
ON facts(valid_from, valid_to);

CREATE INDEX IF NOT EXISTS idx_facts_lookup
ON facts(person_id, category, key, status, valid_from, valid_to);

CREATE INDEX IF NOT EXISTS idx_sources_hash
ON sources(file_hash);

CREATE INDEX IF NOT EXISTS idx_fact_sources_source
ON fact_sources(source_id);

CREATE INDEX IF NOT EXISTS idx_fact_corrections_fact
ON fact_corrections(fact_id);
