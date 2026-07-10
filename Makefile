# VKG connectivity harness. Secrets/config live in secrets/.env; compose reads it via --env-file.
# Build rung by rung (CLAUDE.md): rung 0 = Ontop -> Postgres liveness.

COMPOSE := docker compose --env-file secrets/.env
PY := .venv/bin/python
PIP := .venv/bin/pip
PG_DRIVER := ontop/jdbc/postgresql-42.7.4.jar
TRINO_DRIVER := ontop/jdbc/trino-jdbc-478.jar   # matches trinodb/trino:478 in docker-compose.yml

.PHONY: venv deps up-rung0 down ps logs test-rung0 smoke ui sql clean \
        fetch tables load-postgres up-rung2 test-rung2 parity parity-detail ui-app \
        up-rung3 load-iceberg test-rung3 parity-rung3

venv:
	test -d .venv || python3 -m venv .venv
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -e ".[dev]"

$(PG_DRIVER):
	mkdir -p ontop/jdbc
	curl -fsSL -o $@ https://repo1.maven.org/maven2/org/postgresql/postgresql/42.7.4/postgresql-42.7.4.jar

$(TRINO_DRIVER):
	mkdir -p ontop/jdbc
	curl -fsSL -o $@ https://repo1.maven.org/maven2/io/trino/trino-jdbc/478/trino-jdbc-478.jar

deps: venv $(PG_DRIVER) $(TRINO_DRIVER)   # venv + pinned Postgres & Trino JDBC drivers Ontop mounts

up-rung0: $(PG_DRIVER)    # bring up Postgres + Ontop (rung 0)
	$(COMPOSE) --profile rung0 up -d

down:                     # stop/remove containers across ALL rung profiles (keeps volumes)
	$(COMPOSE) --profile "*" down   # every service is profile-gated; plain `down` would skip them

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f --tail=120

test-rung0: venv         # liveness: q08 returns a binding
	$(PY) -m pytest -m rung0 -q

smoke: venv              # run q08 against Ontop, print rows + telemetry
	$(PY) -m harness.run_query ontop queries/q08_smoke.rq

# --- rung 2: Ontop -> Postgres, full slice, parity vs ground truth -------------------------------
fetch: venv              # download Hetionet TSVs into data/ (idempotent; edits via ingest.fetch --force)
	$(PY) -m ingest.fetch

tables: fetch            # filter TSVs -> per-table slice CSVs (data/hetionet/tables/)
	$(PY) -m ingest.build_tables

load-postgres: tables    # create rung-2 schema + COPY the slice into Postgres (needs postgres up)
	$(PY) -m ingest.load_postgres

up-rung2: $(PG_DRIVER)   # Postgres + Ontop with the full mapping (edited mapping? `make down` first)
	$(COMPOSE) --profile rung2 up -d

test-rung2: venv         # label parity for q02/q05 vs the GraphDB ground truth (both endpoints up)
	$(PY) -m pytest -m rung2 -q

parity: venv             # print the per-query Ontop-vs-ground-truth diff (q02, q05)
	$(PY) -m harness.parity q02 q05

parity-detail: venv      # same, but side-by-side rows + per-endpoint telemetry
	$(PY) -m harness.parity --detail q02 q05

# --- rung 3: Ontop -> Trino -> Iceberg (compound), parity vs ground truth -------------------------
# Switching rungs shares Ontop's host port :7300 — run `make down` first if another rung is up.
up-rung3: $(TRINO_DRIVER)   # minio + nessie + trino + Ontop(->Trino); blocks until Trino is healthy
	$(COMPOSE) --profile rung3 up -d

load-iceberg: tables       # create iceberg.hetionet schema + compound table via Trino, INSERT slice
	$(PY) -m ingest.load_iceberg

test-rung3: venv           # label parity for q01/q06 vs the GraphDB ground truth (stack up + loaded)
	$(PY) -m pytest -m rung3 -q

parity-rung3: venv         # per-query Ontop-vs-ground-truth diff (q01, q06); add --detail by hand
	$(PY) -m harness.parity q01 q06

UI_HOST_PORT ?= 7400
ui-app: venv             # local compare UI: virtual vs materialized + SQL translation (needs stack up)
	@echo "Compare UI: http://localhost:$(UI_HOST_PORT)/  (Ctrl+C to stop)"
	@UI_HOST_PORT=$(UI_HOST_PORT) $(PY) -m ui.server

ui:                      # the SPARQL console is Ontop's built-in YASGUI
	@set -a; . ./secrets/.env; set +a; echo "Ontop SPARQL console (YASGUI): http://localhost:$${ONTOP_HOST_PORT:-7300}/"
	@echo "This 5.5.0 YASGUI has no SQL view; see the SPARQL->SQL rewrite with 'make sql Q=<file.rq>'."

Q ?= queries/q02_disease_associates_gene.rq
sql:                     # print the SQL Ontop generates for a query: make sql Q=queries/q05_count_genes.rq
	@set -a; . ./secrets/.env; set +a; \
	curl -s -G "http://localhost:$${ONTOP_HOST_PORT:-7300}/ontop/reformulate" --data-urlencode "query@$(Q)"

clean:                   # tear down and drop the pgdata volume (forces re-seed on next up)
	$(COMPOSE) down -v
