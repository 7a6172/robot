"""`caasi exec` — run a command on a target, optionally inside its ROS environment.

This is the generic counterpart to `caasi ros`, which is limited to delegating the `ros2`
CLI. Anything else a remote workload needs — a diagnostic binary, a build tool, a probe
script, `nvidia-smi` — goes through this one path so that argument handling, environment
setup, timeouts and outcome classification are identical everywhere.

caasi is glue: the command runs as itself on the target. caasi contributes transport,
environment preparation and an honest report of what happened.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from .. import state
from ..core import execution
from ..core import defaults as defaults_core
from ..core import targets as targets_core
from ..i18n import _
from ..utils import output


def exec_command(
    command: list[str] = typer.Argument(
        ..., help=_("exec.arg.command")
    ),
    target_name: Optional[str] = typer.Option(
        None, "--target", "-t", help=_("exec.flag.target")
    ),
    cwd: Optional[str] = typer.Option(None, "--cwd", help=_("exec.flag.cwd")),
    env: Optional[list[str]] = typer.Option(
        None, "--env", "-e", help=_("exec.flag.env")
    ),
    ros: bool = typer.Option(False, "--ros", help=_("exec.flag.ros")),
    ros_setup: Optional[str] = typer.Option(
        None, "--ros-setup", help=_("exec.flag.ros_setup")
    ),
    overlay: Optional[str] = typer.Option(
        None, "--overlay", help=_("exec.flag.overlay")
    ),
    timeout: float = typer.Option(
        execution.DEFAULT_TIMEOUT, "--timeout", help=_("exec.flag.timeout")
    ),
    detach: bool = typer.Option(False, "--detach", "-d", help=_("exec.flag.detach")),
    name: Optional[str] = typer.Option(None, "--name", help=_("exec.flag.name")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    """Run CMD on a target and report exit status, output and outcome."""
    cfg = state.cfg()
    resolved = defaults_core.resolve_target_name(cfg, target_name)
    if target_name is None and resolved == defaults_core.LOCAL:
        # No flag and no choice: refuse rather than quietly running on this workstation.
        output.fail(_("exec.error.no_target"))
        raise typer.Exit(1)
    note = defaults_core.target_note(cfg, target_name)
    if note and not output.wants_json(json_output):
        output.echo(f"[dim]{note}[/dim]")

    target = targets_core.find_target(cfg, resolved)
    if target is None:
        output.fail(_("exec.error.unknown_target", name=resolved))

    env_map: dict[str, str] = {}
    for entry in env or []:
        if "=" not in entry:
            output.fail(_("exec.error.bad_env", entry=entry))
        # NOTE: do not unpack into '_' here -- it would shadow the i18n _() import
        # for the whole function (found by running this command, not by reading it).
        key, sep, value = entry.partition("=")
        if not key.strip():
            output.fail(_("exec.error.bad_env", entry=entry))
        env_map[key.strip()] = value

    # Resolve ROS setup from the target's own discovery rather than assuming a distro:
    # an unknown distro is reported, never guessed.
    setup_path = ros_setup
    if setup_path is None and (ros or overlay):
        try:
            setup_path = execution.ros_setup_for(target, config=cfg)
        except execution.RosDiscoveryError as err:
            output.fail(_("exec.error.ros_probe_failed").format(name=target.name, reason=err))
            raise typer.Exit(1)
        if setup_path is None:
            output.fail(_("exec.error.unknown_ros", name=target.name))

    request = execution.ExecRequest(
        argv=list(command),
        cwd=cwd,
        env=env_map,
        ros_setup=setup_path,
        overlay_setup=overlay,
        timeout=timeout,
    )
    if detach:
        # Managed mode: same target/env/argv resolution, handed to the existing run
        # lifecycle so `caasi run status|logs|stop` work on it. Not a second supervisor.
        from ..core import runs as runs_core

        try:
            record = runs_core.start_target_command(
                target, cfg,
                argv=list(command),
                work_dir=cwd,
                env=env_map,
                ros_setup=setup_path,
                overlay_setup=overlay,
                name=name or "command",
            )
        except (RuntimeError, ValueError) as err:
            output.fail(str(err))

        if output.wants_json(json_output):
            output.echo_json({
                "run_id": record.run_id,
                "target": record.target,
                "pid": record.pid,
                "pgid": record.pgid,
                "remote_run_dir": record.remote_run_dir,
            })
        else:
            typer.echo(f"started {record.run_id} on {record.target} (pid {record.pid})")
            typer.echo(f"  status: caasi run status {record.run_id}")
            typer.echo(f"  logs:   caasi run logs {record.run_id}")
            typer.echo(f"  stop:   caasi run stop {record.run_id}")
        raise typer.Exit(0)

    result = execution.run_on_target(target, request)

    if json_output:
        output.echo_json(result.summary())
    else:
        _render(result)

    # Mirror the outcome in the exit status. A transport or setup failure must never look
    # like a successful command, and a remote non-zero must survive unchanged.
    if result.outcome == execution.OUTCOME_OK:
        raise typer.Exit(0)
    if result.outcome in (execution.OUTCOME_NONZERO,):
        raise typer.Exit(result.returncode if result.returncode > 0 else 1)
    if result.outcome == execution.OUTCOME_TIMEOUT:
        raise typer.Exit(124)
    if result.outcome == execution.OUTCOME_NO_ROS2:
        raise typer.Exit(execution.EXIT_NO_ROS2)
    if result.outcome == execution.OUTCOME_TRANSPORT:
        # ssh's own convention: a transport failure is never a command failure.
        raise typer.Exit(execution.SSH_TRANSPORT_FAILURE)
    raise typer.Exit(execution.EXIT_SETUP_FAILED)


def _render(result: execution.ExecResult) -> None:
    if result.stdout:
        typer.echo(result.stdout, nl=not result.stdout.endswith("\n"))
    if result.stderr:
        typer.echo(result.stderr, err=True, nl=not result.stderr.endswith("\n"))

    label = {
        execution.OUTCOME_OK: _("exec.outcome.ok"),
        execution.OUTCOME_NONZERO: _("exec.outcome.nonzero"),
        execution.OUTCOME_TIMEOUT: _("exec.outcome.timeout"),
        execution.OUTCOME_TRANSPORT: _("exec.outcome.transport"),
        execution.OUTCOME_SETUP: _("exec.outcome.setup"),
        execution.OUTCOME_NO_ROS2: _("exec.outcome.no_ros2"),
    }.get(result.outcome, result.outcome)

    detail = f"exit {result.returncode}"
    if result.error:
        detail = f"{detail} — {result.error}"
    typer.echo(f"\n[{result.target}] {label} ({detail})", err=True)
