class Plugin:
    extension_point: str = ""
    name: str = ""
    version: str = "0.1.0"
    description: str = ""
    priority: int = 0
    author: str = ""
    permissions: list[str] = []
    required_permissions_for_run: list[str] = []

    async def on_load(self) -> None: pass
    async def on_unload(self) -> None: pass
    def config_schema(self) -> dict | None: return None
