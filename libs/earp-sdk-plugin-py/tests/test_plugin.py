import pytest
from earp_sdk_plugin import Plugin, PluginManager, ExtensionPoint, PolicyEvaluatorProtocol
from earp_sdk_plugin.extensions import PlannerStrategyProtocol

class PassStrategy(Plugin, PlannerStrategyProtocol):
    extension_point = ExtensionPoint.PLANNER_STRATEGY
    name = "pass-strategy"; priority = 10
    async def plan(self, intent: dict, goals: list[dict]) -> list[dict]:
        return goals + [{"goal_id": "added"}]

class LowPriorityStrategy(Plugin, PlannerStrategyProtocol):
    extension_point = ExtensionPoint.PLANNER_STRATEGY
    name = "low-strategy"; priority = 1
    async def plan(self, intent: dict, goals: list[dict]) -> list[dict]:
        return goals

class FailingLoadPlugin(Plugin, PlannerStrategyProtocol):
    extension_point = ExtensionPoint.PLANNER_STRATEGY
    name = "failing-load"; priority = 99
    async def plan(self, i, g): return g
    async def on_load(self): raise RuntimeError("load failed")

class NoProtocolPlugin(Plugin):
    extension_point = ExtensionPoint.PLANNER_STRATEGY
    name = "no-protocol"

class TestPluginManager:
    def test_register_and_get(self):
        m = PluginManager(); m.register(PassStrategy()); m.register(LowPriorityStrategy())
        assert len(m.get(ExtensionPoint.PLANNER_STRATEGY)) == 2
        assert m.get(ExtensionPoint.PLANNER_STRATEGY)[0].name == "pass-strategy"

    def test_register_invalid_extension_point(self):
        with pytest.raises(ValueError, match="not valid"):
            p = Plugin(); p.name = "test"; p.version = "1.0"; p.extension_point = "invalid.ep"  # type: ignore
            PluginManager().register(p)

    def test_register_duplicate_name(self):
        m = PluginManager(); m.register(PassStrategy())
        with pytest.raises(ValueError, match="already registered"):
            m.register(PassStrategy())

    def test_get_primary(self):
        m = PluginManager(); m.register(PassStrategy()); m.register(LowPriorityStrategy())
        p = m.get_primary(ExtensionPoint.PLANNER_STRATEGY)
        assert p.name == "pass-strategy"

    def test_register_no_protocol(self):
        with pytest.raises(TypeError, match="does not implement"):
            PluginManager().register(NoProtocolPlugin())

    async def test_load_all_isolates_failure(self):
        m = PluginManager(); m.register(FailingLoadPlugin()); m.register(PassStrategy())
        await m.load_all()
        assert len(m.get(ExtensionPoint.PLANNER_STRATEGY)) == 2

    async def test_unload_all_reverse(self):
        order = []
        class A(Plugin, PlannerStrategyProtocol):
            extension_point = ExtensionPoint.PLANNER_STRATEGY; name = "a"
            async def plan(self, i, g): return g
            async def on_unload(self): order.append("a")
        class B(Plugin, PlannerStrategyProtocol):
            extension_point = ExtensionPoint.PLANNER_STRATEGY; name = "b"
            async def plan(self, i, g): return g
            async def on_unload(self): order.append("b")
        m = PluginManager(); m.register(A()); m.register(B())
        await m.unload_all()
        assert order == ["b", "a"]

    def test_get_empty(self):
        assert PluginManager().get(ExtensionPoint.PLANNER_STRATEGY) == []

class TestPluginBase:
    def test_defaults(self):
        p = PassStrategy(); assert p.name == "pass-strategy"; assert p.permissions == []
