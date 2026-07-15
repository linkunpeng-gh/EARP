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
        assert e.value.code == ConnectorErrorCode.INVALID_RESPONSE

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
