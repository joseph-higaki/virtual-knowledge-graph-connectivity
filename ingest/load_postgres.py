"""Create the rung-2 Postgres schema and COPY the slice CSVs into it (CLAUDE.md rung 2).

Loads the PG-resident slice tables only: gene, disease, gene_disease_association. (compound_gene_binding
is a Postgres table too but belongs to rung 4; compound / compound_disease_treatment live in Iceberg —
loaded by load_iceberg.py.) Idempotent: CREATE IF NOT EXISTS + TRUNCATE + COPY, so re-running fully
replaces contents and supersedes the rung-0 8-gene initdb seed. No FK constraints — cross-store joins
are keyed on unenforced id strings by design (CLAUDE.md store layout).

Connects host-side (localhost:${POSTGRES_HOST_PORT}); credentials come from secrets/.env via
require_env (same fail-loud primitive as the SPARQL config).

CLI: `python -m ingest.load_postgres`  (run after fetch + build_tables)
"""
from __future__ import annotations

import psycopg
from psycopg import sql

from harness.config import require_env
from ingest.build_tables import OUT_DIR

_NODE_COLDEF = sql.SQL("(id TEXT PRIMARY KEY, name TEXT NOT NULL)")
_ASSOC_COLDEF = sql.SQL("(source_id TEXT NOT NULL, target_id TEXT NOT NULL)")

# rung-2 PG tables: (table, column-definition, copy-columns). Order-independent (no FKs).
TABLES = [
    ("gene", _NODE_COLDEF, ("id", "name")),
    ("disease", _NODE_COLDEF, ("id", "name")),
    ("gene_disease_association", _ASSOC_COLDEF, ("source_id", "target_id")),
]


def connect() -> psycopg.Connection:
    """Host-side connection to the compose Postgres, per secrets/.env."""
    return psycopg.connect(
        host="localhost",
        port=require_env("POSTGRES_HOST_PORT"),
        dbname=require_env("POSTGRES_DB"),
        user=require_env("POSTGRES_USER"),
        password=require_env("POSTGRES_PASSWORD"),
    )


def load(tables=TABLES) -> dict[str, int]:
    counts: dict[str, int] = {}
    with connect() as conn, conn.cursor() as cur:
        for table, coldef, cols in tables:
            csv_path = OUT_DIR / f"{table}.csv"
            if not csv_path.exists():
                raise FileNotFoundError(f"{csv_path} missing — run `python -m ingest.build_tables` first")
            ident = sql.Identifier(table)
            cur.execute(sql.SQL("CREATE TABLE IF NOT EXISTS {} {}").format(ident, coldef))
            cur.execute(sql.SQL("TRUNCATE {}").format(ident))
            copy_sql = sql.SQL("COPY {} ({}) FROM STDIN WITH (FORMAT CSV, HEADER true)").format(
                ident, sql.SQL(", ").join(map(sql.Identifier, cols))
            )
            with cur.copy(copy_sql) as copy, csv_path.open("rb") as fh:
                for block in iter(lambda: fh.read(1 << 16), b""):
                    copy.write(block)
            cur.execute(sql.SQL("SELECT count(*) FROM {}").format(ident))
            counts[table] = cur.fetchone()[0]
    return counts


def main(argv=None) -> int:
    for table, n in load().items():
        print(f"loaded {table:<28} {n:>7,} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
