# Decision: Trino is the polyglot layer, not Ontop

**Status: decided.**

## Context

Real analytics initiatives are **brownfield**: the operational Postgres already exists for some other
purpose, and Trino is introduced later to reach the lakehouse. This harness deliberately mirrors that —
a VKG has to span a pre-existing Postgres *and* Iceberg without re-platforming either. So the polyglot
question is not "what do we build," it is where the **cross-source join** lands, and it has a specific
brownfield shape:

- **Does Ontop talk to both** — a Postgres-mapped endpoint and a Trino-mapped endpoint — federating them
  itself? or
- **Does Trino adopt the non-related Postgres** as a catalog and become the single SQL entry layer, with
  Ontop bound only to Trino?

The two candidates are built for different jobs:

- **Ontop is a rewriter, not a federation engine.** Its production model binds **one JDBC connection to
  one SQL source**; it has no distributed executor or cross-source join planner. Its engine is the source.
- **Trino is a federation engine.** Many catalogs behind one SQL surface, cost-based optimization,
  per-connector pushdown, Iceberg partition pruning.

## Decision

**Trino adopts the pre-existing Postgres and the Iceberg lakehouse as catalogs and becomes the single SQL
entry layer.** Ontop binds to one source — Trino — and never points at two JDBC sources. Adopting a
non-related operational Postgres is a real coupling decision, accepted deliberately (see Consequences).

## Why

- **Iceberg forces a query engine — decisive.** `compound` / `compound_disease_treatment` live in
  Iceberg-on-MinIO, a table *format* with no query server. Ontop has no engine and cannot read it at all,
  so Trino is non-negotiable for the lakehouse leg regardless. Once it exists, making it *the* polyglot
  layer is the parsimonious move — no second federation mechanism.
- **The cross-boundary join must live in a real engine.** Any query joining a Postgres-backed entity to an
  Iceberg-backed one needs a cost-based, distributed joiner. Trino is built for exactly that; the source
  databases can't (they don't see each other), and the graph layer shouldn't (next section).
- **It is Ontop's own recommendation.** Ontop's documented way to span multiple databases is its
  "Federating multiple databases" path: put a federation engine underneath and let Ontop see one virtual
  database. Trino/Presto/Athena are first-class there since **Ontop 5.0.2** (this repo runs 5.5.0).
  Pointing one Ontop at multiple JDBC sources is *not* a supported path.
- **One SQL entry layer, one governance chokepoint.** A single Trino surface is also the single place to
  enforce access control and propagate identity (see `enterprise-auth-findings.md`). Two federated
  endpoints would split that surface in two.

## The alternative — Ontop federates (SPARQL `SERVICE`), and why it is costly

"Ontop talks to both" is not one Ontop with two connections (stock Ontop is single-source). It is **two
Ontop endpoints** — one on Postgres, one on Trino — federated at query time with SPARQL 1.1 `SERVICE`.
The consequence: the Postgres↔Iceberg join executes **in the graph layer**, not in SQL. The SPARQL
federation engine has no cost-based optimizer, no distributed hash/merge join, and no cross-boundary
pushdown — it pulls bindings from one endpoint and probes the other, roughly a nested loop. That is the
most expensive way to run a large relational join, and it degrades with data size exactly where it hurts
most. So `SERVICE` federation is rejected whenever queries cross the boundary; it is only reasonable when
the subgraphs are genuinely disjoint (nothing joins across sources), where it is the lighter, lower-
coupling option.

The same cross-boundary query — "compounds and the diseases they treat" — written both ways (prefixes and
predicate IRIs illustrative; the mapping defines the exact vocabulary):

<table>
<tr>
<th align="left">1 · Seamless — Trino is the entry layer (one graph)</th>
<th align="left">2 · Federated — SPARQL <code>SERVICE</code> across two endpoints</th>
</tr>
<tr>
<td valign="top">

```sparql
PREFIX hetio: <https://het.io/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?compoundLabel ?diseaseLabel WHERE {
  ?c a hetio:Compound ;        # Iceberg
     rdfs:label ?compoundLabel ;
     hetio:treats ?d .         # CtD (Iceberg)
  ?d a hetio:Disease ;         # Postgres
     rdfs:label ?diseaseLabel .
}
```

</td>
<td valign="top">

```sparql
PREFIX hetio: <https://het.io/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

# issued against the Iceberg-backed endpoint
SELECT ?compoundLabel ?diseaseLabel WHERE {
  ?c a hetio:Compound ;
     rdfs:label ?compoundLabel ;
     hetio:treats ?d .         # CtD (Iceberg)

  SERVICE <http://ontop-pg:8080/sparql> {
    ?d a hetio:Disease ;       # Postgres
       rdfs:label ?diseaseLabel .
  }
}
```

</td>
</tr>
</table>

In **#1** the store split is invisible: `?d` ties the Iceberg compound to the Postgres disease and Trino
resolves the join in one SQL plan. In **#2** the split is explicit — the `SERVICE` block names the other
endpoint, and the engine ships each `?d` binding from Iceberg over to the Postgres endpoint to resolve its
label. That per-binding probe (the nested loop) is what makes the graph-layer join expensive.

## Consequences (accepted trade-offs)

- **Coupling to a non-related operational Postgres.** Trino can now issue heavy scans against a
  transactional DB to feed cross-catalog joins. Mitigate by pointing Trino at a read replica, or by
  landing the needed tables in the lakehouse via CDC so Trino never touches the OLTP source — a
  freshness-vs-isolation choice, out of scope here.
- **Two optimizers in series** (SPARQL→SQL in Ontop, SQL→execution in Trino): perf debugging means reading
  both Ontop's rewrite and Trino's `EXPLAIN`. The upside of that seam is that federation is verifiable —
  an `EXPLAIN` showing both catalogs scanned proves the join lives in Trino.
- Extra hop and coordinator planning overhead — real cost on tiny point queries, accepted because Trino is
  required for Iceberg anyway.
- A cross-catalog join materializes at least one side in Trino, forgoing the source DB's own indexed join.

## References

- [`enterprise-auth-findings.md`](./enterprise-auth-findings.md) — auth/identity at each hop of this topology.
- Ontop — [Federating multiple databases](https://ontop-vkg.org/tutorial/federation/) (federation engine underneath a single Ontop; Trino/Presto/Athena supported since 5.0.2).
