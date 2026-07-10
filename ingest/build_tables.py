"""Filter the Hetionet TSVs to the slice and emit one CSV per table (CLAUDE.md #6).

Pure transform, no DB. Reads nodes.tsv + edges.sif.gz (the TSVs are CRLF — the csv module strips
the trailing \\r that a manual split would leave on the last column), keeps only the slice's node
kinds and metaedges, and writes data/hetionet/tables/<table>.csv. Node rows -> (id, name);
association rows -> (source_id, target_id), preserving the edge's own direction (source=subject).
Produces all six slice tables; which ones get loaded where is a per-rung decision in the loaders.

Metaedge abbreviations are the exact strings from metaedges.tsv (CLAUDE.md #5): DaG/CbG/CtD.

CLI: `python -m ingest.build_tables`
"""
from __future__ import annotations

import csv
import gzip
from pathlib import Path

_DATA = Path(__file__).resolve().parents[1] / "data" / "hetionet"
NODES_TSV = _DATA / "hetionet-v1.0-nodes.tsv"
EDGES_SIF = _DATA / "hetionet-v1.0-edges.sif.gz"
OUT_DIR = _DATA / "tables"

# node kind (nodes.tsv col 'kind') -> output table
NODE_KINDS = {"Gene": "gene", "Disease": "disease", "Compound": "compound"}
# metaedge abbrev (edges.sif col 'metaedge') -> output table. Casing confirmed vs metaedges.tsv.
EDGE_METAEDGES = {
    "DaG": "gene_disease_association",    # Disease - associates - Gene
    "CbG": "compound_gene_binding",       # Compound - binds - Gene
    "CtD": "compound_disease_treatment",  # Compound - treats - Disease
}


def _write_filtered(reader, key_col, mapping, header, pick, counts):
    """Route each input row whose `key_col` value is in `mapping` to that table's writer via `pick`."""
    writers, files = {}, {}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        for table in dict.fromkeys(mapping.values()):  # unique, order-preserving
            fh = (OUT_DIR / f"{table}.csv").open("w", newline="", encoding="utf-8")
            files[table] = fh
            w = csv.writer(fh)
            w.writerow(header)
            writers[table] = w
            counts[table] = 0
        for row in reader:
            table = mapping.get(row[key_col])
            if table is None:
                continue
            writers[table].writerow(pick(row))
            counts[table] += 1
    finally:
        for fh in files.values():
            fh.close()


def build() -> dict[str, int]:
    counts: dict[str, int] = {}
    with NODES_TSV.open(newline="", encoding="utf-8") as f:
        _write_filtered(
            csv.DictReader(f, delimiter="\t"),
            key_col="kind", mapping=NODE_KINDS, header=("id", "name"),
            pick=lambda r: (r["id"], r["name"]), counts=counts,
        )
    with gzip.open(EDGES_SIF, mode="rt", newline="", encoding="utf-8") as f:
        _write_filtered(
            csv.DictReader(f, delimiter="\t"),
            key_col="metaedge", mapping=EDGE_METAEDGES, header=("source_id", "target_id"),
            pick=lambda r: (r["source"], r["target"]), counts=counts,
        )
    return counts


def main(argv=None) -> int:
    for table, n in build().items():
        print(f"{table:<28} {n:>7,} rows -> {OUT_DIR / (table + '.csv')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
