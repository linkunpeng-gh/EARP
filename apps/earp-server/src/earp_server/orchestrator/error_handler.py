"""Step error handling — 3 modes (langchain §2.3): fail / swallow / custom callable."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ErrorMode(StrEnum):
    FAIL = "fail"       # raise and stop the Plan
    SWALLOW = "swallow"  # skip this step, continue with next
    CUSTOM = "custom"    # call custom handler


@dataclass
class ErrorHandler:
    mode: ErrorMode = ErrorMode.FAIL
    fallback_output: dict[str, Any] | None = None
    custom_handler: Callable[[Exception], dict[str, Any]] | None = None

    def handle(self, error: Exception, step_id: str, context: dict[str, Any]) -> dict[str, Any]:
        if self.mode == ErrorMode.SWALLOW:
            return self.fallback_output or {"status": "skipped", "error": str(error)}
        if self.mode == ErrorMode.CUSTOM and self.custom_handler:
            return self.custom_handler(error)
        raise error


DEFAULT_ERROR_HANDLER = ErrorHandler(mode=ErrorMode.FAIL)
SWALLOW_ERROR_HANDLER = ErrorHandler(mode=ErrorMode.SWALLOW, fallback_output={"status": "skipped"})
