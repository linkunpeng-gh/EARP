#!/usr/bin/env python3
"""
Golden hash generator for Catalog 10 kinds.

Canonicalization rules (FROZEN, per CONTRACT-ECMC-N01A-CANONICALIZATION §1.1):
1. Unicode NFC normalization on all string values
2. Recursive key sorting (all objects)
3. Array sorting: PATH-AWARE + TYPE-AWARE. Arrays default to PRESERVE ORDER.
   Only explicitly declared collection paths are sorted, using (type_tag, canonical_value) keys.
   - /entries (manifest) → kind, stable_id, version
   - /pack_lock (manifest) → layer, pack_id
   - /owners (manifest) → role_key
   - /signers (attestation envelope) → role_key, name
   - /attributes (entity_type) → name
   - any path ending /required (JSON Schema) → sort by typed value
   - any path ending /enum (JSON Schema) → sort by typed value
   - any path ending /type when array (JSON Schema) → sort by typed value
4. Null/empty handling: object OPTIONAL fields with null or "" are omitted;
   array elements are FULLY PRESERVED (including null and "").
5. Text validation: reject C0/C1 invisible control chars by default;
   description/notes fields allow \n and \t only.
6. Numbers: Decimal semantic parse (parse_float=Decimal); reject binary float;
   shortest decimal NON-EXPONENTIAL output via as_tuple(); -0 → 0.
7. Duplicate rejection: duplicate JSON keys, NFC key collisions, duplicate
   collection composite keys, and duplicate primitive collection elements are rejected.
8. JSON: separators=(',', ':'), ensure_ascii=False, custom Decimal serializer
9. SHA-256 of UTF-8 encoded canonical JSON

Usage:
  .venv/bin/python arch/catalog/scripts/generate_golden_hashes.py
  .venv/bin/python arch/catalog/scripts/generate_golden_hashes.py --check
"""
import json
import hashlib
import os
import sys
import unicodedata
from decimal import Decimal, InvalidOperation

# Canonicalizer version. Any change to normalization rules requires a new version.
# Old payloads must use the canonicalizer version recorded in their schema.
# Current frozen algorithm: sha256/canonical-json/v1 (no prior Catalog hash was published).
CANONICALIZER_VERSION = "sha256/canonical-json/v1"

# Mapping: schema_version → canonicalizer version.
# Per CONTRACT §1.1: "旧 payload 一律使用旧版本实现校验，绝不'升级后重算'."
# All current Phase 1 schemas use v1. Future breaking changes create /v2 schemas
# and a new canonicalize_v2() implementation; v1 payloads continue to use v1.
# NOTE: catalog-profile/v1 and /v2 are RESERVED mappings. Current Profile validation
# uses file blob SHA-256 (not canonical JSON). These entries exist so future Profile
# canonical-hash support has a version slot; they are not used by validate_catalog.py.
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


def resolve_canonicalizer(schema_version):
    """Resolve schema_version to canonicalizer implementation.
    Unknown or unmapped versions are rejected (fail closed)."""
    canon_version = SCHEMA_CANONICALIZER_MAP.get(schema_version)
    if canon_version is None:
        raise ValueError(
            f"Unknown schema_version {schema_version!r}. "
            f"Must be one of: {sorted(SCHEMA_CANONICALIZER_MAP.keys())}"
        )
    if canon_version == "sha256/canonical-json/v1":
        return canonicalize_v1
    raise ValueError(
        f"Canonicalizer {canon_version!r} is not implemented. "
        f"Only {CANONICALIZER_VERSION} is available."
    )


# Fields that are "explanation" text and may contain \n, \t
_DESCRIPTION_FIELDS = frozenset({"description", "notes", "rationale", "comment", "remarks"})


def _is_description_path(path):
    """Return True if the JSON Pointer path points to an explanation field."""
    if not path:
        return False
    last_segment = path.rsplit("/", 1)[-1]
    # Unescape JSON Pointer: ~1 -> /, ~0 -> ~
    last_segment = last_segment.replace("~1", "/").replace("~0", "~")
    return last_segment in _DESCRIPTION_FIELDS


def validate_text(s, path):
    """Reject invisible control characters per CONTRACT §1.1 item 2.
    - Default: reject Unicode Cc (C0/C1 control) and Cf (format control) chars.
    - Description/notes fields: allow \n (0x0A) and \t (0x09), reject all others.
    Cf includes zero-width space (U+200B), bidirectional overrides (U+202E), etc.
    """
    is_desc = _is_description_path(path)
    for i, ch in enumerate(s):
        cp = ord(ch)
        cat = unicodedata.category(ch)
        if cp == 0x0A or cp == 0x09:  # \n, \t
            if is_desc:
                continue
            raise ValueError(
                f"Control character \\{'n' if cp == 0x0A else 't'} not allowed at {path}[{i}]. "
                f"Only description/notes fields may contain newlines/tabs."
            )
        if cat in ("Cc", "Cf"):
            raise ValueError(
                f"Invisible control character U+{cp:04X} (category {cat}) at {path}[{i}] "
                f"is not allowed in canonical input."
            )


