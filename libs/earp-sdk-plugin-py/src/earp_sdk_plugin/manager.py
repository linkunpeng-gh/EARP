import logging, traceback
from typing import Any
from earp_sdk_core import CapabilityError, CapabilityErrorCode
from earp_sdk_plugin.base import Plugin
from earp_sdk_plugin.extensions import EXTENSION_POINT_PROTOCOLS, ExtensionPoint
from earp_sdk_plugin.permissions import Permission

logger = logging.getLogger(__name__)

class PluginManager:
    def __init__(self):
        self._plugins: dict[ExtensionPoint, list[Plugin]] = {}
        self._all: list[Plugin] = []

    def register(self, plugin: Plugin) -> None:
        ep = plugin.extension_point
        if ep not in EXTENSION_POINT_PROTOCOLS:
            raise ValueError(f"extension_point '{ep}' is not valid")
        if ep not in self._plugins:
            self._plugins[ep] = []
        if any(p.name == plugin.name for p in self._plugins[ep]):
            raise ValueError(f"Plugin '{plugin.name}' already registered")
        for perm in plugin.permissions:
            if perm not in Permission:
                raise ValueError(f"Invalid permission '{perm}'")
        required = EXTENSION_POINT_PROTOCOLS.get(ep)
        if required and not isinstance(plugin, required):
            raise TypeError(f"Plugin '{plugin.name}' does not implement {required.__name__}")
        self._plugins[ep].append(plugin)
        self._all.append(plugin)
        self._plugins[ep].sort(key=lambda p: p.priority, reverse=True)

    def get(self, ext: ExtensionPoint) -> list[Plugin]:
        return self._plugins.get(ext, [])

    def get_primary(self, ext: ExtensionPoint) -> Plugin | None:
        return self._plugins.get(ext, [None])[0]

    async def load_all(self) -> None:
        for plugin in self._all:
            try:
                await plugin.on_load()
            except Exception as e:
                logger.error("Failed to load plugin '%s': %s\n%s", plugin.name, e, traceback.format_exc())

    async def unload_all(self) -> None:
        for plugin in reversed(self._all):
            try:
                await plugin.on_unload()
            except Exception:
                logger.error("Failed to unload plugin '%s'", plugin.name)

    @staticmethod
    async def wrap_call(plugin: Plugin, coro: Any) -> Any:
        try:
            return await coro
        except CapabilityError:
            raise
        except Exception as e:
            raise CapabilityError(CapabilityErrorCode.SYSTEM_ERROR, f"Plugin '{plugin.name}' error: {e}", cause=e) from e
