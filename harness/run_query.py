"""Send a SPARQL query to an endpoint (ontop|ground_truth) and return rows + a small telemetry dict.

Telemetry is a plain dict, not a framework (project scope): endpoint, url, http_status,
elapsed_ms, row_count. Layer attribution (mapping-gap vs source-load-gap) is a parity-time
concern added by parity.py, not here.

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


def run_query(endpoint: str, query: str, timeout: float = 60.0) -> dict:
    if endpoint not in ENDPOINTS:
        raise ValueError(f"unknown endpoint {endpoint!r}; choose from {sorted(ENDPOINTS)}")
    url = endpoint_url(endpoint)
    headers = {
        "Content-Type": "application/sparql-query",
        "Accept": "application/sparql-results+json",
    }
    t0 = time.perf_counter()
    resp = requests.post(url, data=query.encode("utf-8"), headers=headers, timeout=timeout)
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
    telemetry = {
        "endpoint": endpoint,
        "url": url,
        "http_status": resp.status_code,
        "elapsed_ms": elapsed_ms,
        "row_count": None,
    }
    resp.raise_for_status()
    payload = resp.json()
    cols = payload.get("head", {}).get("vars", [])
    rows = [
        {c: b.get(c, {}).get("value") for c in cols}
        for b in payload.get("results", {}).get("bindings", [])
    ]
    telemetry["row_count"] = len(rows)
    return {"columns": cols, "rows": rows, "telemetry": telemetry}


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
