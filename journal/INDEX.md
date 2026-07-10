# Session journal index

Cumulative build cost. `Total` is the deduped per-session total (sums cleanly down the column).

| Date | Session | Model | Input | Output | Cache read | Cache write | Total | Focus |
|---|---|---|---|---|---|---|---|---|
| 2026-07-09 | 01 | claude-fable-5 | 8,779 | 133,196 | 7,740,331 | 404,980 | 8,287,286 | Repo init + rung 0 + ground-truth rename |
| 2026-07-10 | 02 | claude-opus-4-8 | 7,249 | 138,889 | 13,747,229 | 648,690 | 14,542,057 | Rung 2 parity + ingest + SQL tooling + compare UI |
| 2026-07-10 | 03 | claude-opus-4-8 | 7,725 | 80,645 | 7,249,884 | 217,112 | 7,555,366 | Rung 3 — Ontop → Trino → Iceberg (Nessie) parity |
| 2026-07-10 | 04 | claude-opus-4-8 | 7,799 | 194,421 | 16,638,892 | 268,134 | 17,109,246 | Rung 4 polyglot federation → v0.1.0; column refactor + CbG→Iceberg; UI/query de-rung |
