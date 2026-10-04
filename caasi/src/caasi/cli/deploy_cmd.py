"""`caasi deploy` — target-aware project deployment and synchronization."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.table import Table

from .. import state
from ..core import deploy as deploy_core
from ..core import project as projects
from ..core import targets as targets_core
from ..i18n import _
from ..utils import output


def _require_project_root() -> Path:
    root = projects.find_project_root()
    if root is None:
        output.fail(_("project.not_found"))
        raise typer.Exit(1)
    return root


def _require_target(name: str) -> targets_core.Target:
    target = targets_core.find_target(state.cfg(), name)
    if target is None:
        valid = ", ".join(t.name for t in targets_core.list_targets(state.cfg())) or "-"
        output.fail(_("target.not_found", query=name, valid=valid))
        raise typer.Exit(1)
    return target


def _format_bytes(num_bytes: int) -> str:
    """Format byte counts into human-readable strings."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    elif num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KiB"
    elif num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f} MiB"
    return f"{num_bytes / (1024 * 1024 * 1024):.2f} GiB"


def _render_status(target_name: str, dest: Optional[str] = None, json_output: bool = False) -> None:
    c = output.console()
    target = _require_target(target_name)
    # Pass the project root so the read path derives the same destination the
    # deployment writer used (<deployment_root>/<project_name>).
    status_rec = deploy_core.get_deployment_status(
        target, dest, state.cfg(), project_root=projects.find_project_root()
    )

    if output.wants_json(json_output):
        if status_rec:
            output.echo_json(status_rec.to_dict())
        else:
            output.echo_json({"status": "no_deployment", "target": target.name})
        return

    if not status_rec:
        c.print(f"\n[yellow]No active caasi deployment found on target '{target.name}'.[/yellow]\n")
        return

    c.print(f"\n[bold cyan]Active Deployment on {target.name}:[/bold cyan]")
    c.print(f"  [dim]Deployment ID:[/dim]  [bold]{status_rec.deployment_id}[/bold]")
    c.print(f"  [dim]Project:[/dim]        {status_rec.project_name} v{status_rec.project_version}")
    c.print(f"  [dim]Git Revision:[/dim]   {status_rec.git_revision}")
    c.print(f"  [dim]Destination:[/dim]    {status_rec.destination_path}")
    c.print(f"  [dim]Deployed At:[/dim]    {status_rec.deployed_at}")
    c.print(f"  [dim]Status:[/dim]         [bold green]{status_rec.status.upper()}[/bold green]")
    c.print(f"  [dim]Files Count:[/dim]    {status_rec.file_count:,} ({_format_bytes(status_rec.total_bytes)})\n")


def _render_list(target_name: Optional[str] = None, json_output: bool = False) -> None:
    project_root = _require_project_root()
    records = deploy_core.list_local_deployments(project_root, target_name)

    if output.wants_json(json_output):
        output.echo_json([r.to_dict() for r in records])
        return

    if not records:
        output.echo("[yellow]No deployment records found for this project.[/yellow]")
        return

    table = Table(title="Recorded Deployments")
    table.add_column("Deployment ID", style="bold cyan")
    table.add_column("Target", style="magenta")
    table.add_column("Version / Rev", style="dim")
    table.add_column("Status")
    table.add_column("Transferred")
    table.add_column("Deployed At", style="dim")

    for r in records:
        status_style = "green" if r.status == "verified" else "yellow"
        table.add_row(
            r.deployment_id,
            r.target_name,
            f"{r.project_version} ({r.git_revision[:8]})",
            f"[{status_style}]{r.status.upper()}[/{status_style}]",
            _format_bytes(r.transferred_bytes),
            r.deployed_at,
        )

    output.console().print(table)


def deploy_command(
    target: Optional[str] = typer.Argument(None, help=_("deploy.arg.target")),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help=_("deploy.flag.dry_run")),
    force: bool = typer.Option(False, "--force", "-f", help=_("deploy.flag.force")),
    dest: Optional[str] = typer.Option(None, "--dest", help=_("deploy.flag.dest")),
    status: bool = typer.Option(False, "--status", help=_("deploy.flag.status")),
    list_deployments: bool = typer.Option(False, "--list", "-l", help=_("deploy.list_help")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    """Deploy and synchronize project workspaces to execution targets."""
    if list_deployments:
        _render_list(target, json_output)
        return

    if target is None:
        output.echo("Usage: caasi deploy <target> [OPTIONS]")
        output.echo("Run 'caasi deploy --help' for details.")
        raise typer.Exit(0)

    if status:
        _render_status(target, dest, json_output)
        return

    c = output.console()
    project_root = _require_project_root()
    target_obj = _require_target(target)

    spec = deploy_core.create_deployment_spec(
        project_root=project_root,
        target=target_obj,
        config=state.cfg(),
        destination_override=dest,
    )

    record = deploy_core.execute_deployment(
        spec=spec,
        dry_run=dry_run,
        force=force,
        config=state.cfg(),
    )

    if output.wants_json(json_output):
        output.echo_json(record.to_dict())
        if record.status in ("failed", "verification_failed"):
            raise typer.Exit(1)
        return

    # Render Terminal Output
    mode_str = "[bold yellow](DRY RUN)[/bold yellow]" if dry_run else ""
    c.print(f"\n[bold cyan]Project Deployment[/bold cyan] {mode_str}")
    c.print(f"  [dim]Project:[/dim]     {spec.project_name} v{spec.project_version} (rev: {spec.git_revision[:10]})")
    c.print(f"  [dim]Target:[/dim]      [bold]{target_obj.name}[/bold] ({target_obj.transport})")
    c.print(f"  [dim]Destination:[/dim] {spec.destination_path}")

    if record.warnings:
        c.print("\n[bold yellow]Preflight Warnings:[/bold yellow]")
        for w in record.warnings:
            c.print(f"  [yellow]⚠[/yellow] {w}")

    if record.errors:
        c.print("\n[bold red]Deployment Errors:[/bold red]")
        for err in record.errors:
            c.print(f"  [red]✖[/red] {err}")
        c.print("")
        raise typer.Exit(1)

    c.print("\n[bold]Content Synchronization[/bold]")
    c.print(f"  [dim]Total Project Files:[/dim] {record.file_count:,} ({_format_bytes(record.total_bytes)})")
    c.print(f"  [dim]Transferred Volume:[/dim]  {_format_bytes(record.transferred_bytes)} in {record.duration_seconds:.2f}s")
    c.print(f"  [dim]Changed Files:[/dim]       {len(record.changed_files)}")

    if record.changed_files:
        preview_count = min(10, len(record.changed_files))
        for f in record.changed_files[:preview_count]:
            c.print(f"    - [cyan]{f}[/cyan]")
        if len(record.changed_files) > preview_count:
            c.print(f"    [dim]... and {len(record.changed_files) - preview_count} more files[/dim]")

    if dry_run:
        c.print("\n[bold yellow]✔ Dry run complete. No files were written to the target.[/bold yellow]\n")
        return

    status_color = "green" if record.status == "verified" else "yellow"
    c.print(f"\n[bold green]✔ Deployment {record.deployment_id} materialization complete.[/bold green]")
    c.print(f"  [dim]Status:[/dim]       [{status_color}]{record.status.upper()}[/{status_color}]")
    c.print(f"  [dim]Destination:[/dim]  {record.destination_path}\n")
