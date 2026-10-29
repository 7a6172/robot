"""Persistent runtime lifecycle.

Answers: *if caasi deploys software to a long-lived target such as a robot, how
does caasi install / configure / enable / verify / manage that deployment over
time?*

Lifecycle model::

    deploy -> install -> enable -> start -> operate -> update -> verify -> rollback

Boundary, held strictly:

* **caasi owns identity, declaration, invocation, verification and provenance.**
* **The native mechanism owns running the thing.** caasi writes the unit a project
  declares, installs it, enables it, and then *asks systemd* whether it is enabled
  and running. caasi has no restart loop, no dependency graph and no process table
  of its own - it is not a supervisor.

Two persistent concerns are kept separate, because conflating them is what made
the reference deployment unverifiable:

``environment``
    A shell (or a unit, or a container) must be able to find ROS and the project
    overlay. The ROS 1 reference solved this by appending to ``~/.bashrc``. That is
    shell-specific, not idempotent, and not verifiable, so caasi instead declares
    the environment and renders it into the form the target needs.
``runtime``
    The stack should start itself and come back after reboot. The reference never
    solved this; caasi declares an entrypoint and delegates enablement and startup
    to the native mechanism.

Nothing here deletes anything. ``rollback`` reinstalls a previous revision; it does
not remove the newer one.
"""

from __future__ import annotations

import json
import shlex
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import Config
from .targets import Target, remote_path_expr, target_ssh_prefix

# The native mechanisms caasi knows how to invoke. Only systemd is implemented;
# the registry shape is left open so a container restart policy or another init
# can be added later without changing the lifecycle model.
BACKEND_SYSTEMD = "systemd"
KNOWN_BACKENDS = (BACKEND_SYSTEMD,)

# Filenames caasi owns on the target. Kept in the deployment root so everything
# caasi installed is discoverable in one place.
REVISION_MARKER = ".caasi-runtime.json"
ENV_FRAGMENT = ".caasi-env.sh"

DEFAULT_RESTART = "on-failure"


class RuntimeLifecycleError(ValueError):
    """Raised for an invalid runtime declaration or an unusable lifecycle request."""


# ---------------------------------------------------------------------------
# Declaration
# ---------------------------------------------------------------------------


