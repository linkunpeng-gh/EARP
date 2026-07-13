"""Tests for the schema module — Pydantic → JSONSchema conversion and validation."""

from __future__ import annotations

from typing import Optional

import pytest
from pydantic import BaseModel, Field

from earp_sdk_capability.schema import schema_of, validate_input, SchemaValidationError


# ── Test models ──


class SimpleModel(BaseModel):
    name: str
    age: int


class WithDefaults(BaseModel):
    name: str
    count: int = 10
    enabled: bool = True


class NestedInner(BaseModel):
    x: float
    y: float


class NestedModel(BaseModel):
    label: str
    point: NestedInner


class WithList(BaseModel):
    tags: list[str]
    scores: list[float]


class WithOptional(BaseModel):
    required_field: str
    optional_field: Optional[str] = None
    nullable_int: int | None = None


# ── Tests: schema_of ──


class TestSchemaOf:
    def test_simple_model(self):
        """Basic types: string, integer."""
        schema = schema_of(SimpleModel)
        assert schema["$schema"] == "https://json-schema.org/draft-07/schema#"
        assert schema["type"] == "object"
        assert schema["properties"]["name"]["type"] == "string"
        assert schema["properties"]["age"]["type"] == "integer"
        assert schema["required"] == ["name", "age"]

    def test_default_values(self):
        """Fields with defaults are not required in the schema."""
        schema = schema_of(WithDefaults)
        assert "name" in schema["required"]
        assert "count" not in schema.get("required", [])
        assert schema["properties"]["count"]["default"] == 10
        assert schema["properties"]["enabled"]["default"] is True

    def test_nested_model(self):
        """Nested models produce a JSON Schema with $defs."""
        schema = schema_of(NestedModel)
        # The nested type should be defined in $defs
        assert "$defs" in schema
        assert "NestedInner" in schema["$defs"]
        assert schema["properties"]["point"]["$ref"].endswith("NestedInner")

    def test_list_types(self):
        """List fields produce array type schemas."""
        schema = schema_of(WithList)
        assert schema["properties"]["tags"]["type"] == "array"
        assert schema["properties"]["tags"]["items"]["type"] == "string"
        assert schema["properties"]["scores"]["type"] == "array"
        assert schema["properties"]["scores"]["items"]["type"] == "number"

    def test_optional_fields(self):
        """Optional[T] and T | None are reflected in the schema."""
        schema = schema_of(WithOptional)
        required = schema.get("required", [])
        assert "required_field" in required
        assert "optional_field" not in required
        assert "nullable_int" not in required
        # nullable_int should accept null
        nullable = schema["properties"]["nullable_int"]
        assert nullable.get("anyOf") or nullable.get("oneOf")


# ── Tests: validate_input ──


class TestValidateInput:
    def test_valid_input(self):
        """Valid data passes through."""
        result = validate_input(SimpleModel, {"name": "Alice", "age": 30})
        assert result == {"name": "Alice", "age": 30}

    def test_defaults_applied(self):
        """Missing optional fields get default values."""
        result = validate_input(WithDefaults, {"name": "Bob"})
        assert result["name"] == "Bob"
        assert result["count"] == 10
        assert result["enabled"] is True

    def test_invalid_type_raises(self):
        """Type mismatch raises SchemaValidationError."""
        with pytest.raises(SchemaValidationError) as exc:
            validate_input(SimpleModel, {"name": "Alice", "age": "not-a-number"})
        assert len(exc.value.details) >= 1
        assert exc.value.details[0]["field"] == "age"

    def test_missing_required_raises(self):
        """Missing required field raises SchemaValidationError."""
        with pytest.raises(SchemaValidationError) as exc:
            validate_input(SimpleModel, {"name": "Alice"})
        assert len(exc.value.details) >= 1
        # Should mention 'age' is required
        messages = " ".join(d["message"] for d in exc.value.details)
        assert "age" in messages or "required" in messages

    def test_extra_fields_stripped(self):
        """Extra fields not in the model are removed."""
        result = validate_input(SimpleModel, {"name": "Eve", "age": 25, "extra": "ignored"})
        assert result == {"name": "Eve", "age": 25}
        assert "extra" not in result

    def test_nested_validation(self):
        """Nested input data is validated correctly."""
        data = {"label": "point-a", "point": {"x": 1.0, "y": 2.5}}
        result = validate_input(NestedModel, data)
        assert result["point"]["x"] == 1.0
        assert result["point"]["y"] == 2.5
