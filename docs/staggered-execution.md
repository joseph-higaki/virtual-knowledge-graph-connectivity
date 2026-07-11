# Staggered execution — the rung ladder

The README describes the **final state** (a polyglot VKG: Ontop → Trino → PostgreSQL + Iceberg).
That state is *built* one layer at a time. Each step — a **rung** — adds exactly one moving part and
must pass its parity check before the next is started, so a failure is always attributable to the
layer just introduced. After the top rung lands, every earlier rung stays runnable (compose
profiles + make targets) for bisecting a regression.

This file holds the ladder, the run commands, and the **execution logs** — the gotchas and insights
worth keeping so they are written down rather than rediscovered.

## The ladder

| Rung | Path                                     | Proves                                        | Query set     |
|------|------------------------------------------|-----------------------------------------------|---------------|
| 0    | SPARQL → Ontop (Postgres, tiny load)     | endpoint boots, one binding, errors surface   | q08           |
| 2    | SPARQL → Ontop → Postgres                | single relational source, parity on labels    | q02, q05      |
| 3    | SPARQL → Ontop → **Trino** → Iceberg     | lakehouse source (Iceberg needs an engine)    | q01, q06      |
| 4    | SPARQL → Ontop → Trino → (PG + Iceberg)  | true polyglot federation, cross-store joins   | q03, q04, q07 |

There is no rung 1 and no "Ontop → Iceberg direct" rung: Iceberg is a table format with no query
engine, so Trino appears the moment Iceberg does. `v0.1.0` ships at rung 4.

Prereqs: Docker + Docker Compose, Python 3.11+, `make`. Config/secrets live in `secrets/.env`
(copy from `secrets/.env.example`). Rungs share Ontop's host port `:7300`, so run `make down`
before switching rungs.

## Rung 0 — liveness (Ontop → Postgres)

```
make deps        # .venv (editable install) + pinned Postgres & Trino JDBC drivers — one-time
make up-rung0    # start Postgres (self-seeds 8 genes via initdb) + standalone Ontop
make test-rung0  # q08 (SELECT * LIMIT 1) returns a binding → endpoint is live
make smoke       # same query, prints rows + telemetry dict
make ui          # prints the Ontop console URL
```

The SPARQL console is Ontop's built-in **YASGUI** at <http://localhost:7300/> — syntax
highlighting out of the box. This 5.5.0 build's YASGUI has **no "View SQL" button**; the SPARQL→SQL
rewrite is exposed at the HTTP endpoint `GET /ontop/reformulate?query=…` — use `make sql
Q=<file.rq>` (or open the URL) to see the SQL Ontop pushes to the source. `make down` stops
containers (keeps data); `make clean` also drops the `pgdata` volume (forces a re-seed on next `up`).

## Rung 2 — Ontop → Postgres (parity)

The full Postgres slice — every `Gene` and `Disease` node plus every `Disease–associates–Gene`
(DaG) edge — served directly from Postgres and checked for label parity against the ground truth.

```
make up-rung2       # Postgres + Ontop with the full postgres.obda mapping
make load-postgres  # fetch TSVs → filter the slice → COPY gene/disease/gene_disease_association
make test-rung2     # label parity for q02, q05 vs the GraphDB ground truth
make parity         # same check, printed as a per-query diff + fidelity-loss dict
```

`make load-postgres` runs the `ingest/` pipeline: `fetch.py` pulls the Hetionet TSVs (the
`edges.sif.gz` is Git-LFS-tracked, so it comes from the LFS media host, not `raw.`), `build_tables.py`
filters to the slice's node kinds and metaedges (`DaG`/`CbG`/`CtD`, casing confirmed against
`metaedges.tsv`), and `load_postgres.py` creates the schema and `COPY`s the three PG-resident tables.
It **supersedes the rung-0 8-gene seed** — `TRUNCATE` + `COPY` replaces `gene` with all 20,945.

The queries bind entities by **label, never by IRI** (`?d rdfs:label "restless legs syndrome"`),
so a single `.rq` runs unchanged on Ontop and on GraphDB despite their different IRI schemes
(`https://het.io/…` vs `ncbigene:`/`do:`), and each projects only its label/scalar columns —
the parity comparison never sees an IRI. `q02` (12 genes) and `q05` (20,945 genes) both PASS.

To watch the rewrite as you tune the mapping, `make sql Q=queries/q02_disease_associates_gene.rq`
prints the pushed SQL (a single `disease ⋈ gene_disease_association ⋈ gene` join with the label as a
`WHERE` predicate); `make sql Q=queries/q05_count_genes.rq` shows the `COUNT(*)` delegated straight
to Postgres.

