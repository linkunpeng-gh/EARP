"""EARP Runtime SDK — invoke Capabilities, manage Sessions, subscribe to events.

Depends on:
    earp-sdk-core → shared error types (CapabilityError, CapabilityNotFoundError, ...)
"""

__version__ = "0.1.0.dev0"
USER_AGENT = f"earp-sdk-runtime/{__version__}"

from earp_sdk_runtime.client import RuntimeClient
from earp_sdk_runtime.session import Session
from earp_sdk_runtime.invoker import CapabilityInvoker
from earp_sdk_runtime.events import EventSubscriber
from earp_sdk_runtime.models import (
    CapabilityInfo,
    ResolvedCapability,
    SearchResponse,
    RuntimeEvent,
    SessionStatus,
    RetryConfig,
)
from earp_sdk_runtime.testing.mock_runtime import MockRuntimeClient

__all__ = [
    "RuntimeClient",
    "Session",
    "CapabilityInvoker",
    "EventSubscriber",
    "CapabilityInfo",
    "ResolvedCapability",
    "SearchResponse",
    "RuntimeEvent",
    "SessionStatus",
    "RetryConfig",
    "MockRuntimeClient",
]
