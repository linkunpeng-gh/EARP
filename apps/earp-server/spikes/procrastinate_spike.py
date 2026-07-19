"""procrastinate spike - PRD-2026-020 AC-05 / tech-stack-analysis v1.1 section 4.4.

Standalone by design (Gate B P0-3): does NOT import earp_server. Builds its own
engine/sessionmaker straight from the DSN.
Run via: uv run python spikes/procrastinate_spike.py --workers 2 --tasks 100
(NOT pytest - this script uses bare assert and needs a real PG + worker process;
it is an offline spike, not a CI regression test per ADR-007).

Four scenarios map 1:1 to the decision matrix:
  S1 concurrency     - 2 workers x N tasks, all complete, no connection leak
  S2 retry           - max_attempts=3 task fails 3 times then ends 'failed'
  S3 session-coexist - task body uses an independent SQLAlchemy async session;
                       pool returns to zero checked-out connections
  S4 tx-enqueue      - business row + job row in ONE tx: rollback leaves no job,
                       commit leaves both (transactional enqueue)

Evidence: spikes/spike-evidence.json. Exit code 0 = all PASS (D6 finalized).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys
import time
from typing import Any

import procrastinate
import psycopg
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

DEFAULT_DSN = "postgresql://postgres:postgres@localhost:5433/earp"
EVIDENCE_PATH = pathlib.Path(__file__).parent / "spike-evidence.json"


def build_app(dsn: str) -> procrastinate.App:
    return procrastinate.App(connector=procrastinate.PsycopgConnector(conninfo=dsn))


async def ensure_schema(app: procrastinate.App) -> None:
    row = await app.connector.execute_query_one_async("SELECT to_regclass('public.procrastinate_jobs') AS reg")
    if row["reg"] is None:
        await app.schema_manager.apply_schema_async()


async def pg_connection_count(dsn: str) -> int:
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        cur = await conn.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()")
        row = await cur.fetchone()
        return int(row[0]) if row else -1


async def drain(app: procrastinate.App, *, workers: int, concurrency: int) -> None:
    """Run N worker coroutines until the queue is empty (wait=False)."""
    await asyncio.gather(
        *(
            app.run_worker_async(concurrency=concurrency, wait=False, install_signal_handlers=False)
            for _ in range(workers)
        )
    )


async def scenario_concurrency(app: procrastinate.App, dsn: str, workers: int, tasks: int) -> dict[str, Any]:
    @app.task(name="spike.noop")
    async def noop(i: int) -> None:
        await asyncio.sleep(0.005)

    conn_before = await pg_connection_count(dsn)
    t0 = time.monotonic()
    for i in range(tasks):
        await noop.defer_async(i=i)
    await drain(app, workers=workers, concurrency=2)
    elapsed = time.monotonic() - t0
    conn_after = await pg_connection_count(dsn)

    row = await app.connector.execute_query_one_async(
        "SELECT count(*) AS bad FROM procrastinate_jobs WHERE task_name = 'spike.noop' AND status <> 'succeeded'"
    )
    ok = row["bad"] == 0 and (conn_after - conn_before) <= 2
    return {
        "pass": ok,
        "tasks": tasks,
        "workers": workers,
        "elapsed_s": round(elapsed, 2),
        "unfinished_jobs": row["bad"],
        "connections_before": conn_before,
        "connections_after": conn_after,
    }


async def scenario_retry(app: procrastinate.App) -> dict[str, Any]:
    # procrastinate semantics: retry=N means "N retries AFTER the first run",
    # i.e. N+1 total executions (retry.py: RetryStrategy(max_attempts=retry),
    # stop when job.attempts >= max_attempts, attempts counted post-failure).
    # EARP mapping note: ConnectorRetryConfig.max_attempts (= total attempts,
    # Temporal convention) -> procrastinate retry = max_attempts - 1.
    @app.task(name="spike.always_fail", retry=3)
    async def always_fail() -> None:
        raise RuntimeError("spike: intentional failure")

    await always_fail.defer_async()
    await drain(app, workers=1, concurrency=1)
    row = await app.connector.execute_query_one_async(
        "SELECT status::text AS status, attempts FROM procrastinate_jobs "
        "WHERE task_name = 'spike.always_fail' ORDER BY id DESC LIMIT 1"
    )
    retries_done = row["attempts"] - 1
    ok = row["status"] == "failed" and retries_done == 3
    return {
        "pass": ok,
        "final_status": row["status"],
        "total_executions": row["attempts"],
        "retries_done": retries_done,
        "expected_retries": 3,
        "semantics": "procrastinate retry=N == N retries (N+1 executions); EARP max_attempts -> retry=max_attempts-1",
    }


async def scenario_session_coexist(app: procrastinate.App, dsn: str) -> dict[str, Any]:
    engine = create_async_engine(dsn.replace("postgresql://", "postgresql+psycopg://", 1), pool_size=2)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    results: list[int] = []

    @app.task(name="spike.db_query")
    async def db_query() -> None:
        async with factory() as session:
            value = await session.execute(text("SELECT 41 + 1"))
            results.append(int(value.scalar_one()))

    for _ in range(10):
        await db_query.defer_async()
    await drain(app, workers=1, concurrency=2)

    checked_out = engine.pool.checkedout()  # type: ignore[attr-defined]
    await engine.dispose()
    ok = results.count(42) == 10 and checked_out == 0
    return {"pass": ok, "query_results_ok": results.count(42), "pool_checked_out_after": checked_out}


async def scenario_tx_enqueue(dsn: str) -> dict[str, Any]:
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        await conn.execute("CREATE TABLE IF NOT EXISTS spike_tx_probe (id bigserial PRIMARY KEY)")
        await conn.commit()

        insert_job = (
            "INSERT INTO procrastinate_jobs (queue_name, task_name, priority, args, status) "
            "VALUES ('default', 'spike.tx_probe', 0, '{}'::jsonb, 'todo')"
        )

        # rollback path: business row + job row must both vanish
        await conn.execute("INSERT INTO spike_tx_probe DEFAULT VALUES")
        await conn.execute(insert_job)
        await conn.rollback()

        cur = await conn.execute("SELECT count(*) FROM procrastinate_jobs WHERE task_name = 'spike.tx_probe'")
        jobs_after_rollback = int((await cur.fetchone())[0])
        cur = await conn.execute("SELECT count(*) FROM spike_tx_probe")
        probes_after_rollback = int((await cur.fetchone())[0])

        # commit path: both must persist atomically
        await conn.execute("INSERT INTO spike_tx_probe DEFAULT VALUES")
        await conn.execute(insert_job)
        await conn.commit()

        cur = await conn.execute("SELECT count(*) FROM procrastinate_jobs WHERE task_name = 'spike.tx_probe'")
        jobs_after_commit = int((await cur.fetchone())[0])
        cur = await conn.execute("SELECT count(*) FROM spike_tx_probe")
        probes_after_commit = int((await cur.fetchone())[0])

        # cleanup
        await conn.execute("DELETE FROM procrastinate_jobs WHERE task_name = 'spike.tx_probe'")
        await conn.execute("DROP TABLE spike_tx_probe")
        await conn.commit()

    ok = jobs_after_rollback == 0 and probes_after_rollback == 0 and jobs_after_commit == 1 and probes_after_commit == 1
    return {
        "pass": ok,
        "jobs_after_rollback": jobs_after_rollback,
        "probes_after_rollback": probes_after_rollback,
        "jobs_after_commit": jobs_after_commit,
        "probes_after_commit": probes_after_commit,
    }


async def run(dsn: str, workers: int, tasks: int) -> int:
    app = build_app(dsn)
    async with app.open_async():
        await ensure_schema(app)
        evidence: dict[str, Any] = {
            "spike": "procrastinate 3.6 (D6, tech-stack-analysis v1.1 section 4.4)",
            "dsn_host": dsn.split("@")[-1],
            "S1_concurrency": await scenario_concurrency(app, dsn, workers, tasks),
            "S2_retry": await scenario_retry(app),
            "S3_session_coexist": await scenario_session_coexist(app, dsn),
            "S4_tx_enqueue": await scenario_tx_enqueue(dsn),
        }

    all_pass = all(v["pass"] for k, v in evidence.items() if k.startswith("S"))
    evidence["verdict"] = "PASS - D6 finalized: procrastinate" if all_pass else "FAIL - fallback to Celery (D6)"
    EVIDENCE_PATH.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")

    for key in ("S1_concurrency", "S2_retry", "S3_session_coexist", "S4_tx_enqueue"):
        print(f"{key}: {'PASS' if evidence[key]['pass'] else 'FAIL'}  {evidence[key]}")
    print(evidence["verdict"])
    return 0 if all_pass else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="procrastinate spike (AC-05)")
    parser.add_argument("--dsn", default=DEFAULT_DSN)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--tasks", type=int, default=100)
    args = parser.parse_args()
    return asyncio.run(run(args.dsn, args.workers, args.tasks))


if __name__ == "__main__":
    sys.exit(main())
