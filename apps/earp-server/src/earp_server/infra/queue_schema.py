"""Apply procrastinate schema + grants using the MIGRATION role (dual-role strategy).

Run after alembic: `uv run python -m earp_server.infra.queue_schema`
The worker's ensure_schema() only guards/fails-fast; schema ownership belongs here.
"""

from __future__ import annotations

import asyncio

import procrastinate

from earp_server.config import Settings, psycopg_dsn

_GRANTS = """
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO earp_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO earp_app;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO earp_app;
"""


async def apply(settings: Settings | None = None) -> None:
    cfg = settings or Settings()
    app = procrastinate.App(connector=procrastinate.PsycopgConnector(conninfo=psycopg_dsn(cfg.migration_database_url)))
    async with app.open_async():
        row = await app.connector.execute_query_one_async("SELECT to_regclass('public.procrastinate_jobs') AS reg")
        if row["reg"] is None:
            await app.schema_manager.apply_schema_async()
        for statement in _GRANTS.strip().splitlines():
            await app.connector.execute_query_async(statement)


if __name__ == "__main__":
    asyncio.run(apply())
