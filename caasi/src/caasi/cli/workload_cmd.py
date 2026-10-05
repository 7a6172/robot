"""``caasi workload`` — declared work, and its composition.

The composition runs a workload's declared ``steps`` by calling the **existing**
caasi operations, in order, on an **explicitly named** target:

    compatibility check -> deploy -> build -> run -> collect

Everything the individual commands do remains available: this is an addition for
convenience, never a replacement. A failing step stops the chain, names the failed
link, and leaves the already-produced ids visible so the operator can continue with
the lower-level commands.

The target is **required**. Composition never selects, forwards or allocates a
different target; those capabilities remain deferred (R8).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.table import Table

from .. import state
from ..core import compose as compose_core
from ..core import project as projects
from ..core import targets as targets_core
from ..core import workload as workload_core
from ..core.workload import WorkloadError
from ..i18n import _
from ..utils import output

app = typer.Typer(no_args_is_help=True)


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


@app.command("list", help=_("workload.list_help"))
def workload_list(
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    """List the workloads a project declares."""
    root = _require_project_root()
    try:
        workloads = workload_core.list_workloads(root)
    except WorkloadError as err:
        output.fail(str(err))
        raise typer.Exit(1)

    if output.wants_json(json_output):
        output.echo_json({"project": root.name, "workloads": [w.to_dict() for w in workloads]})
        return

    if not workloads:
        output.echo(_("workload.none", dir=str(workload_core.workload_dir(root))))
        return

    table = Table(title=_("workload.title"), header_style="bold", **output.table_styles())
    table.add_column(_("workload.col.name"))
    table.add_column(_("workload.col.requires"))
    table.add_column(_("workload.col.steps"))
    for workload in workloads:
        requires = ", ".join(
            f"{k}{_version_hint(v)}" for k, v in sorted(workload.requires.items())
        ) or "—"
        steps = " → ".join(s.name for s in workload.steps) or "—"
        table.add_row(workload.name, requires, steps)
    output.echo(table)


@app.command("inspect", help=_("workload.inspect_help"))
def workload_inspect(
    name: str = typer.Argument(..., help=_("workload.arg.name")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    """Show one workload's requirements and steps."""
    root = _require_project_root()
    try:
        workload = workload_core.find_workload(root, name)
    except WorkloadError as err:
        output.fail(str(err))
        raise typer.Exit(1)

    if workload is None:
        known = ", ".join(w.name for w in workload_core.list_workloads(root)) or "-"
        output.fail(_("workload.not_found", query=name, valid=known))
        raise typer.Exit(1)

    if output.wants_json(json_output):
        output.echo_json(workload.to_dict())
        return

    output.echo(f"[bold]{workload.name}[/bold]")
    if workload.description:
        output.echo(f"  {workload.description}")
    if workload.requires:
        output.echo(f"  {_('workload.col.requires')}:")
        for key, value in sorted(workload.requires.items()):
            output.echo(f"    {key}{_version_hint(value)}")
    else:
        output.echo(f"  {_('workload.col.requires')}: —")
    if workload.steps:
        output.echo(f"  {_('workload.col.steps')}:")
        for step in workload.steps:
            options = f" {step.options}" if step.options else ""
            output.echo(f"    {step.name}{options}")
    else:
        output.echo(f"  {_('workload.col.steps')}: —")
    if workload.outputs:
        output.echo(f"  {_('workload.col.outputs')}:")
        for item in workload.outputs:
            path = item.get("path") if isinstance(item, dict) else item
            output.echo(f"    {path}")


