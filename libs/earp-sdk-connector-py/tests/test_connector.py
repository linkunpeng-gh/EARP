import json, httpx, pytest
from earp_sdk_core import ConnectorConfig, AuthConfig, ConnectorError, ConnectorErrorCode
from earp_sdk_connector import BaseConnector, RESTConnector, ConnectorResult, ConnectorCapability, ConnectorStatus
from earp_sdk_connector.testing.harness import ConnectorTestHarness

def _make_transport(handler):
    return httpx.MockTransport(lambda r: handler(r))

class FakeConnector(RESTConnector):
    connector_id = "test"; name = "Test"; protocol = "http"; version = "1.0.0"
    endpoints = {
        "ping": {"method":"GET","path":"/api/v1/ping","query_params":["msg"],"required_params":["msg"]},
        "create": {"method":"POST","path":"/api/v1/items","body_type":"json","required_params":["name"]},
    }

class TestBaseConnector:
    def test_default_fields(self):
        assert FakeConnector.connector_id == "test"
        assert FakeConnector.protocol == "http"
    def test_default_status(self):
        assert FakeConnector().status == ConnectorStatus.REGISTERED
    def test_get_capabilities_empty(self):
        assert FakeConnector().get_capabilities() == []

class TestRESTConnector:
    @pytest.fixture
    def conn(self): return FakeConnector()

    async def test_test_connection_success(self, conn):
        async def h(req): return httpx.Response(200)
        conn._transport = httpx.AsyncClient(transport=_make_transport(h))
        conn.config = ConnectorConfig(base_url="http://mock")
        r = await conn.test_connection()
        assert r["status"] == "ok"; await conn._transport.aclose()

    async def test_execute_get(self, conn):
        async def h(req):
            assert "msg=hello" in str(req.url); return httpx.Response(200, json={"echo":"hello"})
        conn._transport = httpx.AsyncClient(transport=_make_transport(h))
        conn.config = ConnectorConfig(base_url="http://mock")
        r = await conn.execute("ping", {"msg":"hello"})
        assert r.data == {"echo":"hello"}; await conn._transport.aclose()

    async def test_execute_missing_required(self, conn):
        conn.config = ConnectorConfig(base_url="http://mock")
        r = await conn.execute("ping", {"wrong":"val"})
        assert r.status == "error" and "msg" in r.error

    async def test_execute_unknown_operation(self, conn):
        conn.config = ConnectorConfig(base_url="http://mock")
        with pytest.raises(ConnectorError) as e:
            await conn.execute("unknown", {})
        assert e.value.code == ConnectorErrorCode.OPERATION_NOT_FOUND

    async def test_execute_http_error(self, conn):
        async def h(req): return httpx.Response(500)
        conn._transport = httpx.AsyncClient(transport=_make_transport(h))
        conn.config = ConnectorConfig(base_url="http://mock")
        with pytest.raises(ConnectorError) as e:
            await conn.execute("ping", {"msg":"x"})
        assert e.value.code == ConnectorErrorCode.SYSTEM_ERROR; await conn._transport.aclose()

    async def test_bearer_auth(self, conn):
        hdrs = {}
        async def h(req):
            hdrs.update(dict(req.headers)); return httpx.Response(200)
        conn._transport = httpx.AsyncClient(transport=_make_transport(h))
        conn.config = ConnectorConfig(base_url="http://mock", auth=AuthConfig(type="bearer", token="t"))
        await conn.execute("ping", {"msg":"hi"})
        assert hdrs.get("authorization") == "Bearer t"; await conn._transport.aclose()

    async def test_execute_post(self, conn):
        body = {}
        async def h(req):
            nonlocal body; body = json.loads(req.content); return httpx.Response(201, json={"id":"n"})
        conn._transport = httpx.AsyncClient(transport=_make_transport(h))
        conn.config = ConnectorConfig(base_url="http://mock")
        r = await conn.execute("create", {"name":"x"})
        assert r.status == "ok" and body["name"] == "x"; await conn._transport.aclose()

    async def test_health_check(self, conn):
        async def h(req): return httpx.Response(200)
        conn._transport = httpx.AsyncClient(transport=_make_transport(h))
        conn.config = ConnectorConfig(base_url="http://mock")
        s = await conn.health_check()
        assert s in ("healthy","degraded","unreachable"); await conn._transport.aclose()

