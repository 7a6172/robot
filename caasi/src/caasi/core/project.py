"""Caasi projects: layout, creation, and robot/scene/task definitions.

A project is a directory containing ``caasi.yaml``. ``project init`` creates the
:data:`~caasi.core.components.BASE_DIRS`; ``project add <component>`` grows the
tree with capability subtrees (§5)::

    project/
    ├── caasi.yaml          # flat manifest (schema/name/version/components/…) + config layer
    ├── .caasi/             # internal: fingerprints, locks, provenance
    ├── robots/ scenes/ tasks/        # definition YAML (kind: robot|scene|task)
    ├── experiments/ datasets/ runs/ artifacts/ logs/
    ├── robot/urdf …        # `robot` component: asset *descriptions*
    └── isaac/sim …         # `isaac_sim` component subtree

Robot, scene and task definitions are YAML files inside ``robots/``, ``scenes/``
and ``tasks/`` respectively — note the singular ``robot/`` component subtree
holds asset files and deliberately coexists with the plural ``robots/``
definitions directory. Everything is inspectable without starting a simulation.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

import yaml

from . import components, manifest as manifests

PROJECT_FILE = manifests.MANIFEST_FILE
COMPONENT_KINDS = ("robot", "scene", "task")
KIND_DIRS = {"robot": "robots", "scene": "scenes", "task": "tasks"}

#: Base directories created by ``project init`` (re-exported from components).
PROJECT_DIRS: tuple[str, ...] = components.BASE_DIRS

#: Manifest keys that ``project validate`` understands (disjoint from config keys).
MANIFEST_KEYS: tuple[str, ...] = manifests.FIELD_ORDER


_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")

TEMPLATES: dict[str, dict[str, Any]] = {
    "robot": {
        "kind": "robot",
        "name": "",
        "description": "",
        "urdf": "",
        "usd": "",
        "dof": 0,
        "sensors": [],
        "tasks": [],
    },
    "scene": {
        "kind": "scene",
        "name": "",
        "description": "",
        "usd": "",
    },
    "task": {
        "kind": "task",
        "name": "",
        "description": "",
    },
}


class ProjectError(ValueError):
    """Raised for invalid project operations."""


def valid_name(name: str) -> bool:
    return bool(_NAME_RE.match(name))


#: True once the fallback has been decided for this process, by configuration or by an explicit
#: call. Kept separate from the value so "explicitly none" is not confused with "not looked up yet".
_fallback_decided = False

#: Guards the lazy lookup below against a configuration load that itself asks for the project root.
_resolving_fallback = False

#: A project chosen with ``caasi choose project``, used when the working directory is not inside one.
#: Process-wide because every command asks :func:`find_project_root` the same question, and threading
#: a configuration object through every caller would put the choice in seventeen places instead of
#: one. It is set once, from the configuration, by :func:`caasi.state.cfg`; nothing else writes it.
_fallback_root: Path | None = None


def set_fallback_root(root: Path | None) -> None:
    """Record the chosen project root, or clear it with ``None``.

    Only used when :func:`find_project_root` is called *without* a starting directory: a caller that
    passes an explicit start is asking about that location and must not be redirected.
    """
    global _fallback_root, _fallback_decided
    _fallback_root = Path(root).expanduser() if root is not None else None
    _fallback_decided = True


def _ensure_fallback_decided() -> None:
    """Ask the configuration which project was chosen, once, without forcing it earlier.

    A command that never touches the configuration (``caasi project info`` in a bare directory)
    still has to honour a project chosen with ``caasi choose project``, so the lookup happens here
    on first need. The flag stops a configuration load that itself asks for the project root from
    recursing.
    """
    global _resolving_fallback
    if _fallback_decided or _resolving_fallback:
        return
    _resolving_fallback = True
    try:
        from .. import state
        from . import defaults as defaults_core

        state.cfg()  # sets the fallback through `state.cfg`
        if not _fallback_decided:
            set_fallback_root(defaults_core.resolve_project_root(state.get().config))
    except Exception:
        # Never let a configuration problem turn "no project here" into a crash.
        pass
    finally:
        _resolving_fallback = False


def fallback_root() -> Path | None:
    """The chosen project root, if one is set and still holds a manifest."""
    if _fallback_root is not None and (_fallback_root / PROJECT_FILE).is_file():
        return _fallback_root
    return None


def find_project_root(start: Path | None = None) -> Path | None:
    """Walk up from *start* (default cwd) looking for ``caasi.yaml``.

    With no *start*, a project chosen with ``caasi choose project`` is used when the working
    directory is not inside one, so commands work from anywhere once a project is chosen.
    """
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / PROJECT_FILE).is_file():
            return candidate
    if start is None:
        _ensure_fallback_decided()
        return fallback_root()
    return None


def chosen_robot_root() -> Path | None:
    """The tree of the robot chosen with ``caasi choose robot``, when it is on this machine."""
    from .. import state
    from . import defaults as defaults_core

    config = state.get().config
    stored = config.get("defaults.robot") if config is not None else None
    if not stored:
        return None
    name = defaults_core.name_from("robot", str(stored))
    candidate = Path("~/caasi").expanduser() / "robots" / name
    return candidate if (candidate / PROJECT_FILE).is_file() else None


def work_roots() -> list[Path]:
    """The trees a relative path may refer to, most specific first.

    A project is your own code; a robot is the shipped tree, which on the robot *is* the deployed
    project. Both are places you stand in when you type ``experiments/bringup.yaml``, so both are
    searched -- that is what makes ``caasi choose robot swjtumover`` worth doing.
    """
    roots: list[Path] = []
    project_root = find_project_root()
    if project_root is not None:
        roots.append(project_root)
    robot_root = chosen_robot_root()
    if robot_root is not None and robot_root not in roots:
        roots.append(robot_root)
    return roots


def resolve_path(path: Path) -> Path:
    """Resolve any local path argument against the chosen project or robot.

    Same rule as :func:`resolve_in_project`, named for the general case: experiment configs, task
    scripts, map files, bags -- anything the operator names relative to the tree they are working in.
    A path that already exists (so `cd`-then-run still works) and any absolute path are untouched.
    """
    return resolve_in_project(path)


def resolve_in_project(path: Path) -> Path:
    """Resolve a relative path argument against the chosen project or robot.

    `caasi choose project` / `caasi choose robot` fix *which tree* commands act on, so an experiment
    given as ``experiments/bringup.yaml`` works from any directory -- otherwise the choice saves you
    ``-t`` and then demands ``cd``. An existing path, and any absolute path, is left alone.
    """
    if path.is_absolute() or path.exists():
        return path
    for root in work_roots():
        candidate = root / path
        if candidate.exists():
            return candidate
    return path


def load_project_meta(root: Path) -> dict[str, Any]:
    """Raw ``caasi.yaml`` as a mapping, bridged through :func:`manifest.migrate`."""
    path = root / PROJECT_FILE
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    if not isinstance(data, dict):
        return {}
    return manifests.migrate(data)


def read_manifest(root: Path) -> manifests.Manifest:
    return manifests.read(root)


def create_project(path: Path, name: str | None = None, force: bool = False) -> Path:
    """Create the project scaffold. Raises ProjectError when unsafe."""
    root = path.expanduser().resolve()
    project_file = root / PROJECT_FILE
    if project_file.is_file() and not force:
        raise ProjectError(f"'{project_file}' already exists (use --force to overwrite)")
    if root.is_file():
        raise ProjectError(f"'{root}' is a file")

    root.mkdir(parents=True, exist_ok=True)
    for sub in PROJECT_DIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)

    manifests.write(
        root,
        manifests.Manifest(name=name or root.name, version="0.0.0", schema=manifests.SCHEMA),
    )
    return root


def definitions_dir(root: Path, kind: str) -> Path:
    return root / KIND_DIRS[kind]


def _definition_path(root: Path, kind: str, name: str) -> Path:
    return definitions_dir(root, kind) / f"{name}.yaml"


def load_definition(root: Path, kind: str, name: str) -> dict[str, Any] | None:
    path = _definition_path(root, kind, name)
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def list_definitions(root: Path, kind: str) -> list[dict[str, Any]]:
    """All definitions of *kind*, sorted by name: [{name, path, data}]."""
    directory = definitions_dir(root, kind)
    if not directory.is_dir():
        return []
    entries = []
    for path in sorted(directory.glob("*.yaml")):
        data = load_definition(root, kind, path.stem) or {}
        entries.append({"name": path.stem, "path": path, "data": data})
    return entries


def save_definition(
    root: Path, kind: str, name: str, description: str = "", overwrite: bool = False
) -> Path:
    """Write a fresh definition from the template. Raises ProjectError."""
    if not valid_name(name):
        raise ProjectError(
            f"invalid name '{name}' (use letters, digits, '-' and '_')"
        )
    path = _definition_path(root, kind, name)
    if path.is_file() and not overwrite:
        raise ProjectError(f"'{path}' already exists")
    data = dict(TEMPLATES[kind])
    data["name"] = name
    if description:
        data["description"] = description
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def validate_project(root: Path) -> list[str]:
    """Component-aware validation. Returns human-readable issues (empty = valid)."""
    issues: list[str] = []
    project_file = root / PROJECT_FILE
    if not project_file.is_file():
        return [f"missing {PROJECT_FILE}"]
    try:
        raw = yaml.safe_load(project_file.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return [f"{PROJECT_FILE}: invalid YAML ({exc})"]
    if not isinstance(raw, dict):
        return [f"{PROJECT_FILE}: must be a mapping"]

    data = manifests.migrate(raw)
    schema = data.get("schema")
    if not isinstance(schema, int):
        issues.append(f"{PROJECT_FILE}: 'schema' must be an integer (got {schema!r})")
    elif schema != manifests.SCHEMA:
        issues.append(
            f"{PROJECT_FILE}: unknown schema {schema} (this Caasi understands {manifests.SCHEMA})"
        )
    if not data.get("name"):
        issues.append(f"{PROJECT_FILE}: 'name' is missing")

    requires = data.get("requires")
    if requires is not None and not isinstance(requires, dict):
        issues.append(f"{PROJECT_FILE}: 'requires' must be a mapping")

    for sub in PROJECT_DIRS:
        if not (root / sub).is_dir():
            issues.append(f"missing directory '{sub}/'")

    manifest = manifests.read(root)
    for key in manifest.registered():
        for sub in components.dirs_for(key):
            if not (root / sub).is_dir():
                issues.append(f"component '{key}': missing directory '{sub}/'")

    for kind in COMPONENT_KINDS:
        for entry in list_definitions(root, kind):
            label = f"{KIND_DIRS[kind]}/{entry['name']}.yaml"
            if not entry["data"]:
                issues.append(f"{label}: empty or invalid YAML")
                continue
            if entry["data"].get("kind") != kind:
                issues.append(f"{label}: kind is '{entry['data'].get('kind')}', expected '{kind}'")
    return issues


# -- component tree management -------------------------------------------

#: ``project add-file <domain> <kind>`` → project-relative base directory.
FILE_DOMAINS: dict[str, str] = {
    "robot": "robot",
    "isaac.sim": "isaac/sim",
    "isaac.lab": "isaac/lab",
    "ros": "ros",
    "ros2": "ros",
    "nav": "nav",
    "nav2": "nav",
    "moveit": "moveit",
}

#: ``project add-file`` kind → leaf directory name.
FILE_KIND_DIRS: dict[str, str] = {
    "urdf": "urdf",
    "xacro": "urdf",
    "usd": "usd",
    "mesh": "meshes",
    "scene": "scenes",
    "config": "config",
    "launch": "launch",
    "param": "params",
    "params": "params",
    "map": "maps",
}


def registered_components(root: Path) -> list[str]:
    return manifests.read(root).registered()


def add_component(root: Path, key: str) -> manifests.Manifest:
    """Register *key* in the manifest and create its directories."""
    manifest = manifests.add_component(root, key)
    for sub in components.dirs_for(key):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return manifest


def remove_component(
    root: Path, key: str, purge: bool = False
) -> tuple[manifests.Manifest, dict[str, list[str]]]:
    """Unregister *key*; remove now-empty dirs (``--purge`` deletes non-empty).

    Returns the updated manifest and ``{"removed": [...], "kept": [...]}`` where
    ``kept`` lists directories left behind because they were non-empty and not
    purged.
    """
    removed: list[str] = []
    kept: list[str] = []
    for sub in components.dirs_for(key):
        directory = root / sub
        if not directory.is_dir():
            continue
        if purge:
            shutil.rmtree(directory, ignore_errors=True)
            removed.append(sub)
            continue
        try:
            directory.rmdir()
            removed.append(sub)
        except OSError:
            kept.append(sub)
    manifest = manifests.remove_component(root, key)
    return manifest, {"removed": removed, "kept": kept}


def placement_dir(root: Path, domain: str, kind: str) -> Path:
    """Deterministic destination directory for ``project add-file``."""
    normalized = domain.strip().lower().replace("-", "_").replace(".", "_")
    dotted = normalized.replace("_", ".")
    base = (
        FILE_DOMAINS.get(dotted)
        or FILE_DOMAINS.get(normalized)
        or normalized.replace("_", "/")
    )
    leaf = FILE_KIND_DIRS.get(kind.strip().lower(), kind.strip().lower())
    return root / base / leaf


def place_file(root: Path, domain: str, kind: str, source: Path) -> Path:
    """Copy *source* into its deterministic location; returns the new path."""
    source = source.expanduser()
    if not source.is_file():
        raise ProjectError(f"'{source}' is not a file")
    dest_dir = placement_dir(root, domain, kind)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / source.name
    shutil.copy2(source, dest)
    return dest

