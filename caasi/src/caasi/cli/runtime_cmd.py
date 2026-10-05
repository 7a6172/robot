"""``caasi runtime`` - persistent runtime lifecycle for a target (Phase 7 Stage E4).

The lifecycle answers: *if caasi deploys software to a long-lived target such as a
robot, how does caasi install / configure / enable / verify / manage it over time?*

    deploy -> install -> enable -> start -> operate -> update -> verify -> rollback

caasi owns identity, declaration, invocation, verification and provenance. The
native mechanism (systemd here) owns actually running the service: caasi writes
the unit a project declares, invokes systemctl, and then *asks* systemd what the
state is. caasi never supervises the process itself.
"""

from __future__ import annotations

from typing import Optional

import typer
from rich.table import Table

from .. import state
from ..core import deploy as deploy_core
from ..core import lifecycle as lifecycle_core
from ..core import manifest as manifests
from ..core import project as projects
from ..core import targets as targets_core
from ..i18n import _
from ..utils import output

app = typer.Typer(no_args_is_help=True)


def _require_project_root():
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


def _load_context(target_name: str):
    """Resolve the project root, manifest, runtime declaration and destination."""
    root = _require_project_root()
    manifest = manifests.read(root)
    try:
        decl = lifecycle_core.parse_runtime(manifest.runtime)
    except lifecycle_core.RuntimeLifecycleError as err:
        output.fail(f"{root}/caasi.yaml: {err}")
        raise typer.Exit(1)

    target = _require_target(target_name)
    destination = deploy_core.resolve_deployment_destination(
        target, manifest.name or root.name
    )
    return root, manifest, decl, target, destination


def _emit(result: lifecycle_core.LifecycleResult, json_output: bool) -> None:
    if output.wants_json(json_output):
        output.echo_json(result.to_dict())
        return
    mark = "[green]✔[/green]" if result.ok else "[red]✖[/red]"
    output.echo(f"{mark} {result.operation} on {result.target}"
                + (f": {result.detail}" if result.detail else ""))
    if not result.ok:
        raise typer.Exit(1)


