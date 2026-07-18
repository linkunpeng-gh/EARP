"""Tests for SandboxManager, PermissionEnforcer, PluginManager audit — PRD-2026-008."""

import json
import logging
import pytest

from earp_sdk_core import PermissionDeniedError
from earp_sdk_plugin import Plugin, PluginManager, PluginStatus
from earp_sdk_plugin.permissions import Permission, PermissionEnforcer
from earp_sdk_plugin.sandbox import (
    SandboxConfig,
    SandboxExecutionError,
    SandboxManager,
    SandboxTimeoutError,
)
from earp_sdk_plugin.testing._sandbox_plugins import (
    BuggyPlugin,
    CalcPlugin,
    ListPlugin,
    NonePlugin,
    SlowPlugin,
    StrPlugin,
)


# ── PermissionEnforcer ──

class TestPermissionEnforcer:
    """AC-01/02: permission declaration enforcement."""

    def test_ensure_declared_passes(self):
        plugin = Plugin()
        plugin.permissions = ["network"]
        enforcer = PermissionEnforcer(plugin)
        enforcer.ensure("network")  # should not raise

    def test_ensure_undeclared_raises(self):
        plugin = Plugin()
        plugin.name = "test-plugin"
        plugin.permissions = ["network"]
        enforcer = PermissionEnforcer(plugin)
        with pytest.raises(PermissionDeniedError, match="test-plugin"):
            enforcer.ensure("filesystem")

    def test_ensure_all_partial_fails(self):
        plugin = Plugin()
        plugin.permissions = ["network"]
        enforcer = PermissionEnforcer(plugin)
        with pytest.raises(PermissionDeniedError):
            enforcer.ensure_all(["network", "filesystem"])

    def test_ensure_all_declared_passes(self):
        plugin = Plugin()
        plugin.permissions = ["network", "filesystem"]
        enforcer = PermissionEnforcer(plugin)
        enforcer.ensure_all(["network", "filesystem"])  # no raise

    def test_empty_permissions_all_denied(self):
        plugin = Plugin()
        plugin.permissions = []
        enforcer = PermissionEnforcer(plugin)
        with pytest.raises(PermissionDeniedError):
            enforcer.ensure("network")


# ── SandboxManager ──

class TestSandboxManager:
    """AC-03/04/05: sandbox config + subprocess isolation."""

    def test_sandbox_config_defaults(self):
        config = SandboxConfig()
        assert config.timeout_seconds == 30.0
        assert config.max_memory_mb == 0

    def test_sandbox_config_custom(self):
        config = SandboxConfig(timeout_seconds=5, max_memory_mb=128)
        assert config.timeout_seconds == 5
        assert config.max_memory_mb == 128

    def test_run_returns_result(self):
        """Execute a simple method in subprocess and get result back."""
        mgr = SandboxManager(SandboxConfig(timeout_seconds=5))
        result = mgr.run(CalcPlugin(), "add", a=3, b=4)
        assert result == {"sum": 7}

    def test_run_timeout(self):
        mgr = SandboxManager(SandboxConfig(timeout_seconds=0.5))
        with pytest.raises(SandboxTimeoutError):
            mgr.run(SlowPlugin(), "compute")

    def test_run_exception_in_subprocess(self):
        mgr = SandboxManager(SandboxConfig(timeout_seconds=5))
        with pytest.raises(SandboxExecutionError) as exc:
            mgr.run(BuggyPlugin(), "crash")
        assert "ValueError" in exc.value.stderr

    def test_run_returns_list(self):
        mgr = SandboxManager()
        result = mgr.run(ListPlugin(), "items")
        assert result == [1, 2, 3]

    def test_run_returns_string(self):
        mgr = SandboxManager()
        result = mgr.run(StrPlugin(), "greet", name="World")
        assert result == "Hello, World"

    def test_run_with_none_return(self):
        mgr = SandboxManager()
        result = mgr.run(NonePlugin(), "nothing")
        assert result is None

    def test_run_permission_precheck_blocks(self):
        """AC-05: plugin lacking required_permissions_for_run is blocked."""
        class RestrictedPlugin(Plugin):
            name = "restricted"
            extension_point = ""
            permissions = ["network"]
            required_permissions_for_run = ["filesystem"]
            def fetch(self):
                return "data"

        from earp_sdk_plugin.permissions import PermissionEnforcer
        # This plugin declares network but requires filesystem for run
        # Filesystem is not declared → PermissionDeniedError
        mgr = SandboxManager()
        with pytest.raises(PermissionDeniedError):
            mgr.run(RestrictedPlugin(), "fetch")


# ── PluginManager audit ──

