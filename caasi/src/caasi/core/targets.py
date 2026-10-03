"""Target abstraction model and capability discovery (Phase 7 Stage A).

A Target represents an execution destination (local workstation, remote robot,
edge device, simulation server, or compute cluster). caasi models targets
in a capability- and resource-driven manner without hardcoding specific robot
hardware or vendor assumptions into core abstractions.
"""

from __future__ import annotations

import json
import os
import platform
import re
import socket
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..utils import shell
from . import environment
from .config import Config
from .remotes import list_remotes

#: Compact Python probe script executed on remote SSH targets without requiring
#: caasi or third-party packages to be preinstalled on the remote target.
REMOTE_PROBE_SCRIPT = r"""
import json, os, platform, shutil, subprocess, sys

def get_mem():
    mem = {}
    try:
        with open('/proc/meminfo', 'r') as f:
            for line in f:
                parts = line.split(':')
                if len(parts) == 2:
                    k = parts[0].strip()
                    v = parts[1].strip().split()[0]
                    if k in ('MemTotal', 'MemAvailable'):
                        mem[k] = int(v)
    except Exception:
        pass
    return mem

def get_cpu():
    try:
        with open('/proc/cpuinfo', 'r') as f:
            for line in f:
                if 'model name' in line:
                    return line.split(':', 1)[1].strip()
    except Exception:
        pass
    return platform.processor() or None

def get_gpu():
    gpus = []
    cuda_driver_max = None
    cuda_toolkit = None
    driver = None
    if shutil.which('nvidia-smi'):
        try:
            res = subprocess.run(
                ['nvidia-smi', '--query-gpu=name,memory.total,driver_version', '--format=csv,noheader,nounits'],
                capture_output=True, text=True, timeout=5
            )
            if res.returncode == 0:
                for line in res.stdout.strip().splitlines():
                    p = [x.strip() for x in line.split(',')]
                    if len(p) >= 3:
                        driver = p[2]
                        gpus.append({'name': p[0], 'memory_total_mib': int(p[1]) if p[1].isdigit() else None, 'driver_version': p[2]})
        except Exception:
            pass
        try:
            res = subprocess.run(['nvidia-smi'], capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    if 'CUDA Version:' in line:
                        cuda_driver_max = line.split('CUDA Version:')[-1].strip().split()[0]
        except Exception:
            pass
    if shutil.which('nvcc'):
        try:
            res = subprocess.run(['nvcc', '--version'], capture_output=True, text=True, timeout=3)
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    if 'release' in line:
                        cuda_toolkit = line.split('release')[-1].split(',')[0].strip()
        except Exception:
            pass
    return gpus, driver, cuda_driver_max, cuda_toolkit

def get_ros():
    distro = os.environ.get('ROS_DISTRO')
    root = None
    if not distro and os.path.isdir('/opt/ros'):
        sub = [d for d in os.listdir('/opt/ros') if os.path.isdir(os.path.join('/opt/ros', d))]
        if sub:
            distro = sorted(sub)[-1]
            root = f'/opt/ros/{distro}'
    elif distro:
        root = f'/opt/ros/{distro}'
    return distro, root

mem = get_mem()
gpus, driver, cuda_driver_max, cuda_toolkit = get_gpu()
ros_distro, ros_root = get_ros()

out = {
    'system': {
        'os': platform.platform(),
        'kernel': platform.release(),
        'arch': platform.machine(),
        'hostname': platform.node(),
    },
    'hardware': {
        'cpu_model': get_cpu(),
        'cpu_count': os.cpu_count(),
        'memory_total_kib': mem.get('MemTotal'),
        'memory_available_kib': mem.get('MemAvailable'),
    },
    'gpu': {'devices': gpus},
    'drivers': {
        'nvidia': driver,
        'cuda_driver_max': cuda_driver_max,
        'cuda_toolkit': cuda_toolkit,
        'cuda': cuda_toolkit or cuda_driver_max,
    },
    'python': {'version': platform.python_version()},
    'ros': {'distro': ros_distro, 'root': ros_root, 'rmw': os.environ.get('RMW_IMPLEMENTATION')},
    'docker': {'installed': shutil.which('docker') is not None}
}
print(json.dumps(out))
"""


def detect_nvcc_toolkit() -> str | None:
    """Return installed CUDA toolkit version from nvcc, if present."""
    if shell.which("nvcc") is None:
        return None
    res = shell.run_cmd(["nvcc", "--version"], timeout=5.0)
    if not res.ok:
        return None
    match = re.search(r"release\s+([\d.]+)", res.stdout)
    return match.group(1) if match else None


