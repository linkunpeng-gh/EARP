"""Tests for AuditEvent + publish_audit_event — AC-04."""

import json
import logging
import uuid
import pytest

from earp_sdk_core import AuditEvent, publish_audit_event


class TestAuditEvent:
    """AC-04: AuditEvent has all 11 Audit Spec §2.1 fields."""

    def test_required_fields(self):
        event = AuditEvent(
            source="security",
            event_type="AUTH_EXPIRED",
            tenant_id="t-1",
            user_id="u-1",
            action="connector_auth",
            result="failure",
        )
        assert event.source == "security"
        assert event.event_type == "AUTH_EXPIRED"
        assert event.tenant_id == "t-1"
        assert event.user_id == "u-1"
        assert event.action == "connector_auth"
        assert event.result == "failure"

    def test_optional_fields_default(self):
        event = AuditEvent(
            source="runtime", event_type="EXECUTION_CREATED",
            tenant_id="t", user_id="u", action="create_session", result="success",
        )
        assert event.execution_id is None
        assert event.subject is None
        assert event.detail is None

    def test_optional_fields_set(self):
        event = AuditEvent(
            source="security", event_type="AUTH_EXPIRED",
            tenant_id="t", user_id="", action="connector_auth", result="failure",
            execution_id="exec-123",
            subject="connector:my-conn",
            detail={"connector_id": "c1", "reason": "expired"},
        )
        assert event.execution_id == "exec-123"
        assert event.subject == "connector:my-conn"
        assert event.detail == {"connector_id": "c1", "reason": "expired"}

    def test_auto_gen_fields_are_empty_before_publish(self):
        event = AuditEvent(
            source="s", event_type="e", tenant_id="t", user_id="u",
            action="a", result="success",
        )
        assert event.log_id == ""
        assert event.timestamp == ""

    def test_system_event_empty_user(self):
        """System events may have empty user_id."""
        event = AuditEvent(
            source="security", event_type="AUTH_EXPIRED",
            tenant_id="t-1", user_id="", action="connector_auth", result="failure",
        )
        assert event.user_id == ""


class TestPublishAuditEvent:
    """AC-04: publish_audit_event writes JSON to logger 'earp.audit'."""

    def test_publish_writes_json_to_audit_logger(self, caplog):
        caplog.set_level(logging.INFO, logger="earp.audit")

        event = AuditEvent(
            source="security",
            event_type="AUTH_EXPIRED",
            tenant_id="tenant-1",
            user_id="",
            action="connector_auth",
            result="failure",
            subject="connector:c1",
            detail={"connector_id": "c1", "reason": "expired"},
        )
        publish_audit_event(event)

        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.name == "earp.audit"
        assert record.levelno == logging.INFO

        data = json.loads(record.message)
        assert data["source"] == "security"
        assert data["event_type"] == "AUTH_EXPIRED"
        assert data["tenant_id"] == "tenant-1"
        assert data["user_id"] == ""
        assert data["action"] == "connector_auth"
        assert data["result"] == "failure"
        assert data["subject"] == "connector:c1"
        assert data["detail"] == {"connector_id": "c1", "reason": "expired"}

        # Auto-generated fields
        uid = uuid.UUID(data["log_id"])
        assert uid.version == 4  # UUID4
        # timestamp should be ISO 8601 with T separator
        assert "T" in data["timestamp"] or "t" in data["timestamp"].lower()

    def test_publish_null_optional_fields_json_null(self, caplog):
        caplog.set_level(logging.INFO, logger="earp.audit")

        event = AuditEvent(
            source="s", event_type="e", tenant_id="t", user_id="u",
            action="a", result="success",
        )
        publish_audit_event(event)

        data = json.loads(caplog.records[0].message)
        assert data["execution_id"] is None
        assert data["subject"] is None
        assert data["detail"] is None

    def test_two_publishes_different_log_ids(self, caplog):
        caplog.set_level(logging.INFO, logger="earp.audit")

        event1 = AuditEvent(source="s", event_type="e1", tenant_id="t",
                            user_id="u", action="a", result="success")
        event2 = AuditEvent(source="s", event_type="e2", tenant_id="t",
                            user_id="u", action="a", result="success")
        publish_audit_event(event1)
        publish_audit_event(event2)

        data1 = json.loads(caplog.records[0].message)
        data2 = json.loads(caplog.records[1].message)
        assert data1["log_id"] != data2["log_id"]

    def test_all_11_fields_present(self, caplog):
        """Verify all 11 Audit Spec §2.1 fields appear in JSON."""
        caplog.set_level(logging.INFO, logger="earp.audit")

        event = AuditEvent(
            source="security", event_type="AUTH_EXPIRED",
            tenant_id="t", user_id="u", action="a", result="failure",
            execution_id="exec-1", subject="s", detail={"k": "v"},
        )
        publish_audit_event(event)

        data = json.loads(caplog.records[0].message)
        expected_fields = {"log_id", "timestamp", "source", "event_type",
                           "tenant_id", "user_id", "execution_id", "subject",
                           "action", "result", "detail"}
        assert set(data.keys()) == expected_fields
