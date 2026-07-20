"""AC-02: api/worker/scheduler entrypoints start and exit gracefully on SIGTERM."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time

import pytest

READY_TIMEOUT = 20.0
GRACE_SECONDS = 5.0


class _Proc:
    def __init__(self, module: str, env: dict[str, str]) -> None:
        self.proc = subprocess.Popen(
            [sys.executable, "-m", module],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self.lines: list[str] = []
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()

    def _pump(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            self.lines.append(line)

    def wait_ready(self, marker: str) -> None:
        deadline = time.monotonic() + READY_TIMEOUT
        while time.monotonic() < deadline:
            if any(marker in line for line in self.lines):
                return
            if self.proc.poll() is not None:
                pytest.fail(f"process exited early ({self.proc.returncode}): {''.join(self.lines)}")
            time.sleep(0.1)
        pytest.fail(f"ready marker {marker!r} not seen within {READY_TIMEOUT}s: {''.join(self.lines)}")


def _run_entrypoint(module: str, env: dict[str, str], ready_marker: str) -> int:
    runner = _Proc(module, env)
    runner.wait_ready(ready_marker)
    runner.proc.send_signal(signal.SIGTERM)
    try:
        return runner.proc.wait(timeout=GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        runner.proc.kill()
        pytest.fail(f"{module} did not exit within {GRACE_SECONDS}s after SIGTERM")


def _env(app_url: str) -> dict[str, str]:
    env = os.environ.copy()
    env["EARP_DATABASE_URL"] = app_url
    env["EARP_APP_ENV"] = "test"
    env["EARP_API_PORT"] = "0"  # bind an ephemeral port
    return env


def test_api_entrypoint_graceful(migrated: str, app_url: str) -> None:
    # uvicorn re-raises the original signal after a clean shutdown (exit 143 / -15),
    # which Kubernetes treats as normal termination. Graceful == full shutdown log.
    runner = _Proc("earp_server.entrypoints.api", _env(app_url))
    runner.wait_ready("Application startup complete")
    runner.proc.send_signal(signal.SIGTERM)
    try:
        code = runner.proc.wait(timeout=GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        runner.proc.kill()
        pytest.fail(f"api did not exit within {GRACE_SECONDS}s after SIGTERM")
    assert code in (0, -signal.SIGTERM, 128 + signal.SIGTERM)
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and not any("Application shutdown complete" in ln for ln in runner.lines):
        time.sleep(0.05)
    assert any("Application shutdown complete" in ln for ln in runner.lines), "".join(runner.lines)


def test_worker_entrypoint_graceful(migrated: str, app_url: str) -> None:
    code = _run_entrypoint("earp_server.entrypoints.worker", _env(app_url), "worker started")
    assert code == 0


def test_scheduler_entrypoint_graceful(migrated: str, app_url: str) -> None:
    code = _run_entrypoint("earp_server.entrypoints.scheduler", _env(app_url), "scheduler started")
    assert code == 0


def test_audit_entrypoint_graceful(migrated: str, app_url: str) -> None:
    """Audit worker: starts, fails Redis connect (no Redis in test), exits gracefully."""
    code = _run_entrypoint("earp_server.entrypoints.audit", _env(app_url), "audit worker starting")
    # SIGTERM after startup — Redis unavailable is non-fatal, exit clean
    assert code == 0
