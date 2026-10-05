"""Runtime observability adapters.

Generalises the E2 observation model beyond ROS 2. Each adapter *asks* a runtime
for its state using that runtime's own native interface and returns a normalised
answer:

    runtime          native interface caasi delegates to
    ---------------  -----------------------------------------------
    process          /proc, ps            (bare processes and services)
    systemd          systemctl, journalctl
    container        docker / podman CLI
    ros2             ros2 CLI             (see caasi.core.ros, E2)

Design boundaries, kept deliberately narrow:

* **caasi asks; the runtime remains authoritative.** Every value reported here is
  produced by the runtime's own tooling. caasi does not implement a process
  manager, a Docker client, an init system, or a metrics database.
* **Absence is reported, not guessed.** A runtime that is not present on a target
  is reported as unavailable with the reason, never as an empty-but-successful
  result. Values that cannot be determined are ``None``.
* **Adapters are selected by what the target actually has.** Detection is
  attempted at query time, so a target without systemd simply has no systemd
  adapter rather than a broken one.
* **Nothing is mutated.** Adapters only read state. There is no start, stop,
  enable, restart or remove operation here - lifecycle belongs to E2/D, and
  enablement to a later stage.
"""

from __future__ import annotations

import shlex
from dataclasses import asdict, dataclass, field
from typing import Any

from ..utils import shell
from .targets import Target, target_ssh_prefix

# Runtime identifiers, matching the capability vocabulary used by Target.
RUNTIME_PROCESS = "process"
RUNTIME_SYSTEMD = "systemd"
RUNTIME_CONTAINER = "container"
RUNTIME_ROS2 = "ros2"

ALL_RUNTIMES = (RUNTIME_PROCESS, RUNTIME_SYSTEMD, RUNTIME_CONTAINER, RUNTIME_ROS2)

# Container CLIs, in preference order. caasi does not care which one a target
# uses; it delegates to whichever is present.
CONTAINER_CLIS = ("docker", "podman")

DEFAULT_TIMEOUT = 30.0


class RuntimeError_(RuntimeError):
    """Raised for an unusable adapter request."""


@dataclass
class RuntimeAvailability:
    """Whether one runtime is usable on a target, and via what."""

    runtime: str
    available: bool
    tool: str | None = None       # the native command found, if any
    detail: str | None = None     # reason when unavailable

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RuntimeItem:
    """One item reported by a runtime: a process, unit, or container."""

    name: str
    state: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RuntimeReport:
    """Normalised answer from one adapter query."""

    runtime: str
    target: str
    available: bool
    tool: str | None = None
    items: list[RuntimeItem] = field(default_factory=list)
    error: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "runtime": self.runtime,
            "target": self.target,
            "available": self.available,
            "tool": self.tool,
            "item_count": len(self.items),
            "items": [i.to_dict() for i in self.items],
            "error": self.error,
            "detail": self.detail,
        }


# ---------------------------------------------------------------------------
# Transport
#
# One primitive, shared by every adapter: run a command either locally or on an
# SSH target. Kept here rather than in each adapter so the transport story stays
# in one place. Mirrors caasi.core.ros's approach - local runs directly, SSH
# joins a single quoted command through the ssh prefix - without duplicating its
# ROS-specific environment sourcing, which adapters do not need.
# ---------------------------------------------------------------------------


def run_on_target(
    target: Target,
    argv: list[str],
    timeout: float | None = DEFAULT_TIMEOUT,
) -> shell.ShellResult:
    """Run *argv* locally, or on an SSH target, capturing output.

    Never raises for a non-zero exit: a transport failure is ``returncode == -1``
    with the reason in stderr, matching :func:`shell.run_cmd`.
    """
    if target.transport != "ssh":
        return shell.run_cmd(argv, timeout=timeout)

    prefix = target_ssh_prefix(target)
    # shlex.join preserves argument boundaries through the remote shell.
    remote = shlex.join([str(a) for a in argv])
    return shell.run_cmd([*prefix, remote], timeout=timeout)


def _budget(target: Target, base: float = DEFAULT_TIMEOUT) -> float:
    """Per-call timeout, sized to the target's link when it is slow."""
    return max(base, float(target.ssh_timeout) * 2)


# ---------------------------------------------------------------------------
# Availability detection
# ---------------------------------------------------------------------------


