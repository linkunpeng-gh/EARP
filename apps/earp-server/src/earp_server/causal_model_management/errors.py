"""Stable N01A domain errors shared by services and HTTP transport."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class N01AError(Exception):
    code: str
    message: str
    status_code: int
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message


def conflict(code: str, message: str, **details: Any) -> N01AError:
    return N01AError(code, message, 409, details)


def forbidden(code: str = "PERMISSION_DENIED", message: str = "Permission denied.") -> N01AError:
    return N01AError(code, message, 403)


def not_found(code: str, message: str) -> N01AError:
    return N01AError(code, message, 404)


def validation_failed(validation_result: dict[str, Any]) -> N01AError:
    return N01AError(
        "MODEL_VALIDATION_FAILED",
        "The causal model contains blocking validation issues.",
        422,
        {"validation_result": validation_result},
    )
