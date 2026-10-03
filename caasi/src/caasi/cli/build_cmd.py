"""`caasi build` — resource-aware workspace build orchestrator."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

import typer

from .. import state
from ..core import build as build_core
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
    json_output: bool = typer.Option(
        False, "--json", help=_("flag.json")
    ),
) -> None:
    """Resource-aware workspace build delegating to colcon."""
    root = build_core.find_build_root()
    workers = jobs if jobs is not None and jobs > 0 else build_core.default_parallel_workers()

    if not output.wants_json(json_output):
        output.echo(
            f"[bold]{_('build.starting', root=str(root), workers=workers)}[/bold]"
        )

    def on_line(line: str) -> None:
        if not output.wants_json(json_output):
            sys.stdout.write(line)
            sys.stdout.flush()

    try:
        res = build_core.execute_build(
            root=root,
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
        else:
            output.echo(
                f"[red]{_('build.failed', code=res.returncode)}[/red]"
            )

    raise typer.Exit(res.returncode)
