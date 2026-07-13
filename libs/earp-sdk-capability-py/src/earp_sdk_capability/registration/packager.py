"""Capability Packager — converts a Python Capability class into the L2-03 three-layer JSON structure.

The packager is the bridge between developer-friendly SDK code and
the platform's Capability Center. It reads class metadata, introspects
type annotations, and generates the standardized format.

Usage:

    from earp_sdk_capability.registration.packager import packager
    from my_caps import QueryEquipmentAlarm

    package = packager.pack(QueryEquipmentAlarm)
    # package["definition"]["capability_id"] == "query_equipment_alarm"
    # package["definition"]["input_schema"]["$schema"] == "https://json-schema.org/draft-07/schema#"
    # package["execution_contract"]["idempotent"] == True
    # package["policy"]["auth_required"] == True
"""

from __future__ import annotations

import inspect
from typing import Any, get_args, get_origin

from pydantic import BaseModel

from earp_sdk_capability.base import Capability
from earp_sdk_capability.contracts import generate_contract, generate_policy
from earp_sdk_capability.schema import schema_of


class Packager:
    """Converts a Capability class into a three-layer JSON package."""

    def pack(self, cap_cls: type[Capability]) -> dict[str, Any]:
        """Convert a Capability subclass into the L2-03 three-layer structure.

        Args:
            cap_cls: A Capability subclass (must have capability_id set).

        Returns:
            dict with keys: "definition", "execution_contract", "policy".

        Raises:
            ValueError: If the class is missing required fields.
        """
        if not issubclass(cap_cls, Capability):
            raise ValueError(f"{cap_cls.__name__} is not a Capability subclass")

        # Resolve InputT and OutputT from Generic base class
        input_model, output_model = self._resolve_io_types(cap_cls)

        # Read metadata from class (set by @capability decorator or direct assignment)
        capability_id = getattr(cap_cls, "capability_id", "") or cap_cls.__name__
        name = getattr(cap_cls, "name", "") or capability_id
        description = getattr(cap_cls, "description", "")
        domain = getattr(cap_cls, "domain", "")
        version = getattr(cap_cls, "version", "0.1.0")
        tags = getattr(cap_cls, "tags", [])
        capability_type = getattr(cap_cls, "capability_type", "query")

        # Validate required fields
        if not description:
            raise ValueError(f"Capability '{capability_id}' must have a description")
        if not domain:
            raise ValueError(f"Capability '{capability_id}' must have a domain")

        # Auto-generate schemas
        input_schema = schema_of(input_model) if input_model else {"type": "object"}
        output_schema = schema_of(output_model) if output_model else {"type": "object"}

        # Build three layers
        definition = {
            "capability_id": capability_id,
            "name": name,
            "description": description,
            "domain": domain,
            "version": version,
            "capability_type": capability_type,
            "tags": tags,
            "input_schema": input_schema,
            "output_schema": output_schema,
        }

        contract = generate_contract(cap_cls, capability_type)
        policy = generate_policy(cap_cls, capability_type)

        return {
            "definition": definition,
            "execution_contract": contract.to_dict(),
            "policy": policy.to_dict(),
        }

    def _resolve_io_types(
        self,
        cap_cls: type[Capability],
    ) -> tuple[type[BaseModel] | None, type[BaseModel] | None]:
        """Extract InputT and OutputT from Generic type parameters.

        Traverses the MRO to find the original Generic[InputT, OutputT] binding.

        Returns:
            (input_model, output_model) — both may be None if not resolvable.
        """
        input_model: type[BaseModel] | None = None
        output_model: type[BaseModel] | None = None

        # Check all base classes for Generic type parameters
        for base in cap_cls.__orig_bases__ if hasattr(cap_cls, "__orig_bases__") else []:
            origin = get_origin(base)
            if origin is not None and issubclass(origin, Capability):
                args = get_args(base)
                if len(args) >= 2:
                    input_model = args[0]
                    output_model = args[1]
                    # Only accept if they're actually BaseModel subclasses
                    if isinstance(input_model, type) and issubclass(input_model, BaseModel):
                        pass
                    else:
                        input_model = None
                    if isinstance(output_model, type) and issubclass(output_model, BaseModel):
                        pass
                    else:
                        output_model = None
                break

        return input_model, output_model


packager = Packager()