@dataclass(frozen=True)
class Target:
    """Configured target specification."""

    name: str
    transport: str = "local"  # "local" | "ssh"
    host: str | None = None
    user: str | None = None
    port: int | None = None
    identity: str | None = None
    deployment_root: str | None = None
    tags: list[str] = field(default_factory=list)
    declared_capabilities: list[str] = field(default_factory=list)
    declared_resources: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TargetResources:
    """Discovered hardware and resource attributes."""

    cpu_model: str | None = None
    cpu_count: int | None = None
    memory_total_kib: int | None = None
    memory_available_kib: int | None = None
    gpus: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TargetEnvironment:
    """Discovered OS and ecosystem software stack."""

    os: str | None = None
    kernel: str | None = None
    arch: str | None = None
    hostname: str | None = None
    python_version: str | None = None
    ros_distro: str | None = None
    ros_root: str | None = None
    rmw: str | None = None
    cuda_driver_max: str | None = None  # Maximum CUDA supported by NVIDIA driver (nvidia-smi)
    cuda_toolkit: str | None = None     # Installed CUDA compiler/toolkit version (nvcc)
    cuda_version: str | None = None     # Effective CUDA version (prefers toolkit, fallback driver)
    nvidia_driver: str | None = None
    isaac_sim: dict[str, Any] | None = None
    isaac_lab: dict[str, Any] | None = None
    docker: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TargetInspection:
    """Comprehensive inspection result for a target."""

    target: Target
    reachable: bool
    status: str  # "online", "unreachable", "error"
    ping_ms: float | None = None           # Network TCP round-trip latency (0.0 ms for local)
    probe_duration_ms: float | None = None # Total elapsed time to collect target inspection facts
    latency_ms: float | None = None        # Alias to ping_ms (preserving API compatibility)
    resources: TargetResources | None = None
    environment: TargetEnvironment | None = None
    discovered_capabilities: list[str] = field(default_factory=list)
    mismatches: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target.to_dict(),
            "reachable": self.reachable,
            "status": self.status,
            "ping_ms": self.ping_ms,
            "probe_duration_ms": self.probe_duration_ms,
            "latency_ms": self.latency_ms,
            "resources": self.resources.to_dict() if self.resources else None,
            "environment": self.environment.to_dict() if self.environment else None,
            "discovered_capabilities": self.discovered_capabilities,
            "mismatches": self.mismatches,
            "error": self.error,
        }


def target_ssh_prefix(target: Target) -> list[str]:
    """Build ssh invocation argument list for an SSH target."""
    args = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=3",
        "-o",
        "StrictHostKeyChecking=accept-new",
    ]
    if target.port:
        args += ["-p", str(target.port)]
    if target.identity:
        args += ["-i", str(Path(target.identity).expanduser())]
    endpoint = f"{target.user}@{target.host}" if target.user else (target.host or "")
    args.append(endpoint)
    return args


def check_socket_reachable(host: str, port: int = 22, timeout: float = 1.5) -> tuple[bool, float | None]:
    """Test TCP connectivity to host:port with bounded timeout."""
    start = time.perf_counter()
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        latency_ms = (time.perf_counter() - start) * 1000.0
        return True, round(latency_ms, 2)
    except (OSError, socket.timeout):
        return False, None


def detect_mismatches(
    target: Target,
    resources: TargetResources | None,
    env: TargetEnvironment | None,
    discovered_capabilities: list[str],
) -> list[str]:
    """Compare declared capabilities and resources against discovered facts."""
    mismatches: list[str] = []
    disc_caps_lower = {c.lower() for c in discovered_capabilities}

    # Verify declared capabilities
    for cap in target.declared_capabilities:
        c_lower = cap.lower().strip()
        # Direct match or prefix match (e.g. 'ros2' matches 'ros2:jazzy')
        if not any(c_lower == dc or dc.startswith(f"{c_lower}:") for dc in disc_caps_lower):
            mismatches.append(f"Declared capability '{cap}' not detected on target")

    # Verify declared resources
    if target.declared_resources:
        # Architecture check
        decl_arch = target.declared_resources.get("arch")
        if decl_arch and env and env.arch:
            if str(decl_arch).lower() != env.arch.lower():
                mismatches.append(
                    f"Architecture mismatch: declared '{decl_arch}', detected '{env.arch}'"
                )

        # GPU presence check
        decl_gpu = target.declared_resources.get("gpu")
        if decl_gpu is True:
            if not resources or not resources.gpus:
                mismatches.append("GPU mismatch: declared gpu=True, but no GPU devices detected")

        # CUDA check
        decl_cuda = target.declared_resources.get("cuda")
        if decl_cuda and env:
            if not env.cuda_version:
                mismatches.append(f"CUDA mismatch: declared '{decl_cuda}', but CUDA was not detected")

        # ROS distro check
        decl_ros = target.declared_resources.get("ros_distro")
        if decl_ros and env and env.ros_distro:
            if str(decl_ros).lower() != env.ros_distro.lower():
                mismatches.append(
                    f"ROS distro mismatch: declared '{decl_ros}', detected '{env.ros_distro}'"
                )

    return mismatches


