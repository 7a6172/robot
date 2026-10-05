"""`caasi target` (and alias `caasi node`) — execution target inspection and discovery.

Supports local workstation, remote robots, edge devices, and compute servers
in a capability- and resource-driven manner.
"""

from __future__ import annotations

from typing import Optional

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


@app.command("runtime", help=_("target.runtime_help"))
def target_runtime(
    target: str = typer.Argument(..., help=_("target.arg.name")),
    runtime: Optional[str] = typer.Option(
        None, "--runtime", "-r", help=_("target.flag.runtime")
    ),
    match: Optional[str] = typer.Option(
        None, "--match", "-m", help=_("target.flag.match")
    ),
    unit: Optional[str] = typer.Option(
        None, "--unit", "-u", help=_("target.flag.unit")
    ),
    lines: int = typer.Option(50, "--lines", "-n", help=_("target.flag.lines")),
    system_scope: bool = typer.Option(
        False, "--system", help=_("target.flag.system_scope")
    ),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    """Observe the runtimes a target exposes, using their own native interfaces.

    caasi asks the target's own tooling and presents the answer consistently; it
    never implements a process manager, container runtime or init system. Omit
    --runtime to see every detected runtime.
    """
    from ..core import runtimes as runtimes_core

    tgt = _require_target(target)
    cfg = state.cfg()

    if runtime is not None:
        if runtime not in runtimes_core.ALL_RUNTIMES:
            output.fail(_("target.runtime_unknown", runtime=runtime,
                          valid=", ".join(runtimes_core.ALL_RUNTIMES)))
            raise typer.Exit(1)
        kwargs: dict = {}
        if runtime == runtimes_core.RUNTIME_PROCESS:
            kwargs = {"match": match}
        elif runtime == runtimes_core.RUNTIME_SYSTEMD:
            kwargs = {"unit": unit, "user": not system_scope}
        try:
            report = runtimes_core.query_runtime(tgt, runtime, **kwargs)
        except runtimes_core.RuntimeError_ as err:
            output.fail(str(err))
            raise typer.Exit(1)
        reports = [report]
        availability = None
    else:
        availability, reports = runtimes_core.query_all(tgt)

    if output.wants_json(json_output):
        payload: dict = {
            "target": tgt.name,
            "transport": tgt.transport,
            "reports": [r.to_dict() for r in reports],
        }
        if availability is not None:
            payload["availability"] = {k: v.to_dict() for k, v in availability.items()}
        output.echo_json(payload)
        return

    c = output.console()
    c.print(f"\n[bold cyan]{_('target.runtime_title', target=tgt.name)}[/bold cyan]")
    c.print(f"  [dim]{_('target.row.transport')}:[/dim] {tgt.transport}\n")

    for report in reports:
        if not report.available:
            c.print(f"  [yellow]○[/yellow] [bold]{report.runtime}[/bold] "
                    f"[dim]- {report.error or 'unavailable'}[/dim]")
            continue
        c.print(f"  [green]●[/green] [bold]{report.runtime}[/bold] "
                f"[dim]({report.tool or 'native'})[/dim]")
        if report.error:
            c.print(f"      [red]{report.error}[/red]")
            continue
        if report.detail.get("output"):
            for line in str(report.detail["output"]).splitlines()[:lines]:
                c.print(f"      {line}", markup=False)
            continue
        if not report.items:
            c.print(f"      [dim]{_('target.runtime_empty')}[/dim]")
            continue
        for item in report.items[:lines]:
            state_txt = f" [dim]{item.state}[/dim]" if item.state else ""
            extra = ""
            if report.runtime == runtimes_core.RUNTIME_PROCESS:
                extra = f" [dim]pid={item.detail.get('pid')} pgid={item.detail.get('pgid')}[/dim]"
            elif report.runtime == runtimes_core.RUNTIME_CONTAINER:
                extra = f" [dim]{item.detail.get('image')} ({item.detail.get('status')})[/dim]"
            c.print(f"      {item.name}{state_txt}{extra}", markup=False)
        if len(report.items) > lines:
            c.print(f"      [dim]… {len(report.items) - lines} more[/dim]")
    c.print("")


@app.command("select", help=_("target.select_help"))
def target_select(
    workload_name: Optional[str] = typer.Argument(None, help=_("target.arg.workload")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    """Report whether each target can satisfy the project's requirements.

    Advisory and read-only: it prints a verdict and the reason behind it for every
    configured target, and it chooses nothing. Execution still names a target
    explicitly. Verdicts reuse the Check Contract ladder, so an out-of-range
    version is reported as a warning rather than asserted incompatible, and a fact
    a target does not expose is reported as unmeasured rather than guessed.
    """
    from ..core import project as projects
    from ..core import selection as selection_core
    from ..core import workload as workload_core

    root = projects.find_project_root()
    if root is None:
        output.fail(_("project.not_found"))
        raise typer.Exit(1)

    # Resolve requirements (project, optionally extended by a workload).
    from ..core import manifest as manifests

    manifest = manifests.read(root)
    requirements = dict(manifest.requires or {})
    sources = ["caasi.yaml"] if requirements else []

    workload = None
    if workload_name:
        workload = workload_core.find_workload(root, workload_name)
        if workload is None:
            known = ", ".join(w.name for w in workload_core.list_workloads(root)) or "-"
            output.fail(_("target.select.workload_not_found", query=workload_name, valid=known))
            raise typer.Exit(1)
        sources.append(f"workload:{workload.name}")

    requirements = workload_core.combined_requirements(requirements, workload)
    tested = list(manifest.tested or [])

    if not requirements:
        output.fail(_("target.select.no_requirements"))
        raise typer.Exit(1)

    config = state.cfg()
    targets = targets_core.list_targets(config)
    inspected = {}
    for target in targets:
        try:
            inspected[target.name] = targets_core.discover_target(target, config)
        except Exception as exc:  # noqa: BLE001 - an unreachable target is a verdict
            inspected[target.name] = None

    # Honour `check.strict` exactly as `caasi check` does. Selection and check must
    # agree about the same requirement; before the F1 consolidation this was
    # hardcoded, so the two commands could report different verdicts (and exit
    # codes) for one project.
    reports = selection_core.select_all(
        targets, requirements, inspected, tested,
        strict=bool(config.get("check.strict", False)),
    )

    if output.wants_json(json_output):
        output.echo_json({
            "project": manifest.name or root.name,
            "sources": sources,
            "requirements": requirements,
            "targets": [r.to_dict() for r in reports],
        })
    else:
        output.echo(f"[bold]{_('target.select.title')}[/bold]")
        output.echo(f"  {_('target.select.sources')}: {', '.join(sources)}")
        req_line = ", ".join(
            f"{name}{_version_hint(requirements[name])}" for name in sorted(requirements)
        )
        output.echo(f"  {_('target.select.requires')}: {req_line}")
        output.echo("")

        table = Table(header_style="bold", **output.table_styles())
        table.add_column(_("target.col.name"))
        table.add_column(_("target.select.col.status"))
        table.add_column(_("target.select.col.why"))
        for report in reports:
            if not report.reachable:
                marker = "[red]✖[/red]"
                reason = report.error or _("target.select.unreachable")
            elif report.status == "incompatible":
                marker = "[red]✖[/red]"
                reason = _first_problem(report)
            elif report.status == "warning":
                marker = "[yellow]~[/yellow]"
                reason = _first_problem(report) or report.summary
            else:
                marker = "[green]●[/green]"
                reason = report.summary
            table.add_row(report.target, f"{marker} {report.status}", reason)
        output.echo(table)

        for report in reports:
            if len(report.verdicts) <= 1:
                continue
            output.echo(f"[bold]{report.target}[/bold]")
            for verdict in report.verdicts:
                style = {"compatible": "green", "missing": "red"}.get(verdict.verdict, "yellow")
                detail = verdict.note or (
                    f"{verdict.required} -> {verdict.detected}" if verdict.required else ""
                )
                output.echo(
                    f"  [{style}]{verdict.verdict}[/{style}] {verdict.name} {detail}".rstrip()
                )
            output.echo("")

        output.echo(f"[dim]{_('target.select.advisory')}[/dim]")

    # Exit policy mirrors the Check Contract: incompatibility is signalled, and
    # warnings are not, so this composes with existing tooling.
    if any(r.status == "incompatible" for r in reports):
        raise typer.Exit(3)


def _version_hint(entry) -> str:
    if isinstance(entry, dict):
        value = entry.get("version")
        return f" {value}" if value else ""
    return f" {entry}" if entry else ""


def _first_problem(report) -> str:
    for verdict in report.verdicts:
        if verdict.verdict in ("missing", "untested") and verdict.note:
            return f"{verdict.name}: {verdict.note}"
    return report.summary
