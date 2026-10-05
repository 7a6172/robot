"""`caasi run` — manage simulation runs as first-class processes.

`run start CONFIG` is the canonical launcher (§5.4): every domain entry point
(`sim run`, `train`, `lab run`, ...) delegates to :func:`launch_experiment`,
so a started run always means a tracked process **plus** the §4.7 provenance
bundle — one semantic operation, many doors.
"""

from __future__ import annotations

import re
import time
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

import typer
from rich.table import Table

from .. import state
from ..core import artifacts as artifacts_mod
from ..core import experiment, provenance, runs
from ..core.config import Config
from ..i18n import _
from ..utils import output

app = typer.Typer(no_args_is_help=True)

_PASS_THROUGH = {"allow_extra_args": True, "ignore_unknown_options": True}


def start_with_provenance(config: Config, **kwargs) -> runs.RunRecord:
    """The single run-start operation: tracked process + provenance bundle."""
    record = runs.start_run(config, **kwargs)
    provenance.write_bundle(config, record)
    return record


def launch_experiment(
    config_path: Path,
    *,
    target: Optional[str] = None,
    backend: Optional[str] = None,
    expect_backend: Optional[str] = None,
    name: Optional[str] = None,
    kind: str = "experiment",
    extra_args: Optional[list[str]] = None,
    extra: Optional[dict] = None,
    force_headless: bool = False,
    dry_run: bool = False,
    json_output: bool = False,
    transform: Optional[Callable[[experiment.Experiment], experiment.Experiment]] = None,
) -> Optional[runs.RunRecord]:
    """Load an experiment CONFIG, build its command and start it as a run.

    *backend* overrides the declared backend (explicit CLI intent wins);
    *expect_backend* only notes a mismatch (domain doors like `sim run` keep
    the config's choice). *transform* may swap the loaded experiment (e.g.
    `lab play` uses an alternative script). Returns the record, or None for
    dry runs; failures exit via :func:`output.fail`.
    """
    cfg = state.cfg()
    if target is not None and target != "local":
        from ..core import targets as targets_core
        target_obj = targets_core.find_target(cfg, target)
        if not target_obj:
            output.fail(_("target.not_found", name=target))
            return None
        if dry_run:
            output.echo(f"[bold]{_('sim.run.dry_title')}[/bold]")
            output.echo(f"  target:  {target_obj.name} ({target_obj.transport})")
            output.echo(f"  config:  {config_path}")
            return None
        try:
            record = runs.start_target_run(
                target=target_obj,
                config=cfg,
                config_path=config_path,
                name=name,
                backend=backend,
                kind=kind,
                extra_args=extra_args,
                extra=extra,
                force_headless=force_headless,
            )
        except Exception as exc:
            output.fail(str(exc))
            return None
        if output.wants_json(json_output):
            output.echo_json(record.to_dict(cfg))
            return record
        output.echo(f"[green]{_('run.started.target', id=record.run_id, target=record.target)}[/green]")
        output.echo(f"  [dim]{_('sim.run.watch', id=record.run_id)}[/dim]")
        return record
    try:
        exp = experiment.load_experiment(config_path)
    except experiment.ExperimentError as exc:
        output.fail(str(exc))
        return None
    if transform is not None:
        exp = transform(exp)

    declared = exp.backend
    if backend is not None and backend != declared:
        exp = replace(exp, backend=backend)
        if not output.wants_json(json_output):
            output.echo(
                f"[yellow]{_('run.start.backend_override', backend=declared, wanted=backend)}[/yellow]"
            )
    elif expect_backend is not None and declared != expect_backend:
        if not output.wants_json(json_output):
            output.echo(
                f"[yellow]{_('run.start.backend_note', backend=declared, wanted=expect_backend)}[/yellow]"
            )

    args = list(extra_args or [])
    if force_headless:
        args = ["--headless", "--no-window", *args]
    try:
        command, env = experiment.build_command(exp, cfg, extra_args=args)
    except experiment.ExperimentError as exc:
        output.fail(str(exc))
        return None

    if dry_run:
        output.echo(f"[bold]{_('sim.run.dry_title')}[/bold]")
        output.echo(f"  command: {' '.join(command)}")
        output.echo(f"  cwd:     {exp.work_dir}")
        for key in sorted(env):
            if key in exp.env or key.startswith("ISAAC"):
                output.echo(f"  env:     {key}={env[key]}")
        return None

    record = start_with_provenance(
        cfg,
        name=name or exp.name,
        command=command,
        cwd=exp.work_dir,
        env=env,
        backend=exp.backend,
        kind=kind,
        extra={
            "experiment": str(exp.config_path),
            "headless": exp.headless or force_headless,
            **(extra or {}),
        },
    )
    if output.wants_json(json_output):
        output.echo_json(record.to_dict())
        return record
    output.echo(f"[green]{_('sim.run.started', id=record.run_id)}[/green]")
    output.echo(f"  [dim]{_('sim.run.watch', id=record.run_id)}[/dim]")
    return record