@dataclass
class RuntimeDeclaration:
    """A project's declared persistent runtime.

    ``environment`` is the generalisation of the reference's ``.bashrc`` appends:
    a list of shell snippets (usually ``source`` lines) that establish the
    environment the entrypoint needs. It is data, so it can be rendered into a
    shell fragment, a unit ``EnvironmentFile``, or a container env list.
    """

    kind: str = BACKEND_SYSTEMD
    unit: str | None = None
    entrypoint: str | None = None
    environment: list[str] = field(default_factory=list)
    working_dir: str | None = None
    restart: str = DEFAULT_RESTART
    description: str | None = None

    @property
    def declared(self) -> bool:
        """Whether the project actually asked for a persistent runtime."""
        return bool(self.unit and self.entrypoint)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_runtime(raw: Any) -> RuntimeDeclaration:
    """Parse a manifest ``runtime:`` block.

    Permissive about shape, strict about meaning: a declaration without both a
    unit and an entrypoint is treated as *not declared* rather than as a broken
    service, so a project can add the block incrementally.
    """
    if raw is None:
        return RuntimeDeclaration()
    if not isinstance(raw, dict):
        raise RuntimeLifecycleError("'runtime' must be a mapping")

    kind = str(raw.get("kind") or BACKEND_SYSTEMD)
    if kind not in KNOWN_BACKENDS:
        raise RuntimeLifecycleError(
            f"unknown runtime kind '{kind}' (known: {', '.join(KNOWN_BACKENDS)})"
        )

    env = raw.get("environment") or []
    if isinstance(env, str):
        env = [env]
    if not isinstance(env, list):
        raise RuntimeLifecycleError("'runtime.environment' must be a list of shell lines")

    return RuntimeDeclaration(
        kind=kind,
        unit=(str(raw["unit"]) if raw.get("unit") else None),
        entrypoint=(str(raw["entrypoint"]).strip() if raw.get("entrypoint") else None),
        environment=[str(e) for e in env],
        working_dir=(str(raw["working_dir"]) if raw.get("working_dir") else None),
        restart=str(raw.get("restart") or DEFAULT_RESTART),
        description=(str(raw["description"]) if raw.get("description") else None),
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def split_environment(entries: list[str]) -> tuple[list[str], list[str]]:
    """Partition declared environment lines into (exports, sources).

    Two different things are declared in one list, and they need different
    treatment. ``export A=B`` sets a variable for the unit; ``source X`` only
    affects a login shell. systemd's ``EnvironmentFile`` understands assignment
    lines but **not** ``source``, which is why they cannot be rendered together.
    """
    exports: list[str] = []
    sources: list[str] = []
    for entry in entries:
        stripped = entry.strip()
        if stripped.startswith("source ") or stripped.startswith(". "):
            sources.append(stripped)
        else:
            exports.append(stripped)
    return exports, sources


def resolve_environment_line(line: str, destination: str) -> str:
    """Resolve one declared environment line against a deployment destination.

    ``{{dest}}`` is substituted first; a relative ``source`` target is then
    resolved against the destination. Doing this in one pass avoids the double
    prefixing that happens if substitution and prefixing are applied in sequence.
    """
    resolved = line.replace("{{dest}}", destination.rstrip("/"))
    if not resolved.startswith("source ") and not resolved.startswith(". "):
        return resolved

    keyword, _, path = resolved.partition(" ")
    path = path.strip()
    if path.startswith("/") or path.startswith("~") or path.startswith("$"):
        target = path
    else:
        target = f"{destination.rstrip('/')}/{path.lstrip('./')}"
    return f"{keyword} {target}"


def render_env_fragment(decl: RuntimeDeclaration, destination: str) -> str:
    """Render the declared environment as a systemd ``EnvironmentFile``.

    This replaces appending to ``~/.bashrc``: it is one owned file, rewritten
    wholesale on each install (so it is idempotent), and it can be read back to
    verify it.

    **Syntax matters.** systemd parses ``KEY=VALUE`` lines and rejects shell
    syntax: a line like ``export KEY=VALUE`` is logged as *"Ignoring invalid
    environment assignment"* and silently dropped, leaving the service running
    with a missing variable. That was measured on the real target during this
    stage, so assignments are normalised to the form systemd accepts rather than
    passed through. ``source`` lines cannot be expressed here at all and are
    handled by the entrypoint instead (see ``render_systemd_unit``).
    """
    exports, _sources = split_environment(decl.environment)
    lines = [
        "# Generated by caasi. Do not edit; changes are overwritten on install.",
        "# systemd EnvironmentFile syntax: KEY=VALUE only (no shell syntax).",
        f"# deployment destination: {destination}",
        "",
    ]
    for entry in exports:
        line = resolve_environment_line(entry, destination)
        if line.startswith("export "):
            line = line[len("export "):]
        lines.append(line)
    lines.append("")
    return "\n".join(lines)


def render_systemd_unit(
    decl: RuntimeDeclaration,
    destination: str,
) -> str:
    """Render a systemd unit from the project's declaration.

    caasi supplies the structure (working directory, environment wiring, restart
    policy) and the project supplies the entrypoint. The unit is a *rendering of a
    declaration*, not a caasi-owned service definition: everything that describes
    what the robot does comes from the project.
    """
    if not decl.declared:
        raise RuntimeLifecycleError("cannot render a unit for an undeclared runtime")

    workdir = decl.working_dir or "."
    if workdir.startswith("/") or workdir.startswith("~"):
        resolved_workdir = workdir
    else:
        resolved_workdir = f"{destination.rstrip('/')}/{workdir.lstrip('./')}"

    description = decl.description or f"caasi-managed runtime ({decl.unit})"
    env_file = f"{destination.rstrip('/')}/{ENV_FRAGMENT}"

    # `source` lines cannot live in a systemd EnvironmentFile, so they are applied
    # by the login shell that runs the entrypoint. `/usr/bin/env bash -lc` runs a
    # login shell, which is also what makes a robot's interactive environment and
    # its service environment agree instead of diverging.
    _exports, sources = split_environment(decl.environment)
    source_lines = [resolve_environment_line(src, destination) for src in sources]
    if source_lines:
        joined = " && ".join(source_lines)
        exec_line = f"{joined} && exec {decl.entrypoint}"
    else:
        exec_line = f"exec {decl.entrypoint}"

    return (
        "[Unit]\n"
        f"Description={description}\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"WorkingDirectory={resolved_workdir}\n"
        f"EnvironmentFile=-{env_file}\n"
        f"ExecStart=/usr/bin/env bash -lc {shlex.quote(exec_line)}\n"
        f"Restart={decl.restart}\n"
        "RestartSec=5\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


# ---------------------------------------------------------------------------
# Remote execution helper
# ---------------------------------------------------------------------------


def _ssh(target: Target, argv: list[str], timeout: float | None = None):
    """Run argv locally or on an SSH target. Mirrors runtimes.run_on_target."""
    from ..utils import shell

    budget = timeout if timeout is not None else max(30.0, float(target.ssh_timeout) * 2)
    if target.transport != "ssh":
        return shell.run_cmd(argv, timeout=budget)
    prefix = target_ssh_prefix(target)
    return shell.run_cmd([*prefix, shlex.join([str(a) for a in argv])], timeout=budget)


def _write_remote(target: Target, path: str, content: str, timeout: float | None = None):
    """Write a file on the target.

    Remote writes pipe the content through ssh's stdin, so no extra transfer tool
    is required and the file lands atomically enough for a unit or marker.
    """
    from ..utils import shell

    budget = timeout if timeout is not None else max(30.0, float(target.ssh_timeout) * 2)

    if target.transport != "ssh":
        try:
            p = Path(path).expanduser()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        except OSError as err:
            return shell.ShellResult(1, "", str(err))
        return shell.ShellResult(0, "", "")

    import subprocess

    # A path like "~/caasi/..." must expand on the target: quoting it whole makes `cat >` write to a
    # directory literally named "~", which then fails or scatters files.
    cmd = (
        f"mkdir -p {remote_path_expr(str(Path(path).parent))} && "
        f"cat > {remote_path_expr(path)}"
    )
    prefix = target_ssh_prefix(target)
    try:
        proc = subprocess.run(prefix + [cmd], input=content, text=True,
                              capture_output=True, timeout=budget)
    except subprocess.TimeoutExpired:
        return shell.ShellResult(-1, "", f"timed out writing {path}")
    return shell.ShellResult(proc.returncode, proc.stdout, proc.stderr)


def _read_remote(target: Target, path: str, timeout: float | None = None) -> str | None:
    result = _ssh(target, ["cat", path], timeout=timeout)
    return result.stdout if result.ok else None


# ---------------------------------------------------------------------------
# Revision identity
# ---------------------------------------------------------------------------


@dataclass
class RuntimeState:
    """What caasi installed and last verified on a target."""

    deployment_id: str | None = None
    git_revision: str | None = None
    installed_at: str | None = None
    unit: str | None = None
    kind: str = BACKEND_SYSTEMD
    destination: str | None = None
    previous: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RuntimeState":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in (data or {}).items() if k in known})


def marker_path(destination: str) -> str:
    return f"{destination.rstrip('/')}/{REVISION_MARKER}"


def read_runtime_state(target: Target, destination: str, timeout: float | None = None) -> RuntimeState | None:
    """Read the revision marker caasi wrote during install, if any."""
    text = _read_remote(target, marker_path(destination), timeout=timeout)
    if not text:
        return None
    try:
        return RuntimeState.from_dict(json.loads(text))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Lifecycle operations
# ---------------------------------------------------------------------------


@dataclass
class LifecycleResult:
    """Outcome of one lifecycle operation."""

    operation: str
    ok: bool
    target: str
    detail: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class InstallPlan:
    """Everything install would write, before it writes anything."""

    destination: str
    unit_name: str
    unit_path: str
    env_fragment_path: str
    marker: dict[str, Any]
    env_fragment: str
    unit_contents: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def systemd_user_unit_dir(target: Target) -> str:
    """Where a user unit lives on the target. systemd decides the path."""
    result = _ssh(target, ["bash", "-lc", 'echo "$HOME/.config/systemd/user"'])
    path = (result.stdout or "").strip()
    return path or "~/.config/systemd/user"


def plan_install(
    target: Target,
    decl: RuntimeDeclaration,
    destination: str,
    deployment_id: str,
    git_revision: str | None,
    project: str | None = None,
    previous: dict[str, Any] | None = None,
) -> InstallPlan:
    """Compute everything install would do. Pure - performs only a path lookup."""
    if not decl.declared:
        raise RuntimeLifecycleError(
            "project declares no 'runtime:' block, so there is nothing to install "
            "(add a runtime: block with a unit and entrypoint)"
        )

    unit_dir = systemd_user_unit_dir(target)
    unit_path = f"{unit_dir.rstrip('/')}/{decl.unit}"

    marker = {
        "deployment_id": deployment_id,
        "git_revision": git_revision,
        "installed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "unit": decl.unit,
        "kind": decl.kind,
        "destination": destination,
        "project": project,
        "previous": previous,
    }

    return InstallPlan(
        destination=destination,
        unit_name=str(decl.unit),
        unit_path=unit_path,
        env_fragment_path=f"{destination.rstrip('/')}/{ENV_FRAGMENT}",
        marker=marker,
        env_fragment=render_env_fragment(decl, destination),
        unit_contents=render_systemd_unit(decl, destination),
    )


def install_runtime(
    target: Target,
    decl: RuntimeDeclaration,
    destination: str,
    deployment_id: str,
    git_revision: str | None,
    project: str | None = None,
    dry_run: bool = False,
    previous_state: RuntimeState | None = None,
    timeout: float | None = None,
) -> tuple[LifecycleResult, InstallPlan]:
    """Install the declared runtime: environment fragment, unit, revision marker.

    Writes only within the deployment destination and the target's own user-unit
    directory. It does not enable or start anything - those are separate steps, so
    a failure part-way through is visible rather than half-applied invisibly.
    """
    prior = previous_state.to_dict() if previous_state else None
    plan = plan_install(target, decl, destination, deployment_id, git_revision,
                        project=project, previous=prior)

    if dry_run:
        return LifecycleResult("install", True, target.name,
                               detail="dry run - nothing written", data=plan.to_dict()), plan

    failures: list[str] = []

    env_res = _write_remote(target, plan.env_fragment_path, plan.env_fragment, timeout=timeout)
    if not env_res.ok:
        failures.append(f"environment fragment: {env_res.stderr.strip() or env_res.returncode}")

    unit_res = _write_remote(target, plan.unit_path, plan.unit_contents, timeout=timeout)
    if not unit_res.ok:
        failures.append(f"unit file: {unit_res.stderr.strip() or unit_res.returncode}")

    marker_res = _write_remote(target, marker_path(destination),
                               json.dumps(plan.marker, indent=2) + "\n", timeout=timeout)
    if not marker_res.ok:
        failures.append(f"revision marker: {marker_res.stderr.strip() or marker_res.returncode}")

    if failures:
        return LifecycleResult("install", False, target.name,
                               detail="; ".join(failures), data=plan.to_dict()), plan

    # systemd must be told the unit changed.
    _ssh(target, ["systemctl", "--user", "daemon-reload"], timeout=timeout)

    return LifecycleResult("install", True, target.name,
                           detail=f"installed {decl.unit}", data=plan.to_dict()), plan


def enable_runtime(target: Target, unit: str, enable: bool = True,
                   timeout: float | None = None) -> LifecycleResult:
    """Enable or disable a unit via systemctl. systemd owns the semantics."""
    action = "enable" if enable else "disable"
    result = _ssh(target, ["systemctl", "--user", action, unit], timeout=timeout)
    ok = result.ok
    return LifecycleResult(
        action, ok, target.name,
        detail=(result.stdout.strip() or result.stderr.strip() or None),
    )


def start_runtime(target: Target, unit: str, start: bool = True,
                  timeout: float | None = None) -> LifecycleResult:
    """Start or stop a unit via systemctl. caasi does not supervise it afterwards."""
    action = "start" if start else "stop"
    result = _ssh(target, ["systemctl", "--user", action, unit], timeout=timeout)
    return LifecycleResult(
        action, result.ok, target.name,
        detail=(result.stdout.strip() or result.stderr.strip() or None),
    )


def runtime_status(target: Target, unit: str, timeout: float | None = None) -> dict[str, Any]:
    """Ask systemd for the unit's state. Delegation only; caasi parses nothing."""
    show = _ssh(
        target,
        ["systemctl", "--user", "show", unit, "--no-pager",
         "-p", "ActiveState", "-p", "SubState", "-p", "UnitFileState",
         "-p", "MainPID", "-p", "ExecMainStatus"],
        timeout=timeout,
    )
    props: dict[str, str] = {}
    if show.ok:
        for line in show.stdout.splitlines():
            k, _, v = line.partition("=")
            props[k.strip()] = v.strip()

    enabled = _ssh(target, ["systemctl", "--user", "is-enabled", unit], timeout=timeout)
    active = _ssh(target, ["systemctl", "--user", "is-active", unit], timeout=timeout)

    return {
        "unit": unit,
        "active_state": props.get("ActiveState") or (active.stdout.strip() or None),
        "sub_state": props.get("SubState") or None,
        "unit_file_state": props.get("UnitFileState") or (enabled.stdout.strip() or None),
        "main_pid": props.get("MainPID") or None,
        "exec_main_status": props.get("ExecMainStatus") or None,
        "enabled": (props.get("UnitFileState") == "enabled"),
        "running": (props.get("ActiveState") == "active"),
    }


def _same_revision(active: str | None, expected: str | None) -> bool:
    """Compare revisions, ignoring the ``-dirty`` suffix.

    ``-dirty`` records that the workstation tree had uncommitted changes at deploy
    time; the commit itself is the same content identity. Treating the suffix as a
    different revision would report drift where the intended code is active.
    """
    def _base(rev: str | None) -> str | None:
        if not rev:
            return rev
        return rev[:-len("-dirty")] if rev.endswith("-dirty") else rev

    return _base(active) == _base(expected) and active is not None


def verify_runtime(
    target: Target,
    unit: str,
    destination: str,
    expect_deployment_id: str | None = None,
    expect_git_revision: str | None = None,
    timeout: float | None = None,
) -> tuple[bool, list[str], dict[str, Any]]:
    """Verify the target's *active* revision matches what we believe is deployed.

    Answers the question the previous stage could not: not merely "did files
    arrive" but "is the revision we think is running actually the one installed".
    Returns (ok, problems, evidence).
    """
    problems: list[str] = []
    evidence: dict[str, Any] = {}

    state = read_runtime_state(target, destination, timeout=timeout)
    status = runtime_status(target, unit, timeout=timeout)
    evidence["runtime_state"] = state.to_dict() if state else None
    evidence["systemd"] = status

    if state is None:
        problems.append(
            f"no revision marker at {marker_path(destination)} - runtime was never installed"
        )
    else:
        evidence["active_deployment_id"] = state.deployment_id
        evidence["active_git_revision"] = state.git_revision

        # A deployment id identifies one deployment *act*, so after a rollback (which
        # redeploys) or a re-install it legitimately differs while the content is
        # correct. It is reported as evidence rather than treated as drift; the
        # revision is what decides whether the intended code is active.
        if expect_deployment_id and state.deployment_id != expect_deployment_id:
            evidence["deployment_id_matches"] = False
        else:
            evidence["deployment_id_matches"] = True

        if expect_git_revision and _same_revision(state.git_revision, expect_git_revision):
            evidence["revision_matches"] = True
        elif expect_git_revision:
            evidence["revision_matches"] = False
            problems.append(
                f"active git revision is {state.git_revision}, expected {expect_git_revision}"
            )
        if state.unit and state.unit != unit:
            problems.append(f"marker records unit {state.unit}, expected {unit}")

    if not status.get("unit_file_state") or status["unit_file_state"] in ("", "not-found"):
        problems.append(f"unit {unit} is not known to systemd (not installed)")
    elif not status.get("enabled"):
        problems.append(f"unit {unit} is installed but not enabled (state={status.get('unit_file_state')})")

    if not status.get("running"):
        problems.append(f"unit {unit} is not active (state={status.get('active_state')})")

    return (not problems), problems, evidence


def update_runtime(
    target: Target,
    decl: RuntimeDeclaration,
    destination: str,
    deployment_id: str,
    git_revision: str | None,
    project: str | None = None,
    timeout: float | None = None,
) -> tuple[LifecycleResult, InstallPlan, RuntimeState | None]:
    """Move the target from the currently active revision to a new one.

    Sequence: capture the current state (so it can be rolled back to), install the
    new revision, restart, then verify. Nothing is deleted; the previous revision
    is retained in the marker.
    """
    active = read_runtime_state(target, destination, timeout=timeout)

    # What should the new marker record as "the revision to roll back to"?
    #
    #  - A genuine update to a different revision: the revision that was active.
    #  - A reinstall of the revision already active (e.g. after a config change):
    #    the *original* rollback point must survive, otherwise repeated installs
    #    would each overwrite it and leave the marker pointing at itself.
    same_revision = (
        active is not None
        and active.deployment_id == deployment_id
        and _same_revision(active.git_revision, git_revision)
    )
    if active is None:
        rollback_to = None
    elif same_revision:
        rollback_to = RuntimeState.from_dict(active.previous) if active.previous else None
    else:
        rollback_to = RuntimeState(
            deployment_id=active.deployment_id,
            git_revision=active.git_revision,
            installed_at=active.installed_at,
            unit=active.unit,
            kind=active.kind,
            destination=active.destination,
        )

    result, plan = install_runtime(
        target, decl, destination, deployment_id, git_revision,
        project=project, previous_state=rollback_to, timeout=timeout,
    )
    if not result.ok:
        return result, plan, active

    # Restart so the new revision is actually the one running.
    _ssh(target, ["systemctl", "--user", "restart", str(decl.unit)], timeout=timeout)

    ok, problems, _ = verify_runtime(
        target, str(decl.unit), destination,
        expect_deployment_id=deployment_id,
        expect_git_revision=git_revision,
        timeout=timeout,
    )
    if not ok:
        return (
            LifecycleResult("update", False, target.name,
                            detail="installed but verification failed: " + "; ".join(problems),
                            data=plan.to_dict()),
            plan, active,
        )

    return (
        LifecycleResult("update", True, target.name,
                        detail=f"active revision is now {git_revision or deployment_id}",
                        data=plan.to_dict()),
        plan, active,
    )


def check_rollback_feasibility(
    target: Target,
    source_root,
    previous_git_revision: str | None,
    timeout: float | None = None,
) -> tuple[bool, str | None]:
    """Decide whether a truthful rollback is possible, before starting one.

    Rollback means *restoring the previous revision's content on the target*, not
    merely relabelling it. The content source is the workstation's working tree,
    so a rollback is only truthful when that tree actually holds the revision
    being rolled back to.

    Without this check, rollback would rewrite the revision marker while leaving
    the newer files in place - the marker would then report a revision that is not
    what is running. That exact inconsistency was measured on a real target during
    this stage (marker said r5 while the process ran r6), which is why rollback
    refuses rather than guesses.
    """
    from . import provenance
    from ..utils import shell

    if not previous_git_revision:
        return False, "no previous revision recorded, so there is nothing to roll back to"

    info = provenance.git_info(source_root)
    head = info.get("head") or "unversioned"

    if head == "unversioned":
        return False, (
            "the workstation working tree has no git revision, so the previous "
            "revision's content cannot be restored"
        )

    if not _same_revision(head, previous_git_revision):
        return False, (
            f"workstation is at {head} but the rollback target is "
            f"{previous_git_revision}; rollback redeploys the previous revision from "
            f"the workstation, so check out {previous_git_revision} first"
        )

    # Dirty is only disqualifying when the dirt could change deployed content.
    # caasi's own bookkeeping (`.caasi/`) is written by caasi, is excluded from
    # deployment, and must not be mistaken for the operator's uncommitted work --
    # otherwise the message tells them to check out the revision they are on.
    if info.get("dirty"):
        status = shell.run_cmd(
            ["git", "-C", str(source_root), "status", "--porcelain"], timeout=15.0
        )
        substantive = [
            line for line in (status.stdout or "").splitlines()
            if line.strip() and not line.strip().split(maxsplit=1)[-1].startswith(".caasi/")
        ]
        if substantive:
            return False, (
                f"workstation has uncommitted changes, so the content does not match "
                f"{head} and a rollback would deploy something else; commit or stash "
                f"them first ({len(substantive)} changed path(s))"
            )

    return True, None


def rollback_runtime(
    target: Target,
    decl: RuntimeDeclaration,
    destination: str,
    source_root=None,
    redeploy=None,
    timeout: float | None = None,
) -> LifecycleResult:
    """Restore the previously active revision by redeploying it from the workstation.

    Rollback is a **redeploy of the recorded previous revision**, not a marker
    rewrite. The workstation is the source of truth for content, so rolling back
    requires the workstation to be at that revision; if it is not, this refuses
    and changes nothing rather than reporting a rollback that did not happen.

    ``redeploy`` is the caller-supplied function that re-materializes the project
    (the existing deploy path); keeping it injected lets this module stay free of
    deploy specifics.
    """
    current = read_runtime_state(target, destination, timeout=timeout)
    if current is None:
        return LifecycleResult("rollback", False, target.name,
                               detail="no revision marker - nothing to roll back to")
    if not current.previous:
        return LifecycleResult("rollback", False, target.name,
                               detail="no previous revision recorded - nothing to roll back to")

    prior_state = RuntimeState.from_dict(current.previous)
    target_revision = prior_state.git_revision

    if source_root is not None:
        feasible, why = check_rollback_feasibility(target, source_root, target_revision,
                                                   timeout=timeout)
        if not feasible:
            return LifecycleResult("rollback", False, target.name, detail=why)

    if redeploy is None:
        return LifecycleResult(
            "rollback", False, target.name,
            detail="rollback requires redeploying the previous revision, which was not provided",
        )

    redeploy_result = redeploy()
    if not redeploy_result or not getattr(redeploy_result, "ok", False):
        detail = getattr(redeploy_result, "detail", None) or "redeployment of the previous revision failed"
        return LifecycleResult("rollback", False, target.name,
                               detail=f"{detail}; the target is unchanged")

    # Only now, with the previous revision's content actually present, is it
    # truthful to record it as active. The revision we are leaving becomes the new
    # "previous", so rollback is itself reversible.
    result, _plan = install_runtime(
        target, decl, destination,
        deployment_id=prior_state.deployment_id or "unknown",
        git_revision=prior_state.git_revision,
        previous_state=RuntimeState(
            deployment_id=current.deployment_id,
            git_revision=current.git_revision,
            installed_at=current.installed_at,
            unit=current.unit,
            kind=current.kind,
            destination=current.destination,
        ),
        timeout=timeout,
    )
    if not result.ok:
        return result

    _ssh(target, ["systemctl", "--user", "restart", str(decl.unit)], timeout=timeout)

    ok, problems, _evidence = verify_runtime(
        target, str(decl.unit), destination,
        expect_deployment_id=prior_state.deployment_id,
        timeout=timeout,
    )
    if not ok:
        return LifecycleResult(
            "rollback", False, target.name,
            detail="rolled back but verification failed: " + "; ".join(problems),
            data={"rolled_back_to": prior_state.to_dict(), "was": current.to_dict()},
        )

    return LifecycleResult(
        "rollback", True, target.name,
        detail=f"redeployed and activated {prior_state.git_revision or prior_state.deployment_id}",
        data={"rolled_back_to": prior_state.to_dict(), "was": current.to_dict()},
    )
