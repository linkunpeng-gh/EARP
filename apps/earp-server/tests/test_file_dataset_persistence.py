from __future__ import annotations

import asyncio
import json
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from earp_server.config import Settings
from earp_server.file_dataset import (
    FileDatasetError,
    acquire_observation,
    list_datasets,
    publish_dataset,
    stage_dataset,
)
from earp_server.main import create_app

SECRET = "earp-dev-secret-change-in-production"


def _package() -> tuple[bytes, dict[str, bytes]]:
    manifest = {
        "schema_version": "earp-file-dataset/v1",
        "dataset": {"id": "file-dataset-test", "name": "File dataset test"},
        "data_domains": [{"data_domain_id": "fd-production", "name": "Production"}],
        "entity_types": [
            {
                "entity_type_id": "fd-mine",
                "name": "Mine",
                "kind": "object",
                "data_domain_id": "fd-production",
            }
        ],
        "entities": {
            "file": "entities.csv",
            "columns": {
                "entity_id": "entity_id",
                "entity_type": "entity_type",
                "name": "name",
                "business_code": "business_code",
                "data_domain_id": "data_domain_id",
            },
        },
        "providers": [
            {
                "provider_key": "file-fd-production",
                "capability_contract_ref": "production_metric_query",
                "file": "production.csv",
                "entity_column": "entity_id",
                "time_column": "observed_at",
                "requirements": {
                    "production_actual_and_baseline": {
                        "value_column": "value",
                        "baseline_column": "baseline",
                        "unit": "t",
                    }
                },
            }
        ],
    }
    return json.dumps(manifest).encode(), {
        "entities.csv": (
            b"entity_id,entity_type,name,business_code,data_domain_id\n"
            b"fd-mine-3,fd-mine,Mine 3,FD-MINE-3,fd-production\n"
        ),
        "production.csv": (b"entity_id,observed_at,value,baseline\nfd-mine-3,2026-08-28T01:00:00+08:00,8200,10000\n"),
    }


@pytest.mark.asyncio
async def test_stage_publish_and_acquire_pins_revision(migrated: str, app_url: str, tmp_path: Path) -> None:
    engine = create_async_engine(app_url)
    tenant_id = "file-dataset-tenant"
    manifest, files = _package()
    try:
        staged = await stage_dataset(engine, tenant_id, tmp_path, manifest, files)
        assert staged["status"] == "staged"
        assert (await list_datasets(engine, tenant_id))[0]["latest_published_hash"] is None

        published = await publish_dataset(engine, tenant_id, tmp_path, "file-dataset-test")
        assert published["status"] == "published"
        assert published["validation"]["entities_imported"] == 1

        result = await acquire_observation(
            engine,
            tenant_id,
            tmp_path,
            {
                "prepare_id": "prepare-file-test",
                "requirement_id": "req-file-test",
                "source_requirement_id": "source-file-test",
                "requirement_key": "production_actual_and_baseline",
                "node_key": "production_output",
                "requirement_level": "required",
                "capability_contract_ref": "production_metric_query",
                "provider_key": "file-fd-production",
                "target": {"entity_id": "fd-mine-3", "entity_type": "fd-mine"},
                "time_window": {
                    "start": "2026-08-28T00:00:00+08:00",
                    "end": "2026-08-29T00:00:00+08:00",
                },
                "measurement": {"aggregation": "sum", "unit": "t"},
                "file_dataset": {
                    "dataset_id": "file-dataset-test",
                    "content_hash": staged["content_hash"],
                },
            },
        )
        assert result["observation"]["value"] == 8200
        assert result["observation"]["provenance"]["dataset_content_hash"] == staged["content_hash"]
        async with engine.connect() as connection:
            await connection.execute(text("SELECT set_config('earp.tenant_id', :tenant, true)"), {"tenant": tenant_id})
            source_ref = (
                await connection.execute(text("SELECT source_ref FROM entities WHERE entity_id='fd-mine-3'"))
            ).scalar_one()
            assert source_ref.endswith(staged["content_hash"])
    finally:
        await engine.dispose()


def _token(tenant_id: str, role_id: str) -> str:
    return jwt.encode(
        {"sub": "file-user", "tenant_id": tenant_id, "role_id": role_id, "exp": 9999999999},
        SECRET,
        algorithm="HS256",
    )


async def _seed_roles(app_url: str, tenant_id: str) -> None:
    engine = create_async_engine(app_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("SELECT set_config('earp.tenant_id', :tenant, true)"), {"tenant": tenant_id})
            await connection.execute(
                text(
                    "INSERT INTO roles (role_id,tenant_id,name,permissions,data_scope,data_domain_access,is_admin) "
                    "VALUES ('fd-api-admin',:tenant,'Admin','{}','all','[]',true),"
                    "('fd-api-ops',:tenant,'Ops','{}','all','[]',false) ON CONFLICT DO NOTHING"
                ),
                {"tenant": tenant_id},
            )
    finally:
        await engine.dispose()


