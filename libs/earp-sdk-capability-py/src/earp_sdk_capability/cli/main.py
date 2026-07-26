"""EARP CLI — register, activate, list, and search capabilities.

Installed as the `earp` command via pyproject.toml entrypoint.

Usage:
    earp register my_capabilities.QueryEquipmentAlarm
    earp activate query_equipment_alarm
    earp list
    earp search "设备报警"
"""

from __future__ import annotations

import importlib

import httpx
import typer
from rich.console import Console
from rich.table import Table

from earp_sdk_capability.base import Capability
from earp_sdk_capability.discovery.client import CapabilityDiscoveryClient
from earp_sdk_capability.registration.client import CapabilityRegistryClient, RegistryError
from earp_sdk_capability.registration.packager import packager

app = typer.Typer(
    name="earp",
    help="EARP Capability SDK — develop, test, and register Capabilities",
    no_args_is_help=True,
)
console = Console()


def _import_capability(module_path: str) -> type[Capability]:
    """Import a Capability class from a Python dotted path."""
    parts = module_path.rsplit(".", 1)
    if len(parts) != 2:
        raise typer.BadParameter(
            f"'{module_path}' is not a valid dotted path. "
            f"Use format: package.module.ClassName"
        )
    module_name, class_name = parts

    try:
        module = importlib.import_module(module_name)
    except ImportError as e:
        raise typer.BadParameter(f"Cannot import module '{module_name}': {e}")

    cap_cls = getattr(module, class_name, None)
    if cap_cls is None:
        raise typer.BadParameter(
            f"Class '{class_name}' not found in module '{module_name}'"
        )
    if not isinstance(cap_cls, type) or not issubclass(cap_cls, Capability):
        raise typer.BadParameter(
            f"'{module_path}' is not a Capability subclass"
        )
    return cap_cls


@app.command()
def register(
    module_path: str = typer.Argument(
        ...,
        help="Python dotted path to the Capability class, e.g. my_caps.QueryEquipmentAlarm",
    ),
) -> None:
    """Register a Capability to the Capability Center (draft status)."""
    cap_cls = _import_capability(module_path)
    console.print(f"📦 Packaging [bold]{cap_cls.capability_id}[/bold]...")

    # Step 1: Validate locally before any network request (AC-08 / SDKMUST-004)
    try:
        package = packager.pack(cap_cls)
    except ValueError as e:
        console.print(f"❌ [red]Invalid capability[/red]: {e}")
        raise typer.Exit(code=1)

    input_schema = package["definition"].get("input_schema", {})
    output_schema = package["definition"].get("output_schema", {})
    schema_errors: list[str] = []
    if input_schema and input_schema.get("type") != "object":
        schema_errors.append("input_schema: top-level type must be 'object'")
    if output_schema and output_schema.get("type") != "object":
        schema_errors.append("output_schema: top-level type must be 'object'")
    if schema_errors:
        console.print("❌ [red]Local schema validation failed:[/red]")
        for err in schema_errors:
            console.print(f"  • {err}")
        raise typer.Exit(code=1)

    # Step 2: Send registration request
    try:
        import asyncio

        async def _do_register():
            client = CapabilityRegistryClient()
            result = await client.register(cap_cls)
            await client.close()
            return result

        result = asyncio.run(_do_register())
        console.print(
            f"✅ [green]Registered[/green] [bold]{result.capability_id}[/bold] "
            f"v{result.version} [dim]({result.status})[/dim]"
        )
    except (RegistryError, httpx.HTTPError) as e:
        console.print(f"❌ [red]Registration failed[/red]: {e}")
        raise typer.Exit(code=1)


@app.command()
def activate(
    capability_id: str = typer.Argument(
        ...,
        help="Capability ID to activate (e.g. query_equipment_alarm)",
    ),
) -> None:
    """Activate a draft Capability."""
    try:
        import asyncio

        async def _do_activate():
            client = CapabilityRegistryClient()
            result = await client.activate(capability_id)
            await client.close()
            return result

        result = asyncio.run(_do_activate())
        console.print(
            f"✅ [green]Activated[/green] [bold]{result.capability_id}[/bold] "
            f"v{result.version} [dim]({result.status})[/dim]"
        )
    except (RegistryError, httpx.HTTPError) as e:
        console.print(f"❌ [red]Activation failed[/red]: {e}")
        raise typer.Exit(code=1)


@app.command(name="list")
def list_capabilities(
    domain: str | None = typer.Option(
        None,
        "--domain",
        "-d",
        help="Filter by domain (e.g. equipment)",
    ),
) -> None:
    """List registered Capabilities."""
    try:
        import asyncio

        async def _do_list():
            client = CapabilityDiscoveryClient()
            if domain:
                result = await client.list_by_domain(domain)
            else:
                result = await client.search("")
            await client.close()
            return result

        result = asyncio.run(_do_list())
    except Exception as e:
        console.print(f"❌ [red]Failed to list capabilities[/red]: {e}")
        raise typer.Exit(code=1)

    if not result.results:
        console.print("[yellow]No capabilities found[/yellow]")
        return

    table = Table(title=f"Capabilities ({result.total} total)")
    table.add_column("ID", style="cyan")
    table.add_column("Name")
    table.add_column("Version", style="green")
    table.add_column("Domain", style="blue")
    table.add_column("Confidence", style="yellow")

    for cap in result.results:
        table.add_row(
            cap.capability_id,
            cap.name,
            cap.version,
            cap.domain,
            f"{cap.confidence:.2f}" if cap.confidence else "-",
        )

    console.print(table)
    if result.page > 1 or result.total > result.page * result.page_size:
        console.print(
            f"[dim]Page {result.page} of ~{(result.total // result.page_size) + 1}[/dim]"
        )


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query (e.g. '设备报警')"),
    domain: str | None = typer.Option(
        None,
        "--domain",
        "-d",
        help="Filter by domain",
    ),
) -> None:
    """Search Capabilities by semantic query."""
    try:
        import asyncio

        async def _do_search():
            client = CapabilityDiscoveryClient()
            result = await client.search(query, domain=domain)
            await client.close()
            return result

        result = asyncio.run(_do_search())
    except Exception as e:
        console.print(f"❌ [red]Search failed[/red]: {e}")
        raise typer.Exit(code=1)

    if not result.results:
        console.print(f"[yellow]No results for '{query}'[/yellow]")
        return

    table = Table(title=f"Search results for '{query}' ({result.total} found)")
    table.add_column("ID", style="cyan")
    table.add_column("Name")
    table.add_column("Version", style="green")
    table.add_column("Domain", style="blue")
    table.add_column("Confidence", style="yellow")

    for cap in result.results:
        table.add_row(
            cap.capability_id,
            cap.name,
            cap.version,
            cap.domain,
            f"{cap.confidence:.2f}" if cap.confidence else "-",
        )

    console.print(table)


def main() -> None:
    """Entry point for the CLI."""
    app()
