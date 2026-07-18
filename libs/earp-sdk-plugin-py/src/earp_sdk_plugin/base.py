from enum import Enum


class PluginStatus(str, Enum):
    """Plugin lifecycle status — aligned with Dify PluginInstallation.status."""
    INACTIVE = "inactive"        # registered but not loaded
    INSTALLING = "installing"    # on_load() in progress
    ACTIVE = "active"            # loaded + health_check passed
    ERROR = "error"              # load or health_check failed


class Plugin:
    extension_point: str = ""
    name: str = ""
    version: str = "0.1.0"
    description: str = ""
    priority: int = 0
    author: str = ""
    permissions: list[str] = []
    required_permissions_for_run: list[str] = []
    status: PluginStatus = PluginStatus.INACTIVE

    async def on_load(self) -> None: pass
    async def on_unload(self) -> None: pass

    def config_schema(self) -> dict | None: return None

    async def health_check(self) -> bool:
        """Post-load health check. Default: pass. Override for custom checks."""
        return True