def detect_availability(
    target: Target, timeout: float | None = None
) -> dict[str, RuntimeAvailability]:
    """Probe which runtimes the target exposes, in ONE round-trip.

    Probing is cheap and explicit: caasi asks the target whether each native tool
    exists rather than assuming a platform. A missing runtime is reported as
    unavailable with a reason, not silently omitted.
    """
    timeout = timeout if timeout is not None else _budget(target, 20.0)

    probe = (
        "for t in systemctl journalctl docker podman ps; do "
        '  if command -v "$t" >/dev/null 2>&1; then echo "TOOL:$t=$(command -v "$t")"; '
        '  else echo "TOOL:$t="; fi; '
        "done; "
        'if [ -d /proc ]; then echo "PROC=1"; else echo "PROC=0"; fi; '
        'if [ -d /run/systemd/system ]; then echo "SYSTEMD_RUNNING=1"; else echo "SYSTEMD_RUNNING=0"; fi'
    )
    result = run_on_target(target, ["bash", "-c", probe], timeout=timeout)

    if not result.ok:
        reason = result.stderr.strip() or "target unreachable"
        return {
            r: RuntimeAvailability(r, False, None, reason) for r in ALL_RUNTIMES
        }

    tools: dict[str, str] = {}
    flags: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if line.startswith("TOOL:"):
            name, _, path = line[5:].partition("=")
            tools[name.strip()] = path.strip()
        elif "=" in line:
            key, _, value = line.partition("=")
            flags[key.strip()] = value.strip()

    has_proc = flags.get("PROC") == "1"
    has_ps = bool(tools.get("ps"))
    systemd_present = bool(tools.get("systemctl")) and flags.get("SYSTEMD_RUNNING") == "1"
    container_cli = next((c for c in CONTAINER_CLIS if tools.get(c)), None)

    out: dict[str, RuntimeAvailability] = {
        RUNTIME_PROCESS: RuntimeAvailability(
            RUNTIME_PROCESS,
            has_proc or has_ps,
            "ps" if has_ps else ("/proc" if has_proc else None),
            None if (has_proc or has_ps) else "no /proc and no ps",
        ),
        RUNTIME_SYSTEMD: RuntimeAvailability(
            RUNTIME_SYSTEMD,
            systemd_present,
            tools.get("systemctl") or None,
            None if systemd_present else (
                "systemctl not present" if not tools.get("systemctl")
                else "systemd not running (not PID 1 / container)"
            ),
        ),
        RUNTIME_CONTAINER: RuntimeAvailability(
            RUNTIME_CONTAINER,
            bool(container_cli),
            tools.get(container_cli) if container_cli else None,
            None if container_cli else "no docker or podman on PATH",
        ),
    }

    # ROS 2 availability is decided by its own adapter; delegate rather than
    # duplicate the check here.
    try:
        from . import ros as ros_core

        env = ros_core.remote_ros_environment(target)
        out[RUNTIME_ROS2] = RuntimeAvailability(
            RUNTIME_ROS2,
            bool(env.get("available")),
            env.get("binary"),
            None if env.get("available") else (
                str(env.get("error")) if env.get("error") else "no ros2 CLI"
            ),
        )
    except Exception as exc:  # pragma: no cover - defensive
        out[RUNTIME_ROS2] = RuntimeAvailability(RUNTIME_ROS2, False, None, str(exc))

    return out


# ---------------------------------------------------------------------------
# Process adapter  (/proc, ps)
# ---------------------------------------------------------------------------


