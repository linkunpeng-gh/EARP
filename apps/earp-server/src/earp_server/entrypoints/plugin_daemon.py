"""Plugin daemon — standalone HTTP server hosting plugin execution.

Runs independently of the API server. Loads plugins from a directory
and exposes REST endpoints for sandboxed execution.

Start: make plugin-daemon
"""

from __future__ import annotations

import asyncio
import logging
import signal
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from earp_server.config import Settings
from earp_server.infra.ext import init_all

logger = logging.getLogger(__name__)

DEFAULT_PORT = 9100
DEFAULT_PLUGIN_DIR = "./plugins"


class ExecuteRequest(BaseModel):
    plugin_name: str
    method: str
    params: dict = {}
    timeout_seconds: int = 30


class ExecuteResponse(BaseModel):
    status: str  # "ok" | "error" | "timeout"
    result: dict | None = None
    error: str | None = None


class PluginRegistry:
    """In-memory plugin registry — loads plugins from a directory on startup.

    Security: plugins are loaded via importlib from a trusted directory.
    Production deployments MUST mount ./plugins as a read-only volume with
    write access restricted to administrator-controlled deployment pipelines.
    This daemon is designed to run in an isolated container/VM — the plugin
    directory is the trust boundary. No runtime code signature verification
    is performed; rely on filesystem-level access control.
    """

    def __init__(self, plugin_dir: str = DEFAULT_PLUGIN_DIR) -> None:
        self._dir = Path(plugin_dir)
        self._plugins: dict[str, object] = {}

    def load_all(self) -> int:
        """Load plugins from the plugin directory. Returns count loaded."""
        if not self._dir.exists():
            logger.warning("plugin dir not found: %s, creating", self._dir)
            self._dir.mkdir(parents=True, exist_ok=True)
        count = 0
        for py_file in self._dir.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            try:
                import importlib.util
                spec = importlib.util.spec_from_file_location(
                    f"earp_plugin_{py_file.stem}", str(py_file),
                )
                if spec is None or spec.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                # Register classes that implement Plugin protocol
                for name in dir(module):
                    obj = getattr(module, name)
                    if hasattr(obj, "extension_point") and hasattr(obj, "name"):
                        self._plugins[name] = obj
                        logger.info("plugin loaded: %s from %s", name, py_file.name)
                        count += 1
            except Exception:
                logger.exception("failed to load plugin: %s", py_file)
        return count

    def get(self, name: str) -> object | None:
        return self._plugins.get(name)

    @property
    def count(self) -> int:
        return len(self._plugins)


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or Settings()
    init_all(cfg)

    registry = PluginRegistry()
    loaded = registry.load_all()
    logger.info("plugin daemon: loaded %d plugins from %s", loaded, DEFAULT_PLUGIN_DIR)

    app = FastAPI(title="EARP Plugin Daemon", version="0.1.0")

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "plugins_loaded": registry.count}

    @app.post("/execute", response_model=ExecuteResponse)
    async def execute(req: ExecuteRequest) -> ExecuteResponse:
        plugin_cls = registry.get(req.plugin_name)
        if plugin_cls is None:
            raise HTTPException(status_code=404, detail=f"plugin not found: {req.plugin_name}")

        try:
            instance = plugin_cls()
            method = getattr(instance, req.method, None)
            if method is None:
                raise HTTPException(
                    status_code=400, detail=f"method not found: {req.method}",
                )
            if asyncio.iscoroutinefunction(method):
                result = await asyncio.wait_for(method(**req.params), timeout=req.timeout_seconds)
            else:
                # Sync method: run in thread pool to avoid blocking event loop
                loop = asyncio.get_running_loop()
                result = await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: method(**req.params)),
                    timeout=req.timeout_seconds,
                )
            return ExecuteResponse(status="ok", result=result if isinstance(result, dict) else {"value": str(result)})
        except TimeoutError:
            return ExecuteResponse(status="timeout", error=f"execution exceeded {req.timeout_seconds}s")
        except Exception as e:
            logger.exception("plugin execute failed: %s.%s", req.plugin_name, req.method)
            return ExecuteResponse(status="error", error=str(e))

    return app


async def _run() -> int:
    import uvicorn

    settings = Settings()
    app = create_app(settings)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    config = uvicorn.Config(app, host="127.0.0.1", port=DEFAULT_PORT, log_level=settings.log_level.lower())
    server = uvicorn.Server(config)

    logger.info("plugin daemon starting on port %d", DEFAULT_PORT)
    server_task = asyncio.create_task(server.serve())

    await stop.wait()
    logger.info("plugin daemon stopping (signal)")
    server.should_exit = True
    await server_task

    logger.info("plugin daemon stopped")
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
