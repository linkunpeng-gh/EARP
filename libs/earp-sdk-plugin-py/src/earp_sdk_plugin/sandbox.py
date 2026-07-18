"""Plugin sandbox — subprocess isolation per Security Spec §7.2 Phase 2."""

from __future__ import annotations

import inspect
import json
import logging
import os
import signal
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from typing import Any

from earp_sdk_core import PermissionDeniedError
from earp_sdk_plugin.permissions import PermissionEnforcer

logger = logging.getLogger(__name__)


# ── Errors ──

class SandboxTimeoutError(TimeoutError):
    """Plugin execution exceeded the configured timeout."""
    pass


class SandboxExecutionError(RuntimeError):
    """Plugin execution failed in the subprocess."""

    def __init__(self, message: str, stderr: str = "") -> None:
        super().__init__(message)
        self.stderr = stderr


# ── Config ──

@dataclass
class SandboxConfig:
    timeout_seconds: float = 30.0
    max_memory_mb: int = 0  # 0 = no limit; Linux-only via setrlimit(RLIMIT_AS)
    protocol: str = "json_stdio"  # "json_stdio" | "grpc" (Phase 3)


# ── Runner template ──

_RUNNER_TEMPLATE = """\
import json, sys, traceback

# --- Imports needed by plugin classes ---
from earp_sdk_plugin import Plugin

# --- Injected plugin class source ---
{plugin_source}

try:
    plugin = {class_name}()
    result = plugin.{method_name}(**json.loads(sys.stdin.read()))
    json.dump(result, sys.stdout, default=str)
except Exception as e:
    err = {{"__error__": repr(e), "traceback": traceback.format_exc()}}
    json.dump(err, sys.stderr)
    sys.exit(1)
"""


# ── SandboxManager ──

class SandboxManager:
    """Execute plugin methods in an isolated subprocess.

    Results are passed via JSON over stdout (safe, no pickle code execution risk).
    Timeout kills the entire process group to prevent orphaned child processes.
    """

    def __init__(self, config: SandboxConfig | None = None) -> None:
        self.config = config or SandboxConfig()

    def run(
        self, plugin: Any, method_name: str, **kwargs: Any
    ) -> Any:
        """Execute plugin.method_name(**kwargs) in a subprocess.

        Args:
            plugin: Plugin instance (must have the named method).
            method_name: Name of the method to call.
            **kwargs: Arguments passed to the method (JSON-serializable).

        Returns:
            JSON-deserialized return value.

        Raises:
            PermissionDeniedError: plugin lacks required permissions.
            SandboxTimeoutError: execution exceeded timeout.
            SandboxExecutionError: subprocess exits non-zero or result is non-JSON-serializable.
        """
        # Permission pre-check
        enforcer = PermissionEnforcer(plugin)
        required = plugin.required_permissions_for_run
        if required:
            enforcer.ensure_all(required)

        # Capture plugin class source
        cls = type(plugin)
        try:
            plugin_source = inspect.getsource(cls)
        except OSError:
            # Fallback: reconstruct from module + class name (for installed packages)
            raise SandboxExecutionError(
                f"Cannot get source for plugin '{cls.__name__}'. "
                f"Plugin classes must be defined in importable modules or source-accessible files."
            )

        class_name = cls.__name__
        script = _RUNNER_TEMPLATE.format(
            plugin_source=textwrap.dedent(plugin_source),
            class_name=class_name,
            method_name=method_name,
        )

        # Memory limit (Linux-only, macOS silently ignored + DEBUG log)
        preexec_fn = None
        if self.config.max_memory_mb > 0 and sys.platform == "linux":
            import resource
            limit = self.config.max_memory_mb * 1024 * 1024
            preexec_fn = lambda: resource.setrlimit(
                resource.RLIMIT_AS, (limit, limit)
            )
        elif self.config.max_memory_mb > 0:
            logger.debug(
                "max_memory_mb=%d ignored on %s (setrlimit RLIMIT_AS not supported)",
                self.config.max_memory_mb, sys.platform,
            )

        proc = subprocess.Popen(
            [sys.executable, "-c", script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            preexec_fn=preexec_fn,
        )

        try:
            stdout, stderr = proc.communicate(
                input=json.dumps(kwargs).encode("utf-8"),
                timeout=self.config.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            proc.wait()
            raise SandboxTimeoutError(
                f"Plugin '{getattr(plugin, 'name', 'unknown')}' "
                f"timed out after {self.config.timeout_seconds}s"
            )

        stderr_text = stderr.decode("utf-8", errors="replace")

        if proc.returncode != 0:
            raise SandboxExecutionError(
                f"Plugin '{getattr(plugin, 'name', 'unknown')}' "
                f"exited with code {proc.returncode}",
                stderr=stderr_text,
            )

        try:
            return json.loads(stdout.decode("utf-8"))
        except json.JSONDecodeError as e:
            raise SandboxExecutionError(
                f"Failed to decode plugin result: {e}",
                stderr=stderr_text,
            )