def validate_key(key, path):
    """Validate object key: reject ALL control characters (no description exception).
    Keys are identifiers, not free text — no \n, \t, or invisible chars allowed."""
    for i, ch in enumerate(key):
        cat = unicodedata.category(ch)
        if cat in ("Cc", "Cf"):
            raise ValueError(
                f"Control character U+{ord(ch):04X} (category {cat}) in key at {path}[{i}] "
                f"is not allowed. Object keys must not contain control characters."
            )


def nfc_str(s):
    return unicodedata.normalize('NFC', s)


def _reject_duplicate_keys(pairs):
    """object_pairs_hook: reject duplicate keys in raw JSON input."""
    seen = set()
    result = {}
    for k, v in pairs:
        if k in seen:
            raise ValueError(f"Duplicate key in JSON input: {k!r}")
        seen.add(k)
        result[k] = v
    return result


def load_json_canonical(text):
    """Load JSON with Decimal semantic parsing and duplicate-key rejection.
    - parse_float=Decimal (no binary float)
    - object_pairs_hook rejects duplicate keys
    Use this instead of json.loads for any input that feeds canonicalization."""
    return json.loads(text, parse_float=Decimal, object_pairs_hook=_reject_duplicate_keys)


def serialize_decimal(d):
    """Serialize Decimal to shortest non-exponential decimal string.
    Uses as_tuple() directly — NO normalize(), NO context precision loss.
    - Remove trailing zeros from fractional part only
    - Non-exponential (fixed-point)
    - -0 → 0
    Per CONTRACT-ECMC-N01A-CANONICALIZATION §1.1 item 5.
    """
    if d == 0:
        return "0"  # handles both 0 and -0
    sign, digits, exp = d.as_tuple()
    digit_list = list(digits)

    # Remove trailing zeros ONLY from fractional part (exp < 0)
    # Integer-part trailing zeros (exp >= 0) are significant
    while exp < 0 and len(digit_list) > 1 and digit_list[-1] == 0:
        digit_list.pop()
        exp += 1

    if exp >= 0:
        # Integer: digits followed by exp zeros
        result = ''.join(str(x) for x in digit_list) + '0' * exp
    else:
        # Fractional: insert decimal point
        int_len = len(digit_list) + exp  # exp is negative
        if int_len > 0:
            int_part = ''.join(str(x) for x in digit_list[:int_len])
            frac_part = ''.join(str(x) for x in digit_list[int_len:])
        else:
            int_part = '0'
            frac_part = '0' * (-int_len) + ''.join(str(x) for x in digit_list)
        result = int_part + '.' + frac_part

    if sign:
        result = '-' + result
    return result


def normalize_number(n):
    """Normalize numbers per contract. Accept int and Decimal; REJECT binary float."""
    if isinstance(n, bool):
        return n
    if isinstance(n, int):
        return n
    if isinstance(n, Decimal):
        # Reject NaN and Infinity
        if n.is_nan() or n.is_infinite():
            raise ValueError(f"NaN/Infinity not allowed in canonical input: {n}")
        return n
    if isinstance(n, float):
        raise TypeError(
            f"Binary float not allowed in canonical input: {n!r}. "
            f"Use load_json_canonical() (parse_float=Decimal) or pass Decimal."
        )
    return n


def type_tag(v):
    """Type tag for stable collection sorting. Distinguishes all JSON types."""
    if v is None:
        return 0
    if isinstance(v, bool):
        return 1
    if isinstance(v, (int, Decimal)):
        return 2
    if isinstance(v, str):
        return 3
    if isinstance(v, list):
        return 4
    if isinstance(v, dict):
        return 5
    return 9


def serialize_canonical(obj):
    """Custom JSON serializer that handles Decimal natively.
    Produces sorted-keys, no-whitespace JSON with canonical Decimal formatting."""
    if obj is None:
        return "null"
    if isinstance(obj, bool):
        return "true" if obj else "false"
    if isinstance(obj, int):
        return str(obj)
    if isinstance(obj, Decimal):
        return serialize_decimal(obj)
    if isinstance(obj, str):
        # Use json.dumps for proper string escaping (NFC already applied)
        return json.dumps(obj, ensure_ascii=False)
    if isinstance(obj, list):
        return "[" + ",".join(serialize_canonical(x) for x in obj) + "]"
    if isinstance(obj, dict):
        parts = []
        for k in sorted(obj.keys()):
            parts.append(json.dumps(k, ensure_ascii=False) + ":" + serialize_canonical(obj[k]))
        return "{" + ",".join(parts) + "}"
    raise TypeError(f"Cannot serialize type {type(obj)}")