async def test_publish_translates_catalog_schema_errors_to_validation_error(
    migrated: str, app_url: str, tmp_path: Path
) -> None:
    engine = create_async_engine(app_url)
    tenant_id = "file-dataset-tamper-tenant"
    try:
        manifest, files = _package()
        staged = await stage_dataset(engine, tenant_id, tmp_path, manifest, files)
        # Simulate a staged revision that predates parse-time catalog validation:
        # it declares an entity_type whose kind the shared schema rejects.
        bad = json.loads(manifest)
        bad["entity_types"][0]["kind"] = "weird"
        async with engine.begin() as connection:
            await connection.execute(text("SELECT set_config('earp.tenant_id', :tenant, true)"), {"tenant": tenant_id})
            await connection.execute(
                text(
                    "UPDATE file_dataset_revisions SET manifest_json=:manifest "
                    "WHERE tenant_id=:tenant AND dataset_id=:dataset AND content_hash=:hash"
                ),
                {
                    "tenant": tenant_id,
                    "dataset": "file-dataset-test",
                    "hash": staged["content_hash"],
                    "manifest": json.dumps(bad),
                },
            )
        with pytest.raises(FileDatasetError, match="cannot be published"):
            await publish_dataset(engine, tenant_id, tmp_path, "file-dataset-test")
        # The publish transaction rolled back: the revision is still staged.
        async with engine.connect() as connection:
            await connection.execute(text("SELECT set_config('earp.tenant_id', :tenant, true)"), {"tenant": tenant_id})
            status = (
                await connection.execute(
                    text(
                        "SELECT status FROM file_dataset_revisions WHERE tenant_id=:tenant "
                        "AND dataset_id=:dataset AND content_hash=:hash"
                    ),
                    {
                        "tenant": tenant_id,
                        "dataset": "file-dataset-test",
                        "hash": staged["content_hash"],
                    },
                )
            ).scalar_one()
            assert status == "staged"
    finally:
        await engine.dispose()


async def test_publish_skips_overlong_entity_id_with_warning(migrated: str, app_url: str, tmp_path: Path) -> None:
    """CSV 提供的 entity_id 超 64 字符（entities.varchar(64) PK）应逐行跳过 + warning，
    而不是让 INSERT 抛 DataError 整批回滚（此前经 publish 翻译为 422 全量失败）。
    """
    engine = create_async_engine(app_url)
    tenant_id = "file-dataset-len-tenant"
    try:
        manifest, files = _package()
        manifest_obj = json.loads(manifest)
        files["entities.csv"] = (
            b"entity_id,entity_type,name,business_code,data_domain_id\n"
            + (b"x" * 65)
            + b",fd-mine,Large entity,FD-LARGE,fd-production\n"
            + b"fd-mine-len,fd-mine,Len entity,FD-LEN,fd-production\n"
        )
        await stage_dataset(engine, tenant_id, tmp_path, json.dumps(manifest_obj).encode(), files)
        published = await publish_dataset(engine, tenant_id, tmp_path, "file-dataset-test")
        assert published["status"] == "published"
        assert published["validation"]["entities_imported"] == 1
        reasons = [w.get("reason", "") for w in published["validation"]["warnings"]]
        assert any("exceeds 64 characters" in r for r in reasons)
        async with engine.connect() as connection:
            await connection.execute(text("SELECT set_config('earp.tenant_id', :tenant, true)"), {"tenant": tenant_id})
            ids = (
                (
                    await connection.execute(
                        text("SELECT entity_id FROM entities WHERE tenant_id=:tenant"), {"tenant": tenant_id}
                    )
                )
                .scalars()
                .all()
            )
        assert ids == ["fd-mine-len"]
    finally:
        await engine.dispose()


def test_file_dataset_api_admin_gate_and_lifecycle(migrated: str, app_url: str, tmp_path: Path) -> None:
    tenant_id = "file-dataset-api-tenant"
    asyncio.run(_seed_roles(app_url, tenant_id))
    manifest, files = _package()
    app = create_app(Settings(database_url=app_url, app_env="test", file_data_root=str(tmp_path)))
    admin_headers = {"Authorization": f"Bearer {_token(tenant_id, 'fd-api-admin')}"}
    ops_headers = {"Authorization": f"Bearer {_token(tenant_id, 'fd-api-ops')}"}
    multipart = [
        ("manifest", ("manifest.yaml", manifest, "application/yaml")),
        *[("files", (name, content, "text/csv")) for name, content in files.items()],
    ]
    with TestClient(app) as client:
        assert client.get("/v1/file-datasets", headers=ops_headers).status_code == 200
        assert client.post("/v1/file-datasets", files=multipart, headers=ops_headers).status_code == 403
        staged = client.post("/v1/file-datasets", files=multipart, headers=admin_headers)
        assert staged.status_code == 201, staged.text
        dataset_id = staged.json()["dataset_id"]
        assert client.get(f"/v1/file-datasets/{dataset_id}", headers=ops_headers).json()["status"] == "staged"
        assert client.post(f"/v1/file-datasets/{dataset_id}/publish", headers=ops_headers).status_code == 403
        published = client.post(f"/v1/file-datasets/{dataset_id}/publish", headers=admin_headers)
        assert published.status_code == 200, published.text
        assert published.json()["status"] == "published"
