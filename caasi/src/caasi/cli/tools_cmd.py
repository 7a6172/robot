"""``caasi <tool> --target <t>`` — run an existing tool against a target (Stage F3).

The principle: **caasi supplies context, then gets out of the way.**

    caasi rviz2 --target robot-01
    caasi rosbag --target robot-01 record /scan

caasi resolves the target, works out what environment the tool needs to reach that
target's ROS 2 system, and then ``exec``s the **real** tool. There is no rviz2
implementation, no rqt subsystem, and no rosbag reimplementation: the tools remain
the domain owners and receive their own arguments unchanged.

Everything after the recognised caasi options reaches the tool verbatim, so a tool
flag caasi has never heard of still works.
"""

from __future__ import annotations

from typing import Optional

import typer

from .. import state
from ..core import targets as targets_core
from ..core import defaults as defaults_core
from ..core import toolctx as toolctx_core
from ..core.toolctx import ToolInvocationError
from ..i18n import _
from ..utils import output

app = typer.Typer(no_args_is_help=True)

#: Tools are invoked through a dispatcher rather than a static sub-command each, so
#: the mechanism stays generic: adding a tool is a registry entry, not a command.
EXTRA_SETTINGS = {"allow_extra_args": True, "ignore_unknown_options": True}


def _require_target(name: str) -> targets_core.Target:
    target = targets_core.find_target(state.cfg(), name)
    if target is None:
        valid = ", ".join(t.name for t in targets_core.list_targets(state.cfg())) or "-"
        output.fail(_("target.not_found", query=name, valid=valid))
        raise typer.Exit(1)
    return target


def _report_plan(plan: toolctx_core.InvocationPlan) -> None:
    output.echo(f"[bold]{_('toolctx.title', tool=plan.tool, target=plan.target)}[/bold]")
    output.echo(f"  {_('toolctx.row.command')}: {' '.join(plan.command)}")
    if plan.environment:
        for key in sorted(plan.environment):
            output.echo(f"  {key}={plan.environment[key]}")
    for note in plan.notes:
        output.echo(f"  [dim]· {note}[/dim]")


@app.command("list", help=_("toolctx.list_help"))
def tools_list(
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    """List the target-aware tools available to invoke."""
    registry = toolctx_core.load_registry(state.cfg())

    if output.wants_json(json_output):
        output.echo_json({"tools": [s.to_dict() for s in registry.values()]})
        return

    output.echo(f"[bold]{_('toolctx.list_title')}[/bold]")
    for name in sorted(registry):
        spec = registry[name]
        output.echo(f"  {name:12s} → {spec.invoke}")


@app.command(
    "run",
    help=_("toolctx.run_help"),
    context_settings=EXTRA_SETTINGS,
)
def tools_run(
    ctx: typer.Context,
    tool: str = typer.Argument(..., help=_("toolctx.arg.tool")),
    target: Optional[str] = typer.Option(
        None, "--target", "-t", help=_("toolctx.flag.target")
    ),
    domain: Optional[int] = typer.Option(None, "--domain", help=_("toolctx.flag.domain")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("toolctx.flag.dry_run")),
    exec_tool: bool = typer.Option(
        False, "--exec", help=_("toolctx.flag.exec")
    ),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    """Resolve a target's context and run an existing tool against it.

    The tool's own arguments pass through unchanged. caasi does not implement the
    tool or DDS: if discovery cannot traverse the network between here and the
    target, that is reported rather than worked around.
    """
    cfg = state.cfg()
    # -t wins; otherwise the chosen target decides which graph the tool attaches to
    given = target is not None
    target = defaults_core.resolve_target_name(cfg, target)
    if not given and target == defaults_core.LOCAL:
        output.fail(_("exec.error.no_target"))
        raise typer.Exit(1)
    registry = toolctx_core.load_registry(cfg)

    try:
        spec = toolctx_core.resolve_tool(registry, tool)
    except ToolInvocationError as err:
        output.fail(str(err))
        raise typer.Exit(1)

    target_obj = _require_target(target)

    # Everything after the recognised options belongs to the tool.
    tool_args = [str(arg) for arg in (ctx.args or [])]

    try:
        plan = toolctx_core.plan_invocation(
            spec, target_obj, tool_args, explicit_domain=domain
        )
    except ToolInvocationError as err:
        # Refusing is a first-class outcome, not an internal error. `output.fail`
        # raises its own exit, so the code must be passed to it rather than raised
        # afterwards -- a later `raise` would never be reached.
        output.fail(str(err), exit_code=3)

    if output.wants_json(json_output):
        output.echo_json(plan.to_dict())
        return

    _report_plan(plan)

    if dry_run:
        output.echo(f"  [dim]{_('toolctx.dry_note')}[/dim]")
        return

    if exec_tool:
        # Interactive path: the tool replaces this process entirely.
        output.echo(f"  [dim]{_('toolctx.execing')}[/dim]")
        try:
            toolctx_core.exec_tool(plan)
        except ToolInvocationError as err:  # pragma: no cover - exec failure
            output.fail(str(err))
            raise typer.Exit(1)
        return

    # Non-exec path: run it as a child so the exit code can be propagated. Used
    # for non-interactive tools and for validation, where replacing the caller's
    # process would be unhelpful.
    import subprocess

    try:
        result = toolctx_core.run_tool(plan)
    except FileNotFoundError:
        output.fail(_("toolctx.not_installed", binary=plan.command[0]))
        raise typer.Exit(1)

    if result.returncode != 0:
        output.echo(
            f"  [red]✖[/red] {_('toolctx.exited', tool=plan.tool, code=result.returncode)}"
        )
    # The tool's own exit code, unmodified -- caasi does not reinterpret it.
    raise typer.Exit(result.returncode)


# ---------------------------------------------------------------------------
# Dispatcher: `caasi <tool> --target <t> ...`
# ---------------------------------------------------------------------------

#: Built-in short names that map directly onto a registry entry, so the documented
#: spelling works without a `run` verb.
DIRECT_TOOLS = ("rviz2", "rqt", "rosbag")


def register_direct_tools(application) -> None:
    """Expose each known tool as a top-level command: ``caasi rviz2 --target t``.

    Registration is driven by the built-in registry, so the mechanism stays
    generic; a tool added purely in configuration is still reachable through
    ``caasi tools run <name>``.
    """
    for name in DIRECT_TOOLS:
        application.command(
            name,
            help=_("toolctx.direct_help", tool=name),
            context_settings=EXTRA_SETTINGS,
        )(_make_direct(name))


def _make_direct(tool_name: str):
    def _command(
        ctx: typer.Context,
        target: Optional[str] = typer.Option(
            None, "--target", "-t", help=_("toolctx.flag.target")
        ),
        domain: Optional[int] = typer.Option(
            None, "--domain", help=_("toolctx.flag.domain")
        ),
        dry_run: bool = typer.Option(False, "--dry-run", help=_("toolctx.flag.dry_run")),
        exec_tool: bool = typer.Option(False, "--exec", help=_("toolctx.flag.exec")),
        json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
    ) -> None:
        tools_run(
            ctx,
            tool=tool_name,
            target=target,
            domain=domain,
            dry_run=dry_run,
            exec_tool=exec_tool,
            json_output=json_output,
        )

    _command.__name__ = f"direct_{tool_name}"
    return _command
