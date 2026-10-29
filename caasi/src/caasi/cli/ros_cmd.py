"""`caasi ros` — orchestrate ROS 2 by delegating to the real ros2 CLI.

The CLI never imports rclpy; every operation is a subprocess call into the
discovered distro's ros2 binary. Long-lived commands (launch, topic echo)
become tracked runs.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import typer

from .. import state
from ..core import deploy as deploy_core
from ..core import manifest as manifests
from ..core import project as projects
from ..core import ros as ros_core
from ..core import runs
from ..core import defaults as defaults_core
from ..core import targets as targets_core
from ..i18n import _
from ..utils import output

app = typer.Typer(no_args_is_help=True)

_EXTRA_SETTINGS = {"allow_extra_args": True, "ignore_unknown_options": True}

LIST_KINDS = {"topics": "topic", "nodes": "node", "services": "service", "actions": "action"}

# A remote query is bounded by the target's SSH budget plus the ros2 call itself.
SERVICE_CALL_TIMEOUT = 60.0
REMOTE_QUERY_TIMEOUT = 60.0


def _binary_or_fail() -> str:
    binary = ros_core.find_ros2_binary()
    if not binary:
        output.fail(_("native.no_ros2"))
        raise typer.Exit(1)  # unreachable, keeps type-checkers happy
    return binary


def _resolve_query_target(name: Optional[str]):
    """Resolve a ``--target`` option into a Target, or None for local.

    Fails cleanly (exit 1) on an unknown target so a typo cannot silently fall
    back to querying the workstation instead of the intended machine.
    """
    if not name:
        # no --target: the chosen target applies, if it is not the workstation itself
        resolved = defaults_core.resolve_target_name(state.cfg())
        if resolved == defaults_core.LOCAL:
            return None
        name = resolved
    target = targets_core.find_target(state.cfg(), name)
    if target is None:
        valid = ", ".join(t.name for t in targets_core.list_targets(state.cfg())) or "-"
        output.fail(_("target.not_found", query=name, valid=valid))
        raise typer.Exit(1)
    return target


def _remote_setups(target) -> tuple[str | None, str | None]:
    """Target-side underlay and optional project overlay paths to source.

    The overlay is derived from the deployment layout caasi itself creates, so a
    remote query answers with the same environment a remote run would use.
    """
    inspection = targets_core.discover_target(target, state.cfg())
    if not inspection.reachable:
        return None, None
    env = inspection.environment
    distro = (env.ros_distro if env else None) or "jazzy"
    ros_setup = f"/opt/ros/{distro}/setup.bash"

    overlay: str | None = None
    try:
        root = projects.find_project_root()
        if root is not None:
            manifest = manifests.read(root)
            dest = deploy_core.resolve_deployment_destination(
                target, manifest.name or root.name
            )
            overlay = f"{dest.rstrip('/')}/install/setup.bash"
    except Exception:
        overlay = None
    return ros_setup, overlay


def _query(target, args: list[str], timeout: float = REMOTE_QUERY_TIMEOUT,
           domain: Optional[int] = None):
    """Run a ros2 query locally or on a target, returning a ShellResult.

    ``domain`` selects ROS_DOMAIN_ID. It matters because a runtime may live on a
    non-default domain, in which case querying the default returns an empty graph
    rather than an error.
    """
    if target is None:
        if domain is None:
            return ros_core.run_ros2(args, timeout=timeout)
        # A domain was requested locally: reuse the same injection path. A local
        # Target is used so `remote_ros2` takes its non-SSH branch.
        local = targets_core.Target(name="local", transport="local")
        return ros_core.remote_ros2(local, args, timeout=timeout, domain_id=domain)
    ros_setup, overlay = _remote_setups(target)
    return ros_core.remote_ros2(
        target, args, timeout=timeout, ros_setup=ros_setup, overlay_setup=overlay,
        domain_id=domain,
    )


def _query_ok(target, args: list[str], timeout: float = REMOTE_QUERY_TIMEOUT) -> bool:
    """True when the ros2 CLI is available for the requested scope.

    Local: the ros2 binary must exist. Remote: we cannot know without asking, so
    the call itself decides (a missing ros2 exits 127).
    """
    if target is None:
        return ros_core.find_ros2_binary() is not None
    return True


def _report_query_failure(target, result, subject: str) -> None:
    """Explain why a remote query failed, distinguishing transport from ros2."""
    if target is None:
        return
    text = (result.stderr or "").strip()
    # A failed SSH transport never produced ros2 output, and ssh itself exits
    # with 255. Both are transport failures, not "the query returned nothing".
    ssh_transport_failure = (
        result.returncode == -1
        or result.returncode == 255
        or (not result.stdout and "connect" in text.lower())
    )
    if ssh_transport_failure:
        output.fail(
            _("ros.target_unreachable", target=target.name, detail=text or "timeout")
        )
    elif result.returncode == 127 or "CAASI_NO_ROS2" in text:
        output.fail(_("ros.target_no_ros2", target=target.name))
    elif "Unable to find" in text or "does not exist" in text:
        # ros2 ran on the target and reported no such object: a query result,
        # not a transport or capability problem.
        output.fail(_("ros.not_found_on_target", target=target.name, subject=subject))
    else:
        output.fail(_("ros.query_failed", target=target.name, subject=subject))


def _print_result(result) -> int:
    """Echo a ShellResult's output and return its exit code."""
    if result.stdout:
        output.echo(result.stdout.rstrip(), markup=False)
    if result.stderr:
        output.echo(result.stderr.rstrip(), markup=False)
    return result.returncode if result.returncode >= 0 else 1