def list_targets(config: Config) -> list[Target]:
    """Return all configured targets.

    Merges targets declared in ``targets:``, automatically ensures the built-in
    ``local`` target exists unless overridden, and imports any legacy ``remotes:``
    entries.
    """
    targets_map: dict[str, Target] = {}

    # 1. Parse declared targets from config
    raw_targets = config.get("targets")
    if isinstance(raw_targets, dict):
        for name, spec in raw_targets.items():
            if not isinstance(spec, dict):
                continue
            transport = spec.get("transport", "ssh" if spec.get("host") else "local")
            targets_map[str(name)] = Target(
                name=str(name),
                transport=str(transport),
                host=spec.get("host"),
                user=spec.get("user"),
                port=spec.get("port"),
                identity=spec.get("identity"),
                deployment_root=spec.get("deployment_root"),
                tags=list(spec.get("tags") or []),
                declared_capabilities=list(spec.get("capabilities") or []),
                declared_resources=dict(spec.get("resources") or {}),
            )

    # 2. Ensure built-in local target is present if not explicitly specified
    if "local" not in targets_map:
        targets_map["local"] = Target(
            name="local",
            transport="local",
            tags=["local", "workstation"],
            deployment_root=".",
        )

    # 3. Import legacy remotes from config
    for remote in list_remotes(config):
        if remote.name not in targets_map:
            targets_map[remote.name] = Target(
                name=remote.name,
                transport="ssh",
                host=remote.host,
                user=remote.user,
                port=remote.port,
                identity=remote.identity,
                deployment_root=remote.path or "~",
                tags=["remote", "gpu"],
            )

    return list(targets_map.values())


def find_target(config: Config, query: str) -> Target | None:
    """Resolve a target by exact name or unique name prefix."""
    query = query.strip()
    targets = list_targets(config)
    exact = [t for t in targets if t.name == query]
    if exact:
        return exact[0]
    matches = [t for t in targets if t.name.startswith(query)]
    return matches[0] if len(matches) == 1 else None