class TestStateMachine:
    async def test_connect_success(self):
        class C(BaseConnector):
            connector_id="x";protocol="http";name="x"
            async def test_connection(self): return {"status":"ok","latency_ms":1,"error":None}
            async def execute(self,o,p): return ConnectorResult()
            async def health_check(self): return "healthy"
        c = C(); s = await c.connect(); assert s == ConnectorStatus.ACTIVE
    async def test_connect_failure(self):
        class C(BaseConnector):
            connector_id="x";protocol="http";name="x"
            async def test_connection(self): raise ConnectionError("x")
            async def execute(self,o,p): return ConnectorResult()
            async def health_check(self): return "unreachable"
        c = C()
        with pytest.raises(ConnectionError): await c.connect()
        assert c.status == ConnectorStatus.ERROR
    async def test_disconnect(self):
        class C(BaseConnector):
            connector_id="x";protocol="http";name="x"
            async def test_connection(self): return {"status":"ok","latency_ms":1,"error":None}
            async def execute(self,o,p): return ConnectorResult()
            async def health_check(self): return "healthy"
        c = C(); c.status = ConnectorStatus.ACTIVE; await c.disconnect()
        assert c.status == ConnectorStatus.DISCONNECTED

class TestModels:
    def test_connector_result(self):
        r = ConnectorResult(status="ok", data={"x":1}); assert r.data == {"x":1}
    def test_connector_capability(self):
        c = ConnectorCapability(capability_id="a", name="A"); assert c.capability_id == "a"

class TestConnectorTestHarness:
    def test_register_response(self):
        h = ConnectorTestHarness(); h.register_response("p", {"e":"ok"})
        assert h.get_response("p") == {"e":"ok"}
    def test_register_error(self):
        h = ConnectorTestHarness(); h.register_error("b", ValueError("boom"))
        with pytest.raises(ValueError, match="boom"): h.get_response("b")
    def test_missing_operation(self):
        with pytest.raises(KeyError, match="not registered"):
            ConnectorTestHarness().get_response("unknown")


# ── Security tests per PRD-2026-005 ──

import logging


class TestSecurityTokenNotLogged:
    """AC-02: RESTConnector._ensure_auth_headers() must not log token in plaintext."""

    async def test_ensure_auth_headers_no_token_in_logs(self, caplog):
        """Token value must not appear in any log message during auth header setup."""
        import logging as _log
        caplog.set_level(_log.DEBUG, logger="earp_sdk_connector.base")

        class NoisyConnector(RESTConnector):
            connector_id = "sec-test"
            name = "SecurityTest"
            protocol = "http"
            endpoints = {"ping": {"method": "GET", "path": "/ping", "required_params": []}}

        conn = NoisyConnector()
        conn.config = ConnectorConfig(
            base_url="http://mock",
            auth=AuthConfig(type="bearer", token="secret-token-do-not-leak"),
        )

        # Trigger auth header construction
        conn._ensure_auth_headers()

        # Verify the token value is not in any log message
        for record in caplog.records:
            msg = record.getMessage()
            assert "secret-token-do-not-leak" not in msg, (
                f"Token leaked in log: {msg}"
            )

    async def test_no_logger_calls_during_auth_header_setup(self, caplog):
        """Verify that _ensure_auth_headers does not emit any log calls at all."""
        import logging as _log
        caplog.set_level(_log.DEBUG, logger="earp_sdk_connector.base")

        class QuietConnector(RESTConnector):
            connector_id = "q"
            name = "Q"
            protocol = "http"
            endpoints = {}

        conn = QuietConnector()
        conn.config = ConnectorConfig(
            base_url="http://mock",
            auth=AuthConfig(type="bearer", token="t"),
        )
        conn._ensure_auth_headers()

        auth_header_logs = [
            r for r in caplog.records
            if "t" in r.getMessage() or "token" in r.getMessage().lower()
        ]
        assert len(auth_header_logs) == 0, (
            f"_ensure_auth_headers emitted log(s) with token: {auth_header_logs}"
        )


