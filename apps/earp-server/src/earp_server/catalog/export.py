"""Pack export through an authoritative Source Adapter, never from Catalog copies."""

from __future__ import annotations

import io
import json
from urllib.parse import quote
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.infra.db import tenant_session

from .governance import CatalogAuthorizationError, assert_pack_export_allowed
from .registration import CatalogRegistrationError, verified_source_ref
from .source import SourceAdapter


class CatalogPackExportError(ValueError):
    """A Pack cannot be exported without authoritative source content."""


class CatalogPackExportService:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def export(
        self,
        *,
        tenant_id: str,
        actor_role: str,
        is_platform_admin: bool,
        pack_id: str,
        version: str,
        adapters: dict[str, SourceAdapter],
    ) -> bytes:
        async with tenant_session(self._engine, tenant_id) as session:
            pack = (
                (
                    await session.execute(
                        text(
                            "SELECT pack_id,version,layer,name,owner_role,content_hash,status "
                            "FROM catalog_packs WHERE tenant_id=:tenant AND pack_id=:pack_id "
                            "AND version=:version AND deleted_at IS NULL"
                        ),
                        {"tenant": tenant_id, "pack_id": pack_id, "version": version},
                    )
                )
                .mappings()
                .first()
            )
            if pack is None:
                raise CatalogPackExportError("Pack version is not found")
            try:
                assert_pack_export_allowed(
                    owner_role=pack["owner_role"],
                    actor_role=actor_role,
                    is_platform_admin=is_platform_admin,
                )
            except CatalogAuthorizationError as error:
                raise CatalogPackExportError(str(error)) from error
            if pack["status"] != "published" or not pack["content_hash"]:
                raise CatalogPackExportError("only a published Pack may be exported")
            rows = (
                await session.execute(
                    text(
                        "SELECT e.kind,e.stable_id,e.version,e.content_hash,r.semantic_schema_version,"
                        "r.source_system,r.source_identity,r.data_domain_id,r.status "
                        "FROM catalog_pack_entries e JOIN catalog_refs r ON "
                        "r.tenant_id=e.tenant_id AND r.kind=e.kind AND r.stable_id=e.stable_id "
                        "AND r.version=e.version WHERE e.tenant_id=:tenant AND e.pack_id=:pack_id "
                        "AND e.pack_version=:version ORDER BY e.kind,e.stable_id,e.version"
                    ),
                    {"tenant": tenant_id, "pack_id": pack_id, "version": version},
                )
            ).mappings()
            entries: list[dict[str, object]] = []
            for row in rows:
                adapter = adapters.get(row["source_system"])
                if adapter is None:
                    raise CatalogPackExportError(f"authoritative source adapter is not ready: {row['source_system']}")
                try:
                    source = await verified_source_ref(
                        adapter,
                        kind=row["kind"],
                        stable_id=row["stable_id"],
                        version=row["version"],
                    )
                except (CatalogRegistrationError, LookupError, ValueError) as error:
                    raise CatalogPackExportError(
                        "authoritative source content is not exportable: "
                        f"{row['kind']}:{row['stable_id']}@{row['version']}"
                    ) from error
                if (
                    source.content_hash != row["content_hash"]
                    or source.schema_version != row["semantic_schema_version"]
                ):
                    raise CatalogPackExportError("source content no longer matches the registered Pack pin")
                if source.status == "inactive":
                    raise CatalogPackExportError("inactive source content cannot enter an export archive")
                entries.append(
                    {
                        "kind": row["kind"],
                        "stable_id": row["stable_id"],
                        "version": row["version"],
                        "content_hash": source.content_hash,
                        "semantic_schema_version": source.schema_version,
                        "source_system": row["source_system"],
                        "source_identity": adapter.source_identity(source),
                        "data_domain_id": row["data_domain_id"],
                        "canonical_input": source.canonical_input,
                    }
                )
            return self._archive(dict(pack), entries)

    @staticmethod
    def _archive(pack: dict[str, object], entries: list[dict[str, object]]) -> bytes:
        output = io.BytesIO()
        with ZipFile(output, "w", ZIP_DEFLATED) as archive:
            archive.writestr(
                "pack.json",
                json.dumps(
                    {
                        "pack_id": pack["pack_id"],
                        "version": pack["version"],
                        "layer": pack["layer"],
                        "name": pack["name"],
                        "content_hash": pack["content_hash"],
                        "entry_count": len(entries),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                ),
            )
            for entry in entries:
                path = (
                    "entries/"
                    + quote(str(entry["kind"]), safe="")
                    + "/"
                    + quote(str(entry["stable_id"]), safe="")
                    + "@"
                    + quote(str(entry["version"]), safe="")
                    + ".json"
                )
                archive.writestr(path, json.dumps(entry, ensure_ascii=False, sort_keys=True, indent=2))
        return output.getvalue()