def _require_run(query: str, backend: Optional[str] = None) -> runs.RunRecord:
    record = runs.find_run(state.cfg(), query)
    if record is None:
        output.fail(_("run.not_found", query=query))
        raise typer.Exit(1)  # unreachable, keeps type-checkers happy
    if backend is not None and record.backend != backend:
        output.fail(
            _("run.wrong_backend", id=record.run_id, backend=record.backend, wanted=backend)
        )
        raise typer.Exit(1)  # unreachable, keeps type-checkers happy
    return record


def _status_style(status: str) -> str:
    return {
        runs.TERMINAL_OK: "green",
        runs.TERMINAL_FAIL: "red",
        runs.RUNNING: "cyan",
        runs.PAUSED: "yellow",
        runs.STOPPED: "dim",
        runs.LOST: "magenta",
    }.get(status, "white")


@app.command("start", help=_("run.start_help"), context_settings=_PASS_THROUGH)
def run_start(
    ctx: typer.Context,
    config_path: Path = typer.Argument(..., help=_("sim.run.config_help")),
    target: Optional[str] = typer.Option(None, "--target", "-t", help=_("run.start.flag.target")),
    backend: Optional[str] = typer.Option(None, "--backend", help=_("run.start.flag.backend")),
    name: Optional[str] = typer.Option(None, "--name", help=_("sim.run.name_help")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("sim.run.dry_run_help")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    if backend is not None and backend not in experiment.VALID_BACKENDS:
        output.fail(
            _("run.start.bad_backend", backend=backend, valid=", ".join(experiment.VALID_BACKENDS))
        )
    launch_experiment(
        config_path,
        target=target,
        backend=backend,
        name=name,
        extra_args=list(ctx.args),
        dry_run=dry_run,
        json_output=json_output,
    )


@app.command("restart", help=_("run.restart_help"))
def run_restart(
    query: str = typer.Argument(..., help=_("run.arg.query")),
    backend: Optional[str] = typer.Option(None, "--backend", help=_("run.flag.backend")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    cfg = state.cfg()
    record = _require_run(query, backend)
    if runs.effective_status(record, cfg) in (runs.RUNNING, runs.PAUSED):
        runs.stop_run(record, config=cfg)
    if record.cwd and not Path(record.cwd).is_dir() and record.target == "local":
        output.fail(_("run.restart.cwd_missing", cwd=record.cwd))
    new = start_with_provenance(
        cfg,
        name=record.name,
        command=record.command,
        cwd=record.cwd,
        backend=record.backend,
        kind=record.kind,
        extra={**(record.extra or {}), "restarted_from": record.run_id},
    )
    if output.wants_json(json_output):
        output.echo_json(new.to_dict(cfg))
        return
    output.echo(f"[green]{_('run.restarted', old=record.run_id, id=new.run_id)}[/green]")
    output.echo(f"  [dim]{_('sim.run.watch', id=new.run_id)}[/dim]")


@app.command("list", help=_("run.list_help"))
def run_list(
    limit: int = typer.Option(20, "--limit", "-n", help=_("run.flag.limit")),
    backend: Optional[str] = typer.Option(None, "--backend", help=_("run.flag.backend")),
    target: Optional[str] = typer.Option(None, "--target", "-t", help=_("run.start.flag.target")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    cfg = state.cfg()
    records = runs.list_runs(cfg)
    if backend is not None:
        records = [r for r in records if r.backend == backend]
    if target is not None:
        records = [r for r in records if r.target == target]
    records = records[: max(limit, 0)]
    if output.wants_json(json_output):
        output.echo_json([r.to_dict(cfg) for r in records])
        return
    if not records:
        output.echo(f"[yellow]{_('run.no_runs')}[/yellow]")
        return
    table = Table(header_style="bold", **output.table_styles())
    for column in ("ID", _("run.col.name"), _("run.col.backend"), _("run.col.target"), _("run.col.status"), _("run.col.created"), "PID"):
        table.add_column(column)
    for record in records:
        status = runs.effective_status(record, cfg)
        table.add_row(
            record.run_id,
            record.name,
            record.backend,
            record.target or "local",
            f"[{_status_style(status)}]{status}[/]",
            record.created,
            str(record.pid) if record.pid else "—",
        )
    output.echo(table)


@app.command("status", help=_("run.status_help"))
def run_status(
    query: str = typer.Argument(..., help=_("run.arg.query")),
    backend: Optional[str] = typer.Option(None, "--backend", help=_("run.flag.backend")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    cfg = state.cfg()
    record = _require_run(query, backend)
    data = record.to_dict(cfg)
    if output.wants_json(json_output):
        output.echo_json(data)
        return
    output.echo(f"[bold]{record.name}[/bold] [dim]({record.run_id})[/dim]")
    items: list[tuple[str, str]] = [
        (_("run.col.status"), str(data["status"])),
        (_("run.col.backend"), str(record.backend)),
        ("Target", f"{record.target} ({record.target_transport})"),
        ("Kind", str(record.kind)),
        (_("run.col.created"), str(record.created)),
        ("PID", str(record.pid) if record.pid else "—"),
    ]
    if record.pgid is not None:
        items.append(("PGID", str(record.pgid)))
    if record.deployment_id:
        items.append(("Deployment", str(record.deployment_id)))
    if record.build_id:
        items.append(("Build", str(record.build_id)))
    if record.destination:
        items.append(("Destination", str(record.destination)))
    if record.remote_run_dir:
        items.append(("Remote Run Dir", str(record.remote_run_dir)))
    items.extend([
        ("Directory", str(record.directory)),
        ("Command", " ".join(record.command)),
    ])
    for label, value in items:
        output.echo(f"  {label:<16} {value}")


_SINCE_RE = re.compile(r"^(\d+)\s*([smhd])$")
_SINCE_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_TIME_TAG_RE = re.compile(r"^\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s*")
_COMPONENT_TAG_RE = re.compile(r"^\[([A-Za-z0-9_.:-]+)\]\s*")
_ERROR_RE = re.compile(
    r"\b(error|fatal|critical|exception|traceback|fail|failed|failure)\b", re.IGNORECASE
)


def _parse_since(value: str) -> Optional[int]:
    match = _SINCE_RE.match(value.strip().lower())
    if not match:
        return None
    return int(match.group(1)) * _SINCE_UNITS[match.group(2)]


def parse_log_line(line: str) -> dict:
    """Parse the §22 ``[HH:MM:SS] [component] message`` convention.

    Both tags are optional — plain lines pass through untagged (and are then
    excluded by ``--component``/``--since``, which cannot attribute them).
    """
    rest = line
    timestamp = None
    match = _TIME_TAG_RE.match(rest)
    if match:
        timestamp = match.group(1)
        rest = rest[match.end():]
    component = None
    match = _COMPONENT_TAG_RE.match(rest)
    if match:
        component = match.group(1)
        rest = rest[match.end():]
    return {
        "line": line,
        "timestamp": timestamp,
        "component": component,
        "message": rest.strip() or line,
    }


def _within_window(timestamp: Optional[str], cutoff: datetime) -> bool:
    if timestamp is None:
        return False  # recency unprovable — honestly excluded
    parts = [int(part) for part in timestamp.split(":")]
    while len(parts) < 3:
        parts.append(0)
    now = datetime.now().astimezone()
    moment = now.replace(hour=parts[0], minute=parts[1], second=parts[2], microsecond=0)
    if moment > now:
        moment -= timedelta(days=1)  # timestamp wrapped past midnight
    return moment >= cutoff


def _line_matches(
    parsed: dict, component: Optional[str], errors: bool, cutoff: Optional[datetime]
) -> bool:
    if component is not None and (parsed["component"] or "").lower() != component.lower():
        return False
    if cutoff is not None and not _within_window(parsed["timestamp"], cutoff):
        return False
    if errors and not _ERROR_RE.search(parsed["message"]):
        return False
    return True


@app.command("logs", help=_("run.logs_help"))
def run_logs(
    query: str = typer.Argument(..., help=_("run.arg.query")),
    lines: int = typer.Option(50, "--lines", "-n", help=_("run.flag.lines")),
    follow: bool = typer.Option(False, "--follow", "-f", help=_("run.flag.follow")),
    stream: str = typer.Option("stdout", "--stream", "-s", help=_("run.flag.stream")),
    component: Optional[str] = typer.Option(None, "--component", help=_("run.flag.component")),
    errors: bool = typer.Option(False, "--errors", help=_("run.flag.errors")),
    since: Optional[str] = typer.Option(None, "--since", help=_("run.flag.since")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    record = _require_run(query)
    if stream not in ("stdout", "stderr"):
        output.fail(_("run.bad_stream", stream=stream))
        return
    cutoff = None
    if since is not None:
        seconds = _parse_since(since)
        if seconds is None:
            output.fail(_("run.bad_since", since=since))
            return
        cutoff = datetime.now().astimezone() - timedelta(seconds=seconds)
    cfg = state.cfg()
    path = runs.log_path(record, stream)
    content = ""
    if path is not None and path.is_file():
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            content = ""
    elif record.target != "local":
        content = runs.read_run_log(record, cfg, stream=stream, lines=max(lines, 200))
    else:
        output.fail(_("run.no_log", stream=stream))
        return

    def matches(parsed: dict) -> bool:
        return _line_matches(parsed, component, errors, cutoff)

    selected = [
        parsed
        for parsed in (parse_log_line(line) for line in content.splitlines())
        if matches(parsed)
    ][-max(lines, 0):]

    if output.wants_json(json_output):
        output.echo_json(
            {
                "run": record.run_id,
                "stream": stream,
                "lines": [
                    {
                        "timestamp": parsed["timestamp"],
                        "component": parsed["component"],
                        "severity": "ERROR" if _ERROR_RE.search(parsed["message"]) else "INFO",
                        "message": parsed["message"],
                    }
                    for parsed in selected
                ],
            }
        )
        return

    for parsed in selected:
        output.echo(parsed["line"], markup=False)

    if not follow:
        return
    if path is not None and path.is_file():
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(0, 2)
                while True:
                    line = handle.readline()
                    if line:
                        if matches(parse_log_line(line.rstrip("\n"))):
                            output.echo(line.rstrip("\n"), markup=False)
                    else:
                        if runs.effective_status(record, cfg) in (
                            runs.TERMINAL_OK,
                            runs.TERMINAL_FAIL,
                            runs.STOPPED,
                        ):
                            break
                        time.sleep(0.5)
        except KeyboardInterrupt:  # pragma: no cover
            pass
    elif record.target != "local" and record.target_transport == "ssh":
        from ..core import targets as targets_core
        import subprocess
        t = targets_core.find_target(cfg, record.target)
        if t and record.remote_run_dir:
            ssh_prefix = targets_core.target_ssh_prefix(t)
            log_file = f"{record.remote_run_dir.rstrip('/')}/{stream}.log"
            cmd = ssh_prefix + [f"tail -n 0 -f '{log_file}' 2>/dev/null"]
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            try:
                while True:
                    line = proc.stdout.readline()
                    if not line:
                        break
                    if matches(parse_log_line(line.rstrip("\n"))):
                        output.echo(line.rstrip("\n"), markup=False)
            except KeyboardInterrupt:
                pass
            finally:
                proc.terminate()


@app.command("attach", help=_("run.attach_help"))
def run_attach(query: str = typer.Argument(..., help=_("run.arg.query"))) -> None:
    record = _require_run(query)
    handles = []
    for stream in ("stdout", "stderr"):
        path = runs.log_path(record, stream)
        if path is not None:
            handles.append((stream, path.open("r", encoding="utf-8", errors="replace")))
    if not handles:
        output.fail(_("run.no_logs"))
        return
    output.echo(f"[dim]{_('run.attached', id=record.run_id)}[/dim]")
    try:
        while True:
            got_line = False
            for stream, handle in handles:
                while True:
                    line = handle.readline()
                    if not line:
                        break
                    got_line = True
                    output.echo(f"[{stream}] {line.rstrip()}", markup=False)
            if got_line:
                continue
            if runs.effective_status(record, state.cfg()) in (
                runs.TERMINAL_OK,
                runs.TERMINAL_FAIL,
                runs.STOPPED,
            ):
                break
            time.sleep(0.25)
    except KeyboardInterrupt:
        output.echo(_("run.detached", id=record.run_id))
    finally:
        for _stream, handle in handles:
            handle.close()


@app.command("stop", help=_("run.stop_help"))
def run_stop(
    query: str = typer.Argument(..., help=_("run.arg.query")),
    backend: Optional[str] = typer.Option(None, "--backend", help=_("run.flag.backend")),
) -> None:
    cfg = state.cfg()
    record = _require_run(query, backend)
    if runs.stop_run(record, config=cfg):
        output.echo(_("run.stopped", id=record.run_id))
        return
    output.fail(_("run.stop_failed", id=record.run_id))


@app.command("pause", help=_("run.pause_help"))
def run_pause(
    query: str = typer.Argument(..., help=_("run.arg.query")),
    backend: Optional[str] = typer.Option(None, "--backend", help=_("run.flag.backend")),
) -> None:
    record = _require_run(query, backend)
    if runs.pause_run(record):
        output.echo(_("run.paused", id=record.run_id))
        return
    output.fail(_("run.not_running", id=record.run_id, status=runs.effective_status(record, state.cfg())))


@app.command("resume", help=_("run.resume_help"))
def run_resume(
    query: str = typer.Argument(..., help=_("run.arg.query")),
    backend: Optional[str] = typer.Option(None, "--backend", help=_("run.flag.backend")),
) -> None:
    record = _require_run(query, backend)
    if runs.resume_run(record):
        output.echo(_("run.resumed", id=record.run_id))
        return
    output.fail(_("run.not_paused", id=record.run_id, status=runs.effective_status(record, state.cfg())))


@app.command("delete", help=_("run.delete_help"))
def run_delete(
    query: str = typer.Argument(..., help=_("run.arg.query")),
    force: bool = typer.Option(False, "--force", help=_("run.flag.force")),
) -> None:
    cfg = state.cfg()
    record = _require_run(query)
    if force and runs.effective_status(record, cfg) in (runs.RUNNING, runs.PAUSED):
        runs.stop_run(record, config=cfg)
        record = runs.load_run(cfg, record.run_id) or record
    if runs.delete_run(record):
        output.echo(_("run.deleted", id=record.run_id))
        return
    output.fail(_("run.delete_running", id=record.run_id))


def _resolve_run_root(record: runs.RunRecord, cfg: Config):
    """Return (root, location, inventory_fn) for a run's output tree.

    Kept separate so inventory, planning and collection all agree on where the
    outputs live, for both local and remote runs.
    """
    if record.target != "local" and record.target_transport == "ssh" and record.remote_run_dir:
        return record.remote_run_dir, "target", None
    if record.remote_run_dir and record.target_transport == "local":
        return record.remote_run_dir, "target", None
    if record.directory:
        return str(record.directory), "workstation", None
    return None, "workstation", None


def _load_output_declarations(config: Config):
    """Declared outputs for the experiment this project last ran, if any.

    Deliberately best-effort: a missing or unreadable experiment config must not
    block collecting the outputs that do exist.
    """
    try:
        from ..core import project as projects

        root = projects.find_project_root()
        if root is None:
            return []
        for exp_path in sorted((root / "experiments").glob("*.yaml")):
            try:
                return experiment.load_experiment(exp_path).outputs
            except Exception:
                continue
    except Exception:
        pass
    return []


def _output_root(record: runs.RunRecord, cfg: Config):
    """Where this run's *results* live.

    Results are produced relative to the run's working directory (the experiment's
    directory), not the run directory - the run directory holds caasi's
    bookkeeping and provenance. Declared outputs are resolved against that same
    working directory, so `results/*.json` means what the experiment author sees.

    Returns (root, location) or (None, ...) when the working directory is gone.
    """
    if not record.cwd:
        return None, "workstation"
    root = Path(record.cwd)
    if record.target != "local" and record.remote_run_dir:
        return root, "target"
    return root, "workstation"


def _inventory_run(record: runs.RunRecord, cfg: Config, verify: bool = False):
    """Inventory a run's produced files for either transport."""
    from ..core import targets as targets_core

    declarations = _load_output_declarations(cfg)
    policy = artifacts_mod.RoutingPolicy.from_config(cfg)

    root, location = _output_root(record, cfg)
    if root is None:
        return []

    if record.target != "local" and record.target_transport == "ssh":
        target = targets_core.find_target(cfg, record.target)
        if target is None:
            return []
        return artifacts_mod.inventory_remote(
            target, str(root), record.run_id,
            declarations=declarations, policy=policy, verify=verify,
        )

    arts = artifacts_mod.inventory_directory(
        Path(root), record.run_id, declarations=declarations, policy=policy, verify=verify
    )
    for art in arts:
        art.location = location
    return arts


def _build_artifact_record(record: runs.RunRecord, cfg: Config, artifacts) -> artifacts_mod.ArtifactRecord:
    return artifacts_mod.ArtifactRecord(
        run_id=record.run_id,
        project=record.project,
        target_name=record.target,
        target_transport=record.target_transport,
        run_status=runs.effective_status(record, cfg),
        deployment_id=record.deployment_id,
        build_id=record.build_id,
        git_revision=record.git_revision,
        remote_run_dir=record.remote_run_dir,
        artifacts=list(artifacts),
    )


@app.command("artifacts", help=_("run.artifacts_help"))
def run_artifacts(
    query: str = typer.Argument(..., help=_("run.arg.query")),
    collect: bool = typer.Option(
        False, "--collect", help=_("run.flag.collect")
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("run.flag.artifacts_dry_run")),
    verify: bool = typer.Option(
        False, "--verify", help=_("run.flag.verify")
    ),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    """List, and optionally collect, a run's produced artifacts.

    Unclassified artifacts are left where they were produced and their location is
    recorded; only artifacts routed to the workstation are copied. Nothing is ever
    deleted.
    """
    cfg = state.cfg()
    record = _require_run(query)

    inventory = _inventory_run(record, cfg, verify=verify)
    art_record = _build_artifact_record(record, cfg, inventory)

    if collect:
        plan = artifacts_mod.plan_collection(inventory)
        if output.wants_json(json_output) and dry_run:
            output.echo_json({**art_record.to_dict(), "plan": plan.to_dict()})
            return
        if dry_run:
            output.echo(f"[bold]{_('run.artifacts_plan')}[/bold] [dim]({record.run_id})[/dim]")
            output.echo(f"  {_('run.artifacts_to_fetch')}: {len(plan.to_fetch)}")
            for art in plan.to_fetch:
                output.echo(f"    {art.path}", markup=False)
            output.echo(f"  {_('run.artifacts_to_leave')}: {len(plan.to_leave)}")
            for art in plan.to_leave:
                output.echo(f"    {art.path}", markup=False)
            output.echo(f"  [dim]{_('run.artifacts_dry_note')}[/dim]")
            return

        if plan.to_fetch:
            if record.directory is None:
                output.fail(_("run.artifacts_no_dir"))
                raise typer.Exit(1)
            from ..core import targets as targets_core

            target = targets_core.find_target(cfg, record.target)
            host_root = Path(record.directory) / "artifacts"
            root = record.remote_run_dir or str(record.directory)
            if target is not None and record.target_transport == "ssh":
                artifacts_mod.collect_artifacts(
                    target, root, inventory, host_root, dry_run=False
                )
            else:
                # Local sandbox target: copy from its path into the run dir.
                import shutil

                written = []
                for art in plan.to_fetch:
                    src = Path(art.abs_path)
                    dst = host_root / art.path
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        shutil.copy2(src, dst)
                        art.collected_to = str(dst)
                        written.append(str(dst))
                    except OSError as err:
                        art_record.errors.append(f"{art.path}: {err}")

        # E1.5: after an ephemeral deployment's declared results are collected,
        # record that the target MAY be released. Recording only - caasi never
        # deletes or releases anything here.
        releasable_note = None
        if record.deployment_id and record.target != "local":
            changed, detail = artifacts_mod.mark_deployment_releasable(art_record, cfg)
            if changed:
                releasable_note = detail

        saved = artifacts_mod.save_artifact_record(art_record, Path(record.directory)) if record.directory else None
        if output.wants_json(json_output):
            output.echo_json({**art_record.to_dict(), "saved": str(saved) if saved else None})
            return
        output.echo(
            f"[green]{_('run.artifacts_collected', id=record.run_id, count=len(plan.to_fetch))}[/green]"
        )
        if saved:
            output.echo(f"  [dim]{_('run.artifacts_saved', path=str(saved))}[/dim]")
        if releasable_note:
            output.echo(f"  [dim]{_('run.artifacts_releasable', note=releasable_note)}[/dim]")
        return

    # Plain listing (no collection).
    if output.wants_json(json_output):
        output.echo_json(art_record.to_dict())
        return
    output.echo(f"[bold]{_('run.artifacts_title')}[/bold] [dim]({record.run_id})[/dim]")
    output.echo(f"  {_('run.artifacts_location')}: {record.target} ({record.target_transport})")
    if not inventory:
        output.echo(f"  [dim]{_('run.artifacts_none')}[/dim]")
        return
    from ..utils.sysinfo import human_bytes

    table = Table(header_style="bold", **output.table_styles())
    table.add_column(_("run.col.artifact"))
    table.add_column(_("run.col.kind"))
    table.add_column(_("run.col.size"), justify="right")
    table.add_column(_("run.col.route"))
    for art in sorted(inventory, key=lambda a: a.path):
        table.add_row(
            art.path, art.kind, human_bytes(art.size_bytes),
            art.route.destination,
        )
    output.echo(table)
    output.echo(
        f"  [dim]{_('run.artifacts_total', count=len(inventory), size=human_bytes(art_record.total_bytes))}[/dim]"
    )


@app.command("inspect", help=_("run.inspect_help"))
def run_inspect(
    query: str = typer.Argument(..., help=_("run.arg.query")),
    json_output: bool = typer.Option(False, "--json", help=_("flag.json")),
) -> None:
    cfg = state.cfg()
    record = _require_run(query)
    files = runs.inspect_run_files(record, cfg)
    payload = {**record.to_dict(cfg), "files": files}
    if output.wants_json(json_output):
        output.echo_json(payload)
        return
    output.echo(f"[bold]{record.name}[/bold] [dim]({record.run_id})[/dim]")
    dir_label = "Remote Directory" if record.target != "local" and record.remote_run_dir else "Directory"
    dir_val = record.remote_run_dir if record.target != "local" and record.remote_run_dir else str(record.directory)
    output.echo(f"  {dir_label}: {dir_val}")
    output.echo(f"  Target:    {record.target} ({record.target_transport})")
    output.echo(f"  Status:    {payload['status']}")
    if not files:
        output.echo(f"  [dim]{_('run.no_files')}[/dim]")
        return
    table = Table(header_style="bold", **output.table_styles())
    table.add_column(_("run.col.file"))
    table.add_column(_("run.col.size"), justify="right")
    from ..utils.sysinfo import human_bytes

    for item in files:
        table.add_row(item["path"], human_bytes(item["size"]))
    output.echo(table)
