# Authentication & identity at each integration point — enterprise findings

**Status: finding, not implemented.** The harness stays deliberately no-auth: it is local-first and
tests *one* variable (serving topology), so every credential here is a docker-compose dev default.
This document records what an enterprise deployment would have to add at each hop, so the gap is
written down rather than rediscovered. Nothing below changes the rungs.

## Headline finding — identity propagation is the whole problem

Ontop is a pure SPARQL→SQL rewriter and connects downstream over **one pooled service connection**
(`jdbc.user=trino`, or a single `ONTOP_DB_USER`). The end user's identity dies at the SPARQL
endpoint. Every fine-grained-access-control engine below (Trino file/OPA/Ranger, Postgres RLS)
keys its policy on the principal it sees — so with a shared connection they can only enforce *one*
policy for the whole world.

The enterprise answer is **option B: propagate the caller's identity end-to-end.**

1. An **authenticating gateway in front of Ontop** establishes the end-user identity (OIDC/JWT or
   mTLS) — OSS Ontop has no built-in authN/authZ, so this is the only place identity can originate.
2. Ontop (or the gateway) connects to Trino as a **trusted service principal**, then sets the
   **session user to the end user** via the Trino JDBC `sessionUser` property / HTTP `X-Trino-User`
   header. Trino gates this with impersonation rules in its system access control, then evaluates
   FGAC *as the end user*, not the service account. This is the "custom header" mechanism.

The unimplemented piece: OSS Ontop sets a **static** `jdbc.user`. Per-request `sessionUser`
injection needs either the fronting gateway to rewrite the header per request, or a custom Ontop
connection provider. That is the core build cost of B, and there is no OSS-Ontop shortcut around it.

## Integration points

| # | Integration point | Rung | This repo's approach (dev default) | Enterprise recommendation |
|---|---|---|---|---|
| 1 | **Client → Ontop** SPARQL endpoint | 0/2/3/4 | No authN. Open `/sparql` on :7300, `CORS *`, `ONTOP_DEV_MODE=true`. Anyone on the network queries freely. | Front Ontop with an authenticating gateway/reverse proxy: OIDC/OAuth2 bearer (JWT) or mTLS, TLS-terminated, CORS locked to known origins. **Identity originates here** and must be propagated down (see Finding). OSS Ontop has no auth of its own. |
| 2 | **Ontop → PostgreSQL** (direct) | 0/2 | Single service account; `ONTOP_DB_USER/PASSWORD` injected from `secrets/.env`; plaintext, no TLS. | Least-privilege read-only role scoped to the mapped tables/columns; short-lived creds from a secrets manager (Vault), not a static password; `sslmode=verify-full`. **Identity gap:** Ontop's pooled connection can't impersonate per query, so per-user Postgres RLS is unreachable through OSS Ontop — accept persona/role granularity, or route this rung through a policy engine too. |
| 3 | **Ontop → Trino** | 3/4 | `jdbc.user=trino`, no password, Trino no-auth, no TLS. Any non-empty username accepted. | Enable Trino authN (OAuth2/JWT/PASSWORD/Kerberos) over HTTPS; Ontop connects as a trusted **service principal**. Propagate the end user via JDBC `sessionUser` / `X-Trino-User`, gated by Trino impersonation rules; Trino then applies FGAC (file/OPA/Ranger) as the end user. **This is the linchpin hop for option B** — and the one requiring custom work (static `jdbc.user` → per-request session user). |
| 4 | **Trino → Nessie** (Iceberg catalog metadata) | 3/4 | Anonymous REST v2 (`http://nessie:19120/api/v2`), no creds, no TLS, `IN_MEMORY` version store. | Nessie behind OIDC; Trino's Nessie catalog presents a bearer token; persistent version store (JDBC/RocksDB); TLS. Nessie **authorization** governs who commits to `main` — branch-level *data governance*, not query FGAC. ⚠ Confirm the exact Trino Nessie-catalog auth property names against the pinned Trino/Nessie versions — version-sensitive. |
| 5 | **Trino → object store** (MinIO/S3, Iceberg data) | 3/4 | MinIO **root** credentials via `${ENV:...}`, static, `http://` (no TLS), path-style. | Scoped least-privilege access keys, ideally **temporary credentials** (STS/AssumeRole, IRSA on EKS); TLS; per-bucket policy; SSE-KMS at rest; rotation via secrets manager. **Granularity ceiling:** object-store policy is table/prefix-level at best — **row/column FGAC cannot live here, it must be Trino.** This hop carries *Trino's* identity, never the end user's. |
| 6 | **Trino → PostgreSQL catalog** | 4 | ⚠ **PLACEHOLDER — `trino/catalog/postgresql.properties` does not exist yet (rung 4). Fill in this cell when the rung lands; do not assume the credential model.** | Least-privilege PG role for the connector; TLS; secrets-manager creds. For end-user pass-through, check whether the pinned Trino PostgreSQL connector supports user-credential pass-through (`user-credential-name` / extra credentials); otherwise per-user policy stays at the Trino engine layer via impersonation (row 3). Confirm connector capabilities when implementing. |

