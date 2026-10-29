"""Resource-aware workspace build orchestrator delegating to colcon.

Orchestrates colcon builds inside caasi projects with automatic RAM-safe
worker sizing, project root discovery, and ROS environment wrapping.
"""

from __future__ import annotations

import datetime
import json
import os
import shlex
import shutil
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from ..utils import shell
from . import deploy as deploy_core, manifest as manifests, project, provenance, rosenv, targets as targets_core
from .config import Config
from .targets import Target, TargetResources, remote_path_expr


class BuildError(RuntimeError):
    """Raised when workspace build encounters an unrecoverable setup error."""


def system_ram_gb() -> float:
    """Detect total system physical RAM in GiB."""
    try:
        mem_bytes = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        return mem_bytes / (1024 ** 3)
    except (ValueError, OSError, AttributeError):
        return 8.0


#: Conservative default heuristic for RAM reserved for OS and background processes (GiB).
#: This is an empirical policy assumption, not a universal physical constant.
SYSTEM_RESERVED_RAM_GB = 2.0
#: Conservative default heuristic for estimated peak memory budget allocated per parallel compilation job (GiB).
#: C++/CUDA heavy compilation units can spike up to several gigabytes; this heuristic protects against OOM killer.
RAM_PER_WORKER_GB = 6.0


def default_parallel_workers() -> int:
    """RAM-safe parallel worker count for colcon/CMake builds.

    Derives parallelism from physical RAM using a conservative heuristic memory budget
    (RAM_PER_WORKER_GB = 6.0 GiB) per parallel compilation process after
    reserving SYSTEM_RESERVED_RAM_GB (2.0 GiB) for system overhead,
    bounded by total CPU cores. These values represent sensible default policy assumptions
    rather than strict universal constants.
    """
    ram = system_ram_gb()
    cpus = os.cpu_count() or 2
    usable_ram = max(0.0, ram - SYSTEM_RESERVED_RAM_GB)
    ram_workers = max(1, int(usable_ram / RAM_PER_WORKER_GB))
    return max(1, min(cpus, ram_workers))


def derive_target_workers(
    resources: TargetResources | None = None,
    requested_jobs: int | None = None,
) -> int:
    """Calculate RAM-safe parallel worker count for a target.

    If requested_jobs is specified and positive, it overrides automatic calculation.
    Otherwise, calculates workers from target physical RAM using the same conservative
    heuristic budget (RAM_PER_WORKER_GB = 6.0 GiB, SYSTEM_RESERVED_RAM_GB = 2.0 GiB),
    bounded by target CPU count.
    """
    if requested_jobs is not None and requested_jobs > 0:
        return requested_jobs

    if resources and resources.memory_total_kib and resources.cpu_count:
        ram_gb = resources.memory_total_kib / (1024 * 1024)
        usable_ram = max(0.0, ram_gb - SYSTEM_RESERVED_RAM_GB)
        ram_workers = max(1, int(usable_ram / RAM_PER_WORKER_GB))
        return max(1, min(resources.cpu_count, ram_workers))

    return default_parallel_workers()


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
class TargetBuildRecord:
    """Recorded provenance and result of a workspace build on a target."""

    build_id: str
    project_name: str
    git_revision: str
    target_name: str
    target_transport: str
    destination_path: str
    built_at: str
    status: str  # "success" or "failed"
    returncode: int
    duration_seconds: float
    workers: int
    command: list[str]
    deployment_id: str | None = None
    packages: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    output: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BuildResult:
    returncode: int
    command: list[str]
    root: Path | str
    workers: int
    duration: float
    output: str = ""
    packages: list[str] = field(default_factory=list)
    target_name: str = "local"
    build_id: str | None = None
    deployment_id: str | None = None

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def dependency_hint(self) -> str | None:
        """A next step when the build failed only because dependencies were not built.

        colcon reports this as "Failed to find ... package.sh" plus "Check that the
        following packages have been built". The useful answer is the build-up-to command,
        not a suggestion to rebuild the whole workspace.
        """
        if self.ok or "package.sh" not in self.output:
            return None
        missing = sorted({
            line.strip().lstrip("- ").strip()
            for line in self.output.splitlines()
            if "/share/" in line and line.strip().startswith("- ")
        })
        names: list[str] = []
        for path in missing:
            parts = [p for p in path.split("/") if p and p != "install"]
            if "share" in parts:
                index = parts.index("share")
                if index + 1 < len(parts):
                    names.append(parts[index + 1])
        names = sorted(set(names))
        if not names:
            return None
        target_flag = "" if self.target_name == "local" else f" --target {self.target_name}"
        return (
            f"These packages have not been built: {', '.join(names)}. "
            f"Build them and their dependencies with: "
            f"caasi build{target_flag} --packages-up-to {names[0]}"
        )

    def to_dict(self) -> dict:
        data = {
            "ok": self.ok,
            "returncode": self.returncode,
            "command": self.command,
            "root": str(self.root),
            "workers": self.workers,
            "duration": round(self.duration, 2),
            "packages": self.packages,
            "output": self.output,
            "target_name": self.target_name,
        }
        if self.build_id:
            data["build_id"] = self.build_id
        if self.deployment_id:
            data["deployment_id"] = self.deployment_id
        return data


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


