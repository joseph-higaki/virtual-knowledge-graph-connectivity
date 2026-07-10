"""Download the Hetionet source-of-truth files into data/hetionet/ (CLAUDE.md #5).

Source of truth is the TSV distribution, NOT the metagraph JSON: nodes.tsv (id/name/kind),
edges.sif.gz (source/metaedge/target — metaedge is an abbreviation), and metaedges.tsv (the
abbrev↔full-name map used to confirm DaG/CbG/CtD casing before filtering). Idempotent: skips a
file already present unless --force. Fail-loud on a non-200 so a moved URL surfaces here, not as a
downstream parse error.

CLI: `python -m ingest.fetch [--force]`
"""
from __future__ import annotations

import argparse
from pathlib import Path

import requests

_RAW = "https://raw.githubusercontent.com/hetio/hetionet/master"
# edges.sif.gz is Git-LFS-tracked: raw.githubusercontent serves a ~130B pointer, not the gzip.
# LFS media host resolves the real object. Plain-text files stay on the raw host.
_MEDIA = "https://media.githubusercontent.com/media/hetio/hetionet/master"
# filename -> upstream path. metaedges.tsv is the abbreviation dictionary (CLAUDE.md #5).
FILES = {
    "hetionet-v1.0-nodes.tsv": f"{_RAW}/hetnet/tsv/hetionet-v1.0-nodes.tsv",
    "hetionet-v1.0-edges.sif.gz": f"{_MEDIA}/hetnet/tsv/hetionet-v1.0-edges.sif.gz",
    "metaedges.tsv": f"{_RAW}/describe/edges/metaedges.tsv",
}
DEST = Path(__file__).resolve().parents[1] / "data" / "hetionet"


def fetch(force: bool = False) -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    for name, url in FILES.items():
        out = DEST / name
        if out.exists() and not force:
            print(f"skip  {name} (exists; --force to re-download)")
            continue
        resp = requests.get(url, timeout=120)
        resp.raise_for_status()  # fail loud: a moved file must not look like empty data
        out.write_bytes(resp.content)
        print(f"fetch {name}  ({len(resp.content):,} bytes)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Fetch Hetionet TSVs into data/hetionet/.")
    ap.add_argument("--force", action="store_true", help="re-download even if present")
    fetch(ap.parse_args(argv).force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
