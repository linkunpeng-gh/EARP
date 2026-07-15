from earp_sdk_plugin.manager import PluginManager
class MockPluginManager(PluginManager):
    async def load_all(self) -> None: pass
    async def unload_all(self) -> None: pass
