"""删除指定 name 的 ECMC 测试模型（仅本地 dev 库执行）。

安全要求：必须显式传模型名，否则不删除任何数据（2026-08-31 误删已发布模型事故后加固）。

用法:
  EARP_MIGRATION_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5433/earp \
    .venv/bin/python scripts/cleanup_ecmc_test_data.py "我的测试模型A" "测试模型B"

注意：本脚本会连同已发布模型的 version/snapshot 引用一并清理（孤儿 snapshot
请另行处理）；恢复误删已发布模型请用 scripts/restore_ecmc_model_from_snapshot.py。
"""
import asyncio, os, sys
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

async def main() -> None:
    names = [a for a in sys.argv[1:] if a]
    if not names:
        print("no model names given - nothing deleted (safe by design)")
        return
    url = os.environ["EARP_MIGRATION_DATABASE_URL"]
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        # 跳过 draft-only guard 触发器（仅 postgres 超管会话有效）
        await conn.execute(text("SET session_replication_role = replica"))
        rows = (
            await conn.execute(
                text("SELECT model_id FROM causal_models WHERE name = ANY(:names)"),
                {"names": names},
            )
        ).mappings().all()
        for r in rows:
            mid = r["model_id"]
            vers = (
                await conn.execute(
                    text("SELECT model_version_id FROM causal_model_versions WHERE model_id=:m"),
                    {"m": mid},
                )
            ).scalars().all()
            print("clean", mid, vers)
            for v in vers:
                # children first (dependency order), then the version itself
                for t in (
                    "causal_capability_bindings",
                    "causal_data_bindings",
                    "causal_nodes",
                    "causal_edges",
                    "causal_rules",
                    "causal_model_validation_runs",
                    "causal_model_reviews",
                    "blueprint_compile_records",
                ):
                    await conn.execute(text(f"DELETE FROM {t} WHERE model_version_id=:v"), {"v": v})
            await conn.execute(text("DELETE FROM causal_model_versions WHERE model_id=:m"), {"m": mid})
            await conn.execute(text("DELETE FROM causal_models WHERE model_id=:m"), {"m": mid})
        print("remaining models:", (await conn.execute(text("SELECT count(*) FROM causal_models"))).scalar())
    await engine.dispose()

asyncio.run(main())