def collection_item_key(v):
    """Stable sort key for collection items: (type_tag, canonical_serialization).
    Ensures mixed-type enums like [1, "1"] sort deterministically regardless of input order."""
    return (type_tag(v), serialize_canonical(v))


# Path-aware sort policies
def _is_collection_path(path):
    """Return (is_collection, sort_keys) for a given JSON Pointer path.
    sort_keys is a list of dict keys for object arrays, or None for primitive arrays."""
    if path == "/entries":
        return True, ["kind", "stable_id", "version"]
    if path == "/pack_lock":
        return True, ["layer", "pack_id"]
    if path == "/owners":
        return True, ["role_key"]
    if path == "/signers":
        return True, ["role_key", "name"]
    if path == "/attributes":
        return True, ["name"]
    if path.endswith("/required"):
        return True, None
    if path.endswith("/enum"):
        return True, None
    if path.endswith("/type"):
        return True, None
    return False, None


def _escape_pointer_segment(seg):
    return seg.replace("~", "~0").replace("/", "~1")


def canonicalize_v1(obj, path=""):
    """Canonicalizer v1 (FROZEN): path-aware, type-aware canonicalization.
    Arrays preserve ALL elements (including null and "").
    Objects omit optional null and empty-string fields.
    Numbers must be int or Decimal; binary float is rejected.
    This implementation is bound to sha256/canonical-json/v1 and must not change
    without creating canonicalize_v2() and new /v2 schemas.
    IMPORTANT: internal recursion MUST call canonicalize_v1() directly, NOT the
    generic canonicalize() dispatcher. Otherwise a future v2 default would cause
    "top-level v1, child nodes v2" mixed normalization and break historical hashes.
    """
    if obj is None:
        return None
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, (int, Decimal, float)):
        return normalize_number(obj)
    if isinstance(obj, str):
        # NFC normalize, but DO NOT convert "" to None here.
        # Empty-string removal happens only at object-field level.
        s = nfc_str(obj)
        validate_text(s, path)
        return s
    if isinstance(obj, list):
        # Arrays preserve all elements, including null and ""
        items = []
        for i, item in enumerate(obj):
            child_path = f"{path}/{i}"
            c = canonicalize_v1(item, child_path)
            items.append(c)
        is_coll, sort_keys = _is_collection_path(path)
        if is_coll and items:
            if sort_keys and isinstance(items[0], dict):
                def obj_sort_key(x):
                    return tuple(collection_item_key(x.get(k)) for k in sort_keys)
                items.sort(key=obj_sort_key)
                # Reject duplicate composite keys (P1: duplicate identity causes order-dependent hash)
                seen_keys = set()
                for item in items:
                    key = tuple(item.get(k) for k in sort_keys)
                    if key in seen_keys:
                        raise ValueError(
                            f"Duplicate composite key {sort_keys}={key} in collection {path}. "
                            f"Collection entries must have unique identity."
                        )
                    seen_keys.add(key)
            else:
                items.sort(key=collection_item_key)
                # Reject duplicate elements in primitive collections
                # (required/enum/type): semantically equivalent ["a"] and ["a","a"]
                # must not produce different hashes.
                seen = set()
                for item in items:
                    key = collection_item_key(item)
                    if key in seen:
                        raise ValueError(
                            f"Duplicate element {item!r} in collection {path}. "
                            f"Primitive collection entries must be unique."
                        )
                    seen.add(key)
        return items
    if isinstance(obj, dict):
        result = {}
        seen_keys = set()
        for k in sorted(obj.keys()):
            nk = nfc_str(k)
            # Detect NFC-normalized key collisions
            if nk in seen_keys:
                raise ValueError(f"NFC key collision at {path}/{nk}: two input keys normalize to same key")
            seen_keys.add(nk)
            child_path = f"{path}/{_escape_pointer_segment(nk)}"
            # Object keys must not contain any control characters (no description exception)
            validate_key(nk, child_path)
            v = canonicalize_v1(obj[k], child_path)
            # Object fields: omit null and empty string (optional field = absent)
            if v is not None and v != "":
                result[nk] = v
        return result
    return obj


def canonicalize(obj, path="", schema_version=None):
    """Version-dispatching canonicalizer.
    schema_version: e.g. "catalog-manifest/v1". Resolved via SCHEMA_CANONICALIZER_MAP.
    If None, uses current CANONICALIZER_VERSION (backward compat for tests).
    Unknown versions are rejected (fail closed)."""
    if schema_version is None:
        canon_fn = canonicalize_v1
    else:
        canon_fn = resolve_canonicalizer(schema_version)
    return canon_fn(obj, path)