def discover_target(
    target: Target,
    config: Config | None = None,
    timeout: float = 3.0,
) -> TargetInspection:
    """Perform capability discovery and resource inspection on a target."""
    cfg = config if config is not None else Config({}, [])

    start = time.perf_counter()

    if target.transport == "local":
        raw_env = environment.collect(cfg)
        probe_duration_ms = round((time.perf_counter() - start) * 1000.0, 2)
        ping_ms = 0.0

        hw = raw_env.get("hardware") or {}
        gpu_info = raw_env.get("gpu") or {}
        sys_info = raw_env.get("system") or {}
        drivers = raw_env.get("drivers") or {}
        python_info = raw_env.get("python") or {}
        ros_info = raw_env.get("ros") or {}
        isaac_info = raw_env.get("isaac") or {}
        docker_info = raw_env.get("docker") or {}

        resources = TargetResources(
            cpu_model=hw.get("cpu_model"),
            cpu_count=hw.get("cpu_count"),
            memory_total_kib=hw.get("memory_total_kib"),
            memory_available_kib=hw.get("memory_available_kib"),
            gpus=gpu_info.get("devices") or [],
        )

        cuda_toolkit = detect_nvcc_toolkit()
        cuda_driver_max = drivers.get("cuda")
        cuda_eff = cuda_toolkit or cuda_driver_max

        target_env = TargetEnvironment(
            os=sys_info.get("os"),
            kernel=sys_info.get("kernel"),
            arch=sys_info.get("arch"),
            hostname=sys_info.get("hostname"),
            python_version=python_info.get("version"),
            ros_distro=ros_info.get("distro"),
            ros_root=ros_info.get("root"),
            rmw=ros_info.get("rmw"),
            cuda_driver_max=cuda_driver_max,
            cuda_toolkit=cuda_toolkit,
            cuda_version=cuda_eff,
            nvidia_driver=drivers.get("nvidia"),
            isaac_sim=isaac_info.get("sim"),
            isaac_lab=isaac_info.get("lab"),
            docker=bool(docker_info.get("installed")),
        )

        caps: list[str] = []
        if resources.gpus:
            caps.append("gpu")
        if target_env.cuda_version:
            caps.append("cuda")
        if target_env.ros_distro:
            caps.append("ros2")
            caps.append(f"ros2:{target_env.ros_distro}")
        if target_env.isaac_sim and target_env.isaac_sim.get("status") in ("detected", "installed", "ok"):
            caps.append("isaac_sim")
        if target_env.isaac_lab and target_env.isaac_lab.get("status") in ("detected", "installed", "ok"):
            caps.append("isaac_lab")
        if target_env.docker:
            caps.append("docker")

        mismatches = detect_mismatches(target, resources, target_env, caps)

        return TargetInspection(
            target=target,
            reachable=True,
            status="online",
            ping_ms=ping_ms,
            probe_duration_ms=probe_duration_ms,
            latency_ms=ping_ms,
            resources=resources,
            environment=target_env,
            discovered_capabilities=sorted(caps),
            mismatches=mismatches,
        )

    # Remote SSH transport
    if not target.host:
        return TargetInspection(
            target=target,
            reachable=False,
            status="error",
            error="Remote target missing host address",
        )

    port = target.port or 22
    reachable, ping_ms = check_socket_reachable(target.host, port, timeout=min(timeout, 2.0))
    if not reachable:
        return TargetInspection(
            target=target,
            reachable=False,
            status="unreachable",
            error=f"Could not connect to {target.host}:{port}",
        )

    # Execute remote Python probe script
    cmd = target_ssh_prefix(target) + ["python3", "-c", REMOTE_PROBE_SCRIPT.strip()]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        probe_duration_ms = round((time.perf_counter() - start) * 1000.0, 2)
        return TargetInspection(
            target=target,
            reachable=True,
            status="error",
            ping_ms=ping_ms,
            probe_duration_ms=probe_duration_ms,
            latency_ms=ping_ms,
            error=f"Remote probe timed out after {timeout}s",
        )
    except OSError as err:
        probe_duration_ms = round((time.perf_counter() - start) * 1000.0, 2)
        return TargetInspection(
            target=target,
            reachable=True,
            status="error",
            ping_ms=ping_ms,
            probe_duration_ms=probe_duration_ms,
            latency_ms=ping_ms,
            error=f"Failed to execute SSH probe: {err}",
        )

    probe_duration_ms = round((time.perf_counter() - start) * 1000.0, 2)

    if proc.returncode != 0:
        err_msg = proc.stderr.strip() or f"exit code {proc.returncode}"
        return TargetInspection(
            target=target,
            reachable=True,
            status="error",
            ping_ms=ping_ms,
            probe_duration_ms=probe_duration_ms,
            latency_ms=ping_ms,
            error=f"Remote probe failed: {err_msg}",
        )

    try:
        raw = json.loads(proc.stdout)
    except json.JSONDecodeError as err:
        return TargetInspection(
            target=target,
            reachable=True,
            status="error",
            ping_ms=ping_ms,
            probe_duration_ms=probe_duration_ms,
            latency_ms=ping_ms,
            error=f"Invalid JSON returned from remote probe: {err}",
        )

    hw = raw.get("hardware") or {}
    gpu_info = raw.get("gpu") or {}
    sys_info = raw.get("system") or {}
    drivers = raw.get("drivers") or {}
    python_info = raw.get("python") or {}
    ros_info = raw.get("ros") or {}
    docker_info = raw.get("docker") or {}

    resources = TargetResources(
        cpu_model=hw.get("cpu_model"),
        cpu_count=hw.get("cpu_count"),
        memory_total_kib=hw.get("memory_total_kib"),
        memory_available_kib=hw.get("memory_available_kib"),
        gpus=gpu_info.get("devices") or [],
    )

    cuda_driver_max = drivers.get("cuda_driver_max")
    cuda_toolkit = drivers.get("cuda_toolkit")
    cuda_eff = drivers.get("cuda") or cuda_toolkit or cuda_driver_max

    target_env = TargetEnvironment(
        os=sys_info.get("os"),
        kernel=sys_info.get("kernel"),
        arch=sys_info.get("arch"),
        hostname=sys_info.get("hostname"),
        python_version=python_info.get("version"),
        ros_distro=ros_info.get("distro"),
        ros_root=ros_info.get("root"),
        rmw=ros_info.get("rmw"),
        cuda_driver_max=cuda_driver_max,
        cuda_toolkit=cuda_toolkit,
        cuda_version=cuda_eff,
        nvidia_driver=drivers.get("nvidia"),
        docker=bool(docker_info.get("installed")),
    )

    caps = []
    if resources.gpus:
        caps.append("gpu")
    if target_env.cuda_version:
        caps.append("cuda")
    if target_env.ros_distro:
        caps.append("ros2")
        caps.append(f"ros2:{target_env.ros_distro}")
    if target_env.docker:
        caps.append("docker")

    mismatches = detect_mismatches(target, resources, target_env, caps)

    return TargetInspection(
        target=target,
        reachable=True,
        status="online",
        ping_ms=ping_ms,
        probe_duration_ms=probe_duration_ms,
        latency_ms=ping_ms,
        resources=resources,
        environment=target_env,
        discovered_capabilities=sorted(caps),
        mismatches=mismatches,
    )
