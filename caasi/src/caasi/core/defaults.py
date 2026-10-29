"""The chosen target and project — what a command acts on when it is not told.

Named after the configuration section it is stored in. Not to be confused with
:mod:`caasi.core.selection`, which answers a different question: whether a target *can* satisfy a
project's requirements. This module answers *which* target and project the operator is working on.

A **target** is a machine (``swjtumover-05``, ``local``). A **project** is what lives in a
directory with a ``caasi.yaml`` (``swjtumover``, ``openmover``).

Both can be *chosen* once instead of repeated on every command:

    caasi choose target swjtumover-05
    caasi choose project ~/work/swjtumover

The choice is stored in the ``defaults`` section of the configuration, which is what that section is
for: the things a command does when it is not told otherwise. ``caasi choose --session`` prints shell
``export`` lines instead, so a choice can be scoped to one terminal with
``eval "$(caasi choose --session target swjtumover-05)"``.

Precedence, highest first:

    explicit flag (--target)  >  session environment  >  chosen default  >  local / current directory

Two rules make a chosen machine safe to leave in place:

* an explicit flag always wins, so a one-off does not disturb the choice;
* :func:`target_origin` reports *where* the answer came from, so a command can say which machine it
  is about to touch instead of leaving the operator to assume.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .config import Config

#: Environment variable holding a target chosen for one shell.
ENV_TARGET = "CAASI_TARGET"
#: Environment variable holding a project chosen for one shell.
ENV_PROJECT = "CAASI_PROJECT"
#: Environment variable holding a robot chosen for one shell.
ENV_ROBOT = "CAASI_ROBOT"
#: The implicit target: this machine.
LOCAL = "local"

#: Where a resolved answer came from, in the order they are tried.
ORIGIN_FLAG = "flag"
ORIGIN_SESSION = "session"
ORIGIN_SELECTION = "selection"
ORIGIN_DEFAULT = "default"


def session_target() -> str | None:
    """A target chosen for this shell with ``caasi choose --session``, if any."""
    value = os.environ.get(ENV_TARGET)
    return value.strip() if value and value.strip() else None


def session_project() -> Path | None:
    """A project chosen for this shell, if any. Never validated here; callers check the manifest."""
    value = os.environ.get(ENV_PROJECT)
    if not value or not value.strip():
        return None
    return Path(value.strip()).expanduser()


def _configured_target(config: "Config | None") -> str | None:
    if config is None:
        return None
    value = config.get("defaults.target")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _configured_project(config: "Config | None") -> Path | None:
    if config is None:
        return None
    value = config.get("defaults.project")
    if value is None:
        return None
    text = str(value).strip()
    return Path(text).expanduser() if text else None


def target_origin(config: "Config | None", explicit: str | None = None) -> str:
    """Where the effective target came from: flag, session, selection, or default."""
    if explicit and str(explicit).strip():
        return ORIGIN_FLAG
    if session_target() is not None:
        return ORIGIN_SESSION
    if _configured_target(config) is not None:
        return ORIGIN_SELECTION
    return ORIGIN_DEFAULT


def resolve_target_name(config: "Config | None", explicit: str | None = None) -> str:
    """The target a command should act on.

    ``explicit`` is the ``--target`` value, which always wins. Otherwise the session choice, then the
    chosen default, then :data:`LOCAL`. Never returns an empty string.
    """
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    session = session_target()
    if session is not None:
        return session
    configured = _configured_target(config)
    if configured is not None:
        return configured
    return LOCAL


def resolve_project_root(config: "Config | None") -> Path | None:
    """The chosen project as a local directory, when that is what it is."""
    """The project directory to act on when the working directory is not inside one.

    Returns ``None`` when nothing has been chosen, leaving the caller to use the working directory.
    The path is only checked for a manifest, not interpreted.
    """
    session = session_project()
    if session is not None:
        return session
    configured = _configured_project(config)
    if configured is None:
        return None
    if configured.is_absolute() or str(configured).startswith("."):
        return configured
    # a bare name chosen from the caasi tree
    return _local_project_path(str(configured)) or configured


def target_note(config: "Config | None", explicit: str | None = None) -> str | None:
    """A one-line description of the target a command will act on, or None when it was explicit.

    Commands that change a machine print this: acting on the wrong robot is the failure a chosen
    default makes possible, and saying which machine is being touched costs one dim line.
    """
    origin = target_origin(config, explicit)
    if origin == ORIGIN_FLAG:
        return None
    name = resolve_target_name(config, explicit)
    if name == LOCAL:
        return (
            "target: local (nothing chosen; 'caasi choose target <name>' to pick a machine)"
        )
    return f"target: {name} (from {origin})"


def describe(config: "Config | None") -> dict[str, Any]:
    """A report of the current selection, with the origin of each answer."""
    from .project import PROJECT_FILE, find_project_root

    cwd_project = find_project_root()
    chosen_project = resolve_project_root(config)
    target = resolve_target_name(config)
    machine, notice = working_machine(config)
    robot_value = str(config.get("defaults.robot")) if config and config.get("defaults.robot") else None
    project_value = str(config.get("defaults.project")) if config and config.get("defaults.project") else None

    def located(kind: str, value: str | None) -> dict[str, Any] | None:
        if not value:
            return None
        name = name_from(kind, value)
        found = [loc.to_dict() for loc in search(config, kind, name) if loc.exists]
        return {"name": name, "found": found}

    return {
        "target": target,
        "target_origin": target_origin(config),
        "session_target": session_target(),
        "configured_target": _configured_target(config),
        "machine_notice": notice,
        "robot": located("robot", robot_value),
        "project": located("project", project_value),
        "cwd_project": str(cwd_project) if cwd_project else None,
        "chosen_project": str(chosen_project) if chosen_project else None,
        "session_robot": os.environ.get(ENV_ROBOT) or None,
        "session_project": (
            str(session_project()) if session_project() is not None else None
        ),
        "role_targets": {
            role: str(value)
            for role, value in (
                (config.get("defaults.targets") or {}).items() if config else []
            )
        },
        "configured_robot": (
            str(config.get("defaults.robot")) if config and config.get("defaults.robot") else None
        ),
        "configured_project": (
            str(_configured_project(config)) if _configured_project(config) else None
        ),
    }


# ---------------------------------------------------------------------------
# Finding a robot or a project by name
# ---------------------------------------------------------------------------
#
# caasi owns a fixed tree on every machine it manages (``core/layout.py``):
#
#     ~/caasi/robots/<name>      the shipped robot: its code and deployed environment
#     ~/caasi/projects/<name>    your own work, which uses that robot's topics and services
#     ~/caasi/workspaces/<name>  a source checkout
#
# A bare name is therefore enough, and it is searched on the machine you are working on: the chosen
# target when there is one, otherwise this computer. A path is still accepted for anything outside
# the tree.

#: Kind name -> the layout roots that may hold it, in search order.
KIND_ROOTS = {
    "robot": ("robots",),
    "project": ("projects", "workspaces"),
}

#: Said out loud when a name is searched with no target chosen.
NO_TARGET_NOTICE = "no target set, defaulting to local machine"


@dataclass
class Location:
    """Where a named robot or project was found, and whether it was really there."""

    kind: str
    name: str
    machine: str
    path: str
    exists: bool
    transport: str = "local"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "machine": self.machine,
            "path": self.path,
            "exists": self.exists,
            "transport": self.transport,
        }


def working_machine(config: "Config | None") -> tuple[str, str | None]:
    """The machine a name is searched on, and a notice when it had to fall back.

    ``("local", notice)`` when no target is chosen -- said out loud, because a search that silently
    looked somewhere else is how the wrong copy gets used.
    """
    target = resolve_target_name(config)
    if target == LOCAL:
        return LOCAL, NO_TARGET_NOTICE
    return target, None


def name_from(kind: str, value: str) -> str:
    """The name a stored value refers to, if it came from the caasi tree (``~/caasi/robots/x``)."""
    for root in KIND_ROOTS.get(kind, ()):
        prefix = f"~/caasi/{root}/"
        if value.startswith(prefix):
            return value[len(prefix):].strip("/")
    return value


def _local_project_path(name: str) -> Path | None:
    """A local project of that name in the caasi tree, so a chosen name is still a directory."""
    from pathlib import Path

    from .project import PROJECT_FILE

    for relative in _candidates("project", name):
        candidate = Path("~/caasi").expanduser() / relative
        if (candidate / PROJECT_FILE).is_file():
            return candidate
    return None


def _candidates(kind: str, name: str) -> list[str]:
    return [f"{root}/{name}" for root in KIND_ROOTS.get(kind, ())]


def _local_exists(relative: str) -> bool:
    from pathlib import Path

    from .project import PROJECT_FILE

    return (Path("~/caasi").expanduser() / relative / PROJECT_FILE).is_file()


def _target_exists(target, relative: str) -> bool:
    from . import execution

    request = execution.ExecRequest(argv=["test", "-f", f"~/caasi/{relative}/caasi.yaml"])
    try:
        result = execution.run_on_target(target, request)
    except Exception:
        # An unreachable target is "cannot tell", which the caller reports as not found.
        return False
    return bool(result.ok)


def search(config: "Config | None", kind: str, name: str) -> list[Location]:
    """Every place *kind* called *name* could be: the working machine first, then this one.

    The other side is inspected too, so the report can say "it is on the robot but not here" --
    a different answer from "nowhere", and the difference decides what to do next.
    """
    from . import targets as targets_core

    machine, _ = working_machine(config)
    found: list[Location] = []
    for relative in _candidates(kind, name):
        if machine == LOCAL:
            found.append(
                Location(kind, name, LOCAL, f"~/caasi/{relative}", _local_exists(relative))
            )
        else:
            target = targets_core.find_target(config, machine) if config else None
            exists = _target_exists(target, relative) if target is not None else False
            found.append(
                Location(kind, name, machine, f"~/caasi/{relative}", exists,
                         getattr(target, "transport", "ssh"))
            )
    if machine != LOCAL:
        for relative in _candidates(kind, name):
            if _local_exists(relative):
                found.append(Location(kind, name, LOCAL, f"~/caasi/{relative}", True))
    return found


def resolve_named(config: "Config | None", kind: str, value: str) -> Location | None:
    """The first place *value* exists, or None.

    An existing local directory is accepted as given, for anything outside the caasi tree.
    """
    from pathlib import Path

    from .project import PROJECT_FILE

    candidate = Path(value).expanduser()
    if candidate.is_dir() and (candidate / PROJECT_FILE).is_file():
        return Location(kind, value, LOCAL, str(candidate.resolve()), True)
    for location in search(config, kind, value):
        if location.exists:
            return location
    return None


# ---------------------------------------------------------------------------
# Roles: which machine a *kind* of work needs
# ---------------------------------------------------------------------------
#
# One current machine is not enough once work divides by capability. A robot has no GPU, so
# simulation cannot run on it; a GPU server has no wheels, so hardware cannot run there. A role is a
# tag on a target (``robot``, ``gpu``) plus the choice of which target fills it:
#
#     caasi choose target gpu-01 --role gpu
#     caasi choose target swjtumover05 --role robot
#
# A role never falls back to the general chosen target: sending a simulation to the robot because it
# happens to be the current machine would be worse than running it here, where caasi can at least say
# what the machine lacks.

ROLE_GPU = "gpu"


def role_env(role: str) -> str:
    """Environment variable holding a role's target for one shell."""
    return f"CAASI_TARGET_{role.upper()}"


def resolve_role_target_name(
    config: "Config | None", role: str, explicit: str | None = None
) -> str:
    """The machine work of *role* should run on: explicit, then the role's choice, then this one.

    Deliberately does **not** consult the general chosen target. ``caasi choose target swjtumover05``
    says which machine commands act on; it does not claim the robot can simulate.
    """
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    session = os.environ.get(role_env(role))
    if session and session.strip():
        return session.strip()
    if config is not None:
        value = config.get(f"defaults.targets.{role}")
        if value is not None and str(value).strip():
            return str(value).strip()
    return LOCAL


def role_note(config: "Config | None", role: str, explicit: str | None = None) -> str | None:
    """A line saying which machine *role* work will run on, or None when it was explicit."""
    if explicit and str(explicit).strip():
        return None
    name = resolve_role_target_name(config, role, explicit)
    if name == LOCAL:
        return (
            f"{role}: local (no {role} target chosen; "
            f"'caasi choose target <name> --role {role}' to send it elsewhere)"
        )
    return f"{role}: {name} (from defaults.targets.{role})"
