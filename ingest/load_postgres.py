"""Create the rung-2 Postgres schema and COPY the slice CSVs into it (CLAUDE.md rung 2).

Loads the full PG-resident slice: gene, disease, gene_disease_association. The compound entity and
BOTH compound edges (compound_gene_binding, compound_disease_treatment) live in Iceberg — loaded by
load_iceberg.py — so Postgres holds no compound-side table. Idempotent full replace: DROP + CREATE +
COPY each run (like load_iceberg), so re-running rebuilds schema *and* data and supersedes the rung-0
8-gene initdb seed. DROP (not TRUNCATE) is deliberate — it lets a column/schema change land on a
pre-existing pgdata volume; TRUNCATE would keep the stale columns and break COPY. No FK constraints —
cross-store joins are keyed on unenforced id strings by design (CLAUDE.md store layout).

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
# gene_disease_association is the only PG-resident edge; its columns follow the DaG direction
# (Disease -> Gene). The compound edges are Iceberg-side (see load_iceberg.py).
_GDA_COLDEF = sql.SQL("(disease_id TEXT NOT NULL, gene_id TEXT NOT NULL)")

# PG tables: (table, column-definition, copy-columns). Order-independent (no FKs).
TABLES = [
    ("gene", _NODE_COLDEF, ("id", "name")),
    ("disease", _NODE_COLDEF, ("id", "name")),
    ("gene_disease_association", _GDA_COLDEF, ("disease_id", "gene_id")),
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
            # DROP + CREATE = true full replace: schema drift (e.g. a column rename) lands even on a
            # pre-existing volume, where CREATE IF NOT EXISTS would silently keep the old columns.
            cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(ident))
            cur.execute(sql.SQL("CREATE TABLE {} {}").format(ident, coldef))
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
