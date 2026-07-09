"""Harness config: resolve SPARQL endpoint URLs from secrets/.env (single source of truth).

No masking defaults: an unset/empty var raises by name (require_env) instead of falling back to
a plausible-but-wrong endpoint that would surface as a connection error, not a config error.
URL resolution is lazy + per-endpoint (endpoint_url) because run_query needs only one endpoint
while parity needs both — validating both at import would fail a single-endpoint run for the
wrong reason. This is only the Python boundary; compose vars (DB creds) fail loud in compose via
`${VAR:?...}`.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_REPO_ROOT / "secrets" / ".env")

# endpoint name -> env var supplying its URL. parity.py compares the two;
# "ground_truth" is the existing GraphDB.
_ENV_VARS = {"ontop": "ONTOP_SPARQL_URL", "ground_truth": "GROUND_TRUTH_SPARQL_URL"}
ENDPOINTS = tuple(_ENV_VARS)  # valid endpoint names (argparse choices / membership checks)


def require_env(name: str) -> str:
    """Value of env var `name`, or raise naming it — the fail-loud primitive for any harness var."""
    val = os.environ.get(name, "")
    if not val:
        raise RuntimeError(f"{name} not set — add it to secrets/.env (see secrets/.env.example)")
    return val


def endpoint_url(endpoint: str) -> str:
    """URL for `endpoint`, resolved lazily so only the endpoint actually used must be configured."""
    return require_env(_ENV_VARS[endpoint])
