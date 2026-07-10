"""Prove a rung-4 query crosses the Postgres↔Iceberg boundary in Trino (CLAUDE.md DoD).

Fetch Ontop's SPARQL→SQL rewrite (`/ontop/reformulate`), then `EXPLAIN (TYPE IO, FORMAT JSON)` it in
Trino and read the input tables' catalogs from the plan. A query *crosses* iff the plan scans BOTH
the `postgresql` and `iceberg` catalogs — i.e. Trino, not Ontop, did the federation. This is the
DoD's "confirm via EXPLAIN that both catalogs are scanned", not a telemetry framework.

CLI: `python -m harness.explain q03 q04 q07`  (nonzero exit unless >=2 queries cross).
"""
from __future__ import annotations

import argparse
import json
import sys

import trino

from harness.config import require_env
from harness.parity import _resolve
from harness.run_query import reformulate

_REQUIRED = {"postgresql", "iceberg"}


def _native_sql(reformulated: str) -> str:
    """Pull the executable SQL out of Ontop's /reformulate dump. That dump is Ontop's IQ tree —
    `ans1(...)` / `CONSTRUCT` / `NATIVE [...]` header lines wrapping the leaf NATIVE SQL node — so the
    SQL is the block from the first line that starts with SELECT to the end. Bare table names in it
    (e.g. "compound") resolve via the session default catalog/schema below, matching Ontop's JDBC."""
    lines = reformulated.splitlines()
    for i, ln in enumerate(lines):
        if ln.lstrip().upper().startswith("SELECT"):
            return "\n".join(lines[i:]).strip()
    raise ValueError(f"no SELECT block in reformulated output:\n{reformulated[:200]}")


def catalogs_scanned(sql: str) -> set[str]:
    """Catalogs Trino's IO plan reads for `sql`, via EXPLAIN (TYPE IO, FORMAT JSON). Session default
    catalog/schema = iceberg/hetionet so Ontop's bare (unqualified) Iceberg table names resolve."""
    conn = trino.dbapi.connect(host="localhost", port=int(require_env("TRINO_HOST_PORT")),
                               user="trino", catalog="iceberg", schema="hetionet")
    cur = conn.cursor()
    cur.execute(f"EXPLAIN (TYPE IO, FORMAT JSON) {sql}")
    plan = json.loads(cur.fetchone()[0])
    return {t["table"]["catalog"] for t in plan.get("inputTableColumnInfos", [])}


def check(name: str) -> dict:
    """{query, catalogs, crosses} for one query, going through Ontop's own reformulated SQL."""
    sql = _native_sql(reformulate(_resolve(name).read_text(encoding="utf-8"))["sql"])
    cats = catalogs_scanned(sql)
    return {"query": name, "catalogs": sorted(cats), "crosses": _REQUIRED <= cats}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Prove rung-4 queries scan both Trino catalogs.")
    ap.add_argument("queries", nargs="+", help="query stems or filename prefixes (e.g. q03 q04 q07)")
    args = ap.parse_args(argv)

    results = [check(q) for q in args.queries]
    for r in results:
        print(f"  {r['query']:<28} {'CROSSES' if r['crosses'] else 'single-catalog':<14} catalogs={r['catalogs']}")
    n = sum(r["crosses"] for r in results)
    print(f"{n}/{len(results)} queries cross the Postgres<->Iceberg boundary (DoD needs >=2)", file=sys.stderr)
    return 0 if n >= 2 else 1


if __name__ == "__main__":
    raise SystemExit(main())
