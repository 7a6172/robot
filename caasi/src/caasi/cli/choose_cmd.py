"""``caasi choose`` — fix the machine and the project for the commands that follow.

The choice is stored in the ``defaults`` configuration section, which is where "what a command does
when it is not told otherwise" already lives. ``--session`` prints shell exports instead, for a
choice that should not outlive the terminal.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.table import Table

from .. import state
from ..i18n import _
from ..utils import output
from ..core import project as project_core
from ..core import defaults as defaults_core
from ..core import targets as targets_core


def _config_path() -> Path:
    """Where a choice is written: the global config, or CAASI_CONFIG when that is what is in use.

    A choice is a preference of this account, so the global file is the natural home. When
    CAASI_CONFIG points somewhere else (CI, an experiment), writing the global file would silently
    land somewhere the caller is not looking, so that path wins.
    """
    from ..core.config import writable_config_path

    return writable_config_path()


def _save(config, dotted: str, value: str) -> None:
    config.set(dotted, value)
    config.save(_config_path())


def _clear(config, dotted: str) -> None:
    node = config.data
    parts = dotted.split(".")
    for part in parts[:-1]:
        node = node.get(part) if isinstance(node, dict) else None
        if node is None:
            return
    if isinstance(node, dict):
        node.pop(parts[-1], None)
    config.save(_config_path())


def _show(json_output: bool) -> None:
    cfg = state.cfg()
    info = defaults_core.describe(cfg)
    if output.wants_json(json_output):
        output.echo_json(info)
        return

    if info.get("machine_notice"):
        output.echo(f"[dim]{info['machine_notice']}[/dim]")

    table = Table(title=_("choose.title"), header_style="bold", **output.table_styles())
    table.add_column(_("choose.col.what"))
    table.add_column(_("choose.col.value"))
    table.add_column(_("choose.col.from"))
    table.add_row(_("choose.row.target"), info["target"], info["target_origin"])

    for kind, label in (("robot", _("choose.row.robot")), ("project", _("choose.row.project"))):
        entry = info.get(kind)
        if not entry:
            table.add_row(label, _("choose.none"), _("choose.row.unset"))
            continue
        where = ", ".join(f"{loc['machine']}:{loc['path']}" for loc in entry["found"]) or _("choose.none")
        table.add_row(label, entry["name"], where)

    for role, name in (info.get("role_targets") or {}).items():
        table.add_row(_("choose.row.role", role=role), name, f"defaults.targets.{role}")

    if info.get("cwd_project"):
        table.add_row(_("choose.row.cwd"), info["cwd_project"], _("choose.row.working_directory"))
    output.console().print(table)
    output.echo(f"[dim]{_('choose.hint')}[/dim]")


def _choose_target(name: Optional[str], session: bool, clear: bool, role: Optional[str] = None) -> None:
    cfg = state.cfg()
    if clear:
        if session:
            output.echo(f"unset {defaults_core.role_env(role) if role else defaults_core.ENV_TARGET}")
            return
        _clear(cfg, f"defaults.targets.{role}" if role else "defaults.target")
        output.echo(_("choose.target.cleared"))
        return

    target = targets_core.find_target(cfg, name)
    if target is None:
        valid = ", ".join(t.name for t in targets_core.list_targets(cfg)) or "-"
        output.fail(_("choose.unknown_target", query=name, valid=valid))
        raise typer.Exit(1)

    if role:
        # A role is a claim about what the machine can do; a target that does not carry the tag is
        # still allowed (tags can be added later), but the mismatch is said out loud.
        if role not in (target.tags or []) and target.name != defaults_core.LOCAL:
            output.echo(f"[yellow]{_('choose.role.no_tag', role=role, target=target.name)}[/yellow]")

    if session:
        env = defaults_core.role_env(role) if role else defaults_core.ENV_TARGET
        output.echo(f'export {env}="{target.name}"')
        return
    if role:
        _save(cfg, f"defaults.targets.{role}", target.name)
        output.echo(_("choose.role.saved", role=role, target=target.name))
    else:
        _save(cfg, "defaults.target", target.name)
        output.echo(_("choose.target.saved", target=target.name))


def _choose_named(cfg, kind: str, value: str, session: bool, dotted: str, env_var: str) -> None:
    """Store *value* as the chosen *kind*, resolving a bare name in the caasi layout.

    A path is used as given. A name is searched on the machine being worked on -- the chosen
    target, or this computer with a notice that nothing was chosen -- and the report says where it
    was found, because "on the robot" and "here" lead to different next steps.
    """
    location = defaults_core.resolve_named(cfg, kind, value)
    # NB: not `_`, which is the translation function.
    notice = defaults_core.working_machine(cfg)[1]
    if notice:
        # Said every time a name is resolved, success or failure: the operator must know the search
        # happened on this machine and not on a robot.
        output.echo(f"[dim]{notice}[/dim]")
    if location is None:
        found = defaults_core.search(cfg, kind, value)
        machine = defaults_core.working_machine(cfg)[0]
        places = ", ".join(f"~/caasi/{p}" for p in defaults_core._candidates(kind, value)) or "-"
        output.fail(
            _("choose.not_found", kind=kind, name=value, machine=machine, places=places)
        )
        raise typer.Exit(1)

    if session:
        output.echo(f'export {env_var}="{location.path}"')
        return
    # A name is what identifies it. An explicit path is only kept when the argument *was* a path
    # outside the tree -- storing "~/caasi/robots/x" as if it were a name would search for
    # "robots/~/caasi/robots/x" next time.
    stored = (
        str(Path(location.path).expanduser())
        if location.machine == "local" and not location.path.startswith("~/caasi/")
        else location.name
    )
    _save(cfg, dotted, stored)
    if location.machine == "local":
        output.echo(_("choose.saved_local", kind=kind, name=location.name, path=location.path))
    else:
        output.echo(_("choose.saved_remote", kind=kind, name=location.name,
                      machine=location.machine, path=location.path))


def _choose_project(value: str, session: bool, clear: bool) -> None:
    cfg = state.cfg()
    if clear:
        if session:
            output.echo(f"unset {defaults_core.ENV_PROJECT}")
            return
        _clear(cfg, "defaults.project")
        output.echo(_("choose.project.cleared"))
        return
    _choose_named(cfg, "project", value, session, "defaults.project", defaults_core.ENV_PROJECT)


def _choose_robot(value: str, session: bool, clear: bool) -> None:
    cfg = state.cfg()
    if clear:
        if session:
            output.echo(f"unset {defaults_core.ENV_ROBOT}")
            return
        _clear(cfg, "defaults.robot")
        output.echo(_("choose.robot.cleared"))
        return
    _choose_named(cfg, "robot", value, session, "defaults.robot", defaults_core.ENV_ROBOT)


app = typer.Typer(
    help=_("choose.help"),
    invoke_without_command=True,
    no_args_is_help=False,
)


@app.callback()
def choose_callback(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
    session: bool = typer.Option(
        False, "--session", "-s",
        help=_("choose.flag.session"),
    ),
) -> None:
    """Show or set the target and project commands act on."""
    if ctx.invoked_subcommand is None:
        _show(json_output)
    else:
        # Accepted before the subcommand as well as after it: `caasi choose --session target x`.
        ctx.ensure_object(dict)["session"] = session


@app.command("target", help=_("choose.target_help"))
def choose_target(
    ctx: typer.Context,
    name: Optional[str] = typer.Argument(None, help=_("choose.arg.target")),
    role: Optional[str] = typer.Option(
        None, "--role", "-r",
        help=_("choose.flag.role"),
    ),
    session: bool = typer.Option(
        False, "--session", "-s",
        help=_("choose.flag.session_target"),
    ),
    clear: bool = typer.Option(False, "--clear", help=_("choose.flag.clear")),
) -> None:
    if name is None and not clear:
        output.fail(_("choose.arg_required", what="target"))
        raise typer.Exit(1)
    _choose_target(name, session or bool(ctx.ensure_object(dict).get("session")), clear, role)


@app.command("project", help=_("choose.project_help"))
def choose_project(
    ctx: typer.Context,
    project: Optional[str] = typer.Argument(None, help=_("choose.arg.project")),
    session: bool = typer.Option(
        False, "--session", "-s",
        help=_("choose.flag.session_project"),
    ),
    clear: bool = typer.Option(False, "--clear", help=_("choose.flag.clear")),
) -> None:
    if project is None and not clear:
        output.fail(_("choose.arg_required", what="project"))
        raise typer.Exit(1)
    _choose_project(project, session or bool(ctx.ensure_object(dict).get("session")), clear)


@app.command("robot", help=_("choose.robot_help"))
def choose_robot(
    ctx: typer.Context,
    robot: Optional[str] = typer.Argument(None, help=_("choose.arg.robot")),
    session: bool = typer.Option(
        False, "--session", "-s",
        help=_("choose.flag.session_robot"),
    ),
    clear: bool = typer.Option(False, "--clear", help=_("choose.flag.clear")),
) -> None:
    if robot is None and not clear:
        output.fail(_("choose.arg_required", what="robot"))
        raise typer.Exit(1)
    _choose_robot(robot, session or bool(ctx.ensure_object(dict).get("session")), clear)


@app.command("show", help=_("choose.show_help"))
def choose_show(
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    _show(json_output)
