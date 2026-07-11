# virtual-knowledge-graph-connectivity

A **Virtual Knowledge Graph (VKG)** reference setup that exercises the *plumbing* of an **Ontology-Based Data Access (OBDA)** architecture over a simulated brownfield analytics stack.
Proves one hand-written SPARQL query resolves unchanged across federated relational + lakehouse sources, validated against a **Materialized Knowledge Graph** ground truth.

## Table of Contents

- [The landscape](#the-landscape)
  - [Components](#components)
- [Ontology (TBox)](#ontology-tbox)
- [Architecture](#architecture)
- [OBDA mapping](#obda-mapping)
- [Virtual vs Materialized Knowledge Graph Results](#virtual-vs-materialized-knowledge-graph-results)
- [Compare UI - Virtual vs Materialized](#compare-ui---virtual-vs-materialized)
- [Information Model on Sources (ERD)](#information-model-on-sources-erd)
  - [Gene Disease Registry - PostgreSQL - ABox](#gene-disease-registry---postgresql---abox)
  - [Drug Lake - Lakehouse (Iceberg, Nessie, MinIO)](#drug-lake---lakehouse-iceberg-nessie-minio)
  - [Combined — where federation happens](#combined--where-federation-happens)
- [The ground truth](#the-ground-truth)
- [Running it](#running-it)

## The landscape

The tech stack at this repo mirrors a brownfield analytics enterprise setup.
The information model is deliberately tiny, three entities and their relationships, to keep the focus on connectivity rather than business rules.
The information model is a slice of [Hetionet](https://het.io/) ([hetio/hetionet](https://github.com/hetio/hetionet)).

![hetionet-metagraph](_resources/README.md/hetionet-metagraph.png)

### Components

| Purpose | Technology / tool |
|---|---|
| SPARQL Parity Console | Python console app; hits both graphs |
| SPARQL Compare UI | HTML + stdlib Python server (`ui/server.py`); hits both graphs |
| SPARQL endpoint + SPARQL→SQL rewriting | **[Ontop](https://ontop-vkg.org/)** |
| Relational to RDF mapping | **[OBDA](https://ontop-vkg.org/guide/advanced/mapping-language.html)** mapping files (`mappings/*.obda`) |
| SQL federation across sources | **[Trino](https://trino.io/)** |
| Gene Disease Registry  | **[PostgreSQL](https://www.postgresql.org/)** RDBMS |
| Drug Lake   | **Lakehouse** (Iceberg·Nessie·MinIO) |
| Lakehouse table format | **[Apache Iceberg](https://iceberg.apache.org/)** |
| Lakehouse catalog | **[Nessie](https://projectnessie.org/)** |
| Lakehouse Object storage | **[MinIO](https://min.io/)** (S3-compatible) |
| Ground truth store | **[GraphDB](https://www.ontotext.com/products/graphdb/)** (external, not served) |

## Ontology (TBox)

The slice is three classes and minimal properties. 
Reasoning is **off**, so `rdfs:domain`/`rdfs:range` here are documentation of intent, not inference rules.


```mermaid
graph LR
    Compound -- binds --> Gene
    Compound -- treats --> Disease
    Disease  -- associates --> Gene
```

```turtle
@prefix hetio: <https://het.io/schema/> .
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl:   <http://www.w3.org/2002/07/owl#> .

hetio:Gene     a owl:Class .
hetio:Disease  a owl:Class .
hetio:Compound a owl:Class .

hetio:associates a owl:ObjectProperty ;   # Disease–associates–Gene   (DaG)
    rdfs:domain hetio:Disease  ; rdfs:range hetio:Gene .
hetio:binds      a owl:ObjectProperty ;   # Compound–binds–Gene       (CbG)
    rdfs:domain hetio:Compound ; rdfs:range hetio:Gene .
hetio:treats     a owl:ObjectProperty ;   # Compound–treats–Disease   (CtD)
    rdfs:domain hetio:Compound ; rdfs:range hetio:Disease .
```

## Architecture

SPARQL clients the **compare UI** and the **parity console** hit **one** Ontop endpoint. 

Ontop reads `polyglot.obda` and rewrites SPARQL to SQL against Trino. The mapping is configuration
Ontop consults locally to build that SQL — it is not a network hop, so it never sits between Ontop
and Trino on the wire; the dashed "reads" edge below is a config dependency, not a data-flow step.

Trino is the federation engine and the SQL entry for both the **Drug Lake (Iceberg lakehouse)** and the **Gene–Disease Registry (PostgreSQL)**. 

One **GraphDB instance** (dashed, below) sits off the serving connectivity path; its only purpose is to be the equivalent RDFS Materialized Knowledge Graph the compare UI and parity console diff results against.

It was stood up as part of [biomedical-rag-bench](https://github.com/joseph-higaki/biomedical-rag-bench/tree/v1.1.1).


```mermaid
flowchart TB
    ui["Compare UI<br/>ui/server.py + browser"]
    cmp["Parity engine<br/>harness/parity.py"]

    ontop(["Ontop — SPARQL endpoint :7300<br/>SPARQL to SQL rewriter"])
    obda[/"polyglot.obda<br/>OBDA relational-to-RDF mapping"/]

    subgraph LAKE["Drug Lake — lakehouse source"]
        trino["Trino<br/>query and federation engine"]
        nessie["Nessie<br/>Iceberg catalog"]
        iceberg["Apache Iceberg — table format<br/>compound · compound_gene_binding · compound_disease_treatment"]
        minio[("MinIO / S3<br/>object storage")]
    end

    pg[("Gene–Disease Registry — PostgreSQL<br/>gene · disease · gene_disease_association")]
    gdb[("GraphDB — materialized ABox<br/>ground truth, external")]

    ui  -->|SPARQL| ontop
    cmp -->|SPARQL| ontop
    ui  -.->|parity baseline| gdb
    cmp -.->|parity baseline| gdb

    ontop -.->|reads| obda
    ontop -->|SQL over JDBC| trino

    trino -->|postgresql catalog| pg
    trino -->|iceberg catalog| nessie
    trino -->|native S3| minio
    nessie -.->|table pointers| iceberg
    iceberg -.->|data files| minio

    classDef entry fill:#2563eb,stroke:#1e3a8a,color:#ffffff,stroke-width:2px;
    classDef optional fill:#eeeeee,stroke:#888888,color:#333333,stroke-dasharray:4 4;
    class ontop entry;
    class gdb optional;
```


## OBDA mapping

An **OBDA mapping** is the relational to RDF bridge Ontop uses to rewrite SPARQL into SQL. 

Each `mappingId` is a *triple map*: a **target** RDF template (with `{column}` placeholders) fed by a
**source** SQL query. Ontop never materializes these triples — it composes the maps with the
incoming SPARQL and pushes one SQL query down to the sources.

Each source query uses a fully-qualified Trino identifier (`postgresql.public.*` vs `iceberg.hetionet.*`), which is what lets a single SPARQL query span both stores.
(`iceberg` is the Trino catalog; `hetionet` is the Iceberg schema.)

```
mappingId	compound
target		<https://het.io/compound/{id}> a hetio:Compound ; rdfs:label {name}^^xsd:string .
source		SELECT id, name FROM iceberg.hetionet.compound

mappingId	compound_binds_gene
target		<https://het.io/compound/{compound_id}> hetio:binds <https://het.io/gene/{gene_id}> .
source		SELECT compound_id, gene_id FROM iceberg.hetionet.compound_gene_binding

mappingId	gene
target		<https://het.io/gene/{id}> a hetio:Gene ; rdfs:label {name}^^xsd:string .
source		SELECT id, name FROM postgresql.public.gene
```

The `compound` node + `compound_binds_gene` edge resolve to the Iceberg catalog; `gene` resolves to
Postgres. A SPARQL query touching `hetio:binds` therefore forces Trino to join across both — see
`mappings/polyglot.obda` for the full file.

## Virtual vs Materialized Knowledge Graph Results

The VKG is **correct if it returns the same bindings as the GraphDB ground truth**, compared on the
**label projection** (the human-readable `?xLabel` columns). 

Entity IRIs are *not* compared — Ontop mints its own scheme (`https://het.io/…`) while the GraphDB ground truth uses `ncbigene:`/`do:` URIs. Reconciling those is a benchmark-integration concern, not a connectivity one. Queries bind entities **by label, not by IRI**, so one `.rq` runs unchanged on both endpoints and the parity comparison never sees an IRI.

**Reconciling IRIs is a much bigger problem; this repo tackles only tooling and connectivity.**

## Compare UI - Virtual vs Materialized

`make ui-app` serves a local page (<http://localhost:7400/>) that runs one query against **both**
engines side by side: the **Virtual** VKG (Ontop → Trino → ( Postgres + Iceberg) ) vs the
**Materialized** GraphDB, each endpoint's telemetry, a latency bar, the parity verdict, and the SQL
Ontop pushed down. 

![Compare UI — Virtual vs Materialized, Raw ↔ Labels toggle](_resources/README.md/image-1-imageonline.co-merged.png)


## Information Model on Sources (ERD)

**Dashed** relationships are **cross-store** — a foreign key whose target table lives in the *other* database, which no RDBMS enforces.

**Those dashed edges are the joins Trino federates**.

### Gene Disease Registry - PostgreSQL - ABox

```mermaid
erDiagram
    GENE {
        text id PK
        text name
    }
    DISEASE {
        text id PK
        text name
    }
    GENE_DISEASE_ASSOCIATION {
        text disease_id FK "-> disease.id"
        text gene_id FK "-> gene.id"
    }

    DISEASE ||--o{ GENE_DISEASE_ASSOCIATION : "associates (disease_id)"
    GENE    ||--o{ GENE_DISEASE_ASSOCIATION : "gene_id"
```

### Drug Lake - Lakehouse (Iceberg, Nessie, MinIO)

```mermaid
erDiagram
    COMPOUND {
        text id "no key enforcement"
        text name
    }
    COMPOUND_GENE_BINDING {
        text compound_id "-> compound.id"
        text gene_id "-> gene.id (in Postgres)"
    }
    COMPOUND_DISEASE_TREATMENT {
        text compound_id "-> compound.id"
        text disease_id "-> disease.id (in Postgres)"
    }
    GENE {
        text id "resides in Postgres"
    }
    DISEASE {
        text id "resides in Postgres"
    }

    COMPOUND ||--o{ COMPOUND_GENE_BINDING : "binds (compound_id)"
    GENE     ||..o{ COMPOUND_GENE_BINDING : "gene_id: cross-store, unenforced"
    COMPOUND ||--o{ COMPOUND_DISEASE_TREATMENT : "treats (compound_id)"
    DISEASE  ||..o{ COMPOUND_DISEASE_TREATMENT : "disease_id: cross-store, unenforced"
```

### Combined — where federation happens

Solid edges stay inside one store; the two dashed edges cross the boundary and are exactly what
Trino federates. Node tables are cylinders, association (junction) tables are parallelograms.

```mermaid
flowchart TB
    subgraph PG["PostgreSQL"]
        gene[("gene")]
        disease[("disease")]
        gene_disease_association[/"gene_disease_association"/]
    end
    subgraph ICE["Iceberg (MinIO)"]
        compound[("compound")]
        compound_gene_binding[/"compound_gene_binding"/]
        compound_disease_treatment[/"compound_disease_treatment"/]
    end

    disease -->|associates| gene_disease_association --> gene
    compound -->|binds| compound_gene_binding
    compound_gene_binding -.->|"binds: cross-store join (Trino)"| gene
    compound -->|treats| compound_disease_treatment
    compound_disease_treatment -.->|"treats: cross-store join (Trino)"| disease
```

## The ground truth 

By default the harness points at your **existing biomedical-rag-bench GraphDB** (`GROUND_TRUTH_SPARQL_URL` in
`secrets/.env`, base `http://localhost:7200/`). Because that graph and the SQL tables come from different provenance paths, parity is compared on labels. For a clean-provenance local baseline, a
smoke (partial) and full ABox RDF are under `data/hetionet/rdf/`.

## Running it

All run commands — the rung ladder and per-layer `make` targets — are documented in [docs/how-to-run-ui.md](docs/how-to-run-ui.md) and [docs/staggered-execution.md](docs/staggered-execution.md).

