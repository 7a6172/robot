"""Resource-aware workspace build orchestrator delegating to colcon.

Orchestrates colcon builds inside caasi projects with automatic RAM-safe
worker sizing, project root discovery, and ROS environment wrapping.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from . import project, rosenv


class BuildError(RuntimeError):
    """Raised when workspace build encounters an unrecoverable setup error."""


def system_ram_gb() -> float:
    """Detect total system physical RAM in GiB."""
    try:
        mem_bytes = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        return mem_bytes / (1024 ** 3)
    except (ValueError, OSError, AttributeError):
        return 8.0


def default_parallel_workers() -> int:
    """RAM-safe parallel worker count for colcon/CMake builds."""
    ram = system_ram_gb()
    cpus = os.cpu_count() or 2
    if ram < 16.0:
        return min(2, cpus)
    elif ram < 32.0:
        return min(4, cpus)
    elif ram < 48.0:
        return min(6, cpus)
    else:
        return min(8, cpus)


def find_build_root(start: Path | None = None) -> Path:
    """Find the root directory of the ROS workspace to build.

    Walks up to find caasi.yaml or a directory containing a src/ subdirectory
    with ROS packages.
    """
    proj_root = project.find_project_root(start)
    if proj_root is not None:
        return proj_root

    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "src").is_dir():
            return candidate
    return current


def colcon_available(project_root: Path | None = None) -> bool:
    """True if colcon binary is available in PATH or sourced ROS env."""
    if shutil.which("colcon"):
        return True
    env = rosenv.sourced_env(project_root=project_root)
    path = env.get("PATH", "")
    return any((Path(p) / "colcon").is_file() for p in path.split(os.pathsep) if p)


@dataclass
class BuildResult:
    returncode: int
    command: list[str]
    root: Path
    workers: int
    duration: float
    output: str = ""
    packages: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "returncode": self.returncode,
            "command": self.command,
            "root": str(self.root),
            "workers": self.workers,
            "duration": round(self.duration, 2),
            "packages": self.packages,
            "output": self.output,
        }


def clean_workspace(root: Path) -> list[str]:
    """Remove build/, install/, and log/ subdirectories from root."""
    removed: list[str] = []
    for d in ("build", "install", "log"):
        target = root / d
        if target.is_dir():
            shutil.rmtree(target)
            removed.append(d)
    rosenv.clear_cache()
    return removed


def execute_build(
    root: Path,
    packages_select: Sequence[str] | None = None,
    packages_up_to: Sequence[str] | None = None,
    jobs: int | None = None,
    symlink_install: bool = True,
    cmake_args: Sequence[str] | None = None,
    clean: bool = False,
    continue_on_error: bool = False,
    line_callback: Callable[[str], None] | None = None,
) -> BuildResult:
    """Execute a resource-aware colcon build.

    Raises BuildError if colcon is unavailable or root has no src directory.
    """
    if clean:
        clean_workspace(root)

    src_dir = root / "src"
    if not src_dir.is_dir():
        raise BuildError(f"Directory '{src_dir}' not found. Cannot build without 'src/'.")

    workers = jobs if jobs is not None and jobs > 0 else default_parallel_workers()

    cmd: list[str] = [
        "colcon",
        "build",
        "--parallel-workers",
        str(workers),
    ]

    if symlink_install:
        cmd.append("--symlink-install")

    if packages_select:
        cmd.extend(["--packages-select", *packages_select])

    if packages_up_to:
        cmd.extend(["--packages-up-to", *packages_up_to])

    if continue_on_error:
        cmd.append("--continue-on-error")

    if cmake_args:
        cmd.extend(["--cmake-args", *cmake_args])

    env = rosenv.sourced_env(project_root=root)
    wrapped_cmd = rosenv.wrap(cmd, project_root=root)

    t0 = time.perf_counter()
    lines: list[str] = []

    proc = subprocess.Popen(
        wrapped_cmd,
        cwd=str(root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    if proc.stdout:
        for line in proc.stdout:
            lines.append(line)
            if line_callback:
                line_callback(line)

    proc.wait()
    duration = time.perf_counter() - t0

    # Invalidate cached environment so newly built packages are visible
    rosenv.clear_cache()

    return BuildResult(
        returncode=proc.returncode,
        command=cmd,
        root=root,
        workers=workers,
        duration=duration,
        output="".join(lines),
        packages=list(packages_select or []),
    )