**Compare UI** — `make ui-app` serves a local page at <http://localhost:7400/> that runs one query
against both engines and shows them side by side: virtual (Ontop→Postgres) vs materialized (GraphDB),
each endpoint's telemetry, a latency bar, the parity verdict, and Ontop's SQL translation. A
**Raw ↔ Labels** toggle makes the invariant visible — in Raw the `?gene` IRI columns disagree
(`het.io/gene/…` vs `identifiers.org/ncbigene/…`); in Labels those IRI columns are dropped and the
rows match. It is a live tool (not a Claude Artifact — those run under a CSP that blocks network
calls, so they can't query the endpoints), so the stack must be up. A tiny stdlib server
(`ui/server.py`) proxies both endpoints server-side, reusing `run_query`/`parity`, so the browser
stays same-origin (no CORS).

> Editing a mapping while Ontop is running trips a WSL/9p stale bind-mount on `restart`; use
> `make down && make up-rung2` (a container **recreate**) so the new `.obda` is re-mounted and parsed.

## Rung 3 — Ontop → Trino → Iceberg (parity)

The lakehouse leg. The `compound` node table lives in **Apache Iceberg on MinIO**; Iceberg has no
query engine, so a **second** standalone Ontop is pointed at **Trino**, whose Iceberg connector reads
the table from MinIO through a catalog. Same SPARQL endpoint (`:7300`), same parity contract — only
the physical source moved off Postgres and behind a federation engine.

```
make down          # free :7300 if rung 0/2 is up (rung Ontops share the host port)
make up-rung3      # minio + nessie (catalog) + trino + Ontop→Trino; blocks until Trino is healthy
make load-iceberg  # CREATE SCHEMA/TABLE + INSERT the 1,552 compounds into iceberg.hetionet via Trino
make test-rung3    # label parity for q01 (list compounds) + q06 (COUNT) vs the GraphDB ground truth
make parity-rung3  # same, printed as the per-query diff + fidelity-loss dict
```

`q01` (1,552 compound labels) and `q06` (COUNT → 1,552) both PASS. `make sql
Q=queries/q01_list_compounds.rq` shows the SQL Ontop pushes to **Trino** (`SELECT … FROM "compound"`,
the Iceberg table resolved via the JDBC URL's default `iceberg/hetionet`) — this is the same
`reformulate` view that will prove the cross-catalog scans at rung 4.

**Catalog choice — Nessie.** Trino's Iceberg connector needs a catalog implementation (REST, Nessie,
or Hive Metastore) plus S3 config; the values are version-sensitive, so they mirror the Ontop team's
known-working `ontopic-vkg/ontop-trino-iceberg-playground` (Nessie) and were re-checked against the
Trino 478 docs. Nessie is the lightest that works here: a single container with an **in-memory version
store** — it tracks only catalog pointers (namespaces/table metadata); the parquet + Iceberg metadata
live in MinIO. Trino uses its **native S3** file system (`fs.native-s3.enabled=true`, path-style) — no
Hadoop. Pins: `trinodb/trino:478`, `ghcr.io/projectnessie/nessie:0.108.1`, MinIO
`RELEASE.2025-09-07T16-13-09Z`. Only Trino holds the S3 credentials (injected via Trino's `${ENV:…}`
substitution from `secrets/.env`), so no secret sits in a tracked file.

> **Two rung-3 gotchas.** (1) Every service is profile-gated, so a plain `docker compose down` skips
> them — `make down` now uses `--profile "*"`. (2) Nessie's in-memory store means a container recreate
> drops the catalog pointers (the data stays in MinIO); just re-run `make load-iceberg` — that is the
> rung's normal `up → load` flow, and the loader's `DROP TABLE IF EXISTS` makes it idempotent.

## Rung 4 — Ontop → Trino → (Postgres + Iceberg) polyglot federation

The payoff. **One** Ontop (`polyglot.obda`) speaks to **one** Trino, which now exposes **two**
catalogs: `postgresql` (`gene`, `disease`, `gene_disease_association`) and `iceberg` (`compound` +
both compound edges). A single hand-written SPARQL query resolves across both stores — and **Trino,
not Ontop, does the join**.

```
make down          # free :7300 and switch profiles
make up-rung4      # postgres + minio + nessie + trino(+postgresql catalog) + Ontop(polyglot)
make load-postgres # COPY gene/disease/gene_disease_association into Postgres
make load-iceberg  # INSERT compound + both compound edges into iceberg.hetionet via Trino
make test-rung4    # label parity for q03/q04/q07 vs the GraphDB ground truth
make parity-rung4  # same, printed as the per-query diff + fidelity-loss dict
make explain-rung4 # DoD proof: q03/q04/q07 scan BOTH catalogs (EXPLAIN Ontop's rewritten SQL)
```

`q03` (compounds binding gene **AGTR1** → the 11 "-sartan" ARBs), `q04` (compounds treating
**Alzheimer's disease** → Donepezil/Galantamine/Memantine/Rivastigmine), and `q07` (two-hop: diseases
treated by AGTR1's binders → hypertension/coronary-artery-disease/type-2-diabetes) all PASS. Each
forces the boundary — the compound node + edge live in `iceberg.hetionet`, the anchor/result gene &
disease in `postgresql.public`. `make explain-rung4` confirms via Trino's `EXPLAIN (TYPE IO)` that all
**three** scan both catalogs (DoD needs ≥2). Cross-catalog predicates: `hetio:binds` (CbG),
`hetio:treats` (CtD) — the exact ground-truth verbs (`git grep` the discovery in the journal).

> **Load ordering matters.** Ontop validates every mapping source query against live DB metadata on
> the first SPARQL request (lazy init), so all six relations must exist **before** you query — run
> both loaders after `make up-rung4`. Querying too early fails with `Cannot find relation
> iceberg.hetionet.compound`; just load, then `make down && make up-rung4` (or restart the
> `ontop-polyglot` container) for a clean init.

> **One catalog dir, additive files.** `trino/catalog/` holds both `iceberg.properties` (rung 3+) and
> `postgresql.properties` (rung 4). Postgres creds reach Trino via `${ENV:…}` from the trino service's
> env (`secrets/.env`), never a tracked file. The postgresql catalog only *registers* at startup and
> connects lazily, so **a rung-3 run boots green with Postgres down** (verified) — the earlier rungs
> stay runnable.
