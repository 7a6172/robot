"""`caasi target` (and alias `caasi node`) — execution target inspection and discovery.

Supports local workstation, remote robots, edge devices, and compute servers
in a capability- and resource-driven manner.
"""

from __future__ import annotations

import typer
from rich.table import Table

from .. import state
from ..core import targets as targets_core
from ..i18n import _
from ..utils import output

app = typer.Typer(no_args_is_help=True)


def _require_target(query: str) -> targets_core.Target:
    target = targets_core.find_target(state.cfg(), query)
    if target is None:
        valid = ", ".join(t.name for t in targets_core.list_targets(state.cfg())) or "-"
        output.fail(_("target.not_found", query=query, valid=valid))
        raise typer.Exit(1)
    return target


@app.command("list", help=_("target.list_help"))
def target_list(
    check: bool = typer.Option(False, "--check", "-c", help=_("target.flag.check")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    all_targets = targets_core.list_targets(state.cfg())

    if output.wants_json(json_output):
        if check:
            inspections = [targets_core.discover_target(t, state.cfg()) for t in all_targets]
            output.echo_json([i.to_dict() for i in inspections])
        else:
            output.echo_json([t.to_dict() for t in all_targets])
        return

    table = Table(title=_("target.title"), show_lines=False)
    table.add_column("Target", style="bold cyan")
    table.add_column("Transport", style="dim")
    table.add_column("Endpoint")
    table.add_column("Deployment Root", style="dim")
    table.add_column("Tags", style="magenta")
    if check:
        table.add_column("Status")
        table.add_column("Latency")

    for t in all_targets:
        if t.transport == "local":
            endpoint = "[dim]local[/dim]"
        else:
            port = f":{t.port}" if t.port else ""
            user = f"{t.user}@" if t.user else ""
            endpoint = f"{user}{t.host}{port}"

        root = t.deployment_root or "-"
        tags_str = ", ".join(t.tags) if t.tags else "-"

        if check:
            insp = targets_core.discover_target(t, state.cfg())
            status_style = "green" if insp.status == "online" else "red"
            status_str = f"[{status_style}]{insp.status.upper()}[/{status_style}]"
            lat_str = f"{insp.latency_ms:.1f}ms" if insp.latency_ms is not None else "-"
            table.add_row(t.name, t.transport, endpoint, root, tags_str, status_str, lat_str)
        else:
            table.add_row(t.name, t.transport, endpoint, root, tags_str)

    output.console().print(table)


@app.command("inspect", help=_("target.inspect_help"))
def target_inspect(
    name: str = typer.Argument(..., help=_("target.arg.name")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    target = _require_target(name)
    insp = targets_core.discover_target(target, state.cfg())

    if output.wants_json(json_output):
        output.echo_json(insp.to_dict())
        return

    c = output.console()
    status_color = "green" if insp.status == "online" else "red"
    if target.transport == "local":
        timing_str = f"transport: local | discovery probe: {insp.probe_duration_ms:.1f}ms"
    elif insp.ping_ms is not None:
        probe_str = f" | discovery probe: {insp.probe_duration_ms:.1f}ms" if insp.probe_duration_ms is not None else ""
        timing_str = f"network ping: {insp.ping_ms:.1f}ms{probe_str}"
    else:
        timing_str = "unreachable"

    c.print(f"\n[bold cyan]Target:[/bold cyan] [bold]{target.name}[/bold] ([dim]{target.transport}[/dim])")
    c.print(f"[bold]Status:[/bold] [{status_color}]{insp.status.upper()}[/{status_color}] ({timing_str})")
    if target.deployment_root:
        c.print(f"[bold]Deployment Root:[/bold] {target.deployment_root}")
    if target.tags:
        c.print(f"[bold]Tags:[/bold] {', '.join(target.tags)}")

    if insp.error:
        c.print(f"[bold red]Error:[/bold red] {insp.error}")

    # Resources
    if insp.resources:
        res = insp.resources
        c.print("\n[bold]Resources & Hardware[/bold]")
        cpu_model = res.cpu_model or "Unknown"
        cpu_count = res.cpu_count or "-"
        c.print(f"  [dim]CPU:[/dim]      {cpu_model} ({cpu_count} cores)")
        if res.memory_total_kib:
            total_gib = res.memory_total_kib / (1024 * 1024)
            avail_gib = (res.memory_available_kib or 0) / (1024 * 1024)
            c.print(f"  [dim]Memory:[/dim]   {total_gib:.1f} GiB total ({avail_gib:.1f} GiB available)")
        if res.gpus:
            c.print("  [dim]GPUs:[/dim]")
            for g in res.gpus:
                mem = f" ({g['memory_total_mib']} MiB)" if g.get("memory_total_mib") else ""
                driver = f" [dim][driver: {g.get('driver_version')}][/dim]" if g.get("driver_version") else ""
                c.print(f"    - {g.get('name', 'NVIDIA GPU')}{mem}{driver}")
        else:
            c.print("  [dim]GPUs:[/dim]     None detected")

    # Environment
    if insp.environment:
        env = insp.environment
        c.print("\n[bold]Platform & Environment[/bold]")
        c.print(f"  [dim]OS / Kernel:[/dim]  {env.os or '-'} ({env.kernel or '-'})")
        c.print(f"  [dim]Arch / Host:[/dim]  {env.arch or '-'} ({env.hostname or '-'})")
        c.print(f"  [dim]Python:[/dim]       {env.python_version or '-'}")
        ros_str = f"{env.ros_distro} ({env.ros_root or '-'})" if env.ros_distro else "None detected"
        c.print(f"  [dim]ROS 2:[/dim]        {ros_str}")
        if env.cuda_toolkit and env.cuda_driver_max:
            c.print(f"  [dim]CUDA:[/dim]         {env.cuda_toolkit} (toolkit: nvcc) | driver max: {env.cuda_driver_max}")
        elif env.cuda_toolkit:
            c.print(f"  [dim]CUDA:[/dim]         {env.cuda_toolkit} (toolkit: nvcc)")
        elif env.cuda_driver_max:
            c.print(f"  [dim]CUDA:[/dim]         driver max: {env.cuda_driver_max} (no nvcc toolkit)")
        else:
            c.print("  [dim]CUDA:[/dim]         None detected")
        if env.isaac_sim:
            sim_st = env.isaac_sim.get("status", "unknown")
            sim_dt = env.isaac_sim.get("detail", "")
            c.print(f"  [dim]Isaac Sim:[/dim]    {sim_st} ({sim_dt})")
        if env.isaac_lab:
            lab_st = env.isaac_lab.get("status", "unknown")
            lab_dt = env.isaac_lab.get("detail", "")
            c.print(f"  [dim]Isaac Lab:[/dim]    {lab_st} ({lab_dt})")
        c.print(f"  [dim]Docker:[/dim]       {'Available' if env.docker else 'Not installed'}")

    # Capabilities
    c.print("\n[bold]Capabilities[/bold]")
    decl_str = ", ".join(target.declared_capabilities) if target.declared_capabilities else "(none declared)"
    disc_str = ", ".join(insp.discovered_capabilities) if insp.discovered_capabilities else "(none detected)"
    c.print(f"  [dim]Declared:[/dim]   {decl_str}")
    c.print(f"  [dim]Discovered:[/dim] {disc_str}")

    # Mismatches
    c.print("\n[bold]Capability & Resource Compatibility[/bold]")
    if insp.mismatches:
        for m in insp.mismatches:
            c.print(f"  [bold red]✖[/bold red] {m}")
    else:
        c.print("  [bold green]✔[/bold green] [green]All declared capabilities and resources are compatible.[/green]")
    c.print("")


@app.command("check", help=_("target.check_help"))
def target_check(
    name: str = typer.Argument(..., help=_("target.arg.name")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    target = _require_target(name)
    insp = targets_core.discover_target(target, state.cfg())

    if output.wants_json(json_output):
        output.echo_json(insp.to_dict())
        if not insp.reachable or insp.mismatches:
            raise typer.Exit(1)
        return

    c = output.console()
    if not insp.reachable:
        output.fail(f"Target '{target.name}' is unreachable: {insp.error}")
        raise typer.Exit(1)

    if insp.status == "error":
        output.fail(f"Target '{target.name}' discovery error: {insp.error}")
        raise typer.Exit(1)

    timing = (
        f"local | probe: {insp.probe_duration_ms:.1f}ms"
        if target.transport == "local"
        else f"ping: {insp.ping_ms:.1f}ms | probe: {insp.probe_duration_ms:.1f}ms"
    )

    if insp.mismatches:
        c.print(f"\n[bold yellow]Target '{target.name}' reached ({timing}), but found mismatches:[/bold yellow]")
        for m in insp.mismatches:
            c.print(f"  [bold red]✖[/bold red] {m}")
        c.print("")
        raise typer.Exit(1)

    c.print(f"\n[bold green]✔ Target '{target.name}' is ONLINE ({timing}) and fully COMPATIBLE.[/bold green]")
    c.print(f"  Capabilities: {', '.join(insp.discovered_capabilities) or 'standard'}\n")
