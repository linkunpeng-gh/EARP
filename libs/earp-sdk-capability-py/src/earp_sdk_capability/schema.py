"""Pydantic model → JSONSchema Draft-07 conversion and validation.

Examples:

    class QueryInput(BaseModel):
        equipment_id: str
        limit: int = 10

    schema = schema_of(QueryInput)
    # Returns:
    # {
    #     "$schema": "https://json-schema.org/draft-07/schema#",
    #     "type": "object",
    #     "properties": {
    #         "equipment_id": {"type": "string", "title": "Equipment Id"},
    #         "limit": {"type": "integer", "title": "Limit", "default": 10}
    #     },
    #     "required": ["equipment_id"]
    # }
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError


def schema_of(model: type[BaseModel]) -> dict[str, Any]:
    """Generate a JSON Schema (Draft-07) from a Pydantic model.

    Args:
        model: A Pydantic BaseModel subclass.

    Returns:
        JSON Schema dict with $schema field set to Draft-07.
    """
    schema = model.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft-07/schema#"
    return schema


def validate_input(model: type[BaseModel], data: dict[str, Any]) -> dict[str, Any]:
    """Validate raw input data against a Pydantic model.

    Args:
        model: The Pydantic model to validate against.
        data: Raw input dict.

    Returns:
        The validated and parsed dict.

    Raises:
        SchemaValidationError: If validation fails, with structured details.
    """
    try:
        instance = model.model_validate(data)
        return instance.model_dump()
    except ValidationError as e:
        details = [
            {
                "field": ".".join(str(p) for p in err["loc"]),
                "message": err["msg"],
                "type": err["type"],
            }
            for err in e.errors()
        ]
        raise SchemaValidationError(
            f"Schema validation failed ({len(details)} error(s))",
            details=details,
        ) from e


class SchemaValidationError(ValueError):
    """Raised when input/output data fails schema validation.

    Attributes:
        message: Human-readable summary.
        details: List of per-field validation errors.
    """

    def __init__(
        self,
        message: str = "",
        *,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        self.details = details or []
        super().__init__(message)