def query_processes(
    target: Target,
    match: str | None = None,
    limit: int = 50,
    timeout: float | None = None,
) -> RuntimeReport:
    """List processes via the target's own process tables.

    Uses ``ps`` when available and falls back to ``/proc``. *match* filters by
    command substring, which is how an operator finds "the thing I started".
    """
    timeout = timeout if timeout is not None else _budget(target)
    avail = detect_availability(target, timeout=timeout).get(RUNTIME_PROCESS)
    if avail is None or not avail.available:
        return RuntimeReport(
            RUNTIME_PROCESS, target.name, False, None, [],
            (avail.detail if avail else "process inspection unavailable"),
        )

    if avail.tool == "ps" or (avail.tool or "").endswith("ps"):
        cmd = ["ps", "-eo", "pid=,ppid=,pgid=,stat=,etime=,comm=,args="]
        result = run_on_target(target, cmd, timeout=timeout)
        items: list[RuntimeItem] = []
        if result.ok:
            for line in result.stdout.splitlines():
                parts = line.split(None, 6)
                if len(parts) < 7:
                    continue
                pid, ppid, pgid, stat, etime, comm, args = parts
                if match and match not in line:
                    continue
                # Kernel threads dominate a bare listing and are almost never
                # what an operator wants. ps prints their command in brackets,
                # e.g. "[kthreadd]" or "[kworker/0:0H-ev]", which is a reliable
                # signal. They remain reachable via --match, which bypasses this.
                if not match and args.strip().startswith("["):
                    continue
                items.append(RuntimeItem(
                    name=comm.strip(),
                    state=stat.strip(),
                    detail={"pid": _int(pid), "ppid": _int(ppid), "pgid": _int(pgid),
                            "etime": etime.strip(), "args": args.strip()},
                ))
                if len(items) >= limit:
                    break
        else:
            return RuntimeReport(RUNTIME_PROCESS, target.name, True, avail.tool, [],
                                 result.stderr.strip() or "ps failed")
        return RuntimeReport(RUNTIME_PROCESS, target.name, True, avail.tool, items,
                             detail={"match": match, "limit": limit})

    # /proc fallback: no ps available.
    cmd = ["bash", "-c",
           'for p in /proc/[0-9]*; do '
           '  pid=${p#/proc/}; '
           '  [ -r "$p/comm" ] || continue; '
           '  printf "%s %s %s\\n" "$pid" "$(cat $p/stat 2>/dev/null | cut -d" " -f5)" "$(cat $p/comm 2>/dev/null)"; '
           'done']
    result = run_on_target(target, cmd, timeout=timeout)
    items = []
    if result.ok:
        for line in result.stdout.splitlines():
            pid, _, rest = line.partition(" ")
            pgid, _, comm = rest.partition(" ")
            if match and match not in line:
                continue
            items.append(RuntimeItem(comm.strip(), None,
                                     {"pid": _int(pid), "pgid": _int(pgid)}))
            if len(items) >= limit:
                break
    return RuntimeReport(RUNTIME_PROCESS, target.name, True, avail.tool or "/proc",
                         items, detail={"match": match, "limit": limit})


# ---------------------------------------------------------------------------
# systemd adapter  (systemctl, journalctl)
# ---------------------------------------------------------------------------


def query_systemd(
    target: Target,
    unit: str | None = None,
    user: bool = True,
    timeout: float | None = None,
) -> RuntimeReport:
    """Query systemd units, delegating entirely to systemctl.

    *user* selects the user manager, which is the realistic scope for a
    developer-owned robotics stack and needs no elevated privileges. caasi does
    not interpret unit files - it reports what systemd says.
    """
    timeout = timeout if timeout is not None else _budget(target)
    avail = detect_availability(target, timeout=timeout).get(RUNTIME_SYSTEMD)
    if avail is None or not avail.available:
        return RuntimeReport(
            RUNTIME_SYSTEMD, target.name, False, None, [],
            (avail.detail if avail else "systemd unavailable"),
        )

    scope = ["--user"] if user else []
    if unit:
        cmd = ["systemctl", *scope, "show", unit, "--no-pager"]
        result = run_on_target(target, cmd, timeout=timeout)
        if not result.ok:
            return RuntimeReport(RUNTIME_SYSTEMD, target.name, True, "systemctl", [],
                                 result.stderr.strip() or f"unit '{unit}' not found")
        props = {}
        for line in result.stdout.splitlines():
            key, _, value = line.partition("=")
            if key.strip() in ("Id", "Description", "LoadState", "ActiveState",
                               "SubState", "UnitFileState", "MainPID", "ExecMainStatus"):
                props[key.strip()] = value.strip()
        item = RuntimeItem(
            name=props.get("Id", unit),
            state=props.get("ActiveState"),
            detail={k.lower(): v for k, v in props.items()},
        )
        return RuntimeReport(RUNTIME_SYSTEMD, target.name, True, "systemctl", [item],
                             detail={"scope": "user" if user else "system"})

    cmd = ["systemctl", *scope, "list-units", "--no-pager", "--plain", "--type=service",
           "--all", "--no-legend"]
    result = run_on_target(target, cmd, timeout=timeout)
    if not result.ok:
        return RuntimeReport(RUNTIME_SYSTEMD, target.name, True, "systemctl", [],
                             result.stderr.strip() or "systemctl list-units failed")

    items: list[RuntimeItem] = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        name, load, active, sub = parts[0], parts[1], parts[2], parts[3]
        items.append(RuntimeItem(
            name=name, state=active,
            detail={"load": load, "sub": sub,
                    "description": " ".join(parts[4:]) if len(parts) > 4 else ""},
        ))
    return RuntimeReport(RUNTIME_SYSTEMD, target.name, True, "systemctl", items,
                         detail={"scope": "user" if user else "system"})


