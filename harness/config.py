"""Harness config: resolve SPARQL endpoint URLs from secrets/.env (single source of truth)."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_REPO_ROOT / "secrets" / ".env")

ONTOP_SPARQL_URL = os.environ.get("ONTOP_SPARQL_URL", "http://localhost:7300/sparql")
GROUND_TRUTH_SPARQL_URL = os.environ.get(
    "GROUND_TRUTH_SPARQL_URL", "http://localhost:7200/repositories/hetionet"
)

# The two targets parity.py compares. "ground_truth" is the existing GraphDB.
ENDPOINTS = {"ontop": ONTOP_SPARQL_URL, "ground_truth": GROUND_TRUTH_SPARQL_URL}
