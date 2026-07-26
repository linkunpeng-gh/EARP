"""End-to-end CLI tests — imports and help text."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from earp_sdk_capability.cli.main import app


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestE2ECLI:
    """End-to-end CLI behavior."""

    def test_help_text(self, runner: CliRunner):
        """CLI help shows all commands."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for cmd in ["register", "activate", "list", "search"]:
            assert cmd in result.stdout

    def test_register_valid_module_invalid_class(self, runner: CliRunner):
        """Importing a real module but wrong class gives helpful error."""
        # typer is installed, but Typer is not a Capability
        result = runner.invoke(app, ["register", "typer.Typer"])
        assert result.exit_code != 0
        output = result.stdout + result.stderr
        assert "not a Capability subclass" in output

    def test_activate_unknown_capability(self, runner: CliRunner):
        """Activate without a server shows RegistryError."""
        result = runner.invoke(app, ["activate", "nonexistent_cap"])
        assert result.exit_code == 1
        output = result.stdout + result.stderr
        assert "Activation failed" in output or "Registry API error" in output or result.exception is not None

    def test_list_no_server(self, runner: CliRunner):
        """List without server shows error, not a crash."""
        result = runner.invoke(app, ["list"])
        assert result.exit_code == 1
        output = result.stdout + result.stderr
        assert "Failed to list" in output or "error" in output.lower()

    def test_search_no_server(self, runner: CliRunner):
        """Search without server shows error, not a crash."""
        result = runner.invoke(app, ["search", "alarm"])
        assert result.exit_code == 1
        output = result.stdout + result.stderr
        assert "Search failed" in output or "error" in output.lower()

    def test_register_bad_module_path(self, runner: CliRunner):
        """Register with a non-dotted path."""
        result = runner.invoke(app, ["register", "NoDot"])
        assert result.exit_code != 0
        output = result.stdout + result.stderr
        assert "not a valid dotted path" in output

    def test_no_args_shows_help(self, runner: CliRunner):
        """Calling earp with no args shows help."""
        result = runner.invoke(app)
        assert result.exit_code in (0, 2)  # typer exits 2 when no_args_is_help=True
        output = result.stdout + result.stderr
        assert "Usage:" in output or "Show this message" in output
