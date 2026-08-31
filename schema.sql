CREATE TABLE IF NOT EXISTS drugs (
    id SERIAL PRIMARY KEY,

    drug_name TEXT NOT NULL,

    generic_name TEXT,

    dosage_form TEXT,

    ndc_code TEXT
);

CREATE INDEX IF NOT EXISTS idx_drugs_name
ON drugs (drug_name);

CREATE INDEX IF NOT EXISTS idx_drugs_generic_name
ON drugs (generic_name);


CREATE TABLE IF NOT EXISTS review_queue (
    id SERIAL PRIMARY KEY,

    raw_ocr_text TEXT NOT NULL,

    top_matches JSONB,

    ocr_confidence FLOAT,

    status TEXT DEFAULT 'pending',

    pharmacist_note TEXT,

    created_at TIMESTAMP DEFAULT NOW()
);