def query_systemd_logs(
    target: Target,
    unit: str,
    lines: int = 50,
    user: bool = True,
    timeout: float | None = None,
) -> RuntimeReport:
    """Read a unit's journal via journalctl. Delegation only; nothing is parsed."""
    timeout = timeout if timeout is not None else _budget(target)
    avail = detect_availability(target, timeout=timeout)
    if not avail.get(RUNTIME_SYSTEMD, RuntimeAvailability(RUNTIME_SYSTEMD, False)).available:
        return RuntimeReport(RUNTIME_SYSTEMD, target.name, False, None, [],
                             "systemd unavailable")

    scope = ["--user"] if user else []
    cmd = ["journalctl", *scope, "-u", unit, "-n", str(max(lines, 1)), "--no-pager"]
    result = run_on_target(target, cmd, timeout=timeout)
    text = "\n".join(p for p in (result.stdout, result.stderr) if p).strip()
    return RuntimeReport(
        RUNTIME_SYSTEMD, target.name, True, "journalctl", [],
        error=None if result.ok else (result.stderr.strip() or "journalctl failed"),
        detail={"unit": unit, "lines": lines, "output": text},
    )


# ---------------------------------------------------------------------------
# Container adapter  (docker / podman CLI)
# ---------------------------------------------------------------------------


def query_containers(
    target: Target,
    all_containers: bool = True,
    timeout: float | None = None,
) -> RuntimeReport:
    """List containers via the target's own container CLI.

    caasi does not speak the Docker API and does not manage containers: it asks
    ``docker ps`` (or podman) and reports the answer. Whichever CLI the target
    has is used, so the adapter is not tied to one implementation.
    """
    timeout = timeout if timeout is not None else _budget(target)
    avail = detect_availability(target, timeout=timeout).get(RUNTIME_CONTAINER)
    if avail is None or not avail.available:
        return RuntimeReport(
            RUNTIME_CONTAINER, target.name, False, None, [],
            (avail.detail if avail else "no container runtime"),
        )

    cli = avail.tool or "docker"
    fmt = "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.State}}\t{{.RunningFor}}"
    cmd = [cli, "ps", "--format", fmt]
    if all_containers:
        cmd.insert(2, "-a")
    result = run_on_target(target, cmd, timeout=timeout)
    if not result.ok:
        return RuntimeReport(RUNTIME_CONTAINER, target.name, True, cli, [],
                             result.stderr.strip() or f"{cli} ps failed")

    items: list[RuntimeItem] = []
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        cid, name, image, status, state = parts[0], parts[1], parts[2], parts[3], parts[4]
        items.append(RuntimeItem(
            name=name, state=state,
            detail={"id": cid, "image": image, "status": status,
                    "running_for": parts[5] if len(parts) > 5 else ""},
        ))
    return RuntimeReport(RUNTIME_CONTAINER, target.name, True, cli, items,
                         detail={"cli": cli})


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def query_runtime(
    target: Target,
    runtime: str,
    timeout: float | None = None,
    **kwargs: Any,
) -> RuntimeReport:
    """Query one runtime by name, dispatching to its adapter."""
    if runtime == RUNTIME_PROCESS:
        return query_processes(target, **kwargs)
    if runtime == RUNTIME_SYSTEMD:
        return query_systemd(target, **kwargs)
    if runtime == RUNTIME_CONTAINER:
        return query_containers(target, **kwargs)
    if runtime == RUNTIME_ROS2:
        from . import ros as ros_core

        env = ros_core.remote_ros_environment(target)
        if "error" in env:
            return RuntimeReport(RUNTIME_ROS2, target.name, False, None, [],
                                 str(env["error"]))
        return RuntimeReport(
            RUNTIME_ROS2, target.name, bool(env.get("available")),
            env.get("binary"), [],
            None if env.get("available") else "no ros2 CLI",
            detail={"distro": env.get("distro"), "root": env.get("root"),
                    "rmw": env.get("rmw")},
        )
    raise RuntimeError_(f"unknown runtime '{runtime}' (expected {', '.join(ALL_RUNTIMES)})")


def query_all(
    target: Target, timeout: float | None = None
) -> tuple[dict[str, RuntimeAvailability], list[RuntimeReport]]:
    """Detect every runtime on a target, then query each available one.

    Returns the availability map plus one report per runtime. An unavailable
    runtime still yields a report explaining why, so a caller never has to infer
    absence from an empty list.
    """
    availability = detect_availability(target, timeout=timeout)
    reports: list[RuntimeReport] = []
    for runtime in ALL_RUNTIMES:
        entry = availability.get(runtime)
        if entry is None or not entry.available:
            reports.append(RuntimeReport(
                runtime, target.name, False, entry.tool if entry else None, [],
                entry.detail if entry else "unavailable",
            ))
            continue
        try:
            reports.append(query_runtime(target, runtime, timeout=timeout))
        except Exception as exc:  # pragma: no cover - defensive
            reports.append(RuntimeReport(runtime, target.name, True,
                                         entry.tool, [], str(exc)))
    return availability, reports


def _int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
