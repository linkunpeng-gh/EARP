UV ?= uv
export EARP_DATABASE_URL ?= postgresql+psycopg://earp_app:earp_app@localhost:5433/earp
export EARP_MIGRATION_DATABASE_URL ?= postgresql+psycopg://postgres:postgres@localhost:5433/earp

.PHONY: db-up db-down migrate api dev test lint openapi spike squawk e2e audit-worker plugin-daemon

db-up:
	# langfuse:3 需要 ClickHouse，本仓库 compose 未提供；它是可选可观测性服务，
	# 不参与核心 dev 栈，故这里只等待 pg/valkey/minio（langfuse 单独需要时再拉）。
	docker compose up -d --wait pg valkey minio

db-down:
	docker compose down -v

migrate:
	$(UV) run alembic upgrade head
	$(UV) run python -m earp_server.infra.queue_schema

api:
	$(UV) run python -m earp_server.entrypoints.api

dev:
	$(UV) run uvicorn earp_server.main:create_app --factory --reload

test:
	$(UV) run pytest -q --ignore=tests/test_rbac_scenarios.py

lint:
	$(UV) run ruff check src tests --fix -q
	$(UV) run ruff format src tests -q
	$(UV) run pyright

openapi:
	$(UV) run python -m earp_server.export_openapi > openapi.yaml

spike:
	$(UV) run python spikes/procrastinate_spike.py --workers 2 --tasks 100

squawk:
	$(UV) run alembic upgrade head --sql > /tmp/earp-migration.sql 2>/dev/null && \
	(command -v squawk >/dev/null && squawk /tmp/earp-migration.sql || echo "squawk not installed - skipped (CI runs it)")

e2e:
	$(UV) run pytest tests/test_e2e.py -v --tb=short

audit-worker:
	$(UV) run python -m earp_server.entrypoints.audit

plugin-daemon:
	$(UV) run python -m earp_server.entrypoints.plugin_daemon