def canonical_json(obj, schema_version):
    """Production entry: serialize canonical object to canonical JSON string.
    schema_version is REQUIRED (e.g. "catalog-manifest/v1") to select the
    canonicalizer implementation via SCHEMA_CANONICALIZER_MAP.
    Unknown versions are rejected (fail closed).
    For self-tests, use canonical_json_v1_for_test(obj) instead."""
    if schema_version is None:
        raise ValueError(
            "canonical_json() requires schema_version. "
            "Use canonical_json_v1_for_test() for test helpers, or pass the explicit schema version."
        )
    c = canonicalize(obj, "", schema_version)
    return serialize_canonical(c)


def canonical_json_v1_for_test(obj):
    """Test helper: canonical JSON using frozen v1 algorithm, no schema_version needed.
    ONLY for self-tests. Production code must use canonical_json(obj, schema_version)."""
    return canonical_json(obj, schema_version="catalog-unit/v1")


def sha256(s):
    return hashlib.sha256(s.encode('utf-8')).hexdigest()


# Path-aware sorting handles all collection paths (see _is_collection_path).
# entity_type attributes sorted by /attributes path automatically.

GOLDEN = {
    "data_domain": {
        "kind": "data_domain", "stable_id": "jqmk.production", "version": "1.0.0",
        "domain_id": "production", "semantic_schema_version": "catalog-domain/v1",
        "name": "生产域", "description": "煤矿生产数据域"
    },
    "entity_type": {
        "kind": "entity_type", "stable_id": "coal.mine", "version": "1.0.0",
        "entity_type_id": "coal.mine", "name": "矿井", "kind_type": "object",
        "data_domain_id": "production", "semantic_schema_version": "catalog-entity/v1",
        "description": "煤矿矿井实体",
        "attributes": [
            {"name": "mine_code", "type": "string", "required": True},
            {"name": "capacity", "type": "number", "required": False}
        ]
    },
    "relation_type": {
        "kind": "relation_type", "stable_id": "coal.mines", "version": "1.0.0",
        "relation_type_id": "coal.mines", "name": "拥有工作面",
        "source_type": "coal.mine", "target_type": "coal.working_face",
        "cardinality": "one_to_many", "semantic_schema_version": "catalog-relation/v1",
        "description": "矿井拥有多个工作面"
    },
    "metric": {
        "kind": "metric", "stable_id": "coal.raw_coal_output", "version": "1.0.0",
        "metric_id": "coal.raw_coal_output", "name": "原煤产量",
        "data_domain_id": "production", "semantic_schema_version": "catalog-metric/v1",
        "description": "工作面原煤产量",
        "value_semantics": {
            "measurement_type": "continuous_flow",
            "unit_ref": {"kind": "unit", "stable_id": "common.mass.tonne", "version": "1.0.0"},
            "aggregation_ref": {"kind": "aggregation", "stable_id": "common.agg.daily_total", "version": "1.0.0"},
            "time_window_ref": {"kind": "time_window_schema", "stable_id": "common.time.shift", "version": "1.0.0"}
        }
    },
    "unit": {
        "kind": "unit", "stable_id": "common.mass.tonne", "version": "1.0.0",
        "unit_id": "common.mass.tonne", "name": "吨", "symbol": "t",
        "dimension": "mass", "description": "公吨"
    },
    "aggregation": {
        "kind": "aggregation", "stable_id": "common.agg.daily_total", "version": "1.0.0",
        "aggregation_id": "common.agg.daily_total", "name": "日累计",
        "formula_type": "sum", "description": "按自然日求和"
    },
    "time_window_schema": {
        "kind": "time_window_schema", "stable_id": "common.time.shift", "version": "1.0.0",
        "window_id": "common.time.shift", "name": "班次", "duration": "8h",
        "alignment": "shift", "shift_definition": "早班 00-08, 中班 08-16, 夜班 16-24",
        "description": "三八制班次"
    },
    "binding_template": {
        "kind": "binding_template", "stable_id": "coal.equipment_binding", "version": "1.0.0",
        "template_id": "coal.equipment_binding", "name": "设备→工作面绑定",
        "description": "将设备绑定到工作面",
        "params_schema": {
            "type": "object",
            "properties": {
                "equipment_type_ref": {"type": "ref", "kind": "entity_type", "label": "设备类型"},
                "working_face_ref": {"type": "ref", "kind": "entity_type", "label": "工作面"}
            },
            "required": ["equipment_type_ref", "working_face_ref"]
        }
    },
    "capability_contract": {
        "kind": "capability_contract", "stable_id": "coal.production_forecast", "version": "1.0.0",
        "capability_id": "coal.production_forecast", "name": "产量预测", "role": "primary",
        "input_schema": {"type": "object", "properties": {"face_id": {"type": "string"}}},
        "output_schema": {"type": "object", "properties": {"forecast_tonnage": {"type": "number"}}},
        "description": "工作面产量预测能力"
    },
    "rule_schema": {
        "kind": "rule_schema", "stable_id": "common.rule.sign_propagation_v1", "version": "1.0.0",
        "rule_id": "common.rule.sign_propagation_v1", "name": "符号传播 v1",
        "algorithm_profile": "sign-propagation/v1",
        "params_schema": {"type": "object", "properties": {"damping": {"type": "number"}}},
        "description": "因果符号传播算法"
    }
}


