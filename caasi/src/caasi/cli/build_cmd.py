"""`caasi build` — resource-aware workspace build orchestrator."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

import typer

from .. import state
from ..core import build as build_core
from ..core import defaults as defaults_core
from ..core import targets as targets_core
from ..i18n import _
from ..utils import output


def build_command(
    packages_select: Optional[List[str]] = typer.Option(
        None, "--packages-select", "-p", help=_("build.flag.packages_select")
    ),
    packages_up_to: Optional[List[str]] = typer.Option(
        None, "--packages-up-to", "-u", help=_("build.flag.packages_up_to")
    ),
    jobs: Optional[int] = typer.Option(
        None, "--jobs", "-j", help=_("build.flag.jobs")
    ),
    symlink_install: bool = typer.Option(
        True, "--symlink-install/--no-symlink-install", help=_("build.flag.symlink_install")
    ),
    cmake_args: Optional[List[str]] = typer.Option(
        None, "--cmake-args", help=_("build.flag.cmake_args")
    ),
    clean: bool = typer.Option(
        False, "--clean", help=_("build.flag.clean")
    ),
    continue_on_error: bool = typer.Option(
        False, "--continue-on-error", help=_("build.flag.continue_on_error")
    ),
    target: Optional[str] = typer.Option(
        None, "--target", "-t", help=_("build.flag.target")
    ),
    json_output: bool = typer.Option(
        False, "--json", help=_("flag.json")
    ),
) -> None:
    """Resource-aware workspace build delegating to colcon."""
    root = build_core.find_build_root()

    target_name = defaults_core.resolve_target_name(state.cfg(), target)
    note = defaults_core.target_note(state.cfg(), target)
    if note and not output.wants_json(json_output):
        output.echo(f"[dim]{note}[/dim]")

    target_obj = targets_core.find_target(state.cfg(), target_name)
    if target_obj is None:
        valid = ", ".join(t.name for t in targets_core.list_targets(state.cfg())) or "-"
        output.fail(_("target.not_found", query=target_name, valid=valid))
        raise typer.Exit(1)

    workers = jobs if jobs is not None and jobs > 0 else build_core.default_parallel_workers()

    if not output.wants_json(json_output):
        if target_obj.name == "local":
            output.echo(
                f"[bold]{_('build.starting', root=str(root), workers=workers)}[/bold]"
            )
        else:
            output.echo(
                f"[bold cyan]Target Build:[/bold cyan] [bold]{target_obj.name}[/bold] ({target_obj.transport})"
            )

    def on_line(line: str) -> None:
        if not output.wants_json(json_output):
            sys.stdout.write(line)
            sys.stdout.flush()

    try:
        res = build_core.execute_target_build(
            target=target_obj,
            project_root=root,
            config=state.cfg(),
            packages_select=packages_select,
            packages_up_to=packages_up_to,
            jobs=jobs,
            symlink_install=symlink_install,
            cmake_args=cmake_args,
            clean=clean,
            continue_on_error=continue_on_error,
            line_callback=on_line if not output.wants_json(json_output) else None,
        )
    except build_core.BuildError as exc:
        output.fail(str(exc))
        raise typer.Exit(1)

    if output.wants_json(json_output):
        output.echo_json(res.to_dict())
    else:
        if res.ok:
            output.echo(
                f"[green]{_('build.success', duration=round(res.duration, 2))}[/green]"
            )
            if res.target_name != "local":
                output.echo(
                    f"[dim]{_('build.target.artifacts', target=res.target_name, dest=str(res.root))}[/dim]"
                )
        else:
            output.echo(
                f"[red]{_('build.failed', code=res.returncode)}[/red]"
            )
            hint = res.dependency_hint()
            if hint:
                output.echo(f"[yellow]{hint}[/yellow]")

    raise typer.Exit(res.returncode)