@app.command("run", help=_("workload.run_help"))
def workload_run(
    name: str = typer.Argument(..., help=_("workload.arg.name")),
    target: Optional[str] = typer.Option(None, "--target", "-t", help=_("workload.flag.target")),
    where: Optional[str] = typer.Option(None, "--where", help=_("workload.flag.where")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("workload.flag.dry_run")),
    skip_check: bool = typer.Option(
        False, "--skip-check", help=_("workload.flag.skip_check")
    ),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    """Compose a workload's steps on a named target, or one chosen by policy.

    `--target` names a target explicitly. `--where` asks caasi to choose among the
    targets that currently satisfy the workload, and always explains the choice.
    The two are mutually exclusive and one is required: there is no implicit
    default.

    The chain stops at the first failing step and names it, leaving the ids already
    produced so the run can be continued with the individual commands. Nothing is
    ever deleted, and no other target is chosen on your behalf.
    """
    root = _require_project_root()

    # Either/only-one-of. Enforced here rather than in the parser so `--target`
    # keeps exactly its previous semantics for every existing caller.
    if target and where:
        output.fail(_("workload.target_and_where"))
        raise typer.Exit(1)
    if not target and not where:
        output.fail(_("workload.needs_target_or_where"))
        raise typer.Exit(1)

    target_obj = None
    selection_decision = None

    try:
        workload, requirements, tested = compose_core.load_composition_context(root, name)
    except WorkloadError as err:
        output.fail(str(err))
        raise typer.Exit(1)

    if not workload.steps:
        output.fail(_("workload.no_steps", name=workload.name, known=", ".join(workload_core.KNOWN_STEPS)))
        raise typer.Exit(1)

    cfg = state.cfg()

    # Resolve the target: named explicitly, or chosen by policy among the targets
    # that currently satisfy the workload. Either way the operator is told which one
    # that is, and why.
    if where:
        selection_decision = _select_by_policy(
            workload.name, where, requirements, tested, cfg
        )
        if not selection_decision.ok:
            if output.wants_json(json_output):
                output.echo_json(selection_decision.to_dict())
            else:
                _report_decision(selection_decision)
            # Failing is the required behaviour: no deploy, no queue, no waiting.
            # `output.fail` raises its own exit, so the code must be passed to it;
            # a later `raise` would never be reached (the same trap as F3).
            output.fail(_("workload.nothing_fits"), exit_code=3)
        if not output.wants_json(json_output):
            _report_decision(selection_decision)
        target_obj = _require_target(selection_decision.selected)
    else:
        target_obj = _require_target(target)

    # --dry-run reports the plan and the compatibility verdict, and touches nothing.
    if dry_run:
        inspection = targets_core.discover_target(target_obj, config=cfg)
        proceed, reason = compose_core.check_target_compatibility(
            target_obj, requirements, inspection, tested, config=cfg
        )
        unmeasured = compose_core.unmeasured_requirements(
            target_obj, requirements, inspection, tested, config=cfg
        )
        if output.wants_json(json_output):
            output.echo_json({
                "workload": workload.name,
                "target": target_obj.name,
                "steps": [s.to_dict() for s in workload.steps],
                "compatible": proceed,
                "reason": reason,
                "unmeasured": unmeasured,
            })
            return
        output.echo(f"[bold]{_('workload.plan_title', name=workload.name, target=target_obj.name)}[/bold]")
        for index, step in enumerate(workload.steps, 1):
            options = f" [dim]{step.options}[/dim]" if step.options else ""
            output.echo(f"  {index}. {step.name}{options}")
        if proceed:
            output.echo(f"  [green]✔[/green] {_('workload.compatible')}")
        else:
            output.echo(f"  [red]✖[/red] {reason}")
            raise typer.Exit(3)
        if unmeasured:
            for note in unmeasured:
                output.echo(f"  [yellow]~[/yellow] {note}")
        output.echo(f"  [dim]{_('workload.dry_note')}[/dim]")
        return

    # Compatibility gate: a contradicting requirement stops the run; an
    # *unmeasured* one does not, because absence of evidence is not evidence of
    # absence.
    if not skip_check:
        inspection = targets_core.discover_target(target_obj, config=cfg)
        proceed, reason = compose_core.check_target_compatibility(
            target_obj, requirements, inspection, tested, config=cfg
        )
        if not proceed:
            # `output.fail` raises its own exit, so the code must be passed to it;
            # a following `raise` is unreachable and the refusal would exit 1.
            output.fail(
                reason or _("workload.incompatible", target=target_obj.name),
                exit_code=3,
            )

    runner = compose_core.build_step_runner(
        project_root=root,
        target=target_obj,
        config=cfg,
        workload_outputs=workload.outputs,
        workload_name=workload.name,
        workload_config=str(workload.config_path) if workload.config_path else None,
        selection_policy=selection_decision.policy_raw if selection_decision else None,
        selection_reason=selection_decision.reason if selection_decision else None,
    )

    def on_step(result) -> None:
        if output.wants_json(json_output):
            return
        if result.status == compose_core.STEP_OK:
            style, mark = "green", "✔"
        else:
            style, mark = "red", "✖"
        detail = f" — {result.detail}" if result.detail else ""
        output.echo(f"  [{style}]{mark}[/{style}] {result.name}{detail}")

    if not output.wants_json(json_output):
        output.echo(
            f"[bold]{_('workload.run_title', name=workload.name, target=target_obj.name)}[/bold]"
        )

    report = compose_core.compose(workload, target_obj.name, runner, on_step=on_step)

    if output.wants_json(json_output):
        output.echo_json(report.to_dict())
    else:
        produced = report.produced()
        if produced:
            output.echo(f"  [dim]{_('workload.produced')}: " + ", ".join(
                f"{k}={v}" for k, v in sorted(produced.items()) if v is not None
            ) + "[/dim]")
        if report.ok:
            output.echo(f"[green]✔[/green] {_('workload.complete', name=workload.name)}")
        else:
            output.echo(
                f"[red]✖[/red] {_('workload.failed_step', step=report.failed_step, error=report.error)}"
            )
            output.echo(f"  [dim]{_('workload.failed_hint')}[/dim]")

    if not report.ok:
        raise typer.Exit(1)


def _version_hint(entry) -> str:
    if isinstance(entry, dict):
        value = entry.get("version")
        if value:
            return f" {value}"
        if entry:
            return f" {entry}"
        return ""
    return f" {entry}" if entry else ""


def _select_by_policy(workload_name, where, requirements, tested, cfg):
    """Evaluate every target and apply the policy. Never waits, never queues."""
    from ..core import runs as runs_core
    from ..core import selection as selection_core
    from ..core import where as where_core

    try:
        where_core.parse_policy(where)
    except where_core.SelectionError as err:
        output.fail(str(err))
        raise typer.Exit(1)

    config = state.cfg()
    targets = targets_core.list_targets(config)
    inspections = {}
    for t in targets:
        try:
            inspections[t.name] = targets_core.discover_target(t, config=config)
        except Exception:  # noqa: BLE001 - an uninspectable target is a verdict
            inspections[t.name] = None

    reports = selection_core.select_all(
        targets, requirements, inspections, tested,
        strict=bool(config.get("check.strict", False)),
    )

    # Tag lookup for `prefer:<tag>`; taken from the targets themselves.
    tags_by_target = {t.name: list(t.tags or []) for t in targets}
    unmeasured_by_target = {}
    for t in targets:
        inspection = inspections.get(t.name)
        if inspection is None:
            continue
        unmeasured_by_target[t.name] = compose_core.unmeasured_requirements(
            t, requirements, inspection, tested, config=config
        )

    occupancy = where_core.occupancy_by_target(config)

    decision = where_core.decide(
        workload_name, where, reports,
        occupancy=occupancy,
        unmeasured_by_target=unmeasured_by_target,
        tags_by_target=tags_by_target,
    )
    return decision


def _report_decision(decision) -> None:
    """Always-visible explanation of the choice. Never silent."""
    output.echo(f"[bold]{_('workload.select_title', workload=decision.workload)}[/bold]")
    output.echo(f"  {_('workload.select.policy')}: {decision.policy_raw}")
    output.echo(f"  {_('workload.select.ordering')}: {decision.ordering_note}")
    output.echo("")

    if decision.selected:
        output.echo(f"  [green]✔ SELECTED[/green]   {decision.selected}")
        output.echo(f"      [dim]{decision.reason}[/dim]")
    for eliminated in decision.eliminated:
        evidence = f" — {eliminated.evidence}" if eliminated.evidence else ""
        output.echo(f"  [red]✖ eliminated[/red] {eliminated.target}  {eliminated.reason}{evidence}")

    if decision.unmeasured:
        output.echo("")
        output.echo(f"  [yellow]{_('workload.select.unmeasured')}[/yellow]")
        for note in decision.unmeasured:
            output.echo(f"      · {note}")
    if decision.unknown_occupancy:
        output.echo("")
        output.echo(f"  [yellow]{_('workload.select.unknown')}[/yellow]")
        for note in decision.unknown_occupancy:
            output.echo(f"      · {note}")
    output.echo("")