# Kind → schema_version mapping for golden hash computation.
# Ensures golden fixtures exercise version routing, not just the default path.
KIND_SCHEMA_VERSION = {
    "data_domain": "catalog-domain/v1",
    "entity_type": "catalog-entity/v1",
    "relation_type": "catalog-relation/v1",
    "metric": "catalog-metric/v1",
    "unit": "catalog-unit/v1",
    "aggregation": "catalog-aggregation/v1",
    "time_window_schema": "catalog-time-window/v1",
    "binding_template": "catalog-binding-template/v1",
    "capability_contract": "catalog-capability/v1",
    "rule_schema": "catalog-rule/v1",
}


def compute_results():
    results = {}
    for kind, obj in GOLDEN.items():
        schema_version = KIND_SCHEMA_VERSION[kind]
        cj = canonical_json(obj, schema_version=schema_version)
        h = sha256(cj)
        results[kind] = {
            "stable_id": obj["stable_id"],
            "version": obj["version"],
            "schema_version": schema_version,
            "canonical_json": cj,
            "content_hash": h
        }
    return results


def run_self_tests():
    errors = []
    nfd_name = unicodedata.normalize('NFD', '吨')
    if canonical_json_v1_for_test({"kind": "unit", "name": "吨", "stable_id": "x", "version": "1.0.0"}) != \
       canonical_json_v1_for_test({"kind": "unit", "name": nfd_name, "stable_id": "x", "version": "1.0.0"}):
        errors.append("NFC/NFD not equivalent")
    if canonical_json_v1_for_test({"b": 1, "a": 2}) != canonical_json_v1_for_test({"a": 2, "b": 1}):
        errors.append("Key order not normalized")
    if canonical_json_v1_for_test({"a": 1, "b": None, "c": ""}) != canonical_json_v1_for_test({"a": 1}):
        errors.append("Null/empty not removed from object fields")

    # Arrays PRESERVE null and "" (only object fields omit optional null/empty)
    if canonical_json_v1_for_test({"enum": [None, 1]}) == canonical_json_v1_for_test({"enum": [1]}):
        errors.append("Array null element incorrectly removed")
    if canonical_json_v1_for_test({"enum": ["", "x"]}) == canonical_json_v1_for_test({"enum": ["x"]}):
        errors.append("Array empty-string element incorrectly removed")
    # Array with null and "" still sorts correctly as collection
    if canonical_json_v1_for_test({"enum": [None, 1, "a"]}) != canonical_json_v1_for_test({"enum": ["a", None, 1]}):
        errors.append("Mixed enum with null/empty not sorted deterministically")

    # === Decimal number tests (per CONTRACT §1.1: Decimal semantic, non-exponential) ===
    D = Decimal
    # Adjacent high-precision decimals must NOT collide
    if canonical_json_v1_for_test({"x": D("1.23456789011")}) == canonical_json_v1_for_test({"x": D("1.23456789012")}):
        errors.append("Adjacent high-precision decimals collide")
    # Very close to integer but not exactly integer must NOT become int
    if canonical_json_v1_for_test({"x": D("1.00000000001")}) == canonical_json_v1_for_test({"x": 1}):
        errors.append("1.00000000001 incorrectly normalized to int 1")
    # Exact integral decimal becomes int
    if canonical_json_v1_for_test({"x": D("1.0")}) != canonical_json_v1_for_test({"x": 1}):
        errors.append("Decimal('1.0') not normalized to int 1")
    # -0 → 0
    if canonical_json_v1_for_test({"x": D("-0")}) != canonical_json_v1_for_test({"x": 0}):
        errors.append("Decimal('-0') not normalized to 0")
    # Trailing zeros removed
    if canonical_json_v1_for_test({"x": D("1.2300")}) != canonical_json_v1_for_test({"x": D("1.23")}):
        errors.append("Trailing zeros not removed (1.2300 != 1.23)")
    # Non-exponential output: 1e-7 → "0.0000001", 1e20 → "100000000000000000000"
    if serialize_decimal(D("1e-7")) != "0.0000001":
        errors.append(f"1e-7 not non-exponential: got {serialize_decimal(D('1e-7'))}")
    if serialize_decimal(D("1e20")) != "100000000000000000000":
        errors.append(f"1e20 not non-exponential: got {serialize_decimal(D('1e20'))}")
    if serialize_decimal(D("0.000001")) != "0.000001":
        errors.append(f"0.000001 serialization wrong: got {serialize_decimal(D('0.000001'))}")
    # 1e21 also non-exponential
    if serialize_decimal(D("1e21")) != "1000000000000000000000":
        errors.append(f"1e21 not non-exponential: got {serialize_decimal(D('1e21'))}")
    # High precision: 40+ significant digits must NOT be rounded (as_tuple bypasses context)
    hp = "1.123456789012345678901234567890123456789"
    if serialize_decimal(D(hp)) != hp:
        errors.append(f"High-precision decimal rounded: got {serialize_decimal(D(hp))}")
    hp2 = "9.999999999999999999999999999999999999999"
    if serialize_decimal(D(hp2)) != hp2:
        errors.append(f"High-precision 9.999... rounded to 10: got {serialize_decimal(D(hp2))}")
    # Very large integer
    if serialize_decimal(D("1" + "0" * 50)) != "1" + "0" * 50:
        errors.append("Very large integer not preserved")
    # Very small decimal
    if serialize_decimal(D("0." + "0" * 30 + "1")) != "0." + "0" * 30 + "1":
        errors.append("Very small decimal not preserved")
    # NaN/Infinity rejected (Decimal)
    for bad in [D("NaN"), D("Infinity"), D("-Infinity")]:
        try:
            canonical_json_v1_for_test({"x": bad})
            errors.append(f"Decimal NaN/Infinity not rejected: {bad}")
        except (ValueError, OverflowError):
            pass
    # Binary float REJECTED (contract: 禁止二进制 float)
    try:
        canonical_json_v1_for_test({"x": 1.5})
        errors.append("Binary float not rejected (should use Decimal)")
    except TypeError:
        pass
    # load_json_canonical uses parse_float=Decimal
    loaded = load_json_canonical('{"x": 1.23456789012345}')
    if not isinstance(loaded["x"], Decimal):
        errors.append("load_json_canonical did not parse float as Decimal")

    # Duplicate key rejection in raw JSON
    try:
        load_json_canonical('{"a": 1, "a": 2}')
        errors.append("Duplicate JSON key not rejected")
    except ValueError:
        pass

    # NFC key collision rejection (é precomposed vs e+combining accent)
    e_acute = unicodedata.normalize('NFC', 'é')
    e_combining = unicodedata.normalize('NFD', 'é')
    if e_acute != e_combining:  # they should differ before NFC
        try:
            canonical_json_v1_for_test({e_acute: 1, e_combining: 2})
            errors.append("NFC key collision not rejected")
        except ValueError:
            pass

    # Duplicate composite key in collection object array
    try:
        canonical_json_v1_for_test({"entries": [
            {"kind": "unit", "stable_id": "a", "version": "1.0.0", "x": 1},
            {"kind": "unit", "stable_id": "a", "version": "1.0.0", "x": 2}
        ]})
        errors.append("Duplicate composite key in /entries not rejected")
    except ValueError:
        pass

    # === Control character validation ===
    # C0 control char rejected in normal field
    try:
        canonical_json_v1_for_test({"name": "hello\u0001world"})
        errors.append("C0 control char not rejected in normal field")
    except ValueError:
        pass
    # \n rejected in normal field (not description)
    try:
        canonical_json_v1_for_test({"name": "hello\nworld"})
        errors.append("Newline not rejected in normal field")
    except ValueError:
        pass
    # \n allowed in description field
    try:
        canonical_json_v1_for_test({"description": "hello\nworld\twith tab"})
    except ValueError:
        errors.append("Newline/tab incorrectly rejected in description field")
    # C1 control char rejected
    try:
        canonical_json_v1_for_test({"name": "hello\u0085world"})
        errors.append("C1 control char not rejected")
    except ValueError:
        pass
    # Cf format control chars rejected (zero-width space, RTL override)
    try:
        canonical_json_v1_for_test({"name": "hello\u200bworld"})
        errors.append("Cf zero-width space not rejected")
    except ValueError:
        pass
    try:
        canonical_json_v1_for_test({"name": "hello\u202eworld"})
        errors.append("Cf bidirectional override not rejected")
    except ValueError:
        pass
    # Object key with control char rejected (no description exception)
    try:
        canonical_json_v1_for_test({"nam\u0001e": 1})
        errors.append("Control char in object key not rejected")
    except ValueError:
        pass
    try:
        canonical_json_v1_for_test({"nam\u200be": 1})
        errors.append("Cf char in object key not rejected")
    except ValueError:
        pass

    # === Version routing tests ===
    # Unknown schema_version rejected
    try:
        canonical_json({"a": 1}, schema_version="catalog-unknown/v99")
        errors.append("Unknown schema_version not rejected")
    except ValueError:
        pass
    # v1 schema_version routes to canonicalize_v1, same result as default
    if canonical_json({"b": 1, "a": 2}, schema_version="catalog-manifest/v1") != \
       canonical_json_v1_for_test({"b": 1, "a": 2}):
        errors.append("v1 schema_version produces different result than default")
    # manifest fixture schema version maps to v1 canonicalizer
    if resolve_canonicalizer("catalog-manifest/v1") != canonicalize_v1:
        errors.append("catalog-manifest/v1 does not resolve to canonicalize_v1")
    # Version isolation: canonicalize_v1 must recurse on itself, not via generic dispatcher.
    # Direct call on deeply nested object proves v1 is self-contained.
    nested = {"a": {"b": [{"c": 1, "d": "x"}, {"c": 2, "d": "y"}]}, "e": None}
    direct = serialize_canonical(canonicalize_v1(nested, ""))
    via_dispatch = canonical_json(nested, schema_version="catalog-manifest/v1")
    if direct != via_dispatch:
        errors.append("canonicalize_v1 direct recursion differs from dispatched result")
    # compute_results uses explicit schema_version per kind (verify KIND_SCHEMA_VERSION covers all)
    if set(KIND_SCHEMA_VERSION.keys()) != set(GOLDEN.keys()):
        errors.append(f"KIND_SCHEMA_VERSION mismatch: {set(KIND_SCHEMA_VERSION.keys()) ^ set(GOLDEN.keys())}")

    # === Golden fixture full-comparison negative tests ===
    # Simulate the --check full comparison: tampered fixture must fail
    frozen_fields = ["stable_id", "version", "schema_version", "canonical_json", "content_hash"]
    base_results = compute_results()

    def _fixture_mismatches(computed, fixture):
        """Replicate main() --check comparison logic, return list of mismatch strings."""
        m = []
        if set(computed.keys()) != set(fixture.keys()):
            m.append("kind set mismatch")
        for kind in sorted(set(computed.keys()) & set(fixture.keys())):
            for f in frozen_fields:
                if computed[kind].get(f) != fixture[kind].get(f):
                    m.append(f"{kind}.{f}")
        return m

    # Tamper schema_version → must detect
    tampered_sv = json.loads(json.dumps(base_results))
    tampered_sv["unit"]["schema_version"] = "catalog-unit/v99"
    if not _fixture_mismatches(base_results, tampered_sv):
        errors.append("Tampered schema_version not detected by full comparison")
    # Tamper canonical_json → must detect
    tampered_cj = json.loads(json.dumps(base_results))
    tampered_cj["metric"]["canonical_json"] = "{}"
    if not _fixture_mismatches(base_results, tampered_cj):
        errors.append("Tampered canonical_json not detected by full comparison")
    # Missing kind → must detect
    missing_kind = json.loads(json.dumps(base_results))
    del missing_kind["unit"]
    if not _fixture_mismatches(base_results, missing_kind):
        errors.append("Missing kind not detected by full comparison")
    # Extra kind → must detect
    extra_kind = json.loads(json.dumps(base_results))
    extra_kind["unknown_kind"] = {"content_hash": "x"}
    if not _fixture_mismatches(base_results, extra_kind):
        errors.append("Extra kind not detected by full comparison")
    # Untampered → no mismatches
    if _fixture_mismatches(base_results, json.loads(json.dumps(base_results))):
        errors.append("Untampered fixture incorrectly reported mismatches")

    # === Duplicate primitive collection element rejection ===
    try:
        canonical_json_v1_for_test({"required": ["a", "a"]})
        errors.append("Duplicate element in /required not rejected")
    except ValueError:
        pass
    try:
        canonical_json_v1_for_test({"enum": ["x", "x"]})
        errors.append("Duplicate element in /enum not rejected")
    except ValueError:
        pass
    # Mixed-type duplicate: 1 and "1" have different type_tag, so NOT duplicate
    try:
        canonical_json_v1_for_test({"enum": [1, "1"]})
    except ValueError:
        errors.append("Mixed-type [1,'1'] incorrectly rejected as duplicate")

    # === Type-aware collection sorting ===
    # Mixed-type enum: [1, "1"] and ["1", 1] must have same hash (unordered set)
    if canonical_json_v1_for_test({"enum": [1, "1"]}) != canonical_json_v1_for_test({"enum": ["1", 1]}):
        errors.append("Mixed-type enum [1,'1'] not sorted deterministically")
    # Mixed-type with null: [null, 1, "a"] reorder = same
    if canonical_json_v1_for_test({"enum": [None, 1, "a"]}) != canonical_json_v1_for_test({"enum": ["a", None, 1]}):
        errors.append("Mixed-type enum with null not sorted deterministically")
    # bool vs int: true and 1 have different type tags
    if canonical_json_v1_for_test({"enum": [True, 1]}) == canonical_json_v1_for_test({"enum": [1, True]}):
        pass  # should be same after sorting
    else:
        errors.append("bool/int enum not sorted deterministically")

    # === Path-aware array sorting tests ===
    # Collection paths (/required, /enum) should be sorted → reorder = same hash
    if canonical_json_v1_for_test({"required": ["b", "a", "c"]}) != canonical_json_v1_for_test({"required": ["a", "b", "c"]}):
        errors.append("/required array not sorted (collection path)")
    if canonical_json_v1_for_test({"enum": ["x", "z", "y"]}) != canonical_json_v1_for_test({"enum": ["x", "y", "z"]}):
        errors.append("/enum array not sorted (collection path)")
    # Nested /required inside JSON Schema should also be sorted
    schema_a = {"properties": {"x": {"type": "string"}}, "required": ["b", "a"]}
    schema_b = {"properties": {"x": {"type": "string"}}, "required": ["a", "b"]}
    if canonical_json_v1_for_test(schema_a) != canonical_json_v1_for_test(schema_b):
        errors.append("nested /required not sorted")

    # Non-collection arrays (/default, /examples) should PRESERVE order → reorder = different hash
    if canonical_json_v1_for_test({"default": [1, 2]}) == canonical_json_v1_for_test({"default": [2, 1]}):
        errors.append("/default array incorrectly sorted (ordered array collision!)")
    if canonical_json_v1_for_test({"examples": ["first", "second"]}) == canonical_json_v1_for_test({"examples": ["second", "first"]}):
        errors.append("/examples array incorrectly sorted (ordered array collision!)")

    # Object array collection paths: /entries, /pack_lock, /owners, /attributes
    entries_a = {"entries": [{"kind": "unit", "stable_id": "b"}, {"kind": "unit", "stable_id": "a"}]}
    entries_b = {"entries": [{"kind": "unit", "stable_id": "a"}, {"kind": "unit", "stable_id": "b"}]}
    if canonical_json_v1_for_test(entries_a) != canonical_json_v1_for_test(entries_b):
        errors.append("/entries not sorted by (kind, stable_id)")
    attrs_a = {"attributes": [{"name": "b"}, {"name": "a"}]}
    attrs_b = {"attributes": [{"name": "a"}, {"name": "b"}]}
    if canonical_json_v1_for_test(attrs_a) != canonical_json_v1_for_test(attrs_b):
        errors.append("/attributes not sorted by name")
    # /signers sorted by (role_key, name)
    signers_a = {"signers": [{"role_key": "b", "name": "B"}, {"role_key": "a", "name": "A"}]}
    signers_b = {"signers": [{"role_key": "a", "name": "A"}, {"role_key": "b", "name": "B"}]}
    if canonical_json_v1_for_test(signers_a) != canonical_json_v1_for_test(signers_b):
        errors.append("/signers not sorted by (role_key, name)")

    # Non-collection object array should preserve order
    custom_a = {"items": [{"name": "b"}, {"name": "a"}]}
    custom_b = {"items": [{"name": "a"}, {"name": "b"}]}
    if canonical_json_v1_for_test(custom_a) == canonical_json_v1_for_test(custom_b):
        errors.append("non-collection object array incorrectly sorted")

    results = compute_results()
    for kind, r in results.items():
        if len(r["content_hash"]) != 64:
            errors.append(f"{kind}: hash not 64 chars")
    if errors:
        print("SELF-TEST FAILURES:")
        for e in errors:
            print(f"  - {e}")
        return False
    print("All self-tests passed (55 tests).")
    return True


