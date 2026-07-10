"""Local live compare UI: virtual (Ontop→Trino, federating Postgres + Iceberg) vs materialized (GraphDB) for one SPARQL query.

NOT a Claude Artifact — those run under a CSP that blocks all network calls, so they can't query a
live endpoint. This is a tiny stdlib http.server that (a) serves index.html and (b) proxies one query
to BOTH endpoints server-side, reusing the tested harness code (fetch/reformulate/parity). The browser
therefore talks only to this same origin — no CORS, and no query logic duplicated into JS.

The label projection (for the raw↔labels toggle and the parity verdict) drops any column whose
bindings are IRIs in either endpoint: Ontop and GraphDB mint different IRI schemes, so only the
literal/label columns are comparable (CLAUDE.md #7).

Run: `make ui-app` (needs an Ontop + GraphDB stack up + loaded — e.g. `make up-rung4` + both loaders).
Port via UI_HOST_PORT (default 7400). Endpoint-agnostic: it hits whatever Ontop is on :7300.
"""
from __future__ import annotations

import json
import os
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests

from harness.parity import compare
from harness.run_query import fetch, reformulate

_UI_DIR = Path(__file__).resolve().parent
_QUERIES_DIR = _UI_DIR.parent / "queries"
_EXAMPLES_DIR = _UI_DIR / "examples"  # UI-only teaching queries, kept out of the harness rung set


def _uri_columns(columns: list[str], bindings: list[dict]) -> set[str]:
    """Columns whose present bindings are all IRIs — not comparable across engines, so dropped."""
    uri = set()
    for c in columns:
        present = [b[c] for b in bindings if c in b]
        if present and all(x.get("type") == "uri" for x in present):
            uri.add(c)
    return uri


def _project(rich: dict, keep: list[str]) -> list[dict]:
    return [{c: b.get(c, {}).get("value") for c in keep} for b in rich["bindings"]]


def run_comparison(query: str) -> dict:
    """Run `query` on both endpoints; return raw rows, the label projection, parity, and Ontop's SQL."""
    ontop = fetch("ontop", query)
    ground_truth = fetch("ground_truth", query)

    cols = ontop["columns"]  # same query → same head vars; use Ontop's order as canonical
    dropped = _uri_columns(cols, ontop["bindings"]) | _uri_columns(ground_truth["columns"], ground_truth["bindings"])
    keep = [c for c in cols if c not in dropped]

    label_ontop = {"columns": keep, "rows": _project(ontop, keep), "telemetry": ontop["telemetry"]}
    label_gt = {"columns": keep, "rows": _project(ground_truth, keep), "telemetry": ground_truth["telemetry"]}
    parity = compare("query", label_ontop, label_gt)

    try:
        sql = reformulate(query)
    except Exception as e:  # reformulate is a nice-to-have; a failure shouldn't sink the comparison
        sql = {"sql": f"(reformulate failed: {e})", "http_status": None, "elapsed_ms": None}

    return {
        "ontop": {"columns": cols, "rows": _project(ontop, cols), "telemetry": ontop["telemetry"]},
        "ground_truth": {"columns": ground_truth["columns"],
                         "rows": _project(ground_truth, ground_truth["columns"]),
                         "telemetry": ground_truth["telemetry"]},
        "label": {"columns": keep, "ontop_rows": label_ontop["rows"], "gt_rows": label_gt["rows"],
                  "dropped_uri_columns": sorted(dropped)},
        "parity": parity,
        "sql": sql,
    }


def _list_queries() -> list[dict]:
    items = [{"name": p.stem, "text": p.read_text(encoding="utf-8")}
             for p in sorted(_QUERIES_DIR.glob("*.rq"))]
    items += [{"name": f"example · {p.stem}", "text": p.read_text(encoding="utf-8")}
              for p in sorted(_EXAMPLES_DIR.glob("*.rq"))]
    return items


def _error_text(e: Exception) -> str:
    """Prefer the endpoint's own error body (bad SPARQL → 400 with a message) over the wrapper."""
    resp = getattr(e, "response", None)
    if resp is not None and getattr(resp, "text", ""):
        return f"{e.__class__.__name__}: {resp.text.strip()[:2000]}"
    return f"{e.__class__.__name__}: {e}"


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, obj) -> None:
        self._send(status, json.dumps(obj).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, (_UI_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/api/queries":
            self._json(200, _list_queries())
        else:
            self._json(404, {"error": f"no route {self.path}"})

    def do_POST(self):
        if self.path != "/api/run":
            self._json(404, {"error": f"no route {self.path}"})
            return
        length = int(self.headers.get("Content-Length", 0))
        query = json.loads(self.rfile.read(length) or b"{}").get("query", "").strip()
        if not query:
            self._json(200, {"error": "empty query"})
            return
        try:
            self._json(200, run_comparison(query))
        except Exception as e:  # surface endpoint/connection errors to the page, not a 500
            traceback.print_exc()
            self._json(200, {"error": _error_text(e)})

    def log_message(self, *args):  # quiet the default per-request stderr spam
        pass


def main() -> int:
    port = int(os.environ.get("UI_HOST_PORT", "7400"))
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Compare UI on http://localhost:{port}/  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
