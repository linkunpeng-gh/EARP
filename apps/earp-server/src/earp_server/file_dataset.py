"""Tenant-scoped file scenario datasets and the causal file provider.

The manifest is the stable boundary.  Model definitions refer only to logical
capability contracts; a run pins one published dataset revision and resolves
those contracts to CSV-backed providers.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import shutil
import uuid
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from sqlalchemy import text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.infra.db import tenant_session

SCHEMA_VERSION = "earp-file-dataset/v1"
SUPPORTED_AGGREGATIONS = {"sum", "mean", "min", "max", "latest"}
# Optional manifest catalog sections bind into CHECK-constrained columns at publish time;
# keep these sets in sync with the data_domains / entity_types / relation_types migrations.
CATALOG_CLASSIFICATIONS = {"public", "internal", "confidential", "restricted"}
CATALOG_ENTITY_KINDS = {"object", "concept", "metric"}
CATALOG_CARDINALITIES = {"1:1", "1:N", "N:1", "N:M"}

# section -> (id field, enum field, allowed values, publish-time default)
_CATALOG_SECTION_ENUMS = {
    "data_domains": ("data_domain_id", "data_classification", CATALOG_CLASSIFICATIONS, "internal"),
    "entity_types": ("entity_type_id", "kind", CATALOG_ENTITY_KINDS, "object"),
    "relation_types": ("relation_type_id", "cardinality", CATALOG_CARDINALITIES, "N:M"),
}


class FileDatasetError(ValueError):
    code = "validation"


class FileDatasetInfrastructureError(FileDatasetError):
    code = "connection"


def _safe_id(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 64:
        raise FileDatasetError(f"{name} must be a non-empty string of at most 64 characters")
    if not all(ch.isalnum() or ch in "-_" for ch in value):
        raise FileDatasetError(f"{name} may contain only letters, numbers, '-' and '_'")
    return value


def _safe_filename(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise FileDatasetError("dataset filenames must be non-empty relative names")
    path = PurePosixPath(value)
    if path.is_absolute() or len(path.parts) != 1 or path.parts[0] in {".", ".."}:
        raise FileDatasetError(f"unsafe dataset filename: {value!r}")
    if path.suffix.lower() != ".csv":
        raise FileDatasetError(f"only CSV data files are supported: {value!r}")
    return value


def _catalog_id(value: object, label: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 64:
        raise FileDatasetError(
            f"manifest entry {label} is required and must be a non-empty string of at most 64 characters"
        )


def _validate_optional_catalog(manifest: Mapping[str, Any]) -> None:
    """Structurally validate optional catalog metadata before it can be published.

    These sections are bound straight into NOT NULL / CHECK-constrained columns by
    _publish_catalog. A staged manifest with a missing id or an out-of-enum value
    would otherwise fail publish with an opaque DB error after staging already
    reported the package as valid.
    """
    for section, (id_field, enum_field, allowed, default) in _CATALOG_SECTION_ENUMS.items():
        items = manifest.get(section)
        if items is None:
            continue
        if not isinstance(items, list) or any(not isinstance(item, Mapping) for item in items):
            raise FileDatasetError(f"manifest.{section} must be a list of objects")
        for item in items:
            _catalog_id(item.get(id_field), f"{section}.{id_field}")
            value = item.get(enum_field, default)
            if value not in allowed:
                raise FileDatasetError(
                    f"manifest.{section} entry {item.get(id_field)!r} has unsupported {enum_field}: {value!r}"
                )


def parse_manifest(content: bytes) -> dict[str, Any]:
    try:
        decoded = content.decode("utf-8-sig")
        raw = yaml.safe_load(decoded)
    except (UnicodeDecodeError, yaml.YAMLError) as error:
        raise FileDatasetError("manifest must be valid UTF-8 YAML or JSON") from error
    if not isinstance(raw, dict) or raw.get("schema_version") != SCHEMA_VERSION:
        raise FileDatasetError(f"manifest schema_version must be {SCHEMA_VERSION}")
    dataset = raw.get("dataset")
    if not isinstance(dataset, dict):
        raise FileDatasetError("manifest.dataset is required")
    _safe_id(dataset.get("id"), "dataset.id")
    if not isinstance(dataset.get("name"), str) or not dataset["name"].strip():
        raise FileDatasetError("manifest.dataset.name is required")
    providers = raw.get("providers")
    if not isinstance(providers, list) or not providers:
        raise FileDatasetError("manifest.providers must contain at least one provider")
    seen: set[str] = set()
    for provider in providers:
        if not isinstance(provider, dict):
            raise FileDatasetError("each provider must be an object")
        key = _safe_id(provider.get("provider_key"), "provider_key")
        if key in seen:
            raise FileDatasetError(f"duplicate provider_key: {key}")
        seen.add(key)
        if not isinstance(provider.get("capability_contract_ref"), str) or not provider["capability_contract_ref"]:
            raise FileDatasetError(f"provider {key} lacks capability_contract_ref")
        _safe_filename(provider.get("file"))
        for field in ("entity_column", "time_column"):
            if not isinstance(provider.get(field), str) or not provider[field]:
                raise FileDatasetError(f"provider {key} lacks {field}")
        requirements = provider.get("requirements")
        if not isinstance(requirements, dict) or not requirements:
            raise FileDatasetError(f"provider {key} must declare requirements")
        for requirement_key, mapping in requirements.items():
            if not isinstance(requirement_key, str) or not isinstance(mapping, dict):
                raise FileDatasetError(f"provider {key} has an invalid requirement mapping")
            for field in ("value_column", "baseline_column", "unit"):
                if not isinstance(mapping.get(field), str) or not mapping[field]:
                    raise FileDatasetError(f"provider {key} requirement {requirement_key} lacks {field}")
    for section in ("entities", "relations"):
        spec = raw.get(section)
        if spec is not None:
            if not isinstance(spec, dict):
                raise FileDatasetError(f"manifest.{section} must be an object")
            _safe_filename(spec.get("file"))
            if not isinstance(spec.get("columns"), dict):
                raise FileDatasetError(f"manifest.{section}.columns is required")
    _validate_optional_catalog(raw)
    return raw


def referenced_files(manifest: Mapping[str, Any]) -> set[str]:
    names = {_safe_filename(provider["file"]) for provider in manifest["providers"]}
    for section in ("entities", "relations"):
        spec = manifest.get(section)
        if isinstance(spec, Mapping):
            names.add(_safe_filename(spec.get("file")))
    return names


def _decode_csv(name: str, content: bytes) -> tuple[list[str], list[dict[str, str]]]:
    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise FileDatasetError(f"{name} must be UTF-8 or UTF-8-BOM CSV") from error
    try:
        reader = csv.DictReader(io.StringIO(decoded))
        if not reader.fieldnames or any(not field for field in reader.fieldnames):
            raise FileDatasetError(f"{name} must contain a non-empty header row")
        return list(reader.fieldnames), [dict(row) for row in reader]
    except csv.Error as error:
        raise FileDatasetError(f"{name} is not valid CSV: {error}") from error


def validate_package(manifest: Mapping[str, Any], files: Mapping[str, bytes]) -> dict[str, Any]:
    missing = sorted(referenced_files(manifest) - set(files))
    if missing:
        raise FileDatasetError(f"manifest references missing files: {missing}")
    warnings: list[dict[str, Any]] = []
    usable_provider_rows = 0
    for provider in manifest["providers"]:
        name = provider["file"]
        headers, rows = _decode_csv(name, files[name])
        required = {provider["entity_column"], provider["time_column"]}
        for mapping in provider["requirements"].values():
            required.update((mapping["value_column"], mapping["baseline_column"]))
        absent = sorted(required - set(headers))
        if absent:
            raise FileDatasetError(f"{name} lacks mapped columns: {absent}")
        for row_no, row in enumerate(rows, start=2):
            reason = _provider_row_error(provider, row)
            if reason:
                warnings.append({"file": name, "row": row_no, "reason": reason})
            else:
                usable_provider_rows += 1
    if usable_provider_rows == 0:
        raise FileDatasetError("dataset has no usable provider data rows")
    for section in ("entities", "relations"):
        spec = manifest.get(section)
        if not isinstance(spec, Mapping):
            continue
        name = spec["file"]
        headers, rows = _decode_csv(name, files[name])
        required_keys = (
            ("entity_type", "name", "business_code", "data_domain_id")
            if section == "entities"
            else ("source_code", "relation_type", "target_code")
        )
        mapped = {spec["columns"].get(key) for key in required_keys}
        if None in mapped or "" in mapped:
            raise FileDatasetError(f"manifest.{section}.columns lacks required mappings")
        absent = sorted(str(column) for column in mapped if column not in headers)
        if absent:
            raise FileDatasetError(f"{name} lacks mapped columns: {absent}")
        for row_no, row in enumerate(rows, start=2):
            empty = [key for key in required_keys if not (row.get(spec["columns"][key]) or "").strip()]
            if empty:
                warnings.append({"file": name, "row": row_no, "reason": f"empty fields: {empty}"})
    return {
        "valid": True,
        "warning_count": len(warnings),
        "warnings": warnings,
        "usable_provider_rows": usable_provider_rows,
    }


def _provider_row_error(provider: Mapping[str, Any], row: Mapping[str, str]) -> str | None:
    if not (row.get(provider["entity_column"]) or "").strip():
        return "empty entity identity"
    raw_time = (row.get(provider["time_column"]) or "").strip()
    try:
        timestamp = datetime.fromisoformat(raw_time)
        if timestamp.tzinfo is None:
            raise ValueError
    except ValueError:
        return "time must be timezone-aware ISO-8601"
    for requirement_key, mapping in provider["requirements"].items():
        for column in (mapping["value_column"], mapping["baseline_column"]):
            try:
                value = float(row.get(column, ""))
                if not math.isfinite(value):
                    raise ValueError
            except (TypeError, ValueError):
                return f"{requirement_key}.{column} must be a finite number"
    return None


def _content_hash(manifest_bytes: bytes, files: Mapping[str, bytes]) -> str:
    digest = hashlib.sha256()
    digest.update(b"manifest\0")
    digest.update(manifest_bytes)
    for name in sorted(files):
        digest.update(b"\0file\0")
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update(files[name])
    return digest.hexdigest()


def _root(root: str | Path) -> Path:
    return Path(root).expanduser().resolve()


async def stage_dataset(
    engine: AsyncEngine,
    tenant_id: str,
    root: str | Path,
    manifest_bytes: bytes,
    files: Mapping[str, bytes],
    *,
    max_files: int = 32,
    max_file_bytes: int = 10 * 1024 * 1024,
    max_total_bytes: int = 50 * 1024 * 1024,
) -> dict[str, Any]:
    if len(files) > max_files:
        raise FileDatasetError(f"dataset contains more than {max_files} files")
    if len(manifest_bytes) > max_file_bytes or any(len(content) > max_file_bytes for content in files.values()):
        raise FileDatasetError("dataset contains a file larger than the configured limit")
    if len(manifest_bytes) + sum(map(len, files.values())) > max_total_bytes:
        raise FileDatasetError("dataset exceeds the configured total size limit")
    manifest = parse_manifest(manifest_bytes)
    expected = referenced_files(manifest)
    extras = sorted(set(files) - expected)
    if extras:
        raise FileDatasetError(f"files not referenced by manifest: {extras}")
    report = validate_package(manifest, files)
    dataset_id = manifest["dataset"]["id"]
    content_hash = _content_hash(manifest_bytes, files)
    tenant_component = hashlib.sha256(tenant_id.encode()).hexdigest()[:32]
    relpath = str(Path("tenants") / tenant_component / dataset_id / content_hash)
    destination = (_root(root) / relpath).resolve()
    if _root(root) not in destination.parents:
        raise FileDatasetError("dataset storage path escapes configured root")
    if destination.exists() and destination.is_symlink():
        raise FileDatasetError("dataset storage destination must not be a symbolic link")
    destination.mkdir(parents=True, exist_ok=True)
    manifest_path = destination / "manifest.yaml"
    if manifest_path.exists() and manifest_path.is_symlink():
        raise FileDatasetError("dataset manifest destination must not be a symbolic link")
    manifest_path.write_bytes(manifest_bytes)
    for name, content in files.items():
        file_path = destination / name
        if file_path.exists() and file_path.is_symlink():
            raise FileDatasetError(f"dataset file destination must not be a symbolic link: {name}")
        file_path.write_bytes(content)
    file_meta = [
        {"name": name, "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
        for name, content in sorted(files.items())
    ]
    async with tenant_session(engine, tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO file_datasets (tenant_id,dataset_id,name,description,latest_staged_hash) "
                "VALUES (:tenant,:dataset,:name,:description,:hash) "
                "ON CONFLICT (tenant_id,dataset_id) DO UPDATE SET name=excluded.name,description=excluded.description,"
                "latest_staged_hash=excluded.latest_staged_hash,updated_at=now()"
            ),
            {
                "tenant": tenant_id,
                "dataset": dataset_id,
                "name": manifest["dataset"]["name"],
                "description": manifest["dataset"].get("description"),
                "hash": content_hash,
            },
        )
        await session.execute(
            text(
                "INSERT INTO file_dataset_revisions (tenant_id,dataset_id,content_hash,status,manifest_json,"
                "files_json,validation_json,storage_relpath) VALUES (:tenant,:dataset,:hash,'staged',:manifest,"
                ":files,:validation,:path) ON CONFLICT (tenant_id,dataset_id,content_hash) DO NOTHING"
            ),
            {
                "tenant": tenant_id,
                "dataset": dataset_id,
                "hash": content_hash,
                "manifest": json.dumps(manifest),
                "files": json.dumps(file_meta),
                "validation": json.dumps(report),
                "path": relpath,
            },
        )
    return {
        "dataset_id": dataset_id,
        "content_hash": content_hash,
        "status": "staged",
        "validation": report,
        "files": file_meta,
    }


async def stage_directory(
    engine: AsyncEngine,
    tenant_id: str,
    root: str | Path,
    relative_path: str,
    *,
    max_files: int = 32,
    max_file_bytes: int = 10 * 1024 * 1024,
    max_total_bytes: int = 50 * 1024 * 1024,
) -> dict[str, Any]:
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise FileDatasetError("directory must be relative to EARP_FILE_DATA_ROOT")
    source = (_root(root) / relative).resolve()
    if _root(root) not in source.parents or source.is_symlink() or not source.is_dir():
        raise FileDatasetError("directory is unavailable or outside EARP_FILE_DATA_ROOT")
    manifest_path = source / "manifest.yaml"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise FileDatasetError("directory must contain a regular manifest.yaml")
    manifest_bytes = manifest_path.read_bytes()
    manifest = parse_manifest(manifest_bytes)
    files: dict[str, bytes] = {}
    for name in referenced_files(manifest):
        path = source / name
        if not path.is_file() or path.is_symlink():
            raise FileDatasetError(f"referenced file is unavailable: {name}")
        files[name] = path.read_bytes()
    return await stage_dataset(
        engine,
        tenant_id,
        root,
        manifest_bytes,
        files,
        max_files=max_files,
        max_file_bytes=max_file_bytes,
        max_total_bytes=max_total_bytes,
    )


def _public_revision(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "dataset_id": row["dataset_id"],
        "name": row["name"],
        "description": row["description"],
        "latest_staged_hash": row["latest_staged_hash"],
        "latest_published_hash": row["latest_published_hash"],
        "status": "published" if row["latest_published_hash"] else "staged",
        "validation": row.get("validation_json"),
        "files": row.get("files_json"),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
    }


async def list_datasets(engine: AsyncEngine, tenant_id: str) -> list[dict[str, Any]]:
    async with tenant_session(engine, tenant_id) as session:
        rows = await session.execute(
            text(
                "SELECT d.*,r.validation_json,r.files_json FROM file_datasets d LEFT JOIN file_dataset_revisions r "
                "ON r.tenant_id=d.tenant_id AND r.dataset_id=d.dataset_id AND r.content_hash=d.latest_staged_hash "
                "WHERE d.tenant_id=:tenant ORDER BY d.updated_at DESC"
            ),
            {"tenant": tenant_id},
        )
        return [_public_revision(dict(row)) for row in rows.mappings()]


async def get_dataset(engine: AsyncEngine, tenant_id: str, dataset_id: str) -> dict[str, Any] | None:
    async with tenant_session(engine, tenant_id) as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT d.*,r.validation_json,r.files_json FROM file_datasets d "
                        "LEFT JOIN file_dataset_revisions r ON r.tenant_id=d.tenant_id "
                        "AND r.dataset_id=d.dataset_id AND r.content_hash=d.latest_staged_hash "
                        "WHERE d.tenant_id=:tenant AND d.dataset_id=:dataset"
                    ),
                    {"tenant": tenant_id, "dataset": dataset_id},
                )
            )
            .mappings()
            .first()
        )
        return _public_revision(dict(row)) if row else None


async def published_snapshot(
    engine: AsyncEngine, tenant_id: str, dataset_id: str, content_hash: str | None = None
) -> dict[str, Any] | None:
    async with tenant_session(engine, tenant_id) as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT d.dataset_id,d.latest_published_hash,r.manifest_json,r.files_json,r.storage_relpath "
                        "FROM file_datasets d JOIN file_dataset_revisions r ON r.tenant_id=d.tenant_id "
                        "AND r.dataset_id=d.dataset_id AND r.content_hash=COALESCE(:hash,d.latest_published_hash) "
                        "WHERE d.tenant_id=:tenant AND d.dataset_id=:dataset AND r.status='published'"
                    ),
                    {"tenant": tenant_id, "dataset": dataset_id, "hash": content_hash},
                )
            )
            .mappings()
            .first()
        )
    if not row:
        return None
    return {
        "dataset_id": row["dataset_id"],
        "content_hash": content_hash or row["latest_published_hash"],
        "manifest": row["manifest_json"],
        "files": row["files_json"],
        "storage_relpath": row["storage_relpath"],
    }


async def publish_dataset(engine: AsyncEngine, tenant_id: str, root: str | Path, dataset_id: str) -> dict[str, Any]:
    dataset = await get_dataset(engine, tenant_id, dataset_id)
    if not dataset or not dataset["latest_staged_hash"]:
        raise FileDatasetError("dataset has no staged revision")
    content_hash = dataset["latest_staged_hash"]
    async with tenant_session(engine, tenant_id) as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT manifest_json,storage_relpath,validation_json FROM file_dataset_revisions "
                        "WHERE tenant_id=:tenant AND dataset_id=:dataset AND content_hash=:hash"
                    ),
                    {"tenant": tenant_id, "dataset": dataset_id, "hash": content_hash},
                )
            )
            .mappings()
            .one()
        )
        manifest = row["manifest_json"]
        base = (_root(root) / row["storage_relpath"]).resolve()
        warnings = list(row["validation_json"].get("warnings", []))
        source_ref = f"file-dataset://{dataset_id}/{content_hash}"
        try:
            await _publish_catalog(session, tenant_id, manifest, warnings)
            entities = await _publish_entities(session, tenant_id, base, manifest, source_ref, warnings)
            facts = await _publish_relations(session, tenant_id, base, manifest, source_ref, warnings)
        except (IntegrityError, DataError) as error:
            # Defense in depth: manifests staged before parse-time catalog validation may
            # still carry entries the shared schema rejects. Surface them as actionable
            # validation errors instead of a raw 500 mid-transaction.
            raise FileDatasetError(
                "staged manifest content violates the shared catalog schema and cannot be published"
            ) from error
        report = {
            **row["validation_json"],
            "warning_count": len(warnings),
            "warnings": warnings,
            "entities_imported": entities,
            "relations_imported": facts,
        }
        await session.execute(
            text(
                "UPDATE file_dataset_revisions SET status='published',validation_json=:validation,published_at=now() "
                "WHERE tenant_id=:tenant AND dataset_id=:dataset AND content_hash=:hash"
            ),
            {"tenant": tenant_id, "dataset": dataset_id, "hash": content_hash, "validation": json.dumps(report)},
        )
        await session.execute(
            text(
                "UPDATE file_datasets SET latest_published_hash=:hash,updated_at=now() "
                "WHERE tenant_id=:tenant AND dataset_id=:dataset"
            ),
            {"tenant": tenant_id, "dataset": dataset_id, "hash": content_hash},
        )
    return {"dataset_id": dataset_id, "content_hash": content_hash, "status": "published", "validation": report}


async def _publish_catalog(
    session: Any, tenant_id: str, manifest: Mapping[str, Any], warnings: list[dict[str, Any]]
) -> None:
    for item in manifest.get("data_domains", []):
        if not isinstance(item, Mapping):
            continue
        await session.execute(
            text(
                "INSERT INTO data_domains (data_domain_id,tenant_id,name,description,data_classification) "
                "VALUES (:id,:tenant,:name,:description,:classification) "
                "ON CONFLICT (data_domain_id,tenant_id) DO NOTHING"
            ),
            {
                "id": item.get("data_domain_id"),
                "tenant": tenant_id,
                "name": item.get("name") or item.get("data_domain_id"),
                "description": item.get("description"),
                "classification": item.get("data_classification", "internal"),
            },
        )
    for item in manifest.get("entity_types", []):
        if not isinstance(item, Mapping):
            continue
        await session.execute(
            text(
                "INSERT INTO entity_types (entity_type_id,tenant_id,name,kind,description,data_domain_id) "
                "VALUES (:id,:tenant,:name,:kind,:description,:domain) "
                "ON CONFLICT (entity_type_id,tenant_id) DO NOTHING"
            ),
            {
                "id": item.get("entity_type_id"),
                "tenant": tenant_id,
                "name": item.get("name") or item.get("entity_type_id"),
                "kind": item.get("kind", "object"),
                "description": item.get("description"),
                "domain": item.get("data_domain_id"),
            },
        )
    for item in manifest.get("relation_types", []):
        if not isinstance(item, Mapping):
            continue
        source = item.get("source_type", "")
        target = item.get("target_type", "")
        if isinstance(source, list):
            source = ",".join(source)
        if isinstance(target, list):
            target = ",".join(target)
        await session.execute(
            text(
                "INSERT INTO relation_types (relation_type_id,tenant_id,name,source_type,target_type,cardinality) "
                "VALUES (:id,:tenant,:name,:source,:target,:cardinality) "
                "ON CONFLICT (relation_type_id,tenant_id) DO NOTHING"
            ),
            {
                "id": item.get("relation_type_id"),
                "tenant": tenant_id,
                "name": item.get("name") or item.get("relation_type_id"),
                "source": source,
                "target": target,
                "cardinality": item.get("cardinality", "N:M"),
            },
        )


async def _publish_entities(
    session: Any,
    tenant_id: str,
    base: Path,
    manifest: Mapping[str, Any],
    source_ref: str,
    warnings: list[dict[str, Any]],
) -> int:
    spec = manifest.get("entities")
    if not isinstance(spec, Mapping):
        return 0
    _, rows = _decode_csv(spec["file"], (base / spec["file"]).read_bytes())
    columns = spec["columns"]
    entity_types = set(
        (
            await session.execute(
                text("SELECT entity_type_id FROM entity_types WHERE tenant_id=:tenant AND status='active'"),
                {"tenant": tenant_id},
            )
        ).scalars()
    )
    data_domains = set(
        (
            await session.execute(
                text("SELECT data_domain_id FROM data_domains WHERE tenant_id=:tenant"),
                {"tenant": tenant_id},
            )
        ).scalars()
    )
    count = 0
    for row_no, row in enumerate(rows, start=2):
        values = {key: (row.get(column) or "").strip() for key, column in columns.items() if isinstance(column, str)}
        required = ("entity_type", "name", "business_code", "data_domain_id")
        if any(not values.get(key) for key in required):
            continue
        if values["entity_type"] not in entity_types or values["data_domain_id"] not in data_domains:
            warnings.append(
                {
                    "file": spec["file"],
                    "row": row_no,
                    "reason": "entity type or data domain is unavailable; row skipped",
                }
            )
            continue
        existing = (
            (
                await session.execute(
                    text(
                        "SELECT entity_id,entity_type_id FROM entities "
                        "WHERE tenant_id=:tenant AND business_code=:code AND status='active'"
                    ),
                    {"tenant": tenant_id, "code": values["business_code"]},
                )
            )
            .mappings()
            .all()
        )
        same = [item for item in existing if item["entity_type_id"] == values["entity_type"]]
        if same:
            continue
        if existing:
            warnings.append(
                {
                    "file": spec["file"],
                    "row": row_no,
                    "reason": "business_code exists with another entity type; row skipped",
                }
            )
            continue
        entity_id = values.get("entity_id") or f"ent-{uuid.uuid4().hex[:12]}"
        id_exists = await session.execute(
            text("SELECT 1 FROM entities WHERE entity_id=:id"),
            {"id": entity_id},
        )
        if id_exists.first():
            warnings.append({"file": spec["file"], "row": row_no, "reason": "entity_id already exists; row skipped"})
            continue
        inserted = await session.execute(
            text(
                "INSERT INTO entities (entity_id,tenant_id,entity_type_id,name,business_code,attributes,"
                "source_mode,source_ref,data_domain_id) "
                "VALUES (:id,:tenant,:type,:name,:code,'{}'::jsonb,'extracted',:source,:domain) "
                "ON CONFLICT (entity_id) DO NOTHING RETURNING entity_id"
            ),
            {
                "id": entity_id,
                "tenant": tenant_id,
                "type": values["entity_type"],
                "name": values["name"],
                "code": values["business_code"],
                "source": source_ref,
                "domain": values["data_domain_id"],
            },
        )
        if inserted.scalar_one_or_none() is None:
            warnings.append(
                {
                    "file": spec["file"],
                    "row": row_no,
                    "reason": "entity_id conflicts with another tenant; row skipped",
                }
            )
        else:
            count += 1
    return count


async def _entity_by_code(session: Any, tenant_id: str, code: str, entity_type: str | None) -> str | None:
    sql = "SELECT entity_id FROM entities WHERE tenant_id=:tenant AND business_code=:code AND status='active'"
    params: dict[str, Any] = {"tenant": tenant_id, "code": code}
    if entity_type:
        sql += " AND entity_type_id=:type"
        params["type"] = entity_type
    rows = (await session.execute(text(sql), params)).scalars().all()
    return rows[0] if len(rows) == 1 else None


async def _publish_relations(
    session: Any,
    tenant_id: str,
    base: Path,
    manifest: Mapping[str, Any],
    source_ref: str,
    warnings: list[dict[str, Any]],
) -> int:
    spec = manifest.get("relations")
    if not isinstance(spec, Mapping):
        return 0
    _, rows = _decode_csv(spec["file"], (base / spec["file"]).read_bytes())
    columns = spec["columns"]
    relation_types = set(
        (
            await session.execute(
                text("SELECT relation_type_id FROM relation_types WHERE tenant_id=:tenant AND status='active'"),
                {"tenant": tenant_id},
            )
        ).scalars()
    )
    count = 0
    for row_no, row in enumerate(rows, start=2):

        def value(key: str, current: Mapping[str, str] = row) -> str:
            return (current.get(columns.get(key, "")) or "").strip()

        source_code, relation_type, target_code = value("source_code"), value("relation_type"), value("target_code")
        if not source_code or not relation_type or not target_code:
            continue
        if relation_type not in relation_types:
            warnings.append(
                {"file": spec["file"], "row": row_no, "reason": "relation type is unavailable; row skipped"}
            )
            continue
        source = await _entity_by_code(session, tenant_id, source_code, value("source_type") or None)
        target = await _entity_by_code(session, tenant_id, target_code, value("target_type") or None)
        if not source or not target:
            warnings.append(
                {
                    "file": spec["file"],
                    "row": row_no,
                    "reason": "relation source or target is missing/ambiguous; row skipped",
                }
            )
            continue
        exists = await session.execute(
            text(
                "SELECT 1 FROM facts WHERE tenant_id=:tenant AND source_entity_id=:source "
                "AND relation_type_id=:relation AND target_entity_id=:target "
                "AND status='active' AND valid_to IS NULL"
            ),
            {"tenant": tenant_id, "source": source, "relation": relation_type, "target": target},
        )
        if exists.first():
            continue
        try:
            confidence = float(value("confidence") or 1.0)
            if not 0 <= confidence <= 1:
                raise ValueError
        except ValueError:
            warnings.append({"file": spec["file"], "row": row_no, "reason": "invalid confidence; row skipped"})
            continue
        await session.execute(
            text(
                "INSERT INTO facts (fact_id,tenant_id,source_entity_id,relation_type_id,target_entity_id,"
                "confidence,source_ref) VALUES (:id,:tenant,:source,:relation,:target,:confidence,:ref)"
            ),
            {
                "id": f"fact-{uuid.uuid4().hex[:12]}",
                "tenant": tenant_id,
                "source": source,
                "relation": relation_type,
                "target": target,
                "confidence": confidence,
                "ref": source_ref,
            },
        )
        count += 1
    return count


def _aggregation(value: object) -> str:
    raw = str(value or "mean").lower()
    for name in SUPPORTED_AGGREGATIONS:
        if raw == name or raw.startswith(f"{name}_"):
            return name
    if raw.startswith("availability_"):
        return "mean"
    raise FileDatasetError(f"unsupported file aggregation: {value}")


def _aggregate(rows: list[tuple[datetime, float, float]], method: str) -> tuple[float, float]:
    if method == "latest":
        _, value, baseline = max(rows, key=lambda item: item[0])
        return value, baseline
    values = [item[1] for item in rows]
    baselines = [item[2] for item in rows]
    if method == "sum":
        return sum(values), sum(baselines)
    if method == "mean":
        return sum(values) / len(values), sum(baselines) / len(baselines)
    fn = min if method == "min" else max
    return fn(values), fn(baselines)


async def acquire_observation(
    engine: AsyncEngine, tenant_id: str, root: str | Path, input_: Mapping[str, Any]
) -> dict[str, Any]:
    from earp_server.bmc.reasoning.runtime import _now, _observation, _required_string

    pin = input_.get("file_dataset")
    if not isinstance(pin, Mapping):
        raise FileDatasetError("reasoning.acquire requires a pinned file_dataset")
    dataset_id = _required_string(pin.get("dataset_id"), "file_dataset.dataset_id")
    content_hash = _required_string(pin.get("content_hash"), "file_dataset.content_hash")
    snapshot = await published_snapshot(engine, tenant_id, dataset_id, content_hash)
    if not snapshot:
        raise FileDatasetInfrastructureError("pinned file dataset revision is unavailable")
    manifest = snapshot["manifest"]
    provider_key = input_.get("provider_key")
    contract = input_.get("capability_contract_ref")
    provider = next(
        (
            item
            for item in manifest["providers"]
            if item.get("provider_key") == provider_key and item.get("capability_contract_ref") == contract
        ),
        None,
    )
    if provider is None:
        # 可选未绑定需求：规划期解析为 unbound_optional（provider_key=None）。与 fixture
        # 适配器（runtime.py，文档明确 DATA_UNAVAILABLE 只返回不抛错）一致，以业务终态
        # 返回而非抛基础设施错误——否则被 connector 当作 connection 错误重试，整轮失败。
        if input_.get("provider_resolution_status") == "unbound_optional" or provider_key is None:
            return _unavailable(
                input_,
                provider_key,
                dataset_id,
                content_hash,
                "no file provider binding for optional requirement",
            )
        raise FileDatasetInfrastructureError("pinned file provider binding is unavailable")
    requirement_key = _required_string(input_.get("requirement_key"), "requirement_key")
    mapping = provider["requirements"].get(requirement_key)
    if not isinstance(mapping, Mapping):
        return _unavailable(input_, provider_key, dataset_id, content_hash, "requirement is not mapped")
    base = (_root(root) / snapshot["storage_relpath"]).resolve()
    path = (base / provider["file"]).resolve()
    if base not in path.parents or not path.is_file() or path.is_symlink():
        raise FileDatasetInfrastructureError("pinned CSV file is unavailable")
    expected = next((item["sha256"] for item in snapshot["files"] if item["name"] == provider["file"]), None)
    content = path.read_bytes()
    if not expected or hashlib.sha256(content).hexdigest() != expected:
        raise FileDatasetInfrastructureError("pinned CSV file hash mismatch")
    _, csv_rows = _decode_csv(provider["file"], content)
    target = input_.get("target")
    window = input_.get("time_window")
    if not isinstance(target, Mapping) or not isinstance(window, Mapping):
        raise FileDatasetError("reasoning.acquire target/time_window is invalid")
    try:
        start = datetime.fromisoformat(str(window["start"]))
        end = datetime.fromisoformat(str(window["end"]))
    except (KeyError, ValueError) as error:
        raise FileDatasetError("reasoning.acquire time_window is invalid") from error
    matches: list[tuple[datetime, float, float]] = []
    for row in csv_rows:
        if (row.get(provider["entity_column"]) or "").strip() != target.get("entity_id"):
            continue
        if _provider_row_error(provider, row):
            continue
        observed_at = datetime.fromisoformat(row[provider["time_column"]])
        if start <= observed_at < end:
            matches.append((observed_at, float(row[mapping["value_column"]]), float(row[mapping["baseline_column"]])))
    if not matches:
        return _unavailable(
            input_, provider_key, dataset_id, content_hash, "no valid row matched target and time window"
        )
    method = _aggregation((input_.get("measurement") or {}).get("aggregation"))
    value, baseline = _aggregate(matches, method)
    source_ref = f"file-dataset://{dataset_id}/{content_hash}/{provider['file']}"
    observation = _observation(
        input_,
        provider_key=provider_key,
        source_ref=source_ref,
        status="VALID",
        quality={"status": "valid", "observed_at": _now(), "matched_rows": len(matches), "aggregation": method},
        value=value,
        baseline_value=baseline,
    )
    observation["unit"] = mapping["unit"]
    observation["measurement"]["unit"] = mapping["unit"]
    observation["provenance"].update(
        {"dataset_id": dataset_id, "dataset_content_hash": content_hash, "file": provider["file"]}
    )
    return {
        "terminal_state": "business",
        "task_status": "completed",
        "requirement_id": input_.get("requirement_id"),
        "requirement_level": input_.get("requirement_level"),
        "observation": observation,
    }


def _unavailable(
    input_: Mapping[str, Any], provider_key: str | None, dataset_id: str, content_hash: str, message: str
) -> dict[str, Any]:
    from earp_server.bmc.reasoning.runtime import _now, _observation

    source_ref = f"file-dataset://{dataset_id}/{content_hash}"
    observation = _observation(
        input_,
        provider_key=provider_key,
        source_ref=source_ref,
        status="DATA_UNAVAILABLE",
        quality={"status": "data_unavailable", "observed_at": _now()},
        error={"code": "DATA_UNAVAILABLE", "message": message},
    )
    observation["provenance"].update({"dataset_id": dataset_id, "dataset_content_hash": content_hash})
    return {
        "terminal_state": "business",
        "task_status": "completed",
        "requirement_id": input_.get("requirement_id"),
        "requirement_level": input_.get("requirement_level"),
        "observation": observation,
    }


def copy_package(source: Path, destination: Path) -> None:
    """Kept as a small test seam for storage implementations."""
    shutil.copytree(source, destination, dirs_exist_ok=True)
