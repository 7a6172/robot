"""Sourced-ROS execution.

``ros2`` only works when ``/opt/ros/<distro>/setup.bash`` has been sourced —
an unsourced shell crashes inside ``importlib.metadata`` rather than printing
a helpful error. Caasi therefore wraps ROS commands in a sourcing shell *only
when the current environment is not already sourced*, which is a no-op for
anyone running from a normal ROS terminal.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..utils import shell
from . import ros

#: Markers that prove the ROS environment is already sourced.
SOURCE_MARKERS = ("AMENT_PREFIX_PATH", "COLCON_PREFIX_PATH", "PYTHONPATH")

ENV_TIMEOUT = 5.0

_env_cache: dict[str, dict[str, str]] = {}


def setup_file(distro: str | None = None) -> Path | None:
    """Return ``/opt/ros/<distro>/setup.bash`` when it exists."""
    name, root = ros.find_distro()
    if distro is not None:
        root = ros.ROS_ROOT / distro
    if root is None:
        return None
    candidate = root / "setup.bash"
    return candidate if candidate.is_file() else None


def project_setup_file(project_root: Path | None = None) -> Path | None:
    """Return ``<project_root>/install/setup.bash`` when it exists."""
    if project_root is None:
        env_root = os.environ.get("CAASI_PROJECT_ROOT")
        if env_root:
            cand = Path(env_root) / "install" / "setup.bash"
            if cand.is_file():
                return cand
        from . import project
        found = project.find_project_root()
        if found is not None:
            cand = found / "install" / "setup.bash"
            if cand.is_file():
                return cand
        return None
    cand = project_root / "install" / "setup.bash"
    return cand if cand.is_file() else None


def ros_root(distro: str | None = None) -> Path | None:
    _, root = ros.find_distro()
    if distro is not None:
        root = ros.ROS_ROOT / distro
    return root


def is_sourced(distro: str | None = None, project_root: Path | None = None) -> bool:
    """True when the environment already exposes the ROS install prefix and project overlay (if present)."""
    root = ros_root(distro)
    if root is None:
        return False
    needle = str(root)
    if not any(needle in os.environ.get(marker, "") for marker in SOURCE_MARKERS):
        return False
    proj_setup = project_setup_file(project_root)
    if proj_setup is not None:
        proj_prefix = str(proj_setup.parent)
        if not any(proj_prefix in os.environ.get(marker, "") for marker in SOURCE_MARKERS):
            return False
    return True


def sourced_env(distro: str | None = None, project_root: Path | None = None) -> dict[str, str]:
    """Environment after sourcing setup.bash and optional project overlay (cached; falls back to os.environ)."""
    setup = setup_file(distro)
    proj_setup = project_setup_file(project_root)
    if setup is None and proj_setup is None:
        return dict(os.environ)

    cache_key = f"{setup}:{proj_setup}"
    if cache_key in _env_cache:
        return _env_cache[cache_key]

    source_parts = []
    if setup is not None:
        source_parts.append(f'source "{setup}"')
    if proj_setup is not None:
        source_parts.append(f'source "{proj_setup}"')
    source_chain = " && ".join(source_parts)
    cmd = f"{source_chain} >/dev/null 2>&1 && env"

    result = shell.run_cmd(["bash", "-c", cmd], timeout=ENV_TIMEOUT)
    env = dict(os.environ)
    if result.ok:
        key: str | None = None
        for line in result.stdout.splitlines():
            name, sep, value = line.partition("=")
            if sep and name and not name[0].isdigit():
                key = name
                env[key] = value
            elif key is not None:
                env[key] += "\n" + line
    _env_cache[cache_key] = env
    return env


def wrap(command: list[str], distro: str | None = None, project_root: Path | None = None) -> list[str]:
    """Return *command*, sourcing ROS and project overlay first only when that is actually needed."""
    if is_sourced(distro, project_root):
        return list(command)
    setup = setup_file(distro)
    proj_setup = project_setup_file(project_root)
    if setup is None and proj_setup is None:
        return list(command)

    source_parts = []
    if setup is not None:
        source_parts.append(f'source "{setup}"')
    if proj_setup is not None:
        source_parts.append(f'source "{proj_setup}"')
    source_chain = " && ".join(source_parts)
    return ["bash", "-c", f'{source_chain} >/dev/null 2>&1 && exec "$@"', "--", *command]


def source_hint(distro: str | None = None, project_root: Path | None = None) -> str:
    """The shell line a user needs to run (used by doctor hints)."""
    setup = setup_file(distro)
    proj_setup = project_setup_file(project_root)
    hints: list[str] = []
    if setup:
        hints.append(f"source {setup}")
    if proj_setup:
        hints.append(f"source {proj_setup}")
    return " && ".join(hints)


def clear_cache() -> None:
    """Drop memoised environments (used by the test-suite)."""
    _env_cache.clear()
