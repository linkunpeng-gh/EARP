class Plugin:
    extension_point: "ExtensionPoint"
    name: str = ""
    version: str = "0.1.0"
    description: str = ""
    priority: int = 0
    author: str = ""
    permissions: list[str] = []

    async def on_load(self) -> None: pass
    async def on_unload(self) -> None: pass
    def config_schema(self) -> dict | None: return None
