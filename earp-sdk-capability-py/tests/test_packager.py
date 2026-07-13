"""Tests for Contracts and Packager — the three-layer structure generator."""

from __future__ import annotations

from typing import Optional

import pytest
from pydantic import BaseModel

from earp_sdk_capability import (
    Capability,
    QueryCapability,
    CommandCapability,
    capability,
)
from earp_sdk_capability.registration.packager import packager


# ── Test models ──


class AlarmQuery(BaseModel):
    equipment_id: str
    include_acknowledged: bool = False


class AlarmItem(BaseModel):
    alarm_id: str
    severity: str = "info"


class AlarmResult(BaseModel):
    alarms: list[AlarmItem]
    total: int


# ── Test capabilities ──


@capability(
    capability_id="query_equipment_alarm",
    name="查询设备报警",
    description="根据设备ID查询当前报警信息",
    domain="equipment",
    version="1.0.0",
    tags=["equipment", "alarm"],
)
class QueryEquipmentAlarm(QueryCapability[AlarmQuery, AlarmResult]):
    async def execute(self, ctx, params: AlarmQuery) -> AlarmResult:
        return AlarmResult(alarms=[], total=0)


@capability(
    capability_id="create_work_order",
    name="创建工单",
    description="创建一个新的维修工单",
    domain="maintenance",
    version="1.0.0",
)
class CreateWorkOrder(CommandCapability[AlarmQuery, AlarmResult]):
    async def execute(self, ctx, params: AlarmQuery) -> AlarmResult:
        return AlarmResult(alarms=[], total=0)

    async def compensate(self, ctx, params: AlarmQuery, result: AlarmResult) -> None:
        pass


class BareCap(QueryCapability[AlarmQuery, AlarmResult]):
    capability_id = "bare_cap"
    name = "Bare"
    description = "A capability without @capability decorator"
    domain = "test"
    async def execute(self, ctx, params): pass


# ── Tests: contract generation ──


class TestContracts:
    def test_query_contract(self):
        """Query capability contract: idempotent, no compensation."""
        package = packager.pack(QueryEquipmentAlarm)
        ec = package["execution_contract"]
        assert ec["protocol"] == "sdk"
        assert ec["idempotent"] is True
        assert ec["supports_compensation"] is False
        assert ec["transaction_scope"] == "none"

    def test_command_contract(self):
        """Command capability contract: not idempotent, has compensation."""
        package = packager.pack(CreateWorkOrder)
        ec = package["execution_contract"]
        assert ec["idempotent"] is False
        assert ec["supports_compensation"] is True
        assert ec["compensating_capability"] is None

    def test_query_policy(self):
        """Query policy: summary audit."""
        package = packager.pack(QueryEquipmentAlarm)
        po = package["policy"]
        assert po["auth_required"] is True
        assert po["audit_level"] == "summary"
        assert po["approval_required"] is False

    def test_command_policy(self):
        """Command policy: detail audit + approval required."""
        package = packager.pack(CreateWorkOrder)
        po = package["policy"]
        assert po["audit_level"] == "detail"
        assert po["approval_required"] is True


# ── Tests: packager definition layer ──


class TestPackagerDefinition:
    def test_definition_fields(self):
        """All definition fields are populated correctly."""
        package = packager.pack(QueryEquipmentAlarm)
        d = package["definition"]
        assert d["capability_id"] == "query_equipment_alarm"
        assert d["name"] == "查询设备报警"
        assert d["description"] == "根据设备ID查询当前报警信息"
        assert d["domain"] == "equipment"
        assert d["version"] == "1.0.0"
        assert d["capability_type"] == "query"
        assert "alarm" in d["tags"]

    def test_schema_auto_generated(self):
        """input_schema and output_schema are auto-generated from type params."""
        package = packager.pack(QueryEquipmentAlarm)
        d = package["definition"]
        inp = d["input_schema"]
        out = d["output_schema"]
        assert inp["$schema"] == "https://json-schema.org/draft-07/schema#"
        assert "equipment_id" in inp["properties"]
        assert inp["properties"]["equipment_id"]["type"] == "string"
        assert inp["properties"]["include_acknowledged"]["type"] == "boolean"

        assert "alarms" in out["properties"]
        assert out["properties"]["alarms"]["type"] == "array"

    def test_without_decorator(self):
        """Capability without @capability decorator still works."""
        package = packager.pack(BareCap)
        assert package["definition"]["capability_id"] == "bare_cap"
        assert package["definition"]["domain"] == "test"

    def test_missing_description_raises(self):
        """Capability without description raises ValueError."""
        class NoDesc(QueryCapability):
            capability_id = "no_desc"
            domain = "test"
            async def execute(self, ctx, params): pass

        with pytest.raises(ValueError, match="description"):
            packager.pack(NoDesc)

    def test_missing_domain_raises(self):
        """Capability without domain raises ValueError."""
        class NoDomain(QueryCapability):
            capability_id = "no_domain"
            description = "test"
            async def execute(self, ctx, params): pass

        with pytest.raises(ValueError, match="domain"):
            packager.pack(NoDomain)


# ── Tests: output structure ──


class TestOutputStructure:
    def test_three_layer_structure(self):
        """Output has exactly three top-level keys."""
        package = packager.pack(QueryEquipmentAlarm)
        assert set(package.keys()) == {"definition", "execution_contract", "policy"}

    def test_aligns_with_l2_03_example(self):
        """Output format matches L2-03 §3.4 example structure."""
        package = packager.pack(QueryEquipmentAlarm)
        # Definition layer
        d = package["definition"]
        assert "capability_id" in d
        assert "input_schema" in d
        assert "output_schema" in d
        assert "capability_type" in d

        # Execution Contract
        e = package["execution_contract"]
        assert "protocol" in e
        assert "timeout" in e
        assert "retry_policy" in e
        assert "idempotent" in e
        assert "transaction_scope" in e
        assert "supports_compensation" in e
        assert "compensating_capability" in e

        # Policy
        p = package["policy"]
        assert "auth_required" in p
        assert "required_permissions" in p
        assert "approval_required" in p
        assert "audit_level" in p
        assert "constraints" in p
