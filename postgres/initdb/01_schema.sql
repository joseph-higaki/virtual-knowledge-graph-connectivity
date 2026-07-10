-- Rung 0 schema: minimal Postgres slice (gene only).
-- Rung 2 extends this (disease, gene_disease_association) via ingest/load_postgres.py.
CREATE TABLE IF NOT EXISTS gene (
    id   TEXT PRIMARY KEY,
    name TEXT NOT NULL
);
