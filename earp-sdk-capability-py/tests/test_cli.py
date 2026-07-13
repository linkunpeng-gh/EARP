"""Tests for the CLI — uses Typer's CliRunner for isolated invocation."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from earp_sdk_capability.cli.main import app


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ── Tests: register command ──


class TestRegisterCommand:
    def test_register_invalid_module_path(self, runner: CliRunner):
        """Non-existent module path shows error."""
        result = runner.invoke(app, ["register", "nonexistent.module.Foo"])
        assert result.exit_code != 0
        output = result.stdout + result.stderr
        assert "Cannot import" in output or "not a valid" in output

    def test_register_missing_dot(self, runner: CliRunner):
        """Module path without dot shows error."""
        result = runner.invoke(app, ["register", "FooBar"])
        assert result.exit_code != 0
        output = result.stdout + result.stderr
        assert "not a valid dotted path" in output

    def test_register_non_capability(self, runner: CliRunner):
        """Importing a non-Capability class shows error."""
        result = runner.invoke(app, ["register", "typer.Typer"])
        assert result.exit_code != 0
        output = result.stdout + result.stderr
        assert "not a Capability subclass" in output

    def test_register_dry_help(self, runner: CliRunner):
        """Register command shows in help."""
        result = runner.invoke(app, ["--help"])
        assert "register" in result.stdout


# ── Tests: activate command ──


class TestActivateCommand:
    def test_activate_help(self, runner: CliRunner):
        """Activate command shows in help."""
        result = runner.invoke(app, ["--help"])
        assert "activate" in result.stdout

    def test_activate_with_id(self, runner: CliRunner):
        """Activate with an ID shows error (no server)."""
        result = runner.invoke(app, ["activate", "test_cap"])
        # Will fail because there's no server, but should not crash
        assert result.exit_code == 1
        assert "Activation failed" in result.stdout or "Registry API error" in result.stdout


# ── Tests: list command ──


class TestListCommand:
    def test_list_help(self, runner: CliRunner):
        """List command shows in help."""
        result = runner.invoke(app, ["--help"])
        assert "list" in result.stdout

    def test_list_no_server(self, runner: CliRunner):
        """List without a server shows error."""
        result = runner.invoke(app, ["list"])
        # Will fail because there's no server, but should not crash
        assert result.exit_code == 1
        assert "Failed to list" in result.stdout or "error" in result.stdout.lower()

    def test_list_with_domain(self, runner: CliRunner):
        """List with --domain flag."""
        result = runner.invoke(app, ["list", "--domain", "equipment"])
        assert result.exit_code == 1  # No server
        assert "Failed to list" in result.stdout or "error" in result.stdout.lower()


# ── Tests: search command ──


class TestSearchCommand:
    def test_search_help(self, runner: CliRunner):
        """Search command shows in help."""
        result = runner.invoke(app, ["--help"])
        assert "search" in result.stdout

    def test_search_no_server(self, runner: CliRunner):
        """Search without a server shows error."""
        result = runner.invoke(app, ["search", "设备报警"])
        assert result.exit_code == 1
        assert "Search failed" in result.stdout or "error" in result.stdout.lower()


# ── Tests: help text ──


class TestHelpText:
    def test_help_contains_all_commands(self, runner: CliRunner):
        """Help text lists all 4 commands."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "register" in result.stdout
        assert "activate" in result.stdout
        assert "list" in result.stdout
        assert "search" in result.stdout

    def test_help_contains_sdk_name(self, runner: CliRunner):
        """Help mentions Capability SDK."""
        result = runner.invoke(app, ["--help"])
        assert "EARP" in result.stdout or "Capability" in result.stdout
