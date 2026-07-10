"""Rung tests.

Rung 0 = endpoint liveness: q08 returns >=1 binding; faults surface as failures.
Rung 2 = label parity: q02/q05 return the same projection from Ontop and the GraphDB ground truth.
Rung 2 needs BOTH endpoints up (Ontop on :7300, GraphDB on :7200) and Postgres loaded
(`make load-postgres`).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from harness.parity import run_pair
from harness.run_query import run_query

_QUERIES = Path(__file__).resolve().parents[1] / "queries"


@pytest.mark.rung0
def test_rung0_smoke_endpoint_live():
    query = (_QUERIES / "q08_smoke.rq").read_text(encoding="utf-8")
    result = run_query("ontop", query)
    assert result["telemetry"]["http_status"] == 200
    assert result["telemetry"]["row_count"] >= 1, "SELECT * LIMIT 1 returned no bindings"


@pytest.mark.rung2
@pytest.mark.parametrize("qname", ["q02_disease_associates_gene", "q05_count_genes"])
def test_rung2_parity(qname):
    result = run_pair(qname)
    assert result["pass"], result["fidelity_loss"]
