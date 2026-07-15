"""Execution Contract and Policy Layer auto-generation helpers.

SDK automatically generates these from the Capability class metadata,
reducing the amount of boilerplate developers need to write.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

from earp_sdk_capability.base import CommandCapability


# ── Execution Contract ──


@dataclass
class RetryPolicy:
    max_attempts: int = 0
    backoff: str = "exponential"


@dataclass
class ExecutionContract:
    """Execution Contract — L2-03 §3.2 fields.

    SDK auto-generates sensible defaults; developer can override via @capability kwargs.
    """

    protocol: str = "sdk"
    timeout: int = 30000
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    idempotent: bool = True
    transaction_scope: str = "none"
    supports_compensation: bool = False
    compensating_capability: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def generate_contract(cap_cls: type, capability_type: str) -> ExecutionContract:
    """Generate an Execution Contract from a Capability class.

    Args:
        cap_cls: The Capability subclass.
        capability_type: "query" or "command".

    Returns:
        An ExecutionContract with sensible defaults.
    """
    is_command = capability_type == "command"

    # Detect if compensate() is overridden
    has_compensation = (
        is_command
        and hasattr(cap_cls, "compensate")
        and cap_cls.compensate is not CommandCapability.compensate
    )

    return ExecutionContract(
        protocol="sdk",
        timeout=getattr(cap_cls, "timeout", 30000),
        retry_policy=RetryPolicy(max_attempts=0),
        idempotent=not is_command,  # Query = idempotent, Command = not by default
        transaction_scope="none",
        supports_compensation=has_compensation,
        compensating_capability=None,
    )


# ── Policy Layer ──


@dataclass
class Constraint:
    type: str = ""
    value: str | int | float = 0


@dataclass
class PolicyLayer:
    """Policy Layer — L2-03 §3.3 fields.

    SDK auto-generates sensible defaults; developer can override via @capability kwargs.
    """

    auth_required: bool = True
    required_permissions: list[str] = field(default_factory=list)
    approval_required: bool = False
    audit_level: str = "summary"
    constraints: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "auth_required": self.auth_required,
            "required_permissions": self.required_permissions,
            "approval_required": self.approval_required,
            "audit_level": self.audit_level,
            "constraints": self.constraints,
        }


def generate_policy(cap_cls: type, capability_type: str) -> PolicyLayer:
    """Generate a Policy Layer from a Capability class.

    Args:
        cap_cls: The Capability subclass.
        capability_type: "query" or "command".

    Returns:
        A PolicyLayer with sensible defaults.
    """
    is_command = capability_type == "command"

    return PolicyLayer(
        auth_required=getattr(cap_cls, "auth_required", True),
        required_permissions=getattr(cap_cls, "required_permissions", []),
        approval_required=getattr(cap_cls, "approval_required", is_command),
        audit_level="detail" if is_command else "summary",
        constraints=getattr(cap_cls, "constraints", []),
    )
