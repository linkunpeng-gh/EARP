"""Example: Equipment Alarm Query Capability.

This is a complete example demonstrating how to develop a Capability
using the EARP Capability SDK.

It covers:
    1. Pydantic input/output model definitions
    2. A QueryCapability with connector integration
    3. A CommandCapability with compensation
    4. Local testing with MockRuntime + MockConnector
"""

from __future__ import annotations

from pydantic import BaseModel

from earp_sdk_capability import (
    CommandCapability,
    QueryCapability,
    CapabilityContext,
    ConnectorError,
    capability,
)


# ── 1. Input / Output models ──


class EquipmentAlarmQuery(BaseModel):
    """Input: equipment_id + optional filter."""

    equipment_id: str
    include_acknowledged: bool = False


class AlarmItem(BaseModel):
    """A single alarm record."""

    alarm_id: str
    alarm_code: str
    message: str
    severity: str  # "critical" | "major" | "minor" | "info"
    timestamp: str


class EquipmentAlarmList(BaseModel):
    """Output: list of alarms + total count."""

    alarms: list[AlarmItem]
    total_count: int


class CreateWorkOrderInput(BaseModel):
    """Input for creating a work order."""

    equipment_id: str
    alarm_id: str
    description: str
    assigned_to: str = ""


class WorkOrderResult(BaseModel):
    """Output after creating a work order."""

    work_order_id: str
    status: str
    created_at: str


# ── 2. Query Capability (read-only) ──


@capability(
    capability_id="query_equipment_alarm",
    name="查询设备报警",
    description="根据设备ID查询当前报警信息",
    domain="equipment",
    version="1.0.0",
    tags=["equipment", "alarm", "monitoring"],
)
class QueryEquipmentAlarm(QueryCapability[EquipmentAlarmQuery, EquipmentAlarmList]):
    """Query equipment alarms from the MES system."""

    async def execute(
        self,
        ctx: CapabilityContext,
        params: EquipmentAlarmQuery,
    ) -> EquipmentAlarmList:
        ctx.logger.info(f"Querying alarms for equipment: {params.equipment_id}")

        # Call the MES system via a connector
        result = await ctx.connectors.mes.execute(
            "query_alarms",
            {
                "equipment_id": params.equipment_id,
                "include_acknowledged": params.include_acknowledged,
            },
        )

        return EquipmentAlarmList(**result)


# ── 3. Command Capability (state-changing, with compensation) ──


@capability(
    capability_id="create_work_order",
    name="创建维修工单",
    description="根据设备报警创建一个维修工单",
    domain="maintenance",
    version="1.0.0",
    tags=["maintenance", "work-order"],
)
class CreateWorkOrder(CommandCapability[CreateWorkOrderInput, WorkOrderResult]):
    """Create a work order in the maintenance system.

    If the work order creation fails after the alarm has been acknowledged,
    the compensate() method rolls back the alarm acknowledgment.
    """

    async def execute(
        self,
        ctx: CapabilityContext,
        params: CreateWorkOrderInput,
    ) -> WorkOrderResult:
        ctx.logger.info(f"Creating work order for alarm: {params.alarm_id}")

        # Step 1: Acknowledge the alarm
        await ctx.connectors.mes.execute(
            "acknowledge_alarm",
            {"alarm_id": params.alarm_id},
        )

        # Step 2: Create work order
        result = await ctx.connectors.mes.execute(
            "create_work_order",
            {
                "equipment_id": params.equipment_id,
                "alarm_id": params.alarm_id,
                "description": params.description,
                "assigned_to": params.assigned_to,
            },
        )

        return WorkOrderResult(**result)

    async def compensate(
        self,
        ctx: CapabilityContext,
        params: CreateWorkOrderInput,
        result: WorkOrderResult,
    ) -> None:
        """Rollback: un-acknowledge the alarm if work order creation failed."""
        ctx.logger.warn(f"Compensating: un-acknowledge alarm {params.alarm_id}")

        await ctx.connectors.mes.execute(
            "unacknowledge_alarm",
            {"alarm_id": params.alarm_id},
        )