def save_build_record(record: TargetBuildRecord, project_root: Path, target: Target) -> None:
    """Save build provenance record locally on host and on target."""
    rec_json = json.dumps(record.to_dict(), indent=2)

    # 1. Save on host in project .caasi/builds/<target_name>/<build_id>.json
    local_build_dir = project_root / ".caasi" / "builds" / target.name
    try:
        local_build_dir.mkdir(parents=True, exist_ok=True)
        (local_build_dir / f"{record.build_id}.json").write_text(rec_json, encoding="utf-8")
    except OSError:
        pass

    # 2. Save on target in destination_path/.caasi-build.json
    if target.transport == "local":
        meta_file = Path(record.destination_path).expanduser().resolve() / ".caasi-build.json"
        try:
            meta_file.write_text(rec_json, encoding="utf-8")
        except OSError:
            pass
    elif target.transport == "ssh":
        ssh_prefix = targets_core.target_ssh_prefix(target)
        dest_meta = f"{record.destination_path.rstrip('/')}/.caasi-build.json"
        write_cmd = ssh_prefix + [f"cat > {remote_path_expr(dest_meta)}"]
        try:
            # One SSH round-trip; budget from the target's own link latency.
            subprocess.run(write_cmd, input=rec_json, text=True, capture_output=True,
                           timeout=max(10.0, float(target.ssh_timeout) * 2))
        except Exception:
            pass


def list_build_records(project_root: Path, target_name: str | None = None) -> list[TargetBuildRecord]:
    """List recorded builds from host project .caasi/builds/."""
    build_root = project_root / ".caasi" / "builds"
    if not build_root.is_dir():
        return []

    records: list[TargetBuildRecord] = []
    target_dirs = [build_root / target_name] if target_name else list(build_root.iterdir())

    for t_dir in sorted(target_dirs):
        if not t_dir.is_dir():
            continue
        for f in sorted(t_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                records.append(TargetBuildRecord(**data))
            except Exception:
                continue
    return records


def get_last_build_status(
    target: Target,
    destination_path: str | None = None,
    config: Config | None = None,
    project_root: Path | None = None,
) -> TargetBuildRecord | None:
    """Retrieve the most recent build record from target or host project."""
    dest = destination_path or (target.deployment_root or "~")
    if target.transport == "local":
        meta_file = Path(dest).expanduser().resolve() / ".caasi-build.json"
        if meta_file.is_file():
            try:
                data = json.loads(meta_file.read_text(encoding="utf-8"))
                return TargetBuildRecord(**data)
            except Exception:
                pass
    elif target.transport == "ssh":
        ssh_prefix = targets_core.target_ssh_prefix(target)
        cmd = ssh_prefix + [
            f"cat {remote_path_expr(dest.rstrip('/') + '/.caasi-build.json')} 2>/dev/null"
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True,
                                 timeout=max(10.0, float(target.ssh_timeout) * 2))
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout)
                return TargetBuildRecord(**data)
        except Exception:
            pass

    if project_root:
        records = list_build_records(project_root, target.name)
        if records:
            return records[-1]

    return None


