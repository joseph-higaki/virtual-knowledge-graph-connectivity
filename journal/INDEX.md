# Session journal index

Cumulative build cost. `Total` is the deduped per-session total (sums cleanly down the column).

| Date | Session | Model | Input | Output | Cache read | Cache write | Total | Focus |
|---|---|---|---|---|---|---|---|---|
| 2026-07-09 | 01 | claude-fable-5 | 8,779 | 133,196 | 7,740,331 | 404,980 | 8,287,286 | Repo init + rung 0 + ground-truth rename |
| 2026-07-10 | 02 | claude-opus-4-8 | 7,249 | 138,889 | 13,747,229 | 648,690 | 14,542,057 | Rung 2 parity + ingest + SQL tooling + compare UI |
| 2026-07-10 | 03 | claude-opus-4-8 | 7,725 | 80,645 | 7,249,884 | 217,112 | 7,555,366 | Rung 3 — Ontop → Trino → Iceberg (Nessie) parity |
| 2026-07-10 | 04 | claude-opus-4-8 | 7,799 | 194,421 | 16,638,892 | 268,134 | 17,109,246 | Rung 4 polyglot federation → v0.1.0; column refactor + CbG→Iceberg; UI/query de-rung |
| 2026-07-12 | 05 | claude-opus-4-8 | 5,010 | 208,806 | 7,396,512 | 591,757 | 8,202,085 | Docs/README rewrite + architecture diagrams + UI syntax highlighting → v0.1.1 (catch-up, ~9 sessions) |
| 2026-07-13 | 06 | claude-opus-4-8 | 50 | 29,869 | 1,477,567 | 60,790 | 1,568,276 | Load Hetionet TBox into every Ontop (domain/range active, parity-neutral) → v0.1.2 |
