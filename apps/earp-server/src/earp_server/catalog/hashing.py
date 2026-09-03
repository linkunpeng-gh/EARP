"""Frozen Catalog canonical JSON and SHA-256 contract implementation.

This is the production counterpart of ``arch/catalog/scripts/generate_golden_hashes.py``.
Every production entry point requires a schema version; unknown versions fail closed.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from decimal import Decimal
from typing import Any

CANONICALIZER_VERSION = "sha256/canonical-json/v1"
SCHEMA_CANONICALIZER_MAP = {
    "catalog-manifest/v1": CANONICALIZER_VERSION,
    "catalog-pack/v1": CANONICALIZER_VERSION,
    "catalog-profile/v1": CANONICALIZER_VERSION,
    "catalog-profile/v2": CANONICALIZER_VERSION,
    "catalog-attestation/v1": CANONICALIZER_VERSION,
    "catalog-domain/v1": CANONICALIZER_VERSION,
    "catalog-entity/v1": CANONICALIZER_VERSION,
    "catalog-relation/v1": CANONICALIZER_VERSION,
    "catalog-metric/v1": CANONICALIZER_VERSION,
    "catalog-unit/v1": CANONICALIZER_VERSION,
    "catalog-aggregation/v1": CANONICALIZER_VERSION,
    "catalog-time-window/v1": CANONICALIZER_VERSION,
    "catalog-binding-template/v1": CANONICALIZER_VERSION,
    "catalog-capability/v1": CANONICALIZER_VERSION,
    "catalog-rule/v1": CANONICALIZER_VERSION,
}

_DESCRIPTION_FIELDS = frozenset({"description", "notes", "rationale", "comment", "remarks"})


class CatalogCanonicalizationError(ValueError):
    """A payload cannot be canonicalized under its declared frozen contract."""


def _pointer_segment(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _description_path(path: str) -> bool:
    return bool(path) and path.rsplit("/", 1)[-1].replace("~1", "/").replace("~0", "~") in _DESCRIPTION_FIELDS


def _validate_text(value: str, path: str, *, key: bool = False) -> None:
    for index, char in enumerate(value):
        codepoint = ord(char)
        category = unicodedata.category(char)
        if not key and codepoint in {0x0A, 0x09} and _description_path(path):
            continue
        if category in {"Cc", "Cf"}:
            raise CatalogCanonicalizationError(f"control character U+{codepoint:04X} at {path}[{index}]")


def _decimal(value: Decimal) -> str:
    if not value.is_finite():
        raise CatalogCanonicalizationError("NaN and Infinity are forbidden")
    if value == 0:
        return "0"
    sign, digits, exponent = value.as_tuple()
    if not isinstance(exponent, int):
        raise CatalogCanonicalizationError("NaN and Infinity are forbidden")
    digits_list = list(digits)
    while exponent < 0 and len(digits_list) > 1 and digits_list[-1] == 0:
        digits_list.pop()
        exponent += 1
    if exponent >= 0:
        encoded = "".join(map(str, digits_list)) + "0" * exponent
    else:
        integer_length = len(digits_list) + exponent
        if integer_length > 0:
            integer = "".join(map(str, digits_list[:integer_length]))
            fraction = "".join(map(str, digits_list[integer_length:]))
            encoded = integer + "." + fraction
        else:
            encoded = "0." + "0" * (-integer_length) + "".join(map(str, digits_list))
    return "-" + encoded if sign else encoded


def _serialize(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, Decimal):
        return _decimal(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ",".join(_serialize(item) for item in value) + "]"
    if isinstance(value, dict):
        items = (json.dumps(key, ensure_ascii=False) + ":" + _serialize(value[key]) for key in sorted(value))
        return "{" + ",".join(items) + "}"
    raise CatalogCanonicalizationError(f"unsupported canonical value type: {type(value).__name__}")


def _item_key(value: Any) -> tuple[int, str]:
    if value is None:
        tag = 0
    elif isinstance(value, bool):
        tag = 1
    elif isinstance(value, (int, Decimal)):
        tag = 2
    elif isinstance(value, str):
        tag = 3
    elif isinstance(value, list):
        tag = 4
    else:
        tag = 5
    return tag, _serialize(value)


def _collection(path: str) -> list[str] | None:
    fixed = {
        "/entries": ["kind", "stable_id", "version"],
        "/pack_lock": ["layer", "pack_id"],
        "/owners": ["role_key"],
        "/signers": ["role_key", "name"],
        "/attributes": ["name"],
    }
    if path in fixed:
        return fixed[path]
    if path.endswith(("/required", "/enum", "/type")):
        return []
    return None


def _canonicalize_v1(value: Any, path: str = "") -> Any:
    if value is None or isinstance(value, bool) or isinstance(value, int):
        return value
    if isinstance(value, float):
        raise CatalogCanonicalizationError("binary floats are forbidden; use Decimal")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise CatalogCanonicalizationError("NaN and Infinity are forbidden")
        return value
    if isinstance(value, str):
        normalized = unicodedata.normalize("NFC", value)
        _validate_text(normalized, path)
        return normalized
    if isinstance(value, list):
        items = [_canonicalize_v1(item, f"{path}/{index}") for index, item in enumerate(value)]
        fields = _collection(path)
        if fields is not None:
            if fields:
                if not all(isinstance(item, dict) for item in items):
                    raise CatalogCanonicalizationError(f"collection {path} must contain objects")
                items.sort(key=lambda item: tuple(_item_key(item.get(field)) for field in fields))
                keys = [tuple(item.get(field) for field in fields) for item in items]
            else:
                items.sort(key=_item_key)
                keys = [_item_key(item) for item in items]
            if len(set(keys)) != len(keys):
                raise CatalogCanonicalizationError(f"duplicate collection identity at {path}")
        return items
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            if not isinstance(raw_key, str):
                raise CatalogCanonicalizationError("object keys must be strings")
            key = unicodedata.normalize("NFC", raw_key)
            if key in output:
                raise CatalogCanonicalizationError(f"NFC key collision at {path}/{key}")
            child_path = f"{path}/{_pointer_segment(key)}"
            _validate_text(key, child_path, key=True)
            normalized = _canonicalize_v1(raw_value, child_path)
            if normalized is not None and normalized != "":
                output[key] = normalized
        return output
    raise CatalogCanonicalizationError(f"unsupported canonical value type: {type(value).__name__}")


def canonical_json(value: dict[str, Any], *, schema_version: str) -> str:
    """Produce canonical JSON for an explicitly declared supported schema version."""
    if SCHEMA_CANONICALIZER_MAP.get(schema_version) != CANONICALIZER_VERSION:
        raise CatalogCanonicalizationError(f"unknown schema/canonicalizer version: {schema_version!r}")
    return _serialize(_canonicalize_v1(value))


def content_hash(value: dict[str, Any], *, schema_version: str) -> str:
    """Return the frozen SHA-256 pin for an explicitly versioned payload."""
    return hashlib.sha256(canonical_json(value, schema_version=schema_version).encode("utf-8")).hexdigest()
