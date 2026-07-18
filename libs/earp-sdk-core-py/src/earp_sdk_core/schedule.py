"""Schedule & Trigger — Schedule/Trigger Spec v1.0.

Schedule: cron/interval-based task scheduling
Trigger: event-based workflow triggering
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


# ── Enums ──

class ScheduleType(str, Enum):
    CRON = "cron"
    INTERVAL = "interval"


class ScheduleStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    DISABLED = "disabled"


class TriggerStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    DISABLED = "disabled"


# ── Data Models ──

@dataclass
class Schedule:
    """Cron or interval-based schedule. Schedule Spec §2.2."""
    schedule_id: str = ""
    tenant_id: str = ""
    name: str = ""
    schedule_type: ScheduleType = ScheduleType.CRON
    expression: str = ""  # cron expression or interval like "30m"
    workflow_id: str = ""
    input_params: dict = field(default_factory=dict)
    status: ScheduleStatus = ScheduleStatus.ACTIVE
    timezone: str = "UTC"
    start_at: str | None = None
    end_at: str | None = None
    concurrency: str = "skip"  # skip | queue | parallel
    last_run_at: str | None = None
    next_run_at: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class Trigger:
    """Event-based trigger. Trigger Spec §3.1."""
    trigger_id: str = ""
    tenant_id: str = ""
    name: str = ""
    event_type: str = ""  # wildcards supported: "alarm.*"
    event_filter: dict = field(default_factory=dict)  # {"alarm_level": "critical"}
    workflow_id: str = ""
    status: TriggerStatus = TriggerStatus.ACTIVE
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ScheduleHistory:
    """Execution record for a schedule/trigger run. Schedule Spec §4.1."""
    history_id: str = ""
    schedule_id: str = ""
    trigger_id: str = ""
    execution_id: str = ""
    triggered_at: str = ""
    status: str = "success"  # success | failed | skipped
    error_message: str | None = None


# ── Schedule Store ──

class ScheduleStore:
    """In-memory schedule and trigger store."""

    def __init__(self) -> None:
        self._schedules: dict[str, Schedule] = {}
        self._triggers: dict[str, Trigger] = {}
        self._history: list[ScheduleHistory] = []

    def add_schedule(self, s: Schedule) -> None:
        self._schedules[s.schedule_id] = s

    def get_schedule(self, sid: str) -> Schedule | None:
        return self._schedules.get(sid)

    def list_active_schedules(self, tenant_id: str) -> list[Schedule]:
        return [s for s in self._schedules.values()
                if s.tenant_id == tenant_id and s.status == ScheduleStatus.ACTIVE]

    def add_trigger(self, t: Trigger) -> None:
        self._triggers[t.trigger_id] = t

    def get_trigger(self, tid: str) -> Trigger | None:
        return self._triggers.get(tid)

    def list_active_triggers(self, tenant_id: str) -> list[Trigger]:
        return [t for t in self._triggers.values()
                if t.tenant_id == tenant_id and t.status == TriggerStatus.ACTIVE]

    def record_history(self, h: ScheduleHistory) -> None:
        self._history.append(h)


# ── Trigger Matcher ──

class TriggerMatcher:
    """Match incoming events against registered triggers. Trigger Spec §3.2."""

    _OP_MAP = {
        "eq": lambda a, b: a == b,
        "in": lambda a, b: a in b,
        "gt": lambda a, b: a > b,
        "lt": lambda a, b: a < b,
        "regex": lambda a, b: bool(re.search(b, str(a))),
    }

    def match(self, event: dict, triggers: list[Trigger]) -> list[Trigger]:
        """Return triggers that match the given event."""
        matched: list[Trigger] = []
        event_type = event.get("event_type", "")
        for t in triggers:
            if not self._match_type(event_type, t.event_type):
                continue
            if not self._match_filter(event, t.event_filter):
                continue
            matched.append(t)
        return matched

    @staticmethod
    def _match_type(event_type: str, pattern: str) -> bool:
        """Wildcard matching: 'alarm.*' matches 'alarm.created'."""
        regex = pattern.replace(".", r"\.").replace("*", ".*")
        return bool(re.fullmatch(regex, event_type))

    def _match_filter(self, event: dict, filters: dict) -> bool:
        """Check all filter conditions against event data."""
        for key, condition in filters.items():
            if not isinstance(condition, dict):
                # Simple equality
                if event.get(key) != condition:
                    return False
                continue
            # Operator-based: {"alarm_level": {"eq": "critical"}}
            for op_str, expected in condition.items():
                op = self._OP_MAP.get(op_str)
                if not op:
                    continue
                actual = event.get(key)
                if not op(actual, expected):
                    return False
        return True
