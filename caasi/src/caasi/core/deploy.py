"""Target-aware deployment engine and synchronization foundation (Phase 7 Stage B).

Represents and executes project deployments to execution targets (workstation,
remote robots, edge devices, simulation/compute clusters). Synchronizes selected
project content incrementally, tracks deployment identity and provenance, and
verifies deployed environments without hardcoded vendor assumptions.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..utils import shell
from . import manifest as manifests
from . import provenance
from .config import Config
from .targets import Target, TargetInspection, discover_target, target_ssh_prefix

DEFAULT_EXCLUDE_PATTERNS = [
    "build",
    "install",
    "log",
    ".colcon",
    ".git",
    ".gitignore",
    ".gitattributes",
    "__pycache__",
    "*.pyc",
    "*.pyo",
    ".pytest_cache",
    ".coverage",
    "htmlcov",
    "tests",
    ".caasi/runs",
    ".caasi/datasets",
    ".caasi/deployments",
    ".caasi/builds",
    ".caasi-build.json",
    "*~",
    "*.swp",
    "*.swo",
]


@dataclass(frozen=True)
class DeploymentSpec:
    """Specification defining what project content to deploy and where."""

    project_root: Path
    project_name: str
    project_version: str
    git_revision: str
    target: Target
    destination_path: str
    include_paths: list[str] = field(default_factory=list)
    exclude_patterns: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_root": str(self.project_root),
            "project_name": self.project_name,
            "project_version": self.project_version,
            "git_revision": self.git_revision,
            "target": self.target.to_dict(),
            "destination_path": self.destination_path,
            "include_paths": self.include_paths,
            "exclude_patterns": self.exclude_patterns,
        }


@dataclass
class DeploymentRecord:
    """Recorded provenance and result of a deployment."""

    deployment_id: str
    project_name: str
    project_version: str
    git_revision: str
    target_name: str
    target_transport: str
    destination_path: str
    deployed_at: str
    status: str  # "verified", "active", "dry_run", "failed", "verification_failed"
    target_environment: dict[str, Any] = field(default_factory=dict)
    file_count: int = 0
    total_bytes: int = 0
    transferred_bytes: int = 0
    duration_seconds: float = 0.0
    changed_files: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_deployment_destination(target: Target, project_name: str) -> str:
    """Determine the canonical destination path on the target."""
    if target.transport == "local":
        root = target.deployment_root or "."
        if root == ".":
            # For local self-deployment, default to a designated local deployments sandbox
            return str(Path("~/.caasi/deployments/local").expanduser() / project_name)
        return str(Path(root).expanduser() / project_name)

    # Remote SSH transport
    root = target.deployment_root or f"~/deployments/{project_name}"
    if not root.endswith(project_name):
        return f"{root.rstrip('/')}/{project_name}"
    return root


def create_deployment_spec(
    project_root: Path,
    target: Target,
    config: Config,
    destination_override: str | None = None,
) -> DeploymentSpec:
    """Construct a DeploymentSpec from project manifest and target configuration."""
    manifest = manifests.read(project_root)
    proj_name = manifest.name or project_root.name
    proj_version = manifest.version or "0.0.0"

    git_stat = provenance.git_info(project_root)
    git_rev = git_stat.get("head") or "unversioned"
    if git_stat.get("dirty"):
        git_rev = f"{git_rev}-dirty"

    dest = destination_override or resolve_deployment_destination(target, proj_name)

    # Read project deployment configuration if declared in caasi.yaml
    deploy_cfg = config.get("deployment") or {}
    includes = list(deploy_cfg.get("include") or [])
    excludes = list(deploy_cfg.get("exclude") or DEFAULT_EXCLUDE_PATTERNS)

    return DeploymentSpec(
        project_root=project_root.resolve(),
        project_name=proj_name,
        project_version=proj_version,
        git_revision=git_rev,
        target=target,
        destination_path=dest,
        include_paths=includes,
        exclude_patterns=excludes,
    )


def preflight_target(
    target: Target,
    project_root: Path,
    config: Config,
) -> tuple[bool, TargetInspection, list[str]]:
    """Validate target reachability and capability compatibility before deployment."""
    inspection = discover_target(target, config, timeout=3.0)
    issues: list[str] = []

    if not inspection.reachable:
        issues.append(f"Target '{target.name}' is unreachable: {inspection.error}")
        return False, inspection, issues

    if inspection.status == "error":
        issues.append(f"Target '{target.name}' discovery error: {inspection.error}")
        return False, inspection, issues

    # Check target declared vs discovered mismatches
    if inspection.mismatches:
        for m in inspection.mismatches:
            issues.append(f"Target mismatch: {m}")

    # Check project requirements against target
    manifest = manifests.read(project_root)
    reqs = manifest.requires or {}
    if "ros2" in reqs and "ros2" not in inspection.discovered_capabilities:
        issues.append("Project requires ROS 2, but ROS 2 was not detected on target")

    compatible = len(issues) == 0
    return compatible, inspection, issues


def _parse_rsync_stats(output_text: str) -> tuple[int, int, int, list[str]]:
    """Parse rsync stats and itemized changes output."""
    file_count = 0
    total_bytes = 0
    transferred_bytes = 0
    changed_files: list[str] = []

    for line in output_text.splitlines():
        line = line.strip()
        # Itemized changes e.g. ">f+++++++++ path/to/file"
        if line.startswith(">f") or line.startswith("*deleting") or line.startswith("cd++++++"):
            parts = line.split(maxsplit=1)
            if len(parts) == 2:
                changed_files.append(parts[1])

        # Match rsync stats lines
        if "Number of files:" in line:
            m = re.search(r"Number of files:\s+([\d,]+)", line)
            if m:
                file_count = int(m.group(1).replace(",", ""))
        elif "Total file size:" in line:
            m = re.search(r"Total file size:\s+([\d,]+)", line)
            if m:
                total_bytes = int(m.group(1).replace(",", ""))
        elif "Total transferred file size:" in line:
            m = re.search(r"Total transferred file size:\s+([\d,]+)", line)
            if m:
                transferred_bytes = int(m.group(1).replace(",", ""))

    return file_count, total_bytes, transferred_bytes, changed_files


def execute_deployment(
    spec: DeploymentSpec,
    dry_run: bool = False,
    force: bool = False,
    config: Config | None = None,
) -> DeploymentRecord:
    """Execute target deployment using incremental synchronization and provenance recording."""
    cfg = config or Config({}, [])
    start_time = time.perf_counter()
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    short_rev = spec.git_revision[:8] if spec.git_revision else "rev"
    deploy_id = f"deploy-{spec.project_name}-{timestamp}-{short_rev}"

    # 1. Preflight target compatibility
    compatible, inspection, preflight_issues = preflight_target(spec.target, spec.project_root, cfg)
    if not compatible and not force and not dry_run:
        return DeploymentRecord(
            deployment_id=deploy_id,
            project_name=spec.project_name,
            project_version=spec.project_version,
            git_revision=spec.git_revision,
            target_name=spec.target.name,
            target_transport=spec.target.transport,
            destination_path=spec.destination_path,
            deployed_at=timestamp,
            status="failed",
            target_environment=inspection.environment.to_dict() if inspection.environment else {},
            errors=preflight_issues,
            warnings=["Use --force to override preflight compatibility checks."] if not force else [],
        )

    # 2. Check rsync binary
    if shell.which("rsync") is None:
        return DeploymentRecord(
            deployment_id=deploy_id,
            project_name=spec.project_name,
            project_version=spec.project_version,
            git_revision=spec.git_revision,
            target_name=spec.target.name,
            target_transport=spec.target.transport,
            destination_path=spec.destination_path,
            deployed_at=timestamp,
            status="failed",
            errors=["'rsync' is required on the host system for project deployment."],
        )

    # 3. Build rsync command
    # Source with trailing slash to copy contents into destination
    src_path = str(spec.project_root).rstrip("/") + "/"
    rsync_cmd = ["rsync", "-a", "--delete", "--stats", "-i"]
    if dry_run:
        rsync_cmd.append("-n")

    for pat in spec.exclude_patterns:
        rsync_cmd.extend(["--exclude", pat])

    # If explicit includes are declared, apply them
    if spec.include_paths:
        for inc in spec.include_paths:
            rsync_cmd.extend(["--include", inc])

    # Ensure remote destination directory exists before syncing
    if spec.target.transport == "local":
        dest_local = Path(spec.destination_path).expanduser().resolve()
        if not dry_run:
            try:
                dest_local.mkdir(parents=True, exist_ok=True)
            except OSError as err:
                return DeploymentRecord(
                    deployment_id=deploy_id,
                    project_name=spec.project_name,
                    project_version=spec.project_version,
                    git_revision=spec.git_revision,
                    target_name=spec.target.name,
                    target_transport=spec.target.transport,
                    destination_path=str(dest_local),
                    deployed_at=timestamp,
                    status="failed",
                    errors=[f"Failed to create destination directory '{dest_local}': {err}"],
                )
        dest_arg = str(dest_local) + "/"
    else:
        # Remote SSH transport
        ssh_prefix = target_ssh_prefix(spec.target)
        # Extract ssh flags and endpoint
        ssh_opts = " ".join(ssh_prefix[:-1])
        endpoint = ssh_prefix[-1]
        rsync_cmd.extend(["-e", ssh_opts])

        dest_remote = spec.destination_path
        if not dry_run:
            # Ensure destination directory exists on target
            mkdir_cmd = ssh_prefix + [f"mkdir -p '{dest_remote}'"]
            res = subprocess.run(mkdir_cmd, capture_output=True, text=True, timeout=10.0)
            if res.returncode != 0:
                err_msg = res.stderr.strip() or f"exit code {res.returncode}"
                return DeploymentRecord(
                    deployment_id=deploy_id,
                    project_name=spec.project_name,
                    project_version=spec.project_version,
                    git_revision=spec.git_revision,
                    target_name=spec.target.name,
                    target_transport=spec.target.transport,
                    destination_path=dest_remote,
                    deployed_at=timestamp,
                    status="failed",
                    errors=[f"Failed to create remote destination directory on {spec.target.name}: {err_msg}"],
                )
        dest_arg = f"{endpoint}:{dest_remote.rstrip('/')}/"

    rsync_cmd.extend([src_path, dest_arg])

    # 4. Run rsync
    try:
        proc = subprocess.run(rsync_cmd, capture_output=True, text=True, timeout=120.0)
    except subprocess.TimeoutExpired:
        return DeploymentRecord(
            deployment_id=deploy_id,
            project_name=spec.project_name,
            project_version=spec.project_version,
            git_revision=spec.git_revision,
            target_name=spec.target.name,
            target_transport=spec.target.transport,
            destination_path=spec.destination_path,
            deployed_at=timestamp,
            status="failed",
            errors=["Deployment synchronization timed out after 120s."],
        )
    except OSError as err:
        return DeploymentRecord(
            deployment_id=deploy_id,
            project_name=spec.project_name,
            project_version=spec.project_version,
            git_revision=spec.git_revision,
            target_name=spec.target.name,
            target_transport=spec.target.transport,
            destination_path=spec.destination_path,
            deployed_at=timestamp,
            status="failed",
            errors=[f"Failed to invoke rsync: {err}"],
        )

    duration = round(time.perf_counter() - start_time, 2)

    if proc.returncode != 0:
        err_msg = proc.stderr.strip() or f"exit code {proc.returncode}"
        return DeploymentRecord(
            deployment_id=deploy_id,
            project_name=spec.project_name,
            project_version=spec.project_version,
            git_revision=spec.git_revision,
            target_name=spec.target.name,
            target_transport=spec.target.transport,
            destination_path=spec.destination_path,
            deployed_at=timestamp,
            status="failed",
            duration_seconds=duration,
            errors=[f"rsync failed: {err_msg}"],
        )

    file_count, total_bytes, transferred_bytes, changed_files = _parse_rsync_stats(proc.stdout)

    record = DeploymentRecord(
        deployment_id=deploy_id,
        project_name=spec.project_name,
        project_version=spec.project_version,
        git_revision=spec.git_revision,
        target_name=spec.target.name,
        target_transport=spec.target.transport,
        destination_path=spec.destination_path,
        deployed_at=timestamp,
        status="dry_run" if dry_run else "verified",
        target_environment=inspection.environment.to_dict() if inspection.environment else {},
        file_count=file_count,
        total_bytes=total_bytes,
        transferred_bytes=transferred_bytes,
        duration_seconds=duration,
        changed_files=changed_files,
        warnings=preflight_issues,
    )

    if dry_run:
        return record

    # 5. Record deployment metadata on target and host
    meta_json = json.dumps(record.to_dict(), indent=2)

    # Write .caasi-deployment.json on target
    if spec.target.transport == "local":
        meta_file = Path(spec.destination_path).expanduser().resolve() / ".caasi-deployment.json"
        try:
            meta_file.write_text(meta_json, encoding="utf-8")
        except OSError as err:
            record.status = "failed"
            record.errors.append(f"Failed to write deployment metadata on target: {err}")
    else:
        # Remote SSH: pipe metadata directly via stdin to cat
        ssh_prefix = target_ssh_prefix(spec.target)
        dest_meta = f"{spec.destination_path.rstrip('/')}/.caasi-deployment.json"
        write_cmd = ssh_prefix + [f"cat > '{dest_meta}'"]
        res = subprocess.run(write_cmd, input=meta_json, text=True, capture_output=True, timeout=10.0)
        if res.returncode != 0:
            record.status = "failed"
            record.errors.append(f"Failed to write remote metadata on target: {res.stderr.strip()}")

    # Save local provenance record in project
    local_deploy_dir = spec.project_root / ".caasi" / "deployments" / spec.target.name
    try:
        local_deploy_dir.mkdir(parents=True, exist_ok=True)
        (local_deploy_dir / f"{deploy_id}.json").write_text(meta_json, encoding="utf-8")
    except OSError:
        pass  # Non-fatal

    # 6. Verify deployed artifact structure on target
    verified, verify_err = verify_deployment(spec.target, spec.destination_path)
    if not verified:
        record.status = "verification_failed"
        record.errors.append(verify_err or "Verification failed on target")

    return record


def verify_deployment(target: Target, destination_path: str) -> tuple[bool, str | None]:
    """Verify that a deployment on a target is complete, intact, and readable."""
    if target.transport == "local":
        dest = Path(destination_path).expanduser().resolve()
        if not dest.is_dir():
            return False, f"Deployment directory does not exist: {dest}"
        if not (dest / "caasi.yaml").is_file():
            return False, f"Missing project manifest caasi.yaml in {dest}"
        if not (dest / ".caasi-deployment.json").is_file():
            return False, f"Missing deployment metadata .caasi-deployment.json in {dest}"
        try:
            data = json.loads((dest / ".caasi-deployment.json").read_text(encoding="utf-8"))
            if not data.get("deployment_id"):
                return False, "Corrupted deployment metadata"
        except Exception as err:
            return False, f"Failed to parse deployment metadata: {err}"
        return True, None

    # Remote SSH transport
    ssh_prefix = target_ssh_prefix(target)
    dest = destination_path.rstrip("/")
    check_cmd = (
        f"test -d '{dest}' && "
        f"test -f '{dest}/caasi.yaml' && "
        f"test -f '{dest}/.caasi-deployment.json' && "
        f"cat '{dest}/.caasi-deployment.json'"
    )
    res = subprocess.run(ssh_prefix + [check_cmd], capture_output=True, text=True, timeout=10.0)
    if res.returncode != 0:
        return False, f"Remote verification check failed on {target.name}: {res.stderr.strip() or 'missing files'}"

    try:
        data = json.loads(res.stdout)
        if not data.get("deployment_id"):
            return False, "Remote deployment metadata is corrupted"
    except Exception as err:
        return False, f"Failed to parse remote deployment metadata: {err}"

    return True, None


def get_deployment_status(
    target: Target,
    destination_path: str | None = None,
    config: Config | None = None,
) -> DeploymentRecord | None:
    """Retrieve active deployment status from target."""
    dest = destination_path or (target.deployment_root or "~")
    if target.transport == "local":
        meta_file = Path(dest).expanduser().resolve() / ".caasi-deployment.json"
        if not meta_file.is_file():
            return None
        try:
            data = json.loads(meta_file.read_text(encoding="utf-8"))
            return DeploymentRecord(**data)
        except Exception:
            return None

    # Remote SSH transport
    ssh_prefix = target_ssh_prefix(target)
    cmd = ssh_prefix + [f"cat '{dest.rstrip('/')}/.caasi-deployment.json' 2>/dev/null"]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=10.0)
    if res.returncode != 0 or not res.stdout.strip():
        return None
    try:
        data = json.loads(res.stdout)
        return DeploymentRecord(**data)
    except Exception:
        return None


def list_local_deployments(project_root: Path, target_name: str | None = None) -> list[DeploymentRecord]:
    """List recorded deployments from host project .caasi/deployments/."""
    deploy_root = project_root / ".caasi" / "deployments"
    if not deploy_root.is_dir():
        return []

    records: list[DeploymentRecord] = []
    target_dirs = [deploy_root / target_name] if target_name else list(deploy_root.iterdir())

    for t_dir in target_dirs:
        if not t_dir.is_dir():
            continue
        for f in sorted(t_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                records.append(DeploymentRecord(**data))
            except Exception:
                continue
    return records
