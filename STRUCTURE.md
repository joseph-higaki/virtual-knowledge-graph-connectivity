# Suggested repository file structure

This is the suggested tree. It is a **connectivity + fidelity
harness**, not a benchmark. It exercises exactly one axis — *where the ABox physically lives* —
with human-written SPARQL, reasoning off, and parity checked against a GraphDB ground truth.

```
virtual-knowledge-graph-connectivity/
├── README.md                       # final state: landscape, components, ontology, architecture, mapping, scope
├── CLAUDE.md                       # hard constraints + build order for the coding session
├── STRUCTURE.md                    # this file
├── docs/
│   ├── staggered-execution.md      # the rung ladder, per-rung run commands, execution-log gotchas
│   ├── polyglot-layer-choice.md    # decision: Trino (not Ontop) is the federation layer
│   └── enterprise-auth-findings.md # finding: identity propagation across the Ontop→Trino→store hops
├── docker-compose.yml              # profiles: postgres | minio | trino | ontop  (graphdb ground truth = external by default)
├── secrets/
│   ├── .env.example                # GROUND_TRUTH_SPARQL_URL, ONTOP_SPARQL_URL, MinIO dev creds, JDBC coords (tracked)
│   └── .env                        # real dev values (gitignored)
├── Makefile                        # fetch, up-rung{0,2,3,4}, load-*, test-rung{0,2,3,4}, parity, down
│
├── data/
│   └── hetionet/                   # (gitignored) fetched TSVs land here
│       ├── hetionet-v1.0-nodes.tsv         # id (e.g. Gene::5743), name, kind
│       ├── hetionet-v1.0-edges.sif.gz      # source, metaedge (abbrev), target
│       └── metaedges.tsv                    # abbrev <-> full-name map (from describe/edges/)
│
├── ingest/
│   ├── fetch.py                    # download the three files above from hetio/hetionet
│   ├── build_tables.py            # TSV -> per-type node CSVs + per-metaedge edge CSVs (SLICE ONLY)
│   ├── load_postgres.py           # DDL + COPY: gene, disease, gene_disease_association
│   ├── load_iceberg.py            # Trino DDL + INSERT: compound, compound_gene_binding, compound_disease_treatment  (Iceberg catalog on MinIO)
│   └── build_rdf.py               # OPTIONAL: TSV -> hetionet.ttl for a clean-provenance local ground truth
│
├── ontology/
│   └── hetionet-schema.ttl        # TBox, loaded by every Ontop (ONTOP_ONTOLOGY_FILE) so the schema
│                                  # is part of the served test bed. Ontop consumes domain/range too;
│                                  # a no-op for parity given the slice's referential integrity.
│
├── mappings/
│   ├── postgres.obda              # rung 2: bare tables  (gene, disease, gene_disease_association)
│   ├── iceberg.obda               # rung 3: iceberg.hetionet.compound  (via Trino, iceberg catalog only)
│   └── polyglot.obda              # rung 4: postgresql.public.* + iceberg.hetionet.*  (via Trino, both catalogs)
│
├── ontop/
│   ├── postgres.properties        # JDBC -> Postgres        (rung 2)
│   └── trino.properties           # JDBC -> Trino           (rungs 3 & 4)
│
├── trino/
│   └── catalog/
│       ├── postgresql.properties  # Trino postgresql connector -> Postgres  (rung 4)
│       └── iceberg.properties     # Trino iceberg connector -> Nessie catalog + MinIO/S3  (rung 3, chosen: Nessie)
│
├── queries/                        # hand-written SPARQL. NO generator. Query files are topology-agnostic; the rung each exercises is mapped here + in the pytest markers.
│   ├── q01_list_compounds.rq       # rung 3  — single Iceberg source
│   ├── q02_disease_associates_gene.rq   # rung 2  — single Postgres source
│   ├── q03_compound_binds_gene.rq  # rung 4  — cross-store (compound+edge@Iceberg ⋈ gene@Postgres)
│   ├── q04_compound_treats_disease.rq   # rung 4  — cross-store (compound+edge@Iceberg ⋈ disease@Postgres)
│   ├── q05_count_genes.rq          # rung 2  — COUNT aggregate
│   ├── q06_count_compounds.rq      # rung 3  — COUNT over Iceberg
│   ├── q07_gene_two_hop.rq         # rung 4  — 2-hop crossing the boundary twice
│   └── q08_smoke.rq                # rung 0  — SELECT * ... LIMIT 1 endpoint liveness
│
└── harness/
    ├── run_query.py               # POST a .rq to an endpoint (ontop|ground_truth), return bindings as rows
    ├── parity.py                  # diff Ontop vs ground truth on the LABEL projection; report fidelity loss
    └── test_rungs.py              # pytest: one parametrized test per rung over its query set
```

take qyeries / questions as indicative. Use same rationale to test different rungs, try to reutilize questions, only if possible, from: biomedical-rag-bench-question-reference/questions.jsonl

## Store layout (the slice)

| Table                        | Store             | Populated from                       | Role                         |
|------------------------------|-------------------|--------------------------------------|------------------------------|
| `gene`                       | Postgres          | nodes.tsv where kind=Gene            | node                         |
| `disease`                    | Postgres          | nodes.tsv where kind=Disease         | node                         |
| `compound`                   | Iceberg (MinIO)   | nodes.tsv where kind=Compound        | node                         |
| `gene_disease_association`   | Postgres          | edges.sif where metaedge=DaG         | single-store edge (rung 2)   |
| `compound_gene_binding`      | Iceberg (MinIO)   | edges.sif where metaedge=CbG         | cross-store edge, lake-side  |
| `compound_disease_treatment` | Iceberg (MinIO)   | edges.sif where metaedge=CtD         | cross-store edge, lake-side  |

Both compound edges sit in Iceberg with `compound`, so each crosses to gene/disease in Postgres —
that is the rung-4 federation. `gene_disease_association` stays single-store (Postgres).

Edge tables are named as relational junction/association tables (`<pair>_<relationship-noun>`),
not by their Hetionet metaedge abbreviation. Association columns are entity-semantic and follow the
edge's own direction: `(disease_id, gene_id)`, `(compound_id, gene_id)`, `(compound_id, disease_id)`.

Metaedge abbreviations (`DaG`, `CbG`, `CtD`) must be confirmed against `metaedges.tsv` before
filtering — do not assume casing.

## Rung ladder (build in this order)

| Rung | Path                                   | Proves                                    | Query set     |
|------|----------------------------------------|-------------------------------------------|---------------|
| 0    | SPARQL → Ontop (Postgres, tiny load)   | endpoint boots, one binding, errors surface | q08          |
| 2    | SPARQL → Ontop → Postgres              | single relational source, parity on labels  | q02, q05     |
| 3    | SPARQL → Ontop → **Trino** → Iceberg   | lakehouse source (Iceberg needs an engine)  | q01, q06     |
| 4    | SPARQL → Ontop → Trino → (PG + Iceberg) | true polyglot federation, cross-store joins | q03, q04, q07 |

There is no rung 1 and no "Ontop → Iceberg direct" rung: Iceberg is a table format with no
query engine, so Trino appears the moment Iceberg does. Ship `v0.1.0` at rung 4; keep rungs
0/2/3 runnable as compose profiles afterward for bisecting failures.
