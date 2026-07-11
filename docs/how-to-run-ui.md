# How to run the UI with the full databases loaded

Goal: open the **compare UI** — one SPARQL query run side by side against the **virtual** VKG
(Ontop → Trino → Postgres + Iceberg) and the **materialized** GraphDB — with every node and edge
type loaded. That "everything loaded" state is **rung 4** (polyglot federation), not a UI setting.

For the full rung ladder and per-layer gotchas see [staggered-execution.md](staggered-execution.md);
for what the boxes are, [architecture.md](architecture.md). This doc is just the run recipe.

## Two things called "ui" — pick the right one

| Target        | What it is                                                    | URL                     |
|---------------|--------------------------------------------------------------|-------------------------|
| `make ui`     | Prints the URL of Ontop's built-in **YASGUI** SPARQL console. One endpoint, no comparison. | <http://localhost:7300/> |
| `make ui-app` | The **compare UI**: a local Python server that queries **both** Ontop and GraphDB and diffs them. | <http://localhost:7400/> |

This doc is about **`make ui-app`**. `make ui` needs no data loaders and no GraphDB — it is only a
SPARQL console over whatever rung is currently up.

## Prerequisites (one-time)

1. **`secrets/.env`** exists — copy it from `secrets/.env.example`. It carries the ports and the
   `GROUND_TRUTH_SPARQL_URL`.
2. **`make deps`** — creates the `.venv` (editable install) and downloads the pinned Postgres +
   Trino JDBC drivers that Ontop mounts. One-time; re-run only if a driver version changes.
3. **GraphDB is up on `:7200`.** It is **external** — *not* in `docker-compose.yml`. It is the
   Project-1 instance (stood up under `biomedical-rag-bench`), and its repository must match
   `GRAPHDB_REPOSITORY` in `secrets/.env` (default `hetionet`). The compare UI queries it on
   **every** run; if it is down, the comparison errors as a whole (not just the materialized pane).

## The run recipe

Run these from the repo root, in order:

```bash
make down          # free Ontop's :7300 if a different rung is already up (rungs share the host port)
make up-rung4      # postgres + minio + nessie + trino(+postgresql catalog) + Ontop(polyglot); blocks until Trino is healthy
make load-postgres # gene / disease / gene_disease_association  → Postgres
make load-iceberg  # compound + compound_gene_binding + compound_disease_treatment → Iceberg (via Trino)
make ui-app        # compare UI on http://localhost:7400/  (runs in the foreground; Ctrl+C to stop)
```

Then open <http://localhost:7400/>, pick a query (q03/q04/q07 are the cross-catalog ones), and hit
run. Use the **Raw ↔ Labels** toggle to see the invariant: in Raw the IRI columns disagree across
engines; in Labels they drop and the rows match.

### Why rung 4, and why both loaders

- Lower rungs load only part of the graph: **rung 2** loads Postgres only (gene/disease/association);
  **rung 3** loads Iceberg only (compound). The compare UI runs at any rung, but only **rung 4** has
  all three node types *and* all three edge types present and federated.
- **Both loaders are required** because the data straddles two stores: Postgres holds gene, disease,
  and their association; Iceberg holds compound and *both* compound edges. A query like `q03`/`q04`/`q07`
  needs both sides — that cross-store join is the whole point of rung 4.

## Verifying it worked, without the browser

```bash
make test-rung4    # label parity for q03/q04/q07 vs GraphDB — needs the same stack + both loaders + GraphDB up
make parity-rung4  # the same check printed as a per-query diff + fidelity-loss dict
```

If these pass, the compare UI has everything it needs. `make parity-rung4` failing with an empty
*virtual* side usually means a loader did not run (see gotchas).

## Gotchas

> **GraphDB down → the whole page errors.** `ui-app` always hits the ground-truth endpoint. A
> connection error to `:7200` surfaces on the page, not just in the materialized pane. Start GraphDB
> first.

> **Query too early → `Cannot find relation iceberg.hetionet.compound`.** `make up-rung4` starts the
> stack but does not load it. Run both loaders after it comes up. If you loaded but still hit this,
> Nessie's in-memory catalog was dropped by a container recreate (the data is still in MinIO) — just
> re-run `make load-iceberg`.

> **Switched rungs and the UI shows stale/partial data.** All rungs share Ontop's host port `:7300`.
> Always `make down` before bringing up a different rung, so the right Ontop (with `polyglot.obda`)
> is the one on the port.

> **`make ui-app` blocks the terminal.** It serves in the foreground on `127.0.0.1:7400`. Leave it
> running while you use the page; Ctrl+C stops it. Override the port with `UI_HOST_PORT=… make ui-app`.
