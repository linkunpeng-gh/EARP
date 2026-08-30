"""Fixture-backed logical Capability Contract resolution for Case A.

The Case A fixture describes *logical* contracts and deterministic mock
providers.  Those are deliberately not rows in ``business_capabilities``:
the latter is the existing physical registry and does not yet model the
logical-contract layer.  This adapter is therefore an explicit, test-only
binding between the two concepts, rather than a misleading implicit lookup.

Resolution may choose a provider.  It must never alter the target or time
window emitted by Reasoning Prepare.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast


class CapabilityResolutionError(ValueError):
    """A logical requirement cannot safely be bound to a Case A provider."""


@dataclass(frozen=True)
class ResolvedCapability:
    """The provider binding for one logical evidence requirement."""

    contract_ref: str
    provider_key: str | None
    status: str
    required: bool


class FixtureCapabilityResolver:
    """Resolve Case A's frozen Contract -> Mock Provider mapping.

    ``unavailable_provider_keys`` is an explicit planning-time availability
    input used by contract tests and by a future physical registry adapter. It
    is intentionally not consulted by Prepare.
    """

    def __init__(self, fixture_dir: Path, *, unavailable_provider_keys: set[str] | None = None) -> None:
        self._fixture_dir = fixture_dir
        self._unavailable_provider_keys = unavailable_provider_keys or set()
        self._document = self._load_document(fixture_dir)

    @staticmethod
    def _load_document(fixture_dir: Path) -> dict[str, Any]:
        try:
            document = json.loads((fixture_dir / "capability_fixture.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise CapabilityResolutionError("Case A capability fixture is unavailable or invalid") from error
        if not isinstance(document, dict) or document.get("schema_version") != "case-a-capability-fixture/v1":
            raise CapabilityResolutionError("unsupported Case A capability fixture schema")
        for key in ("contracts", "mock_providers", "provider_bindings"):
            if not isinstance(document.get(key), list):
                raise CapabilityResolutionError(f"Case A capability fixture {key} must be a list")
        return document

    def resolve(self, requirement: Mapping[str, Any]) -> ResolvedCapability:
        contract_ref = requirement.get("capability_contract_ref")
        source_requirement_id = requirement.get("source_requirement_id")
        target_type = requirement.get("target_entity_type")
        level = requirement.get("requirement_level")
        if not all(isinstance(value, str) and value for value in (contract_ref, source_requirement_id, target_type)):
            raise CapabilityResolutionError("prepared requirement lacks contract, source identity, or target type")
        # The all() guard cannot narrow tuple elements; cast after validation.
        contract_ref = cast(str, contract_ref)
        source_requirement_id = cast(str, source_requirement_id)
        target_type = cast(str, target_type)
        if level not in {"required", "optional"}:
            raise CapabilityResolutionError("prepared requirement must be required or optional")
        required = level == "required"

        contracts = {item.get("contract_ref"): item for item in self._document["contracts"] if isinstance(item, dict)}
        contract = contracts.get(contract_ref)
        if not isinstance(contract, dict):
            raise CapabilityResolutionError(f"unknown logical capability contract: {contract_ref}")
        if contract.get("input_scope") != target_type:
            raise CapabilityResolutionError("logical capability contract is incompatible with Prepare target type")

        provider_by_key = {
            item.get("provider_key"): item for item in self._document["mock_providers"] if isinstance(item, dict)
        }
        bindings = {
            item.get("requirement_id"): item.get("provider_key")
            for item in self._document["provider_bindings"]
            if isinstance(item, dict)
        }
        provider_key = bindings.get(source_requirement_id)
        provider = provider_by_key.get(provider_key)
        usable = (
            isinstance(provider_key, str)
            and isinstance(provider, dict)
            and provider.get("contract_ref") == contract_ref
            and target_type in provider.get("applicable_entity_types", [])
            and provider_key not in self._unavailable_provider_keys
        )
        if usable:
            return ResolvedCapability(contract_ref, provider_key, "bound", required)
        if required:
            raise CapabilityResolutionError(
                f"required evidence requirement {source_requirement_id} has no available compatible provider"
            )
        # An optional unbound requirement remains an acquisition task.  T10
        # will turn it into a terminal missing-observation business outcome;
        # it is not silently dropped before Evaluate.
        return ResolvedCapability(contract_ref, None, "unbound_optional", required)