def execute_target_build(
    target: Target,
    project_root: Path,
    config: Config | None = None,
    packages_select: Sequence[str] | None = None,
    packages_up_to: Sequence[str] | None = None,
    jobs: int | None = None,
    symlink_install: bool = True,
    cmake_args: Sequence[str] | None = None,
    clean: bool = False,
    continue_on_error: bool = False,
    line_callback: Callable[[str], None] | None = None,
) -> BuildResult:
    """Execute a target-native workspace build.

    For local workstation target (name == 'local' or local transport with default root),
    delegates directly to execute_build on the workstation workspace.

    For remote targets (SSH or local deployed testbeds), verifies target reachability,
    requires an active verified deployment at the destination, calculates target-safe
    worker count, executes colcon in the target's native environment, and records
    build provenance.
    """
    cfg = config or Config({}, [])
    manifest = manifests.read(project_root)
    proj_name = manifest.name or project_root.name
    git_stat = provenance.git_info(project_root)
    git_rev = git_stat.get("head") or "unversioned"
    if git_stat.get("dirty"):
        git_rev = f"{git_rev}-dirty"

    # A local target is a DEPLOYED target like any other, so a build belongs at its
    # deployment destination -- which is where `run` looks for the record. Keying
    # this on the target being *named* `local` made build record in the project root
    # while run looked at the deployment, so `build` then `run` on the local target
    # failed. The discriminator is whether a deployment exists, not the name.
    #
    # The local-workspace path is kept for its real purpose: a standalone build in
    # one's own checkout, with no deployment to belong to.
    local_deployment = None
    if target.transport == "local":
        candidate = deploy_core.resolve_deployment_destination(
            target, manifests.read(project_root).name or project_root.name
        )
        if deploy_core.get_deployment_status(target, candidate, cfg):
            local_deployment = candidate

    is_local_workspace = (local_deployment is None) and (
        (target.name == "local")
        or (
            target.transport == "local"
            and (not target.deployment_root or target.deployment_root == ".")
        )
    )

    if is_local_workspace:
        res = execute_build(
            root=project_root,
            packages_select=packages_select,
            packages_up_to=packages_up_to,
            jobs=jobs,
            symlink_install=symlink_install,
            cmake_args=cmake_args,
            clean=clean,
            continue_on_error=continue_on_error,
            line_callback=line_callback,
        )
        build_id = f"build-local-{int(time.time())}-{uuid.uuid4().hex[:6]}"
        res.target_name = "local"
        res.build_id = build_id

        record = TargetBuildRecord(
            build_id=build_id,
            project_name=proj_name,
            git_revision=git_rev,
            target_name="local",
            target_transport="local",
            destination_path=str(project_root),
            built_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            status="success" if res.ok else "failed",
            returncode=res.returncode,
            duration_seconds=round(res.duration, 2),
            workers=res.workers,
            command=res.command,
            deployment_id=None,
            packages=res.packages,
            output=res.output[:2000] if not res.ok else "",
        )
        save_build_record(record, project_root, target)
        return res

    # 1. Discover target and check reachability
    inspection = targets_core.discover_target(target, config=cfg)
    if not inspection.reachable:
        raise BuildError(
            f"Target '{target.name}' is unreachable: {inspection.error or 'connection failed'}"
        )

    # 2. Check active deployment on target
    dest = deploy_core.resolve_deployment_destination(target, proj_name)
    deployment = deploy_core.get_deployment_status(target, dest, cfg)
    if not deployment:
        raise BuildError(
            f"No active deployment found on target '{target.name}' at '{dest}'. "
            f"Run 'caasi deploy {target.name}' first."
        )

    # 3. Determine worker count from target resources
    workers = derive_target_workers(inspection.resources, requested_jobs=jobs)

    # 4. Construct colcon command
    colcon_cmd = [
        "colcon",
        "build",
        "--parallel-workers",
        str(workers),
    ]
    if symlink_install:
        colcon_cmd.append("--symlink-install")
    if packages_select:
        colcon_cmd.extend(["--packages-select", *packages_select])
    if packages_up_to:
        colcon_cmd.extend(["--packages-up-to", *packages_up_to])
    if continue_on_error:
        colcon_cmd.append("--continue-on-error")
    if cmake_args:
        colcon_cmd.extend(["--cmake-args", *cmake_args])

    # 5. Determine target ROS underlay setup
    if inspection.environment and inspection.environment.ros_root:
        ros_setup = f"{inspection.environment.ros_root}/setup.bash"
    elif inspection.environment and inspection.environment.ros_distro:
        ros_setup = f"/opt/ros/{inspection.environment.ros_distro}/setup.bash"
    else:
        ros_setup = "/opt/ros/jazzy/setup.bash"

    build_id = f"build-{target.name}-{int(time.time())}-{uuid.uuid4().hex[:6]}"
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

    if target.transport == "local":
        dest_path = Path(dest).expanduser().resolve()
        if not (dest_path / "src").is_dir():
            raise BuildError(f"Directory '{dest_path}/src' not found on target. Cannot build without 'src/'.")
        res = execute_build(
            root=dest_path,
            packages_select=packages_select,
            packages_up_to=packages_up_to,
            jobs=workers,
            symlink_install=symlink_install,
            cmake_args=cmake_args,
            clean=clean,
            continue_on_error=continue_on_error,
            line_callback=line_callback,
        )
        res.target_name = target.name
        res.build_id = build_id
        res.deployment_id = deployment.deployment_id

        record = TargetBuildRecord(
            build_id=build_id,
            project_name=proj_name,
            git_revision=git_rev,
            target_name=target.name,
            target_transport=target.transport,
            destination_path=str(dest_path),
            built_at=timestamp,
            status="success" if res.ok else "failed",
            returncode=res.returncode,
            duration_seconds=round(res.duration, 2),
            workers=workers,
            command=res.command,
            deployment_id=deployment.deployment_id,
            packages=res.packages,
            output=res.output[:2000] if not res.ok else "",
        )
        save_build_record(record, project_root, target)
        return res

    # 6. Remote SSH build
    steps = [f"cd {targets_core.remote_path_expr(dest)}"]
    if clean:
        steps.append("rm -rf build install log")
    steps.append("ulimit -s unlimited 2>/dev/null || true")
    steps.append(
        f"test -f {targets_core.remote_path_expr(ros_setup)} && "
        f". {targets_core.remote_path_expr(ros_setup)}"
    )
    steps.append(shlex.join(colcon_cmd))
    remote_sh = " && ".join(steps)

    ssh_prefix = targets_core.target_ssh_prefix(target)
    remote_exec = ssh_prefix + [f"bash -c {shlex.quote(remote_sh)}"]

    t0 = time.perf_counter()
    lines: list[str] = []

    proc = subprocess.Popen(
        remote_exec,
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

    result = BuildResult(
        returncode=proc.returncode,
        command=colcon_cmd,
        root=dest,
        workers=workers,
        duration=duration,
        output="".join(lines),
        packages=list(packages_select or []),
        target_name=target.name,
        build_id=build_id,
        deployment_id=deployment.deployment_id,
    )

    record = TargetBuildRecord(
        build_id=build_id,
        project_name=proj_name,
        git_revision=git_rev,
        target_name=target.name,
        target_transport=target.transport,
        destination_path=dest,
        built_at=timestamp,
        status="success" if result.ok else "failed",
        returncode=result.returncode,
        duration_seconds=round(duration, 2),
        workers=workers,
        command=colcon_cmd,
        deployment_id=deployment.deployment_id,
        packages=list(packages_select or []),
        output="".join(lines)[:2000] if not result.ok else "",
    )
    save_build_record(record, project_root, target)

    return result

