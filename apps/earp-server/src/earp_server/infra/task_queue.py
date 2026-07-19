"""TaskQueue thin abstraction (tech-stack-analysis v1.1 section 4.4 migration path).

Business code must depend on the TaskQueue protocol only - never on
procrastinate directly - so the implementation can be swapped (Celery fallback).
"""

from __future__ import annotations

import datetime
from collections.abc import Callable
from typing import Any, Protocol

import procrastinate

from earp_server.config import Settings, psycopg_dsn


class TaskQueue(Protocol):
    async def enqueue(
        self, task_name: str, payload: dict[str, Any], *, scheduled_at: datetime.datetime | None = None
    ) -> str: ...

    async def enqueue_in_session(
        self, session: Any, task_name: str, payload: dict[str, Any]
    ) -> str: ...  # F4: same-connection atomic enqueue (M1 added, M1 implemented)

    def task(self, name: str, *, max_attempts: int = 3) -> Callable[..., Any]: ...

    async def run_worker(self, *, concurrency: int = 4) -> None: ...


def build_procrastinate_app(dsn: str) -> procrastinate.App:
    return procrastinate.App(connector=procrastinate.PsycopgConnector(conninfo=dsn))


class ProcrastinateTaskQueue:
    """procrastinate-backed implementation (D6 primary choice)."""

    def __init__(self, settings: Settings) -> None:
        self._app = build_procrastinate_app(psycopg_dsn(settings.database_url))

    @property
    def app(self) -> procrastinate.App:
        return self._app

    async def open(self) -> None:
        await self._app.open_async()

    async def close(self) -> None:
        await self._app.close_async()

    async def assert_schema(self) -> None:
        """Fail fast if the procrastinate schema is missing (Gate C P1-3)."""
        rows = await self._app.connector.execute_query_one_async(
            "SELECT to_regclass('public.procrastinate_jobs') AS reg"
        )
        if rows["reg"] is None:
            raise RuntimeError(
                "procrastinate schema missing - run migrations first "
                "(`make migrate` applies alembic + earp_server.infra.queue_schema)"
            )

    async def enqueue(
        self, task_name: str, payload: dict[str, Any], *, scheduled_at: datetime.datetime | None = None
    ) -> str:
        # NOTE (Gate C P1-7, M1): task_name is not validated against the worker's
        # registry here; enqueueing an unregistered task fails only at execution
        # time. M1 adds registry validation + failed-job audit events.
        # NOTE (Gate C P1-9, M1): pool-based defer is NOT transactional with the
        # caller's business transaction. For transactional enqueue use
        # enqueue_in_session() (below - same-session job-row insertion, spike S4 proven).
        deferrer = self._app.configure_task(name=task_name, schedule_at=scheduled_at)
        job_id = await deferrer.defer_async(**payload)
        return str(job_id)

    async def enqueue_in_session(self, session: Any, task_name: str, payload: dict[str, Any]) -> str:
        """F4: same-connection atomic enqueue (M0 cleanup, M1 implemented).

        Inserts a job row directly on the given SQLAlchemy AsyncSession - the job
        row is part of the caller's transaction (commit/rollback atomically).
        Pattern proven by spike S4: rollback=0 jobs, commit=1 job.
        """
        import json

        from sqlalchemy import text

        job_sql = (
            "INSERT INTO procrastinate_jobs (queue_name, task_name, priority, args, status) "
            "VALUES ('default', :tname, 0, :payload, 'todo')"
        )
        await session.execute(text(job_sql), {"tname": task_name, "payload": json.dumps(payload)})
        result = await session.execute(text("SELECT currval('procrastinate_jobs_id_seq')"))
        return str(result.scalar_one())

    def task(self, name: str, *, max_attempts: int = 3) -> Callable[..., Any]:
        return self._app.task(name=name, retry=max_attempts)

    async def run_worker(self, *, concurrency: int = 4) -> None:
        await self._app.run_worker_async(concurrency=concurrency, wait=True, install_signal_handlers=False)
