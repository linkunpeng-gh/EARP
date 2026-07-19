UV ?= uv
export EARP_DATABASE_URL ?= postgresql+psycopg://earp_app:earp_app@localhost:5433/earp
export EARP_MIGRATION_DATABASE_URL ?= postgresql+psycopg://postgres:postgres@localhost:5433/earp

.PHONY: db-up db-down migrate api dev test lint openapi spike squawk

db-up:
	docker compose up -d --wait

db-down:
	docker compose down -v

migrate:
	$(UV) run alembic upgrade head
	$(UV) run python -m earp_server.infra.queue_schema

api:
	$(UV) run python -m earp_server.entrypoints.api

dev: db-up migrate api

test:
	$(UV) run pytest -q

lint:
	$(UV) run ruff check src tests spikes
	$(UV) run ruff format --check src tests spikes
	$(UV) run pyright
	$(UV) run lint-imports

openapi:
	$(UV) run python -m earp_server.export_openapi > openapi.yaml

spike:
	$(UV) run python spikes/procrastinate_spike.py --workers 2 --tasks 100

squawk:
	$(UV) run alembic upgrade head --sql > /tmp/earp-migration.sql 2>/dev/null && \
	(command -v squawk >/dev/null && squawk /tmp/earp-migration.sql || echo "squawk not installed - skipped (CI runs it)")