@app.command("status", help=_("ros.status_help"))
def ros_status(
    target_name: Optional[str] = typer.Option(
        None, "--target", "-t", help=_("ros.flag.target")
    ),
        domain: Optional[int] = typer.Option(
        None, "--domain", "-d", help=_("ros.flag.domain")
    ),
json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    target = _resolve_query_target(target_name)
    if target is not None:
        env = ros_core.remote_ros_environment(target)
        if "error" in env:
            # Unreachable is an error (exit 1), not an empty result.
            output.fail(
                _("ros.target_unreachable", target=target.name, detail=str(env["error"]))
            )
            raise typer.Exit(1)
        payload = {
            "target": target.name,
            "available": bool(env.get("available")),
            "distro": env.get("distro"),
            "root": env.get("root"),
            "binary": env.get("binary"),
            "rmw": env.get("rmw"),
        }
        if payload["available"]:
            payload["topics"] = len(
                ros_core.remote_ros2_lines(target, ["topic", "list"],
                                           ros_setup=f"/opt/ros/{env['distro']}/setup.bash"
                                           if env.get("distro") else None)
            )
        if output.wants_json(json_output):
            output.echo_json(payload)
            return
        output.echo(f"[bold]{_('ros.title')}[/bold] [dim]({target.name})[/dim]")
        for label, value in (
            (_("ros.row.distro"), payload["distro"] or _("ros.missing")),
            (_("ros.row.root"), payload["root"] or _("ros.missing")),
            (_("ros.row.binary"), payload["binary"] or _("ros.missing")),
            (_("ros.row.rmw"), payload["rmw"] or "(default)"),
            (
                _("ros.row.topics"),
                str(payload["topics"]) if "topics" in payload else _("ros.missing"),
            ),
        ):
            output.echo(f"  {label:<10} {value}")
        if not payload["available"]:
            output.echo(f"  [yellow]{_('ros.target_no_ros2', target=target.name)}[/yellow]")
        return

    distro, root = ros_core.find_distro()
    binary = ros_core.find_ros2_binary()
    rmw = os.environ.get("RMW_IMPLEMENTATION")
    topics = ros_core.ros2_lines(["topic", "list"]) if binary else []
    payload = {
        "available": bool(binary),
        "distro": distro,
        "root": str(root) if root else None,
        "binary": binary,
        "rmw": rmw,
        "topics": len(topics),
    }
    if output.wants_json(json_output):
        output.echo_json(payload)
        return
    output.echo(f"[bold]{_('ros.title')}[/bold]")
    for label, value in (
        (_("ros.row.distro"), distro or _("ros.missing")),
        (_("ros.row.root"), str(root) if root else _("ros.missing")),
        (_("ros.row.binary"), binary or _("ros.missing")),
        (_("ros.row.rmw"), rmw or "(default)"),
        (_("ros.row.topics"), str(len(topics)) if binary else _("ros.missing")),
    ):
        output.echo(f"  {label:<10} {value}")
    if not binary:
        output.echo(f"  [yellow]{_('native.no_ros2')}[/yellow]")


@app.command("doctor", help=_("ros.doctor_help"))
def ros_doctor(
    target_name: Optional[str] = typer.Option(
        None, "--target", "-t", help=_("ros.flag.target")
    ),
        domain: Optional[int] = typer.Option(
        None, "--domain", "-d", help=_("ros.flag.domain")
    ),
json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    target = _resolve_query_target(target_name)
    if target is None and not ros_core.find_ros2_binary():
        output.fail(_("native.no_ros2"))
        return
    result = _query(target, ["doctor"], timeout=90.0, domain=domain)
    if target is not None and not result.ok and not result.stdout:
        _report_query_failure(target, result, "doctor")
        return
    text = "\n".join(part for part in (result.stdout, result.stderr) if part)
    if output.wants_json(json_output):
        payload = {"returncode": result.returncode, "output": text}
        if target is not None:
            payload["target"] = target.name
        output.echo_json(payload)
        raise typer.Exit(result.returncode if result.returncode >= 0 else 1)
    code = _print_result(result)
    raise typer.Exit(code)


@app.command("list", help=_("ros.list_help"))
def ros_list(
    kind: str = typer.Argument(..., help=_("ros.arg.kind")),
    target_name: Optional[str] = typer.Option(
        None, "--target", "-t", help=_("ros.flag.target")
    ),
        domain: Optional[int] = typer.Option(
        None, "--domain", "-d", help=_("ros.flag.domain")
    ),
json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    sub = LIST_KINDS.get(kind)
    if sub is None:
        output.fail(_("ros.bad_kind", kind=kind, valid=", ".join(LIST_KINDS)))
        return
    target = _resolve_query_target(target_name)
    if target is None:
        _binary_or_fail()
    result = _query(target, [sub, "list"], domain=domain)
    if target is not None and not result.ok:
        _report_query_failure(target, result, kind)
        return
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if output.wants_json(json_output):
        output.echo_json(lines)
        return
    if not lines:
        output.echo(f"[yellow]{_('ros.empty', kind=kind)}[/yellow]")
        return
    output.echo(f"[bold]{_('ros.list_title', kind=kind)}[/bold]")
    for line in lines:
        output.echo(f"  {line}", markup=False)


@app.command("launch", help=_("ros.launch_help"), context_settings=_EXTRA_SETTINGS)
def ros_launch(
    ctx: typer.Context,
    target: str = typer.Argument(..., help=_("ros.arg.launch_file")),
    package: Optional[str] = typer.Option(None, "--package", "-p", help=_("ros.flag.package")),
    name: Optional[str] = typer.Option(None, "--name", help=_("ros.flag.name")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("ros.flag.dry_run")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    binary = _binary_or_fail()
    if package is None and os.sep in target and not Path(target).is_file():
        output.fail(_("ros.launch_missing", path=target))
        return
    command = [binary, "launch", *([package] if package else []), target, *[str(a) for a in ctx.args]]
    run_name = name or Path(target).stem

    if dry_run:
        output.echo(f"[bold]{_('replay.dry_title')}[/bold]")
        output.echo(f"  command: {' '.join(command)}")
        return

    record = runs.start_run(
        state.cfg(), name=run_name, command=command, backend="ros", kind="ros",
        extra={"launch": target, "package": package},
    )
    if output.wants_json(json_output):
        output.echo_json(record.to_dict())
        return
    output.echo(f"[green]{_('ros.started', id=record.run_id)}[/green]")
    output.echo(f"  [dim]{_('sim.run.watch', id=record.run_id)}[/dim]")


@app.command("topic", help=_("ros.topic_help"), context_settings=_EXTRA_SETTINGS)
def ros_topic(
    ctx: typer.Context,
    name: str = typer.Argument(..., help=_("ros.arg.topic")),
    echo_stream: bool = typer.Option(False, "--echo", help=_("ros.flag.echo")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("ros.flag.dry_run")),
    target_name: Optional[str] = typer.Option(
        None, "--target", "-t", help=_("ros.flag.target")
    ),
        domain: Optional[int] = typer.Option(
        None, "--domain", "-d", help=_("ros.flag.domain")
    ),
json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    target = _resolve_query_target(target_name)
    if target is not None and echo_stream:
        # An unbounded stream is the execution lifecycle, not a query, and stays out of scope here.
        # A single message is a query: it finishes, so it is answered like every other one.
        if "--once" in [str(a) for a in ctx.args]:
            result = _query(target, ["topic", "echo", "--once", name,
                                     *[str(a) for a in ctx.args]], domain=domain)
            if not result.ok:
                if result.returncode == -1:
                    output.fail(_("ros.no_message", name=name, target=target.name))
                    return
                # The topic tool says precisely why (unknown type, no publisher); pass that on
                # rather than replacing it with a generic failure.
                detail = (result.stderr or "").strip().splitlines()
                if detail:
                    output.fail(detail[-1])
                else:
                    _report_query_failure(target, result, name)
                return
            if output.wants_json(json_output):
                output.echo_json({"topic": name, "target": target.name,
                                  "message": result.stdout.strip()})
                return
            output.echo(result.stdout.rstrip(), markup=False)
            return
        output.fail(_("ros.remote_echo_unsupported", target=target.name))
        return
    binary = _binary_or_fail() if target is None else None
    if echo_stream:
        command = [binary, "topic", "echo", name, *[str(a) for a in ctx.args]]
        if dry_run:
            output.echo(f"[bold]{_('replay.dry_title')}[/bold]")
            output.echo(f"  command: {' '.join(command)}")
            return
        record = runs.start_run(
            state.cfg(), name=f"echo-{name.strip('/').replace('/', '-')}",
            command=command, backend="ros", kind="ros",
            extra={"topic": name, "echo": True},
        )
        if output.wants_json(json_output):
            output.echo_json(record.to_dict())
            return
        output.echo(f"[green]{_('ros.started', id=record.run_id)}[/green]")
        output.echo(f"  [dim]{_('sim.run.watch', id=record.run_id)}[/dim]")
        return
    result = _query(target, ["topic", "info", name], domain=domain)
    if not result.ok:
        if target is not None:
            _report_query_failure(target, result, name)
        else:
            output.fail(_("ros.no_topic", name=name))
        return
    if output.wants_json(json_output):
        payload = {"topic": name, "info": result.stdout.strip()}
        if target is not None:
            payload["target"] = target.name
        output.echo_json(payload)
        return
    output.echo(result.stdout.rstrip(), markup=False)


@app.command("node", help=_("ros.node_help"))
def ros_node(
    name: str = typer.Argument(..., help=_("ros.arg.node")),
    target_name: Optional[str] = typer.Option(
        None, "--target", "-t", help=_("ros.flag.target")
    ),
        domain: Optional[int] = typer.Option(
        None, "--domain", "-d", help=_("ros.flag.domain")
    ),
json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    target = _resolve_query_target(target_name)
    if target is None:
        _binary_or_fail()
    result = _query(target, ["node", "info", name], domain=domain)
    if not result.ok:
        if target is not None:
            _report_query_failure(target, result, name)
        else:
            output.fail(_("ros.no_node", name=name))
        return
    if output.wants_json(json_output):
        payload = {"node": name, "info": result.stdout.strip()}
        if target is not None:
            payload["target"] = target.name
        output.echo_json(payload)
        return
    output.echo(result.stdout.rstrip(), markup=False)


service_app = typer.Typer(no_args_is_help=True)
app.add_typer(service_app, name="service", help=_("ros.service.help"))


@service_app.command("list", help=_("ros.service.list_help"))
def service_list(
    target_name: Optional[str] = typer.Option(
        None, "--target", "-t", help=_("ros.flag.target")
    ),
        domain: Optional[int] = typer.Option(
        None, "--domain", "-d", help=_("ros.flag.domain")
    ),
json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    target = _resolve_query_target(target_name)
    if target is None:
        _binary_or_fail()
    result = _query(target, ["service", "list"], domain=domain)
    if target is not None and not result.ok:
        _report_query_failure(target, result, "services")
        return
    lines = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
    if output.wants_json(json_output):
        output.echo_json(lines)
        return
    if not lines:
        output.echo(f"[yellow]{_('ros.empty', kind='services')}[/yellow]")
        return
    output.echo(f"[bold]{_('ros.list_title', kind='services')}[/bold]")
    for line in lines:
        output.echo(f"  {line}", markup=False)


@service_app.command("info", help=_("ros.service.info_help"))
def service_info(
    name: str = typer.Argument(..., help=_("ros.arg.service")),
    target_name: Optional[str] = typer.Option(
        None, "--target", "-t", help=_("ros.flag.target")
    ),
        domain: Optional[int] = typer.Option(
        None, "--domain", "-d", help=_("ros.flag.domain")
    ),
json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    target = _resolve_query_target(target_name)
    if target is None:
        _binary_or_fail()
    result = _query(target, ["service", "info", name], domain=domain)
    if not result.ok:
        if target is not None:
            _report_query_failure(target, result, name)
        else:
            output.fail(_("ros.no_service", name=name))
        return
    if output.wants_json(json_output):
        payload = {"service": name, "info": result.stdout.strip()}
        if target is not None:
            payload["target"] = target.name
        output.echo_json(payload)
        return
    output.echo(result.stdout.rstrip(), markup=False)


@service_app.command("call", help=_("ros.service.call_help"), context_settings=_EXTRA_SETTINGS)
def service_call(
    ctx: typer.Context,
    name: str = typer.Argument(..., help=_("ros.arg.service")),
    service_type: str = typer.Argument(..., help=_("ros.arg.service_type")),
    target_name: Optional[str] = typer.Option(
        None, "--target", "-t", help=_("ros.flag.target")
    ),
    domain: Optional[int] = typer.Option(
        None, "--domain", "-d", help=_("ros.flag.domain")
    ),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    # Callable on a target like every other query: starting a mission on the robot is the commonest
    # reason to call a service at all, and it should not need a shell wrapper to reach it.
    target = _resolve_query_target(target_name)
    if target is None:
        _binary_or_fail()
    result = _query(
        target,
        ["service", "call", name, service_type, *[str(a) for a in ctx.args]],
        timeout=SERVICE_CALL_TIMEOUT,
        domain=domain,
    )
    if target is not None and not result.ok:
        if result.returncode == -1:
            # A call that produced no reply is not an unreachable robot: say what actually happened.
            output.fail(
                _("ros.service.no_response", name=name, target=target.name,
                  seconds=int(SERVICE_CALL_TIMEOUT))
            )
            return
        _report_query_failure(target, result, name)
        return
    if output.wants_json(json_output):
        output.echo_json(
            {
                "service": name,
                "type": service_type,
                "returncode": result.returncode,
                "stdout": result.stdout.strip(),
            }
        )
        raise typer.Exit(result.returncode if result.returncode >= 0 else 1)
    raise typer.Exit(_print_result(result))


@app.command("graph", help=_("ros.graph_help"))
def ros_graph(
    target_name: Optional[str] = typer.Option(
        None, "--target", "-t", help=_("ros.flag.target")
    ),
        domain: Optional[int] = typer.Option(
        None, "--domain", "-d", help=_("ros.flag.domain")
    ),
json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    target = _resolve_query_target(target_name)
    if target is None:
        _binary_or_fail()
    nodes_result = _query(target, ["node", "list"], domain=domain)
    if target is not None and not nodes_result.ok:
        _report_query_failure(target, nodes_result, "graph")
        return
    nodes = [ln.strip() for ln in nodes_result.stdout.splitlines() if ln.strip()]
    topics_result = _query(target, ["topic", "list"], domain=domain)
    topics = [ln.strip() for ln in topics_result.stdout.splitlines() if ln.strip()]
    if output.wants_json(json_output):
        payload = {"nodes": nodes, "topics": topics}
        if target is not None:
            payload["target"] = target.name
        output.echo_json(payload)
        return
    title = _("ros.graph_title")
    if target is not None:
        output.echo(f"[bold]{title}[/bold] [dim]({target.name})[/dim]")
    else:
        output.echo(f"[bold]{title}[/bold]")
    output.echo(f"  [dim]{_('ros.col.node')} ({len(nodes)})[/dim]")
    for line in nodes:
        output.echo(f"    {line}", markup=False)
    output.echo(f"  [dim]{_('ros.col.topic')} ({len(topics)})[/dim]")
    for line in topics:
        output.echo(f"    {line}", markup=False)
