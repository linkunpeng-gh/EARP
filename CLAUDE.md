# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

EARP (Enterprise AI Runtime Platform) is an enterprise AI operating system — a runtime platform for agent development, scheduling, and execution. It integrates multi-model LLM orchestration, workflow DSL, data platform integration, and the full agent engineering lifecycle.

The repo is a **monorepo** containing the backend server (FastAPI modular monolith), admin/user frontends (vanilla HTML/JS), and Python SDK libraries.

## Essential Commands

All commands assume you're in the relevant app/lib directory.

### earp-server (`apps/earp-server/`)

| Task | Command |
|------|---------|
| Start PostgreSQL + Valkey + MinIO + Langfuse | `make db-up` (Docker) |
| Run migrations | `make migrate` |
| Start API server (dev, with reload) | `make dev` |
| Start API server (production) | `make api` |
| Start task worker | `make audit-worker` (or `uv run python -m earp_server.entrypoints.worker`) |
| Start audit worker (Redis Streams consumer) | `make audit-worker` |
| Start plugin daemon | `make plugin-daemon` |
| Start scheduler | `uv run python -m earp_server.entrypoints.scheduler` |
| Run tests (excludes RBAC scenarios) | `make test` |
| Run e2e test only | `make e2e` |
| Run a single test file | `uv run pytest tests/test_m1_walking_skeleton.py -v` |
| Run a single test function | `uv run pytest tests/test_m1_walking_skeleton.py::test_create_session -v` |
| Lint + format + type-check | `make lint` |
| Export OpenAPI spec | `make openapi` |
| Review DB migration SQL | `make squawk` |

Database URL env vars (see `Makefile`):
- `EARP_DATABASE_URL` — default `postgresql+psycopg://earp_app:earp_app@localhost:5433/earp`
- `EARP_MIGRATION_DATABASE_URL` — default `postgresql+psycopg://postgres:postgres@localhost:5433/earp`

Tests use **testcontainers** — a pgvector/pg16 container is auto-started per test session. No local DB needed.

### SDK libraries (`libs/`)

Each SDK is an independent Python package:
- `earp-sdk-core-py` — Core SDK (config, audit, guard, knowledge, masking, feedback, scheduling)
- `earp-sdk-capability-py` — Capability SDK (base classes, CLI, registration, testing harness)
- `earp-sdk-connector-py` — Connector SDK (REST, DB, MCP connectors, testing harness)
- `earp-sdk-plugin-py` — Plugin SDK (sandbox, gRPC, manager, extensions)
- `earp-sdk-runtime-py` — Runtime SDK (session, invoker, events, client)

Each has its own `pyproject.toml`, `.venv`, and `tests/`. Run tests: `uv run pytest`.

## Architecture

### High-Level Structure

```
apps/earp-server/    — Main backend: FastAPI modular monolith
apps/earp-admin/     — Admin web console (vanilla HTML/JS/CSS)
apps/earp-user/      — End-user web app (vanilla HTML/JS/CSS)
libs/                — Python SDKs (5 packages)
arch/                — Architecture docs (L0 philosophy → L3 detailed design)
rules/               — Development rules for the agentic development workflow
prd/                 — Product requirement documents
tasks/               — Task definitions for agent-driven development
sketches/            — Design sketches
scripts/             — Deployment/CI scripts
```

### `earp-server` Modular Monolith

The server is organized as a **modular monolith** — 12 domain modules, each independently verifiable via import-linter contracts. Import rules are enforced at CI.

**Domain modules** (under `src/earp_server/`):

| Module | Purpose |
|--------|---------|
| `gateway` | JWT auth middleware, input sanitization, WebSocket gateway |
| `runtime` | Session CRUD, invoke endpoint, tenant service |
| `capability` | Capability registry + discovery (pgvector semantic search) |
| `planner` | Intent → Plan resolution (LLM via Ollama + rule-based fallback) |
| `orchestrator` | Multi-step execution engine, StepRunner, checkpoint, Saga compensation, retry, workflow DSL |
| `policy` | RBAC permission checks + data scope output filtering |
| `audit` | Audit event consumer, writes to audit_logs table |
| `knowledge` | RAG pipeline: document → chunk → embed → search |
| `conversation` | Conversation + message CRUD |
| `schedule` | Scheduled trigger management |
| `plugin` | Plugin installer (loads from `./plugins/` directory) |
| `mcp` | MCP (Model Context Protocol) server endpoint |
| `connector` | LLM integration (Ollama chat + streaming) and capability adapter execution |
| `infra` | DB engine, EventBus, Redis EventBus, Langfuse tracer, LLM cache, checkpoint store, task queue (Procrastinate) |
| `schemas` | Pydantic request/response models |
| `config` | Pydantic-settings (env prefix: `EARP_`) |

