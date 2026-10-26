"""The caasi directory layout on a target.

caasi -- not the user -- decides where things live on a machine it manages, so that a
new target needs no convention debate and every command looks in the same place. The
layout is a fixed tree rooted at ``~/caasi``:

    ~/caasi/
    ├── robots/{robot}/                 physical robots and their deployed environments
    ├── projects/{project}/             robotics projects, regardless of where they run
    ├── fleet/                          shared robot inventory, profiles and configuration
    ├── workspaces/{workspace}/         source checkouts and development workspaces
    ├── data/
    │   ├── datasets/{dataset}/
    │   ├── recordings/{recording}/
    │   └── results/{result}-{date}/
    ├── artifacts/{artifact}/           reusable build outputs and packaged releases
    └── cache/{entry}/                  re-creatable temporary data, safe to clear

Each root holds one directory per named entity, so a robot is `robots/swjtumover05`,
a project is `projects/warehouse-navigation`, and a dataset is
`data/datasets/<name>`. Use the helpers below rather than joining strings by hand.

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
#: Run records and their logs. Under data/, not cache/: logs and exit codes must survive
#: a cache clear.
RUNS = f"{DATA}/runs"
DATASETS = f"{DATA}/datasets"
RECORDINGS = f"{DATA}/recordings"
RESULTS = f"{DATA}/results"
ARTIFACTS = f"{ROOT}/artifacts"
CACHE = f"{ROOT}/cache"


def robot_root(robot: str) -> str:
    """A robot's own directory: ``robots/<robot>``."""
    return f"{ROBOTS}/{robot}"


def project_root(project: str) -> str:
    """A project's own directory: ``projects/<project>``."""
    return f"{PROJECTS}/{project}"


def workspace_root(target: str) -> str:
    """Base directory for a non-robot execution target."""
    return f"{WORKSPACES}/{target}"


def workspace(workspace_name: str) -> str:
    """A development workspace: ``workspaces/<name>``."""
    return f"{WORKSPACES}/{workspace_name}"


def run_dir(run_id: str) -> str:
    """A managed run's directory: ``data/runs/<run_id>``."""
    return f"{RUNS}/{run_id}"


def dataset(name: str) -> str:
    """A dataset: ``data/datasets/<name>``."""
    return f"{DATASETS}/{name}"


def recording(name: str) -> str:
    """A recording: ``data/recordings/<name>``."""
    return f"{RECORDINGS}/{name}"


def result(name: str, date: str | None = None) -> str:
    """A result set: ``data/results/<name>[-<date>]``.

    Results are dated because the same operation is re-run; ``date`` is passed in
    rather than read from the clock so callers stay deterministic and testable.
    """
    return f"{RESULTS}/{name}-{date}" if date else f"{RESULTS}/{name}"


def artifact(name: str) -> str:
    """A reusable build output or packaged release: ``artifacts/<name>``."""
    return f"{ARTIFACTS}/{name}"


def cache_entry(name: str) -> str:
    """Clearable scratch space: ``cache/<name>``."""
    return f"{CACHE}/{name}"


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

    A robot owns one directory: ``~/caasi/robots/<robot>`` holds that robot's deployed
    environment. The project name is deliberately **not** appended, because the robot is
    the unit of identity here -- ``~/caasi/robots/swjtumover05`` and
    ``~/caasi/robots/openmover`` are two *robots*, not a robot and a project.

    A non-robot compute target keeps the ``<root>/<project>`` shape, since one machine
    may host several unrelated projects.

    An explicit ``deployment_root`` on the target still wins (see
    :func:`caasi.core.deploy.resolve_deployment_destination`), so existing deployments
    that used the older ``<root>/<project>`` shape remain valid.
    """
    root = default_deployment_root(target, tags).rstrip("/")
    if tags and "robot" in tags:
        return root
    return f"{root}/{project}"


#: Every root, for documentation and for ``caasi`` diagnostics that want to enumerate
#: what it owns on a machine.
ALL_ROOTS = (
    ROBOTS, PROJECTS, FLEET, WORKSPACES, DATA, ARTIFACTS, CACHE,
)
