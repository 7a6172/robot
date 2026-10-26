"""The caasi directory layout on a target.

caasi -- not the user -- decides where things live on a machine it manages, so that a
new target needs no convention debate and every command looks in the same place. The
layout is a fixed tree rooted at ``~/caasi``:

    ~/caasi/
    ├── robots/       physical robots and their deployed environments
    ├── projects/     robotics projects, regardless of where they run
    ├── fleet/        shared robot inventory, profiles and configuration
    ├── workspaces/   source checkouts and development workspaces
    ├── data/         retained or collected data
    │   ├── datasets/
    │   ├── recordings/
    │   └── results/
    ├── artifacts/    reusable build outputs and packaged releases
    └── cache/        re-creatable temporary data, safe to clear

More roots can be added (``simulations``, ``maps``, ...) without changing callers,
because everything goes through the helpers here.

Only the *roots* are policy. A target may still override ``deployment_root`` explicitly
-- an existing deployment keeps working -- but the default is no longer invented per
call site (it used to be ``~/deployments/<project>``, which scattered material across
the home directory and grew a new top-level entry per project).
"""

from __future__ import annotations

#: Root of everything caasi owns on a target. A leading ``~`` is expanded on the
#: target itself by :func:`caasi.core.targets.remote_path_expr`.
ROOT = "~/caasi"

ROBOTS = f"{ROOT}/robots"
PROJECTS = f"{ROOT}/projects"
FLEET = f"{ROOT}/fleet"
WORKSPACES = f"{ROOT}/workspaces"
DATA = f"{ROOT}/data"
DATASETS = f"{DATA}/datasets"
RECORDINGS = f"{DATA}/recordings"
RESULTS = f"{DATA}/results"
ARTIFACTS = f"{ROOT}/artifacts"
CACHE = f"{ROOT}/cache"


def robot_root(robot: str) -> str:
    """Base directory for a physical robot's material."""
    return f"{ROBOTS}/{robot}"


def workspace_root(target: str) -> str:
    """Base directory for a non-robot execution target."""
    return f"{WORKSPACES}/{target}"


def default_deployment_root(target: str, tags: list[str] | None = None) -> str:
    """Default deployment root for *target*.

    A target tagged ``robot`` is a physical robot, so its deployments live under
    ``robots/<name>``; anything else (a GPU workstation, a build server) is an
    execution target whose deployments live under ``workspaces/<name>``. The
    distinction is data, from the target's own tags, not a hardcoded hostname.
    """
    if tags and "robot" in tags:
        return robot_root(target)
    return workspace_root(target)


def deployment_destination(target: str, project: str, tags: list[str] | None = None) -> str:
    """Full destination for *project* deployed to *target*.

    Matches the ``<root>/<project>`` convention the deployment records already use.
    """
    return f"{default_deployment_root(target, tags).rstrip('/')}/{project}"


#: Every root, for documentation and for ``caasi`` diagnostics that want to enumerate
#: what it owns on a machine.
ALL_ROOTS = (
    ROBOTS, PROJECTS, FLEET, WORKSPACES, DATA, ARTIFACTS, CACHE,
)
