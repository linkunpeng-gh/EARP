"""Versioned N01A canonical JSON and SHA-256 implementation."""

from __future__ import annotations

import hashlib
import math
import unicodedata
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Any

CAUSAL_SNAPSHOT_SCHEMA = "causal-snapshot/v1"
BLUEPRINT_IR_SCHEMA = "blueprint-ir/v1"
CANONICALIZER_VERSION = "n01a-canonical-json/v1"

_SNAPSHOT_FIELDS = frozenset(
    {
        "snapshot_schema_version",
        "model_identity",
        "diagnostic_target",
        "algorithm_profile",
        "nodes",
        "edges",
        "rules",
        "evidence_requirements",
        "applicability",
        "catalog_resolutions",
        "semantic_schema_versions",
    }
)
_ARTIFACT_FIELDS = frozenset(
    {
        "artifact_schema_version",
        "source_models",
        "intents",
        "goal_skeletons",
        "constraints",
        "output_contracts",
        "fallback_policy",
        "step_type_pins",
        "steps",
        "dependencies",
        "step_sources",
        "capability_requirements",
    }
)


class CanonicalizationError(ValueError):
    pass


def _nfc(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    for char in normalized:
        category = unicodedata.category(char)
        if category == "Cc" and char not in {"\n", "\t"}:
            raise CanonicalizationError("invisible control characters are forbidden")
    return normalized


def _decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise CanonicalizationError("NaN and Infinity are forbidden")
    if value == 0:
        return "0"
    normalized = value.normalize()
    result = format(normalized, "f")
    if "." in result:
        result = result.rstrip("0").rstrip(".")
    return result


def _quote(value: str) -> str:
    escaped: list[str] = ['"']
    for char in value:
        code = ord(char)
        if char == '"':
            escaped.append('\\"')
        elif char == "\\":
            escaped.append("\\\\")
        elif char == "\b":
            escaped.append("\\b")
        elif char == "\f":
            escaped.append("\\f")
        elif char == "\n":
            escaped.append("\\n")
        elif char == "\r":
            escaped.append("\\r")
        elif char == "\t":
            escaped.append("\\t")
        elif code < 0x20:
            escaped.append(f"\\u{code:04x}")
        else:
            escaped.append(char)
    escaped.append('"')
    return "".join(escaped)


def _encode(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return _quote(_nfc(value))
    if isinstance(value, Decimal):
        return _decimal_text(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalizationError("NaN and Infinity are forbidden")
        raise CanonicalizationError("binary floats are forbidden; use Decimal")
    if isinstance(value, list | tuple):
        return "[" + ",".join(_encode(item) for item in value) + "]"
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise CanonicalizationError("object keys must be strings")
        normalized: list[tuple[str, Any]] = [(_nfc(key), item) for key, item in value.items() if isinstance(key, str)]
        if len({key for key, _ in normalized}) != len(normalized):
            raise CanonicalizationError("Unicode normalization produced duplicate object keys")
        normalized.sort(key=lambda item: item[0])
        return "{" + ",".join(f"{_quote(key)}:{_encode(item)}" for key, item in normalized) + "}"
    raise CanonicalizationError(f"unsupported canonical value type: {type(value).__name__}")


def _key(*fields: str) -> Callable[[dict[str, Any]], tuple[str, ...]]:
    def select(value: dict[str, Any]) -> tuple[str, ...]:
        try:
            return tuple(_nfc(str(value[field])) for field in fields)
        except KeyError as error:
            raise CanonicalizationError(f"semantic collection item lacks stable key {error.args[0]}") from error

    return select


def _sort_list(payload: dict[str, Any], field: str, selector: Callable[[dict[str, Any]], tuple[str, ...]]) -> None:
    value = payload.get(field)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise CanonicalizationError(f"{field} must be an array of objects")
    items: list[dict[str, Any]] = [item for item in value if isinstance(item, dict)]
    keys = [selector(item) for item in items]
    if len(set(keys)) != len(keys):
        raise CanonicalizationError(f"{field} contains duplicate stable keys")
    pairs: list[tuple[tuple[str, ...], dict[str, Any]]] = list(zip(keys, items, strict=True))
    pairs.sort(key=lambda pair: pair[0])
    payload[field] = [item for _, item in pairs]


def _copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy(item) for item in value]
    return value


def _validate_top_level(payload: dict[str, Any], allowed: frozenset[str], schema_field: str, schema: str) -> None:
    actual = frozenset(payload)
    if actual != allowed:
        missing = sorted(allowed - actual)
        unknown = sorted(actual - allowed)
        raise CanonicalizationError(f"invalid top-level fields; missing={missing}, unknown={unknown}")
    if payload.get(schema_field) != schema:
        raise CanonicalizationError(f"unsupported schema: {payload.get(schema_field)!r}")


def normalize_causal_snapshot(value: dict[str, Any]) -> dict[str, Any]:
    payload = _copy(value)
    _validate_top_level(payload, _SNAPSHOT_FIELDS, "snapshot_schema_version", CAUSAL_SNAPSHOT_SCHEMA)
    _sort_list(payload, "nodes", _key("node_key"))
    _sort_list(payload, "edges", _key("from_node_key", "to_node_key", "edge_key"))
    _sort_list(payload, "rules", _key("rule_key"))
    _sort_list(payload, "evidence_requirements", _key("node_key", "requirement_key"))
    _sort_list(payload, "catalog_resolutions", _key("kind", "stable_id", "version"))
    for requirement in payload["evidence_requirements"]:
        supporting = requirement.get("supporting_contract_refs", [])
        if not isinstance(supporting, list) or not all(isinstance(item, dict) for item in supporting):
            raise CanonicalizationError("supporting_contract_refs must be an array of objects")
        requirement["supporting_contract_refs"] = sorted(supporting, key=_key("kind", "stable_id", "version"))
    return payload


def _intent_key(value: dict[str, Any]) -> tuple[str, ...]:
    return _key("entry_point", "direction", "domain", "business_objective", "intent_key")(value)


def normalize_blueprint_ir(value: dict[str, Any]) -> dict[str, Any]:
    payload = _copy(value)
    _validate_top_level(payload, _ARTIFACT_FIELDS, "artifact_schema_version", BLUEPRINT_IR_SCHEMA)
    _sort_list(
        payload,
        "source_models",
        _key("model_type", "model_id", "model_version", "source_snapshot_id", "model_role"),
    )
    _sort_list(payload, "intents", _intent_key)
    _sort_list(payload, "goal_skeletons", _key("goal_skeleton_key"))
    _sort_list(payload, "constraints", _key("constraint_key"))
    _sort_list(payload, "output_contracts", _key("output_key"))
    _sort_list(payload, "step_type_pins", _key("step_type", "version", "handler_version", "handler_hash"))
    _sort_list(payload, "steps", _key("ordinal", "step_key"))
    _sort_list(payload, "dependencies", _key("from_step_key", "to_step_key", "dep_type"))
    _sort_list(
        payload,
        "step_sources",
        _key("step_key", "source_ref_key", "element_type", "element_key", "role"),
    )
    _sort_list(payload, "capability_requirements", _key("requirement_key"))
    return payload


def canonical_json(value: dict[str, Any], family: str) -> str:
    if family == CAUSAL_SNAPSHOT_SCHEMA:
        normalized = normalize_causal_snapshot(value)
    elif family == BLUEPRINT_IR_SCHEMA:
        normalized = normalize_blueprint_ir(value)
    else:
        raise CanonicalizationError(f"unsupported canonical family: {family}")
    return _encode(normalized)


def canonical_hash(value: dict[str, Any], family: str) -> str:
    return hashlib.sha256(canonical_json(value, family).encode("utf-8")).hexdigest()


def decimal(value: str | int | Decimal) -> Decimal:
    """Parse an API decimal without ever passing through binary float."""
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(value)
    except InvalidOperation as error:
        raise CanonicalizationError("invalid decimal") from error
    if not parsed.is_finite():
        raise CanonicalizationError("NaN and Infinity are forbidden")
    return parsed
