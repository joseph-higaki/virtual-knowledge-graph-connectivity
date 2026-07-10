"""Create the Iceberg schema + `compound` table via Trino and INSERT the slice (CLAUDE.md rung 3).

Loads the lake-resident node table `compound` into `iceberg.hetionet` through Trino's iceberg (Nessie)
catalog. Iceberg has no engine of its own, so every write goes through Trino (CLAUDE.md #4) — this
client speaks only to the Trino coordinator; the S3/MinIO credentials are Trino's catalog config, not
ours. Full replace each run (DROP + CREATE + batched INSERT), idempotent like load_postgres.

Two non-obvious points:
- Nessie runs an IN_MEMORY version store, so a container recreate drops the catalog pointers even
  though the parquet stays in MinIO. Re-running rebuilds them — that's the rung's `up -> load` flow.
- The trino client ships a parameterized statement in the `X-Trino-Prepared-Statement` HTTP header
  (url-encoded), so a big multi-row `VALUES (?,?),…` can blow the header size limit. Hence the small
  INSERT batch; values themselves ride in the EXECUTE body and are safely escaped by the client.

CLI: `python -m ingest.load_iceberg`  (needs the rung-3 stack up; run after fetch + build_tables)
"""
from __future__ import annotations

import csv
import time

import trino

from harness.config import require_env
from ingest.build_tables import OUT_DIR

CATALOG = "iceberg"
SCHEMA = "hetionet"
WAREHOUSE = "s3://warehouse/hetionet"  # schema location under the warehouse bucket
_INSERT_BATCH = 50  # keep the url-encoded prepared-statement header well under Trino's limit


def connect(retries: int = 30, delay: float = 2.0) -> trino.dbapi.Connection:
    """Trino DBAPI connection, retried until the coordinator answers `SELECT 1` (cold-start guard)."""
    port = int(require_env("TRINO_HOST_PORT"))
    last: Exception | None = None
    for _ in range(retries):
        try:
            conn = trino.dbapi.connect(host="localhost", port=port, user="trino",
                                       catalog=CATALOG, schema=SCHEMA)
            conn.cursor().execute("SELECT 1").fetchone()
            return conn
        except Exception as e:  # coordinator still warming up (connection refused / 503)
            last = e
            time.sleep(delay)
    raise RuntimeError(f"Trino not ready on localhost:{port} after {retries} tries: {last}")


def _run(cur, sql: str, params=None):
    """Execute and drain: the trino client is lazy, so fetch to force the statement to completion."""
    cur.execute(sql, params)
    return cur.fetchall()


def _rows(csv_path):
    with csv_path.open(newline="", encoding="utf-8") as f:
        r = csv.reader(f)
        next(r)  # skip the id,name header
        yield from r


def load() -> dict[str, int]:
    csv_path = OUT_DIR / "compound.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"{csv_path} missing — run `python -m ingest.build_tables` first")

    conn = connect()
    cur = conn.cursor()
    _run(cur, f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA} WITH (location = '{WAREHOUSE}')")
    # DROP + CREATE = clean full replace; Iceberg row-deletes would otherwise accrue delete files.
    _run(cur, f"DROP TABLE IF EXISTS {CATALOG}.{SCHEMA}.compound")
    _run(cur, f"CREATE TABLE {CATALOG}.{SCHEMA}.compound (id varchar, name varchar)")

    batch: list[tuple[str, str]] = []

    def flush():
        if not batch:
            return
        placeholders = ", ".join(["(?, ?)"] * len(batch))
        params = [v for row in batch for v in row]
        _run(cur, f"INSERT INTO {CATALOG}.{SCHEMA}.compound (id, name) VALUES {placeholders}", params)
        batch.clear()

    for row in _rows(csv_path):
        batch.append((row[0], row[1]))
        if len(batch) >= _INSERT_BATCH:
            flush()
    flush()

    n = _run(cur, f"SELECT count(*) FROM {CATALOG}.{SCHEMA}.compound")[0][0]
    conn.close()
    return {"compound": n}


def main(argv=None) -> int:
    for table, n in load().items():
        print(f"loaded {CATALOG}.{SCHEMA}.{table:<20} {n:>7,} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
