"""Rung tests.

Rung 0 = endpoint liveness: q08 returns >=1 binding; faults surface as failures.
Rung 2 = label parity: q02/q05 return the same projection from Ontop and the GraphDB ground truth.
Rung 3 = label parity over the Iceberg leg: q01/q06 (compound), Ontop -> Trino -> Iceberg.
Rung 4 = label parity over the polyglot leg: q03/q04/q07 cross the Postgres<->Iceberg boundary in
Trino (see harness.explain for the EXPLAIN proof), Ontop -> Trino -> (Postgres + Iceberg).
Each parity rung needs BOTH endpoints up (Ontop on :7300, GraphDB on :7200) and its source loaded:
rung 2 -> `make load-postgres`, rung 3 -> `make up-rung3 && make load-iceberg` (a different Ontop),
rung 4 -> `make up-rung4 && make load-postgres && make load-iceberg`.
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


@pytest.mark.rung3
@pytest.mark.parametrize("qname", ["q01_list_compounds", "q06_count_compounds"])
def test_rung3_parity(qname):
    result = run_pair(qname)
    assert result["pass"], result["fidelity_loss"]


@pytest.mark.rung4
@pytest.mark.parametrize("qname", [
    "q03_compound_binds_gene", "q04_compound_treats_disease", "q07_gene_two_hop",
])
def test_rung4_parity(qname):
    result = run_pair(qname)
    assert result["pass"], result["fidelity_loss"]