**Cross-cutting rules**: Import exceptions between domains are declared in `pyproject.toml` under `[tool.importlinter.contracts]`. If you need a new cross-domain import, add an `ignore_imports` entry explaining why.

### Entrypoints (Process Model)

The server runs as **5 independent processes**, each with its own `entrypoints/` module:

1. **API** (`entrypoints/api.py`) — uvicorn serving the FastAPI app (port 8000)
2. **Worker** (`entrypoints/worker.py`) — Procrastinate task queue worker (async jobs)
3. **Audit Worker** (`entrypoints/audit.py`) — consumes execution events from Redis Streams → PostgreSQL audit_logs
4. **Scheduler** (`entrypoints/scheduler.py`) — DB-driven trigger loop (idle skeleton in M0)
5. **Plugin Daemon** (`entrypoints/plugin_daemon.py`) — standalone HTTP server hosting sandboxed plugin execution (port 9100)

### Tenant Isolation (RLS)

Multi-tenancy uses **PostgreSQL Row-Level Security (RLS)**. Every tenant-scoped table has `tenant_id`. The app sets `SET LOCAL earp.tenant_id` at the start of each request/transaction. In dev/test, use the `tenant_session()` context manager which applies this automatically.

Two DB roles:
- `postgres` (migrations, BYPASSRLS) — via `EARP_MIGRATION_DATABASE_URL`
- `earp_app` (application, FORCE RLS active) — via `EARP_DATABASE_URL`

When writing new data-access code, prefer `tenant_session(engine, tenant_id)` over manual `engine.connect()` + `SET LOCAL`.

### Orchestrator Execution Model

The orchestrator is the core execution engine:

- **`StepRunner`** — executes a single Step (capability call) with Layer hooks (before/after), writes checkpoint on completion
- **`MultiStepExecutor`** — executes a Plan (list of Steps) sequentially with checkpoint-after-each-step, recovery from checkpoint, retry, and Saga compensation
- **Layers** (middleware chain): `AuditLayer` → `PolicyLayer` → [execute] → `PolicyLayer(after)` → `AuditLayer(after)`
- **Execution states**: PENDING → RUNNING → COMPLETED / FAILED / INTERRUPTED / ROLLED_BACK / REPLANNING
- **Saga compensation**: Steps can declare `compensate_call` for rollback on failure

### LLM Integration

`LLMConnector` in `connector.py` is the unified LLM interface:
- **plan(prompt)** — structured JSON output via Ollama `/api/chat` with `format: "json"`, with Redis/memory cache, dynamic capability injection, and fallback to `RuleIntentPlanner`
- **stream(prompt)** — token-by-token streaming via Ollama with `stream: true`
- **Observability**: traces logged to Langfuse when `LANGFUSE_*` env vars are set

### Event Bus

Two implementations behind the same interface:
- **`EventBus`** (in-process) — fire-and-forget via `asyncio.create_task`, used in dev/test
- **`RedisStreamsEventBus`** — Redis-backed, used in production for cross-process event delivery

Events follow CloudEvents 1.0 format. Audit handlers subscribe to `earp.execution.*` patterns.

### Tech Stack

- Python 3.12+, FastAPI, SQLAlchemy 2.0 (async), Alembic
- PostgreSQL 16 + pgvector extension
- Procrastinate (task queue, PostgreSQL-backed)
- Redis/Valkey (event bus, caching)
- Ollama (local LLM serving — `bge-m3:latest` for embeddings, `qwen3.6:35b` for chat)
- Langfuse (LLM observability)
- MinIO (object storage)
- testcontainers-python (integration tests)
- ruff (lint + format), pyright (type checking, strict mode)
- import-linter (architectural dependency enforcement)
- uv (package management)

### Infrastructure Services (docker compose)

`docker compose up -d` starts:
- PostgreSQL 16 + pgvector on port **5433**
- Valkey 8 on port **6380**
- MinIO on ports **9000** (API) / **9001** (console)
- Langfuse on port **3000** (if configured)

### Key Conventions

- **Line length**: 120 characters (ruff config)
- **Type checking**: pyright strict mode; several rules relaxed for FastAPI/SQLAlchemy compatibility (`reportUnknownMemberType`, `reportUnknownArgumentType`, etc.)
- **Arch docs**: The `arch/` directory hierarchy — L0 (philosophy), L1 (architecture design), L2 (platform specs), L3 (detailed technical design). See `arch/README.md` for the reading guide.
- **Migrations**: Alembic in `migrations/versions/`. Migrations run as the superuser role. The app role `earp_app` has no `BYPASSRLS` privilege, so RLS is enforced.

### Existing CLAUDE.md / Rules

If a `CLAUDE.md` already exists at the project root, read it before making changes. Do not overwrite it unless asked. Similarly, check `.claude/` for project-specific settings and `.cursor/rules/` or `.github/copilot-instructions.md` for additional guidance.
