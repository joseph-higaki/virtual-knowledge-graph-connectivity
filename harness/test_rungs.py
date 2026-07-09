"""Rung tests. Rung 0 = endpoint liveness: q08 returns >=1 binding; faults surface as failures."""
from __future__ import annotations

from pathlib import Path

import pytest

from harness.run_query import run_query

_QUERIES = Path(__file__).resolve().parents[1] / "queries"


@pytest.mark.rung0
def test_rung0_smoke_endpoint_live():
    query = (_QUERIES / "q08_smoke.rq").read_text(encoding="utf-8")
    result = run_query("ontop", query)
    assert result["telemetry"]["http_status"] == 200
    assert result["telemetry"]["row_count"] >= 1, "SELECT * LIMIT 1 returned no bindings"
