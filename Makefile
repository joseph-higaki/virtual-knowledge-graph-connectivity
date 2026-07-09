# VKG connectivity harness. Secrets/config live in secrets/.env; compose reads it via --env-file.
# Build rung by rung (CLAUDE.md): rung 0 = Ontop -> Postgres liveness.

COMPOSE := docker compose --env-file secrets/.env
PY := .venv/bin/python
PIP := .venv/bin/pip
PG_DRIVER := ontop/jdbc/postgresql-42.7.4.jar

.PHONY: venv deps up-rung0 down ps logs test-rung0 smoke ui clean

venv:
	test -d .venv || python3 -m venv .venv
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -e ".[dev]"

$(PG_DRIVER):
	mkdir -p ontop/jdbc
	curl -fsSL -o $@ https://repo1.maven.org/maven2/org/postgresql/postgresql/42.7.4/postgresql-42.7.4.jar

deps: venv $(PG_DRIVER)   # venv + pinned Postgres JDBC driver Ontop mounts

up-rung0: $(PG_DRIVER)    # bring up Postgres + Ontop (rung 0)
	$(COMPOSE) --profile rung0 up -d

down:                     # stop/remove containers (keeps pgdata volume)
	$(COMPOSE) down

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f --tail=120

test-rung0: venv         # liveness: q08 returns a binding
	$(PY) -m pytest -m rung0 -q

smoke: venv              # run q08 against Ontop, print rows + telemetry
	$(PY) -m harness.run_query ontop queries/q08_smoke.rq

ui:                      # the SPARQL console is Ontop's built-in YASGUI
	@set -a; . ./secrets/.env; set +a; echo "Ontop SPARQL console (YASGUI): http://localhost:$${ONTOP_HOST_PORT:-7300}/"
	@echo "Type a query; right-click the editor -> 'View SQL translation' for the SPARQL->SQL rewrite."

clean:                   # tear down and drop the pgdata volume (forces re-seed on next up)
	$(COMPOSE) down -v