class TestPluginManagerAudit:
    """AC-06/07: load/unload audit events."""

    @pytest.fixture
    def caplog_audit(self, caplog):
        caplog.set_level(logging.INFO, logger="earp.audit")
        return caplog

    def test_load_publishes_audit(self, caplog_audit):
        class TestP(Plugin):
            name = "audit-plugin"
            version = "1.0.0"
            extension_point = "audit.hook"
            permissions = []

        mgr = PluginManager()
        import asyncio
        p = TestP()
        # Bypass register() validation — directly add to internal lists
        mgr._all = [p]
        mgr._plugins = {"audit.hook": [p]}
        asyncio.run(mgr.load_all())

        records = [r for r in caplog_audit.records if r.name == "earp.audit"]
        assert len(records) >= 1
        data = json.loads(records[0].message)
        assert data["event_type"] == "PLUGIN_LOADED"
        assert data["action"] == "plugin_load"
        assert data["result"] == "success"
        assert data["detail"]["plugin_name"] == "audit-plugin"

    def test_load_failure_publishes_audit(self, caplog_audit):
        class BadPlugin(Plugin):
            name = "bad-plugin"
            extension_point = "audit.hook"
            permissions = []
            async def on_load(self):
                raise RuntimeError("init error")

        mgr = PluginManager()
        import asyncio
        mgr._all = [BadPlugin()]
        mgr._plugins = {"audit.hook": [BadPlugin()]}
        asyncio.run(mgr.load_all())

        records = [r for r in caplog_audit.records if r.name == "earp.audit"]
        assert len(records) >= 1
        data = json.loads(records[0].message)
        assert data["event_type"] == "PLUGIN_LOADED"
        assert data["result"] == "failure"
        assert "init error" in data["detail"]["error"]

    def test_unload_publishes_audit(self, caplog_audit):
        class TestP(Plugin):
            name = "unload-plugin"
            version = "2.0"
            extension_point = "audit.hook"
            permissions = []

        mgr = PluginManager()
        import asyncio
        p = TestP()
        mgr._all = [p]
        mgr._plugins = {"audit.hook": [p]}
        asyncio.run(mgr.load_all())

        # Clear previous audit records
        caplog_audit.clear()

        asyncio.run(mgr.unload_all())
        records = [r for r in caplog_audit.records if r.name == "earp.audit"]
        assert len(records) >= 1
        data = json.loads(records[0].message)
        assert data["event_type"] == "PLUGIN_UNLOADED"


# ── PluginStatus + health_check + manifest validation (PRD-2026-017) ──

class TestPluginStatus:
    """AC-01: PluginStatus lifecycle."""

    def test_default_status(self):
        p = Plugin()
        assert p.status == PluginStatus.INACTIVE

    def test_status_load_cycle(self):
        import asyncio

        class TestP(Plugin):
            name = "status-plugin"
            extension_point = "audit.hook"
            permissions = []

        mgr = PluginManager()
        p = TestP()
        mgr._all = [p]
        mgr._plugins = {"audit.hook": [p]}

        assert p.status == PluginStatus.INACTIVE
        asyncio.run(mgr.load_all())
        assert p.status == PluginStatus.ACTIVE
        asyncio.run(mgr.unload_all())
        assert p.status == PluginStatus.INACTIVE


class TestHealthCheck:
    """AC-02: health_check on load."""

    def test_healthy_plugin_status_active(self):
        import asyncio

        class TestP(Plugin):
            name = "healthy-plugin"
            extension_point = "audit.hook"
            permissions = []
            async def health_check(self):
                return True

        mgr = PluginManager()
        p = TestP()
        mgr._all = [p]
        mgr._plugins = {"audit.hook": [p]}
        asyncio.run(mgr.load_all())
        assert p.status == PluginStatus.ACTIVE

    def test_unhealthy_plugin_status_error(self):
        import asyncio

        class TestP(Plugin):
            name = "unhealthy-plugin"
            extension_point = "audit.hook"
            permissions = []
            async def health_check(self):
                return False

        mgr = PluginManager()
        p = TestP()
        mgr._all = [p]
        mgr._plugins = {"audit.hook": [p]}
        asyncio.run(mgr.load_all())
        assert p.status == PluginStatus.ERROR


class TestManifestValidation:
    """AC-03: register() validates required fields."""

    def test_valid_manifest_passes(self):
        from earp_sdk_plugin.extensions import AuditHookProtocol
        class TestP(Plugin, AuditHookProtocol):
            name = "test"
            version = "1.0"
            extension_point = "audit.hook"
            async def on_audit(self, record): pass
        p = TestP()
        mgr = PluginManager()
        mgr.register(p)  # no exception — manifest ok, protocol check passes

    def test_missing_name_raises(self):
        p = Plugin()
        p.version = "1.0"
        p.extension_point = "audit.hook"
        mgr = PluginManager()
        with pytest.raises(ValueError, match="name"):
            mgr.register(p)

    def test_missing_version_raises(self):
        p = Plugin()
        p.name = "test"
        p.version = ""
        p.extension_point = "audit.hook"
        mgr = PluginManager()
        with pytest.raises(ValueError, match="version"):
            mgr.register(p)

    def test_missing_extension_point_raises(self):
        p = Plugin()
        p.name = "test"
        p.version = "1.0"
        mgr = PluginManager()
        with pytest.raises(ValueError, match="extension_point"):
            mgr.register(p)

    def test_missing_multiple_fields_raises(self):
        p = Plugin()
        p.version = ""
        p.extension_point = ""
        mgr = PluginManager()
        with pytest.raises(ValueError, match="name.*extension_point"):
            mgr.register(p)
