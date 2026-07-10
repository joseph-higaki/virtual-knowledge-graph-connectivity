"""Send a SPARQL query to an endpoint (ontop|ground_truth) and return rows + a small telemetry dict.

Three layers over one HTTP path:
- `fetch`     — full SPARQL JSON incl. each binding's `type` (uri vs literal). The compare UI needs
                types to drop IRI columns for the label projection; run_query throws them away.
- `run_query` — `fetch` flattened to `{col: value}` rows (what parity + the tests consume).
- `reformulate` — Ontop's SPARQL→SQL rewrite via GET /ontop/reformulate (this 5.5.0 YASGUI has no
                SQL view). Ontop-only; there is no such thing on the ground truth.

Telemetry is a plain dict, not a framework: endpoint, url, http_status, elapsed_ms, row_count.
Layer attribution (mapping-gap vs source-load-gap) is a parity-time concern in parity.py, not here.

CLI: `python -m harness.run_query ontop queries/q08_smoke.rq`
(run as a module — relative imports mean `python harness/run_query.py` won't work).
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import requests

from .config import ENDPOINTS, endpoint_url


def _post(endpoint: str, query: str, accept: str, timeout: float):
    if endpoint not in ENDPOINTS:
        raise ValueError(f"unknown endpoint {endpoint!r}; choose from {sorted(ENDPOINTS)}")
    url = endpoint_url(endpoint)
    headers = {"Content-Type": "application/sparql-query", "Accept": accept}
    t0 = time.perf_counter()
    resp = requests.post(url, data=query.encode("utf-8"), headers=headers, timeout=timeout)
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
    telemetry = {
        "endpoint": endpoint, "url": url, "http_status": resp.status_code,
        "elapsed_ms": elapsed_ms, "row_count": None,
    }
    return resp, telemetry


def fetch(endpoint: str, query: str, timeout: float = 60.0) -> dict:
    """Full result: {columns, bindings (raw SPARQL-JSON with value+type), telemetry}."""
    resp, telemetry = _post(endpoint, query, "application/sparql-results+json", timeout)
    resp.raise_for_status()
    payload = resp.json()
    columns = payload.get("head", {}).get("vars", [])
    bindings = payload.get("results", {}).get("bindings", [])
    telemetry["row_count"] = len(bindings)
    return {"columns": columns, "bindings": bindings, "telemetry": telemetry}


def run_query(endpoint: str, query: str, timeout: float = 60.0) -> dict:
    """`fetch` flattened to `{col: value}` rows (types dropped) — the shape parity + tests use."""
    r = fetch(endpoint, query, timeout)
    rows = [{c: b.get(c, {}).get("value") for c in r["columns"]} for b in r["bindings"]]
    return {"columns": r["columns"], "rows": rows, "telemetry": r["telemetry"]}


def reformulate(query: str, timeout: float = 30.0) -> dict:
    """Ontop's SPARQL→SQL rewrite: {sql, http_status, elapsed_ms}. Ontop-only (GET /ontop/reformulate)."""
    base = endpoint_url("ontop").rsplit("/sparql", 1)[0]
    t0 = time.perf_counter()
    resp = requests.get(f"{base}/ontop/reformulate", params={"query": query}, timeout=timeout)
    return {
        "sql": resp.text,
        "http_status": resp.status_code,
        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
    }


def _read_query(arg: str) -> str:
    p = Path(arg)
    return p.read_text(encoding="utf-8") if p.exists() else arg


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run a SPARQL query against ontop|ground_truth.")
    ap.add_argument("endpoint", choices=sorted(ENDPOINTS))
    ap.add_argument("query", help="path to a .rq file or an inline SPARQL string")
    args = ap.parse_args(argv)
    print(json.dumps(run_query(args.endpoint, _read_query(args.query)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
