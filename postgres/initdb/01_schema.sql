-- Rung 0 schema: minimal Postgres slice (gene only).
-- Rungs 2+ extend this (disease, edge_dag, edge_cbg) via ingest/load_postgres.py.
CREATE TABLE IF NOT EXISTS gene (
    id   TEXT PRIMARY KEY,
    name TEXT NOT NULL
);