@app.command("install", help=_("runtime.install_help"))
def runtime_install(
    target: str = typer.Argument(..., help=_("target.arg.name")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("runtime.flag.dry_run")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    """Install the project's declared runtime on a target.

    Writes the environment fragment, the unit and a revision marker. It does not
    enable or start anything - those are separate steps so a partial failure is
    visible rather than half-applied invisibly.
    """
    _root, manifest, decl, tgt, destination = _load_context(target)

    if not decl.declared:
        output.fail(_("runtime.not_declared", project=manifest.name or "this project"))
        raise typer.Exit(1)

    deployment = deploy_core.get_deployment_status(
        tgt, destination, state.cfg(), project_root=projects.find_project_root()
    )
    if deployment is None and not dry_run:
        output.fail(_("runtime.no_deployment", target=tgt.name, dest=destination))
        raise typer.Exit(1)

    previous = lifecycle_core.read_runtime_state(tgt, destination)
    result, plan = lifecycle_core.install_runtime(
        tgt, decl, destination,
        deployment_id=deployment.deployment_id if deployment else "dry-run",
        git_revision=deployment.git_revision if deployment else None,
        project=manifest.name,
        dry_run=dry_run,
        previous_state=previous,
    )

    if output.wants_json(json_output):
        output.echo_json({**result.to_dict(), "plan": plan.to_dict()})
        return
    if dry_run:
        output.echo(f"[bold]{_('runtime.plan_title')}[/bold]")
        output.echo(f"  unit:        {plan.unit_path}")
        output.echo(f"  environment: {plan.env_fragment_path}")
        output.echo(f"  marker:      {lifecycle_core.marker_path(destination)}")
        output.echo(f"  [dim]{_('runtime.dry_note')}[/dim]")
        return
    _emit(result, json_output)


@app.command("enable", help=_("runtime.enable_help"))
def runtime_enable(
    target: str = typer.Argument(..., help=_("target.arg.name")),
    disable: bool = typer.Option(False, "--disable", help=_("runtime.flag.disable")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    """Enable (or disable) the unit via systemctl. systemd owns the semantics."""
    _root, _manifest, decl, tgt, _dest = _load_context(target)
    if not decl.declared:
        output.fail(_("runtime.not_declared", project="this project"))
        raise typer.Exit(1)
    _emit(lifecycle_core.enable_runtime(tgt, str(decl.unit), enable=not disable),
          json_output)


@app.command("start", help=_("runtime.start_help"))
def runtime_start(
    target: str = typer.Argument(..., help=_("target.arg.name")),
    stop: bool = typer.Option(False, "--stop", help=_("runtime.flag.stop")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    """Start (or stop) the unit. caasi does not supervise it afterwards."""
    _root, _manifest, decl, tgt, _dest = _load_context(target)
    if not decl.declared:
        output.fail(_("runtime.not_declared", project="this project"))
        raise typer.Exit(1)
    _emit(lifecycle_core.start_runtime(tgt, str(decl.unit), start=not stop), json_output)


@app.command("status", help=_("runtime.status_help"))
def runtime_status(
    target: str = typer.Argument(..., help=_("target.arg.name")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    """Ask systemd for the unit's state, and read caasi's recorded revision."""
    _root, _manifest, decl, tgt, destination = _load_context(target)
    if not decl.declared:
        output.fail(_("runtime.not_declared", project="this project"))
        raise typer.Exit(1)

    status = lifecycle_core.runtime_status(tgt, str(decl.unit))
    marker = lifecycle_core.read_runtime_state(tgt, destination)

    payload = {
        "target": tgt.name,
        "destination": destination,
        "systemd": status,
        "installed_revision": marker.to_dict() if marker else None,
    }
    if output.wants_json(json_output):
        output.echo_json(payload)
        return

    output.echo(f"[bold]{_('runtime.title', target=tgt.name)}[/bold]")
    output.echo(f"  {_('runtime.row.unit')}:       {status['unit']}")
    output.echo(f"  {_('runtime.row.scheme')}:     systemd (user)")
    output.echo(f"  {_('runtime.row.enabled')}:    {status['unit_file_state'] or '-'}")
    output.echo(f"  {_('runtime.row.active')}:     {status['active_state'] or '-'}"
                f" ({status['sub_state'] or '-'})")
    output.echo(f"  {_('runtime.row.mainpid')}:    {status['main_pid'] or '-'}")
    if marker:
        output.echo(f"  {_('runtime.row.revision')}:   {marker.git_revision or '-'}")
        output.echo(f"  {_('runtime.row.deployed')}:   {marker.deployment_id or '-'}")
        output.echo(f"  {_('runtime.row.installed')}:  {marker.installed_at or '-'}")
    else:
        output.echo(f"  [yellow]{_('runtime.row.no_marker')}[/yellow]")


@app.command("verify", help=_("runtime.verify_help"))
def runtime_verify(
    target: str = typer.Argument(..., help=_("target.arg.name")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    """Verify the ACTIVE revision matches what caasi believes is deployed.

    Answers the question `deploy` alone cannot: not merely "did the files arrive",
    but "is the revision we think is running the one actually installed and
    enabled".
    """
    _root, _manifest, decl, tgt, destination = _load_context(target)
    if not decl.declared:
        output.fail(_("runtime.not_declared", project="this project"))
        raise typer.Exit(1)

    deployment = deploy_core.get_deployment_status(
        tgt, destination, state.cfg(), project_root=projects.find_project_root()
    )

    ok, problems, evidence = lifecycle_core.verify_runtime(
        tgt, str(decl.unit), destination,
        expect_deployment_id=deployment.deployment_id if deployment else None,
        expect_git_revision=deployment.git_revision if deployment else None,
    )

    if output.wants_json(json_output):
        output.echo_json({"ok": ok, "target": tgt.name, "problems": problems,
                          "evidence": evidence})
        return

    if ok:
        output.echo(f"[green]✔[/green] {_('runtime.verified', target=tgt.name)}")
        active = evidence.get("active_git_revision") or evidence.get("active_deployment_id")
        output.echo(f"  {_('runtime.row.active_rev')}: {active or '-'}")
        return

    output.echo(f"[red]✖[/red] {_('runtime.verify_failed', target=tgt.name)}")
    for problem in problems:
        output.echo(f"  - {problem}")
    raise typer.Exit(1)


@app.command("update", help=_("runtime.update_help"))
def runtime_update(
    target: str = typer.Argument(..., help=_("target.arg.name")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    """Move the target to the newly deployed revision, then verify.

    Captures the currently active revision first, so a failed update can be rolled
    back. Nothing is deleted.
    """
    _root, manifest, decl, tgt, destination = _load_context(target)
    if not decl.declared:
        output.fail(_("runtime.not_declared", project="this project"))
        raise typer.Exit(1)

    deployment = deploy_core.get_deployment_status(
        tgt, destination, state.cfg(), project_root=projects.find_project_root()
    )
    if deployment is None:
        output.fail(_("runtime.no_deployment", target=tgt.name, dest=destination))
        raise typer.Exit(1)

    result, _plan, previous = lifecycle_core.update_runtime(
        tgt, decl, destination,
        deployment_id=deployment.deployment_id,
        git_revision=deployment.git_revision,
        project=manifest.name,
    )
    if not result.ok and previous:
        output.echo(f"  [yellow]{_('runtime.update_rollback_hint', rev=previous.git_revision or previous.deployment_id or '-')}[/yellow]")
    _emit(result, json_output)


@app.command("rollback", help=_("runtime.rollback_help"))
def runtime_rollback(
    target: str = typer.Argument(..., help=_("target.arg.name")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    """Reinstall the previously active revision and restart.

    Rollback reinstalls; it never deletes the newer revision, so an operator can
    roll forward again if the rollback turns out to be wrong.
    """
    root, _manifest, decl, tgt, destination = _load_context(target)
    if not decl.declared:
        output.fail(_("runtime.not_declared", project="this project"))
        raise typer.Exit(1)

    def _redeploy():
        """Re-materialize the project through the normal deploy path.

        Rollback restores content by redeploying, so it goes through exactly the
        same code as `caasi deploy` rather than a private shortcut.
        """
        spec = deploy_core.create_deployment_spec(root, tgt, state.cfg())
        record = deploy_core.execute_deployment(spec, config=state.cfg())
        ok = record.status == "verified"
        return lifecycle_core.LifecycleResult(
            "redeploy", ok, tgt.name,
            detail=(None if ok else f"deploy status was '{record.status}'"),
        )

    _emit(
        lifecycle_core.rollback_runtime(
            tgt, decl, destination, source_root=root, redeploy=_redeploy
        ),
        json_output,
    )
