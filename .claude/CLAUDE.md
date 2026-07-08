You are scaffolding and implementing a **VKG/OBDA connectivity harness**. Read this whole file
before writing code. `README.md` and `STRUCTURE.md` are the design record; this file is the
operating contract. When in doubt, prefer fewer moving parts.

## What this is

A harness proving one hand-written SPARQL query resolves unchanged through
**standalone Ontop → Trino → PostgreSQL + Apache Iceberg (on MinIO)**, with results validated
against a **GraphDB oracle**. It is not a benchmark. There is no LLM and no reasoning.

## Hard constraints (do not violate)

1. **One variable only — serving topology.** No SPARQL generator (queries are hand-written, in
   `queries/*.rq`). No OWL reasoning (Ontop runs with reasoning off; the ontology is optional).
   Do not add either. If a task seems to need them, it belongs to a different project — stop and
   flag it.
2. **Standalone Ontop, not GraphDB-embedded Ontop.** Use the `ontop/ontop` container reading a
   `.obda` mapping + a `.properties` JDBC file. GraphDB appears in this repo **only as the
   oracle** (an external SPARQL endpoint), never as Ontop's host.
3. **Ontop binds to ONE SQL source per rung.** Rung 2 → Postgres directly. Rungs 3 and 4 → Trino
   only; Trino exposes the other stores as catalogs. Do not attempt to point one Ontop instance
   at two JDBC sources — that is Trino's job underneath.
4. **Iceberg is only ever reached through Trino.** Never try to connect Ontop to Iceberg
   directly; it has no query engine. Trino's Iceberg connector reads it from MinIO.
5. **Data source of truth = the Hetionet TSVs**, `hetionet-v1.0-nodes.tsv` and
   `hetionet-v1.0-edges.sif.gz`. **Not** the metagraph JSON (that is the schema, not instances).
   The `metaedge` column holds abbreviations — resolve them via `describe/edges/metaedges.tsv`;
   confirm the exact strings/casing for `DaG`, `CbG`, `CtD` before filtering.
6. **Scope = the slice only.** Nodes `{Gene, Disease, Compound}`; edges `{DaG, CbG, CtD}`.
   Topology + labels only — the TSVs carry no attributes, so do not model chromosome/inchikey/etc.
   Do not implement all 24 metaedges.
7. **Parity is compared on the label projection, not on IRIs.** Ontop may mint any consistent
   IRI template. Do NOT try to reproduce Project-1's URI scheme. Compare the `?xLabel` columns,
   sorted, modulo order. A rung passes iff Ontop's label bindings equal the oracle's.
8. **Local-first, cost-conscious.** Everything runs in `docker compose`. No cloud SaaS
   dependency (no real Snowflake/Databricks). No orchestration frameworks. Hand-rolled Python
   (`requests`/`SPARQLWrapper`, `psycopg`, `trino` python client, `pytest`).
9. **Build rung by rung, in order (0 → 2 → 3 → 4).** Do not scaffold polyglot first. Each rung
   must pass its tests before the next is started. After a later rung lands, earlier rungs stay
   runnable via compose profiles + make targets.

## Store layout to implement

| Table      | Store           | Filter                     |
|------------|-----------------|----------------------------|
| `gene`     | Postgres        | nodes.tsv kind=Gene        |
| `disease`  | Postgres        | nodes.tsv kind=Disease     |
| `compound` | Iceberg/MinIO   | nodes.tsv kind=Compound    |
| `edge_dag` | Postgres        | edges.sif metaedge=DaG     |
| `edge_cbg` | Postgres        | edges.sif metaedge=CbG     |
| `edge_ctd` | Iceberg/MinIO   | edges.sif metaedge=CtD     |

Node tables: `(id TEXT, name TEXT)`. Edge tables: `(source_id TEXT, target_id TEXT)`. No FK
constraints (cross-store joins are keyed on id strings, unenforced — this is intentional).

## Rung build order

- **Rung 0 — liveness.** Compose `postgres` + `ontop` with `mappings/postgres.obda` and a small
  `gene` load. Hit the endpoint with `q08` (`SELECT * WHERE {?s ?p ?o} LIMIT 1`). Confirm the
  endpoint boots and a mapping/connection error would surface clearly. This replaces any
  "SPARQL-only" idea — Ontop needs a source, so this is a smoke test, not a query test.
- **Rung 2 — Ontop → Postgres.** Full Postgres slice (`gene`, `disease`, `edge_dag`). Map to
  `hetio:Gene`/`hetio:Disease`/`rdfs:label` and `?d hetio:associates ?g`. Run `q02`, `q05`;
  parity vs oracle.
- **Rung 3 — Ontop → Trino → Iceberg.** Bring up `minio` + Iceberg catalog + `trino`. Load
  `compound` into Iceberg via Trino DDL/INSERT. Point Ontop at **Trino** using the iceberg
  catalog only (`mappings/iceberg.obda`, tables like `iceberg.hetionet.compound`). Run `q01`,
  `q06`; parity.
- **Rung 4 — Ontop → Trino → (Postgres + Iceberg).** Trino now exposes both `postgresql` and
  `iceberg` catalogs; load `edge_cbg` (PG) and `edge_ctd` (Iceberg). Use `mappings/polyglot.obda`
  addressing `postgresql.public.*` and `iceberg.hetionet.*`. Run `q03`, `q04`, `q07` — each must
  force a cross-catalog join. Parity, then tag `v0.1.0`.

Note that the SQL identifiers in the mappings change across rungs (bare `gene` at rung 2 vs
`postgresql.public.gene` at rung 4). That is expected and part of what the rungs demonstrate.

## Iceberg catalog — verify before pinning

Trino's Iceberg connector needs a catalog implementation (REST, Nessie, or Hive Metastore) plus
MinIO/S3 config. **Do not invent these property values from memory** — they are version-sensitive.
Mirror the Ontop team's known-working reference,
`ontopic-vkg/ontop-trino-iceberg-playground` (Trino + Nessie catalog + MinIO + Ontop), and verify
the current Trino Iceberg connector docs before writing `trino/catalog/iceberg.properties`.
Prefer the lightest catalog that works locally; record the choice in the README.

## Parity + telemetry

- `harness/run_query.py`: send a `.rq` to a target endpoint (`ontop` | `oracle`), return rows.
- `harness/parity.py`: for each query, run against both endpoints, project to the label
  column(s), sort, diff. Report per-query fidelity loss = `{in_oracle_not_ontop, in_ontop_not_oracle}`.
- On a miss, attribute the layer: **mapping gap** (Ontop returns fewer rows than the source has)
  vs **source-load gap** (the table itself is short). There is no LLM layer here, so those are
  the only two attributions. Keep this as a small dict on the result; do not build a telemetry
  framework.

## Do NOT build (out of scope)

LLM SPARQL writer · OWL reasoning · node/edge attributes · all 24 metaedges · cross-DB foreign-key
enforcement · persistent-identifier / URI-scheme reproduction · GraphDB-embedded Ontop ·
orchestration frameworks · any cloud SaaS backend.

## Definition of done for `v0.1.0`

`make up-rung4 && make test-rung4` passes: all rung-4 queries return label-parity with the oracle,
at least two of them provably cross the Postgres↔Iceberg boundary in Trino (confirm via Trino's
query plan / `EXPLAIN` that both catalogs are scanned), and rungs 0/2/3 remain runnable.
