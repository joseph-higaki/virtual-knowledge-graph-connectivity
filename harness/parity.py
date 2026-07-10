"""Parity check: run one query against Ontop and the GraphDB ground truth, diff on the projection.

The rung invariant (CLAUDE.md #7): a rung passes iff Ontop's bindings equal the ground truth's,
compared on the projected columns modulo order. The queries already project only comparable columns
(labels / scalars, never IRIs — Ontop mints its own IRI scheme), so we compare the rows directly as
a multiset (Counter), which is "sort + diff" with duplicate-safety.

Fidelity loss is the small dict CLAUDE.md asks for, not a framework:
  fidelity_loss = {in_ground_truth_not_ontop, in_ontop_not_ground_truth}
Layer attribution has only two causes here (no LLM, and at rung 2 no Trino): a **mapping gap**
(Ontop returns fewer rows than its SQL source holds) vs a **source-load gap** (the table itself is
short). Splitting them needs the source row count, so `attribute` takes an optional source_count;
without it the loss is reported unattributed rather than guessed.

CLI: `python -m harness.parity q02 q05`  (accepts a query stem or filename prefix; nonzero exit on
any parity failure).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from .run_query import run_query

_QUERIES = Path(__file__).resolve().parents[1] / "queries"


def _rows(result: dict) -> Counter:
    """Multiset of projected rows, as tuples in the result's column order."""
    cols = result["columns"]
    return Counter(tuple(row.get(c) for c in cols) for row in result["rows"])


def attribute(missing: list, surplus: list, ontop_count: int, source_count: int | None) -> str | None:
    """Name the layer responsible for a loss. None when parity holds. See module docstring."""
    if not missing and not surplus:
        return None
    if missing:  # Ontop dropped rows the ground truth returned
        if source_count is None:
            return "mapping_or_source_gap (pass source_count to split)"
        return "mapping_gap" if ontop_count < source_count else "source_load_gap"
    return "ontop_surplus"  # Ontop returned rows the ground truth lacks (ground truth short)


def compare(name: str, ontop: dict, ground_truth: dict, source_count: int | None = None) -> dict:
    c_ontop, c_gt = _rows(ontop), _rows(ground_truth)
    missing = sorted(list(t) for t in (c_gt - c_ontop).elements())  # in ground truth, not Ontop
    surplus = sorted(list(t) for t in (c_ontop - c_gt).elements())  # in Ontop, not ground truth
    return {
        "query": name,
        "pass": not missing and not surplus,
        "counts": {"ontop": c_ontop.total(), "ground_truth": c_gt.total()},
        "elapsed_ms": {
            "ontop": ontop["telemetry"]["elapsed_ms"],
            "ground_truth": ground_truth["telemetry"]["elapsed_ms"],
        },
        "fidelity_loss": {
            "in_ground_truth_not_ontop": missing,
            "in_ontop_not_ground_truth": surplus,
        },
        "layer": attribute(missing, surplus, c_ontop.total(), source_count),
    }


def _resolve(name: str) -> Path:
    """Map a query stem/prefix (q02, q02_disease_associates_gene) to its .rq path."""
    exact = _QUERIES / (name if name.endswith(".rq") else f"{name}.rq")
    if exact.exists():
        return exact
    hits = sorted(_QUERIES.glob(f"{name}*.rq"))
    if len(hits) != 1:
        raise ValueError(f"query {name!r} matches {[h.name for h in hits]}; be more specific")
    return hits[0]


def run_both(name: str, source_count: int | None = None) -> tuple[dict, dict, dict]:
    """Run `name` against both endpoints; return (ontop_result, ground_truth_result, compare())."""
    query = _resolve(name).read_text(encoding="utf-8")
    ontop = run_query("ontop", query)
    ground_truth = run_query("ground_truth", query)
    return ontop, ground_truth, compare(name, ontop, ground_truth, source_count)


def run_pair(name: str, source_count: int | None = None) -> dict:
    """Run `name` against both endpoints and return the compare() dict."""
    return run_both(name, source_count)[2]


def _fmt_row(cols: list[str], row: dict | None) -> str:
    """One projected row as 'v1 | v2 | …' (a placeholder dash when an endpoint has no such row)."""
    return " | ".join(str(row.get(c)) for c in cols) if row is not None else "—"


def render(name: str, ontop: dict, ground_truth: dict, result: dict, file=sys.stdout) -> None:
    """Human side-by-side of one query: per-endpoint telemetry, then aligned rows + PASS/FAIL."""
    p = lambda *a: print(*a, file=file)
    ot, gt = ontop["telemetry"], ground_truth["telemetry"]
    p(f"\n=== {name} ===")
    p(f"{'telemetry':<14}{'ontop':<40}ground_truth")
    for k in ("http_status", "row_count", "elapsed_ms", "url"):
        p(f"  {k:<12}{str(ot[k]):<40}{gt[k]}")

    # Rows sorted so the two columns line up despite each endpoint's own ordering (parity is modulo order).
    cols = ontop["columns"]
    o_rows = sorted(ontop["rows"], key=lambda r: [str(r.get(c)) for c in cols])
    g_rows = sorted(ground_truth["rows"], key=lambda r: [str(r.get(c)) for c in cols])
    width = max([24, *(len(_fmt_row(cols, r)) for r in o_rows)]) + 2
    p(f"\n  {'#':<4}{'ontop → Postgres':<{width}}{'ground_truth':<{width}}match")
    for i in range(max(len(o_rows), len(g_rows))):
        o = o_rows[i] if i < len(o_rows) else None
        g = g_rows[i] if i < len(g_rows) else None
        of, gf = _fmt_row(cols, o), _fmt_row(cols, g)
        p(f"  {i + 1:<4}{of:<{width}}{gf:<{width}}{'✓' if of == gf else '✗'}")
    loss = result["fidelity_loss"]
    verdict = "PASS" if result["pass"] else "FAIL"
    p(f"  → {verdict}  (missing={len(loss['in_ground_truth_not_ontop'])}, "
      f"surplus={len(loss['in_ontop_not_ground_truth'])}, layer={result['layer']})")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Diff Ontop vs the GraphDB ground truth per query.")
    ap.add_argument("queries", nargs="+", help="query stems or filename prefixes (e.g. q02 q05)")
    ap.add_argument("--detail", action="store_true",
                    help="print per-endpoint telemetry + side-by-side rows instead of the JSON diff")
    args = ap.parse_args(argv)

    results = []
    for q in args.queries:
        ontop, ground_truth, result = run_both(q)
        results.append(result)
        if args.detail:
            render(q, ontop, ground_truth, result)
    if not args.detail:
        print(json.dumps(results, indent=2))

    ok = all(r["pass"] for r in results)
    print(("PASS" if ok else "FAIL") + f" — {sum(r['pass'] for r in results)}/{len(results)} queries", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
