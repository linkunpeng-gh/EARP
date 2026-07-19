"""AC-06: domain module independence enforced by import-linter."""

from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_import_contracts_kept() -> None:
    lint_imports = pathlib.Path(sys.executable).parent / "lint-imports"
    result = subprocess.run(
        [str(lint_imports)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "kept" in result.stdout.lower()