def main():
    check_mode = "--check" in sys.argv
    if not run_self_tests():
        sys.exit(1)
    results = compute_results()
    out_path = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'schemas', 'golden-hashes.json'))
    if check_mode:
        if not os.path.exists(out_path):
            print(f"FAIL: {out_path} does not exist")
            sys.exit(1)
        with open(out_path, 'r', encoding='utf-8') as f:
            existing = json.load(f)
        mismatches = []
        # 1. Kind set must match exactly (no missing, no extra)
        expected_kinds = set(results.keys())
        actual_kinds = set(existing.keys())
        if expected_kinds != actual_kinds:
            missing = expected_kinds - actual_kinds
            extra = actual_kinds - expected_kinds
            if missing:
                mismatches.append(f"missing kinds: {sorted(missing)}")
            if extra:
                mismatches.append(f"unexpected kinds: {sorted(extra)}")
        # 2. Compare ALL frozen fields per kind (not just content_hash)
        frozen_fields = ["stable_id", "version", "schema_version", "canonical_json", "content_hash"]
        for kind in sorted(expected_kinds & actual_kinds):
            r = results[kind]
            e = existing[kind]
            for field in frozen_fields:
                rv = r.get(field)
                ev = e.get(field)
                if rv != ev:
                    if field == "canonical_json":
                        mismatches.append(f"{kind}.{field}: mismatch (len computed={len(rv)}, len fixture={len(ev)})")
                    else:
                        mismatches.append(f"{kind}.{field}: computed={rv!r}, fixture={ev!r}")
        if mismatches:
            print("CHECK FAILED:")
            for m in mismatches:
                print(f"  - {m}")
            sys.exit(1)
        print(f"CHECK PASSED: all {len(results)} golden fixtures match (full field comparison).")
    else:
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"Written to {out_path}")
        for kind, r in results.items():
            print(f"  {kind:25s} {r['content_hash'][:16]}...")


if __name__ == '__main__':
    main()