Notes on topology not shown as rows:

- **Nessie → object store:** none in this setup. The `IN_MEMORY` Nessie tracks only catalog pointers;
  **Trino** performs all S3 I/O, so the object-store credential is Trino's (row 5), not Nessie's.
  An enterprise persistent-catalog deployment may give the catalog server its own S3 identity —
  re-evaluate then.
- **Bootstrap `createbuckets` (mc) → MinIO:** uses MinIO root creds to create the `warehouse` bucket
  once at startup. Provisioning, not the serving path; in production this is an infra/IaC step with
  its own scoped admin identity, not a runtime hop.

## Cross-cutting concerns

- **TLS everywhere.** Every hop above is plaintext HTTP/JDBC on the compose network. Production is
  mTLS or TLS-with-verification on all of them; the no-TLS posture is only safe inside a single trust
  boundary.
- **Secrets management.** `secrets/.env` (static, gitignored) is the dev stand-in for a secrets
  manager (Vault/cloud KMS) issuing short-lived, rotated credentials. The repo already keeps
  passwords out of tracked files via `${ENV:...}` / `ONTOP_DB_*` injection — the enterprise change is
  *where the value comes from and how long it lives*, not the injection mechanism.
- **Where FGAC can and cannot be enforced.** Authorization (row/column policy) is downstream of
  authentication: it only becomes *per-user* once identity propagation (B) works. Object storage
  can gate whole tables/prefixes but never rows/columns — so the polyglot rungs' only place for
  uniform row/column FGAC across Postgres + Iceberg is the **Trino** engine (file-based rules, OPA,
  or Ranger). Enforcing there also means a masked/filtered **join key** (e.g. `compound_id`/`gene_id`)
  would silently drop cross-store joins — target policy at label/attribute columns, not join keys.
- **Defense-in-depth vs. bypass.** A policy only at the gateway/Ontop layer is bypassable by anyone
  who can reach Trino or Postgres directly. The lower the enforcement, the harder to bypass but the
  more it is expressed in physical (table/column) rather than semantic (class/predicate) terms.

## Rung-4 placeholder

Row 6 and any rung-4-only credential detail are intentionally left as placeholders. When rung 4 adds
`mappings/polyglot.obda` and `trino/catalog/postgresql.properties`, fill in the "this repo's
approach" cell for the Trino→PostgreSQL catalog hop and revisit whether that connector changes the
identity-propagation story (row 3).

## Sources

- Trino — [File-based access control (row filters, column masks)](https://trino.io/docs/current/security/file-system-access-control.html)
- Trino — [Open Policy Agent access control](https://trino.io/docs/current/security/opa-access-control.html) · [OPA arrived (Trino 438)](https://trino.io/blog/2024/02/06/opa-arrived.html)
- Trino — [JDBC driver (`sessionUser`)](https://trino.io/docs/current/client/jdbc.html) · [SET SESSION AUTHORIZATION / impersonation](https://trino.io/docs/current/sql/set-session-authorization.html)
- Ontop — [Deploying a SPARQL endpoint](https://ontop-vkg.org/tutorial/endpoint/) (no built-in authN/authZ documented)
