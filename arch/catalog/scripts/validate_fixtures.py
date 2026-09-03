#!/usr/bin/env python3
"""
CI validation for Catalog fixtures: manifest + attestation.

Validates:
1. manifest-example.json passes catalog-manifest.schema.json
2. manifest_hash recomputes correctly from projection (x_hash_projection_whitelist)
3. attestation-example.json passes catalog-attestation.schema.json
4. envelope_hash recomputes correctly from envelope fields
5. Negative: tampering effective_from changes envelope_hash
6. Negative: tampering manifest_hash changes envelope_hash
7. signers array is sorted (collection path /signers)

Usage:
  .venv/bin/python arch/catalog/scripts/validate_fixtures.py
"""
import json
import sys
import os
from pathlib import Path
from jsonschema import validate, ValidationError, FormatChecker

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT / "arch/catalog/scripts"))
from generate_golden_hashes import canonical_json, sha256, load_json_canonical

SCHEMAS = ROOT / "arch/catalog/schemas"
FIXTURES = SCHEMAS / "fixtures"

# Manifest hash projection whitelist (from catalog-manifest.schema.json x_hash_projection_whitelist)
MANIFEST_HASH_FIELDS = [
    "manifest_schema_version", "manifest_id", "manifest_revision",
    "scope", "pack_lock", "entries", "owners", "resolver_adapter"
]

# Envelope fields (from attestation schema)
ENVELOPE_FIELDS = [
    "manifest_hash", "signoff_tag", "change_order", "signed_at",
    "effective_from", "effective_until", "signers"
]


def validate_manifest():
    errors = []
    schema = json.load(open(SCHEMAS / "catalog-manifest.schema.json"))
    m = load_json_canonical(open(FIXTURES / "manifest-example.json").read())

    # 1. Schema validation
    try:
        validate(m, schema, format_checker=FormatChecker())
        print("[OK] manifest fixture passes schema")
    except ValidationError as e:
        errors.append(f"manifest schema: {e.message}")
        return errors

    # 2. manifest_hash recomputation (using schema_version to select canonicalizer)
    projection = {k: m[k] for k in MANIFEST_HASH_FIELDS if k in m}
    recomputed = sha256(canonical_json(projection, schema_version=m["manifest_schema_version"]))
    if recomputed == m["manifest_hash"]:
        print(f"[OK] manifest_hash recomputes correctly ({recomputed[:16]}...)")
    else:
        errors.append(f"manifest_hash mismatch: declared={m['manifest_hash'][:16]}..., recomputed={recomputed[:16]}...")

    # 3. entries sorted by (kind, stable_id, version)
    entries = m["entries"]
    expected = sorted(entries, key=lambda e: (e["kind"], e["stable_id"], e["version"]))
    if entries == expected:
        print("[OK] entries sorted by (kind, stable_id, version)")
    else:
        errors.append("entries not sorted")

    # 4. pack_lock sorted by (layer, pack_id)
    pl = m["pack_lock"]
    expected_pl = sorted(pl, key=lambda x: (x["layer"], x["pack_id"]))
    if pl == expected_pl:
        print("[OK] pack_lock sorted by (layer, pack_id)")
    else:
        errors.append("pack_lock not sorted")

    return errors


def validate_attestation():
    errors = []
    schema = json.load(open(SCHEMAS / "catalog-attestation.schema.json"))
    a = load_json_canonical(open(FIXTURES / "attestation-example.json").read())

    # 1. Schema validation
    try:
        validate(a, schema, format_checker=FormatChecker())
        print("[OK] attestation fixture passes schema")
    except ValidationError as e:
        errors.append(f"attestation schema: {e.message}")
        return errors

    # 2. envelope_hash recomputation (using schema_version to select canonicalizer)
    envelope = {k: a[k] for k in ENVELOPE_FIELDS if k in a}
    recomputed = sha256(canonical_json(envelope, schema_version=a["attestation_schema_version"]))
    if recomputed == a["envelope_hash"]:
        print(f"[OK] envelope_hash recomputes correctly ({recomputed[:16]}...)")
    else:
        errors.append(f"envelope_hash mismatch: declared={a['envelope_hash'][:16]}..., recomputed={recomputed[:16]}...")

    # 3. signers sorted by (role_key, name)
    signers = a["signers"]
    expected = sorted(signers, key=lambda s: (s["role_key"], s["name"]))
    if signers == expected:
        print("[OK] signers sorted by (role_key, name)")
    else:
        errors.append("signers not sorted")

    # 4. Negative: tamper effective_from → envelope_hash changes
    env2 = dict(envelope)
    env2["effective_from"] = "2026-10-01T00:00:00+08:00"
    h_tampered = sha256(canonical_json(env2, schema_version=a["attestation_schema_version"]))
    if h_tampered != a["envelope_hash"]:
        print("[OK] tampering effective_from changes envelope_hash")
    else:
        errors.append("tampering effective_from did NOT change envelope_hash")

    # 5. Negative: tamper manifest_hash → envelope_hash changes
    env3 = dict(envelope)
    env3["manifest_hash"] = "0" * 64
    h_tampered2 = sha256(canonical_json(env3, schema_version=a["attestation_schema_version"]))
    if h_tampered2 != a["envelope_hash"]:
        print("[OK] tampering manifest_hash changes envelope_hash")
    else:
        errors.append("tampering manifest_hash did NOT change envelope_hash")

    # 6. attestation manifest_hash matches manifest fixture
    m = load_json_canonical(open(FIXTURES / "manifest-example.json").read())
    if a["manifest_hash"] == m["manifest_hash"]:
        print("[OK] attestation.manifest_hash matches manifest fixture")
    else:
        errors.append("attestation.manifest_hash does not match manifest fixture")

    return errors


def main():
    print("=== Catalog Fixture CI Validation ===")
    all_errors = []

    print("\n--- Manifest ---")
    all_errors.extend(validate_manifest())

    print("\n--- Attestation ---")
    all_errors.extend(validate_attestation())

    if all_errors:
        print(f"\n=== FAILED ({len(all_errors)} errors) ===")
        for e in all_errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print("\n=== ALL FIXTURE VALIDATIONS PASSED ===")


if __name__ == "__main__":
    main()
