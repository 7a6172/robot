"""Experiment configuration: what `caasi sim run` / `caasi train` execute.

An experiment YAML declares *what* to run and *which backend* runs it::

    name: my-experiment
    backend: sim          # sim | lab | python
    script: experiment.py # relative to the YAML file
    args: ["--steps", "100"]
    env:
      MY_VAR: "1"
    python: /custom/python  # optional override
    headless: true
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import artifacts as artifacts_mod
from .config import Config, ResolvedTool
from ..utils import shell

VALID_BACKENDS = ("sim", "lab", "python")


class ExperimentError(ValueError):
    """Raised for invalid experiment configurations."""


@dataclass
class Experiment:
    name: str
    backend: str
    script: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    python: str | None = None
    headless: bool = True
    cwd: str | None = None
    config_path: Path | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    # Declared run outputs. Empty means "route by policy",
    # which leaves unclassified data on the target and records where it is.
    outputs: list["artifacts_mod.OutputDeclaration"] = field(default_factory=list)

    @property
    def script_path(self) -> Path:
        script = Path(self.script).expanduser()
        if script.is_absolute():
            return script
        base = self.config_path.parent if self.config_path else Path.cwd()
        return (base / script).resolve()

    @property
    def work_dir(self) -> Path:
        if self.cwd:
            return Path(self.cwd).expanduser().resolve()
        base = self.config_path.parent if self.config_path else Path.cwd()
        return base.resolve()


def experiment_not_found_message(path: Path) -> str:
    """Say what was tried and, when a tree is chosen, that it was searched too.

    "not found: /home/you/experiments/bringup.yaml" leaves the operator guessing why a file that
    plainly exists in the project is invisible -- the answer is usually that they are standing in
    the wrong directory and have not chosen a project or robot yet.
    """
    from . import project as project_core

    message = f"experiment config not found: {path}"
    roots = project_core.work_roots()
    if roots:
        searched = ", ".join(str(root / path) for root in roots)
        message += f" (also tried {searched})"
    else:
        message += (
            " -- no project or robot is chosen, so only the current directory was searched;"
            " run 'caasi choose project <path>' or 'caasi choose robot <name>'"
        )
    return message


def load_experiment(path: Path | str) -> Experiment:
    path = Path(path)
    # Every command that understands an experiment comes through here, so the chosen project or
    # robot is honoured once, for all of them, and a path that exists locally is left alone.
    from . import project as project_core

    path = project_core.resolve_path(path).expanduser().resolve()
    if not path.is_file():
        raise ExperimentError(experiment_not_found_message(path))
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ExperimentError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ExperimentError(f"experiment config must be a mapping: {path}")

    backend = str(data.get("backend", "sim")).lower()
    if backend not in VALID_BACKENDS:
        raise ExperimentError(
            f"unknown backend '{backend}' (expected one of {', '.join(VALID_BACKENDS)})"
        )
    script = data.get("script")
    if not script:
        raise ExperimentError(f"'script' is required in {path}")

    args = data.get("args") or []
    if not isinstance(args, list):
        raise ExperimentError("'args' must be a list")
    env = data.get("env") or {}
    if not isinstance(env, dict):
        raise ExperimentError("'env' must be a mapping")

    # Declared outputs are optional; an invalid declaration is a config error
    # surfaced here rather than silently producing an empty collection.
    try:
        declarations = artifacts_mod.parse_outputs(data.get("outputs"))
    except artifacts_mod.ArtifactError as err:
        raise ExperimentError(f"{path}: {err}") from err

    return Experiment(
        name=str(data.get("name") or path.stem),
        backend=backend,
        script=str(script),
        args=[str(a) for a in args],
        env={str(k): str(v) for k, v in env.items()},
        python=data.get("python"),
        headless=bool(data.get("headless", True)),
        cwd=data.get("cwd"),
        config_path=path,
        raw=data,
        outputs=declarations,
    )


def _resolve_backend_tool(config: Config, backend: str) -> ResolvedTool | None:
    tool_name = {"sim": "isaacsim", "lab": "isaaclab"}.get(backend)
    if not tool_name:
        return None
    return config.resolve_tool(tool_name)


def _default_python_for(resolved: ResolvedTool | None, backend: str) -> str | None:
    path = resolved.expanded_path if resolved else None
    if not path:
        return None
    if backend == "sim":
        candidate = path / "python.sh"
        return str(candidate) if candidate.is_file() else str(path / "python.sh")
    candidate = path / "isaaclab.sh"
    return str(candidate) if candidate.is_file() else str(path / "isaaclab.sh")


def build_command(
    experiment: Experiment, config: Config, extra_args: list[str] | None = None
) -> tuple[list[str], dict[str, str]]:
    """Build (command, env) for the experiment. Raises ExperimentError."""
    args = [*experiment.args, *(extra_args or [])]
    env: dict[str, str] = {**experiment.env}
    script = str(experiment.script_path)
    if experiment.config_path:
        env.setdefault("CAASI_EXPERIMENT", str(experiment.config_path))

    from . import project, rosenv
    proj_root = None
    if experiment.config_path:
        proj_root = project.find_project_root(experiment.config_path.parent)
    if proj_root is None:
        proj_root = project.find_project_root()
    if proj_root is not None:
        env.setdefault("CAASI_PROJECT_ROOT", str(proj_root))

    backend = experiment.backend
    if backend in ("sim", "ros"):
        ros_env = rosenv.sourced_env(project_root=proj_root)
        for k in ("AMENT_PREFIX_PATH", "COLCON_PREFIX_PATH", "ROS_DISTRO", "ROS_VERSION", "RMW_IMPLEMENTATION", "LD_LIBRARY_PATH"):
            if k in ros_env and k not in env:
                env[k] = ros_env[k]
        if "PYTHONPATH" in ros_env:
            if "PYTHONPATH" not in env:
                env["PYTHONPATH"] = ros_env["PYTHONPATH"]
            else:
                env["PYTHONPATH"] = f"{env['PYTHONPATH']}:{ros_env['PYTHONPATH']}"

    if backend == "python":
        python = experiment.python or sys.executable
        return [python, script, *args], env

    resolved = _resolve_backend_tool(config, backend)
    if not resolved or not resolved.path:
        from ..i18n import _

        tool = "isaacsim" if backend == "sim" else "isaaclab"
        raise ExperimentError(
            _("experiment.backend_missing", backend=backend, tool=tool)
        )

    env.setdefault(
        "ISAACSIM_PATH" if backend == "sim" else "ISAACLAB_PATH", resolved.path
    )

    if experiment.python:
        return [experiment.python, script, *args], env
    if resolved.python:
        return [resolved.python, script, *args], env

    launcher = _default_python_for(resolved, backend)
    if not launcher:
        from ..i18n import _

        raise ExperimentError(
            _("experiment.no_launcher", backend=backend, path=resolved.path)
        )

    if backend == "sim":
        if not Path(launcher).is_file():
            from ..i18n import _

            raise ExperimentError(
                _("experiment.launcher_missing", launcher=launcher)
            )
        return [launcher, script, *args], env

    # Isaac Lab: isaaclab.sh -p script ...
    if Path(launcher).is_file():
        return [launcher, "-p", script, *args], env
    # Fallback: plain python inside the lab repo (./source/... venvs vary)
    if shell.which("python3"):
        return ["python3", script, *args], env
    return [sys.executable, script, *args], env
