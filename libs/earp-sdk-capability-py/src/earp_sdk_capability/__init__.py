"""EARP Capability SDK — develop, test, and register Capabilities.

Depends on:
    earp-sdk-core  → shared error types (ConnectorError, CapabilityError)
"""

from earp_sdk_capability.base import Capability, QueryCapability, CommandCapability
from earp_sdk_capability.context import CapabilityContext
from earp_sdk_capability.decorators import capability
from earp_sdk_capability.schema import schema_of

from earp_sdk_core import ConnectorError, CapabilityError

__all__ = [
    "Capability",
    "QueryCapability",
    "CommandCapability",
    "CapabilityContext",
    "capability",
    "schema_of",
    "ConnectorError",
    "CapabilityError",
]