class TestSecurityAuthExpiredAudit:
    """AC-05: AUTH_EXPIRED must emit structured audit event via logger.critical."""

    async def test_auth_expired_emits_critical_audit_log(self, caplog):
        """When AUTH_EXPIRED error occurs, a critical log with structured extra is emitted."""
        import logging as _log
        caplog.set_level(_log.CRITICAL, logger="earp_sdk_connector.base")

        class AuditConnector(RESTConnector):
            connector_id = "audit-conn-1"
            name = "AuditTest"
            protocol = "http"
            endpoints = {"p": {"method": "GET", "path": "/p", "required_params": []}}

        conn = AuditConnector()
        conn.config = ConnectorConfig(base_url="http://mock")

        # Simulate an AUTH_EXPIRED error via _on_error
        from earp_sdk_core import ConnectorError, ConnectorErrorCode
        ce = ConnectorError(ConnectorErrorCode.AUTH_EXPIRED, "Token expired")
        await conn._on_error(ce)

        # Verify the critical audit log was emitted
        critical_records = [r for r in caplog.records if r.levelno == _log.CRITICAL]
        assert len(critical_records) >= 1, "Expected at least one CRITICAL log for AUTH_EXPIRED"

        audit_record = critical_records[0]
        assert audit_record.getMessage() == "Security audit: AUTH_EXPIRED"
        # Extra fields are now directly set on the LogRecord via makeRecord
        assert getattr(audit_record, "audit_type", None) == "AUTH_EXPIRED", \
            f"Expected audit_type='AUTH_EXPIRED', got {getattr(audit_record, 'audit_type', None)}"
        assert getattr(audit_record, "connector_id", None) == "audit-conn-1", \
            f"Expected connector_id='audit-conn-1', got {getattr(audit_record, 'connector_id', None)}"
        ts = getattr(audit_record, "timestamp", None)
        assert ts is not None and len(ts) > 0, f"Expected non-empty timestamp, got {ts}"

    async def test_non_auth_errors_no_audit_log(self, caplog):
        """Non-AUTH_EXPIRED errors should NOT emit audit critical logs."""
        import logging as _log
        caplog.set_level(_log.CRITICAL, logger="earp_sdk_connector.base")

        class NoAuditConnector(RESTConnector):
            connector_id = "na-1"
            name = "NoAudit"
            protocol = "http"
            endpoints = {}

        conn = NoAuditConnector()
        conn.config = ConnectorConfig(base_url="http://mock")

        from earp_sdk_core import ConnectorError, ConnectorErrorCode
        ce = ConnectorError(ConnectorErrorCode.TIMEOUT, "Timed out")
        await conn._on_error(ce)

        audit_records = [
            r for r in caplog.records
            if r.levelno == _log.CRITICAL and "AUTH_EXPIRED" in r.getMessage()
        ]
        assert len(audit_records) == 0, (
            "TIMEOUT should not emit AUTH_EXPIRED audit log"
        )


class TestSecurityAuditPhase2:
    """AC-05: AUTH_EXPIRED publishes AuditEvent via publish_audit_event (Phase 2)."""

    async def test_auth_expired_publishes_audit_event(self, caplog):
        """AUTH_EXPIRED triggers publish_audit_event → JSON in 'earp.audit' logger."""
        import logging as _log, json
        caplog.set_level(_log.INFO, logger="earp.audit")

        class Phase2Connector(RESTConnector):
            connector_id = "phase2-conn"
            name = "Phase2Test"
            protocol = "http"
            endpoints = {}

        conn = Phase2Connector()
        conn.config = ConnectorConfig(base_url="http://mock")

        from earp_sdk_core import ConnectorError, ConnectorErrorCode
        ce = ConnectorError(ConnectorErrorCode.AUTH_EXPIRED, "Token expired")
        await conn._on_error(ce)

        audit_logs = [r for r in caplog.records if r.name == "earp.audit"]
        assert len(audit_logs) == 1, (
            f"Expected 1 audit event, got {len(audit_logs)}"
        )

        data = json.loads(audit_logs[0].message)
        assert data["source"] == "security"
        assert data["event_type"] == "AUTH_EXPIRED"
        assert data["action"] == "connector_auth"
        assert data["result"] == "failure"
        assert data["subject"] == "connector:phase2-conn"
        assert data["detail"]["connector_id"] == "phase2-conn"

    async def test_auth_expired_fallback_critical_log_still_present(self, caplog):
        """Phase 1 fallback logger.critical still fires alongside publish_audit_event."""
        import logging as _log
        caplog.set_level(_log.CRITICAL, logger="earp_sdk_connector.base")

        class FallbackConnector(RESTConnector):
            connector_id = "fb-conn"
            name = "FallbackTest"
            protocol = "http"
            endpoints = {}

        conn = FallbackConnector()
        conn.config = ConnectorConfig(base_url="http://mock")

        from earp_sdk_core import ConnectorError, ConnectorErrorCode
        ce = ConnectorError(ConnectorErrorCode.AUTH_EXPIRED, "Expired")
        await conn._on_error(ce)

        critical_records = [r for r in caplog.records if r.levelno == _log.CRITICAL]
        assert len(critical_records) >= 1, "Fallback critical log should still be emitted"
        assert "Security audit: AUTH_EXPIRED" in critical_records[0].getMessage()
