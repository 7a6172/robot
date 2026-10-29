"""ROS 2 discovery and delegation helpers.

The CLI never speaks rclpy — every ROS 2 operation is delegated to the real
``ros2`` CLI via subprocess, so caasi stays a thin orchestration layer.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..utils import shell

ROS_ROOT = Path("/opt/ros")

DEFAULT_TIMEOUT = 20.0


class RosError(RuntimeError):
    """Raised when the ros2 CLI itself is unavailable."""


def find_distro() -> tuple[str | None, Path | None]:
    """Return (distro name, root path) using ROS_DISTRO first, then /opt/ros scan."""
    distro = os.environ.get("ROS_DISTRO")
    if distro:
        root = ROS_ROOT / distro
        return distro, (root if root.is_dir() else None)
    if ROS_ROOT.is_dir():
        try:
            entries = sorted(ROS_ROOT.iterdir())
        except OSError:
            return None, None
        for entry in entries:
            if entry.is_dir() and (entry / "setup.bash").exists():
                return entry.name, entry
    return None, None


def find_ros2_binary() -> str | None:
    """Locate the ros2 CLI (distro bin first, then PATH)."""
    _, root = find_distro()
    if root is not None:
        candidate = root / "bin" / "ros2"
        if candidate.exists():
            return str(candidate)
    return shell.which("ros2")


def require_ros2() -> str:
    """Return the ros2 binary path or raise :class:`RosError`."""
    binary = find_ros2_binary()
    if not binary:
        from ..i18n import _

        raise RosError(_("native.no_ros2"))
    return binary


def run_ros2(
    args: list[str], timeout: float | None = DEFAULT_TIMEOUT
) -> shell.ShellResult:
    """Run ``ros2 <args>`` capturing output.

    The command is wrapped so that it works in an unsourced shell too (see
    :mod:`caasi.core.rosenv`); in an already-sourced shell the wrapper is a
    no-op and the plain binary is executed.

    Raises :class:`RosError` only when the ros2 binary is missing; failing
    ros2 calls are reported through the returned ShellResult.
    """
    from . import rosenv

    binary = require_ros2()
    return shell.run_cmd(rosenv.wrap([binary, *args]), timeout=timeout)


def ros2_lines(
    args: list[str], timeout: float | None = DEFAULT_TIMEOUT
) -> list[str]:
    """Run a ros2 command and return its non-empty stdout lines."""
    result = run_ros2(args, timeout=timeout)
    if not result.ok:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def pkg_prefix(name: str) -> Path | None:
    """Return the install prefix of a ROS package, if installed."""
    result = run_ros2(["pkg", "prefix", name], timeout=DEFAULT_TIMEOUT)
    text = result.stdout.strip()
    if not result.ok or not text:
        return None
    path = Path(text)
    return path if path.is_dir() else None


# --------------------------------------------------------------------------
# Remote ROS 2 queries
#
# caasi stays a thin orchestration layer here too: remote queries delegate to the
# target's own `ros2` CLI over SSH. caasi never speaks rclpy and never
# reimplements DDS or any ROS 2 internals - it only *asks* the target's ROS 2 for
# information, using the same command surface as locally.
# --------------------------------------------------------------------------


def _remote_ros_snippet(ros_setup: str | None, overlay_setup: str | None) -> str:
    """Build the target-side shell that sources ROS and runs a ros2 subcommand.

    The snippet is deliberately minimal: source the underlay, then the optional
    project overlay, then exec ros2. It mirrors what :func:`rosenv.wrap` does
    locally, so a remote answer means the same thing as a local one.
    """
    parts: list[str] = []
    if ros_setup:
        parts.append(f'test -f "{ros_setup}" && . "{ros_setup}"')
    if overlay_setup:
        parts.append(f'test -f "{overlay_setup}" && . "{overlay_setup}"')
    guard = " ; ".join(parts)
    # `command -v ros2` distinguishes "no ROS 2 on the target" from "ros2 failed",
    # which the caller reports differently.
    probe = 'if ! command -v ros2 >/dev/null 2>&1; then echo "CAASI_NO_ROS2" >&2; exit 127; fi'
    return f'{guard} ; {probe} ; exec ros2 "$@"'


#: Subcommands whose answers come from the `ros2` daemon. The daemon caches discovery for two hours
#: and holds UDP 7000 while it lives -- on this robot that is the LiDAR's own port, so a single
#: `ros2 topic list` was enough to break the next bringup. Asking these queries for `--no-daemon`
#: keeps caasi a good citizen: it never leaves a daemon behind.
DAEMONLESS_VERBS = frozenset({"list", "info", "show", "get", "types", "names", "count"})


def without_daemon(args: list[str]) -> list[str]:
    """Append `--no-daemon` to a query that would otherwise start (or use) the ros2 daemon."""
    if len(args) >= 2 and args[1] in DAEMONLESS_VERBS:
        return [*args, "--no-daemon"]
    return list(args)


def remote_ros2(
    target: "Target",
    args: list[str],
    timeout: float | None = DEFAULT_TIMEOUT,
    ros_setup: str | None = None,
    overlay_setup: str | None = None,
    domain_id: int | str | None = None,
) -> "shell.ShellResult":
    """Run ``ros2 <args>`` on a remote SSH target and capture the output.

    Thin delegation: the target's own ros2 CLI produces the answer. Only SSH
    transport, environment sourcing and ROS_DOMAIN_ID selection are caasi's
    concern - DDS discovery itself is entirely ROS 2's.

    This is now a caller of :func:`execution.run_on_target` rather than its own
    snippet builder, so every remote command in caasi shares one implementation of
    environment setup, argument handling and outcome classification.

    Returns a ShellResult; never raises for a non-zero ros2 exit. A transport
    failure (unreachable, timeout) is reported as ``returncode == -1`` with the
    reason in ``stderr``, matching :func:`shell.run_cmd` semantics.
    """
    from . import execution as execution_core

    env = {}
    if domain_id is not None:
        env["ROS_DOMAIN_ID"] = str(domain_id)

    request = execution_core.ExecRequest(
        argv=["ros2", *without_daemon(args)],
        env=env,
        ros_setup=ros_setup,
        overlay_setup=overlay_setup,
        timeout=timeout if timeout is not None else execution_core.DEFAULT_TIMEOUT,
    )
    outcome = execution_core.run_on_target(target, request)
    return shell.ShellResult(
        returncode=outcome.returncode, stdout=outcome.stdout, stderr=outcome.stderr
    )


def remote_ros2_lines(
    target: "Target",
    args: list[str],
    timeout: float | None = DEFAULT_TIMEOUT,
    ros_setup: str | None = None,
    overlay_setup: str | None = None,
    domain_id: int | str | None = None,
) -> list[str]:
    """Run a ros2 command on a remote target and return its non-empty stdout lines."""
    result = remote_ros2(target, args, timeout=timeout,
                         ros_setup=ros_setup, overlay_setup=overlay_setup,
                         domain_id=domain_id)
    if not result.ok:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def remote_ros_environment(target: "Target") -> dict[str, object]:
    """Discover the ROS 2 environment on a remote target, in one SSH round-trip.

    Reports only what the target itself states: whether a ros2 CLI is present,
    the distro name, its install root, and the RMW implementation if set. Values
    that cannot be determined are reported as ``None`` rather than guessed.
    """
    from . import targets as targets_core

    if target.transport != "ssh":
        distro, root = find_distro()
        binary = find_ros2_binary()
        return {
            "available": bool(binary),
            "distro": distro,
            "root": str(root) if root else None,
            "binary": binary,
            "rmw": os.environ.get("RMW_IMPLEMENTATION"),
        }

    prefix = targets_core.target_ssh_prefix(target)
    # ros2 is not on the default non-interactive PATH; a distro must be sourced
    # first, exactly as a run would. Probe every installed distro so the answer
    # reflects what the target actually has rather than a hardcoded assumption.
    probe = (
        'for d in /opt/ros/*/setup.bash; do '
        '  [ -f "$d" ] || continue; . "$d" 2>/dev/null || true; '
        'done; '
        'if ! command -v ros2 >/dev/null 2>&1; then echo "AVAILABLE=0"; exit 0; fi; '
        'echo "AVAILABLE=1"; '
        'echo "DISTRO=${ROS_DISTRO:-}"; '
        'echo "ROOT=${ROS_ROOT:-}"; '
        'echo "RMW=${RMW_IMPLEMENTATION:-}"'
    )
    result = shell.run_cmd([*prefix, probe], timeout=max(10.0, float(target.ssh_timeout) * 2))
    if not result.ok:
        return {"available": False, "error": result.stderr.strip() or "unreachable"}

    fields: dict[str, str] = {}
    for line in result.stdout.splitlines():
        name, sep, value = line.partition("=")
        if sep:
            fields[name.strip()] = value.strip()

    root = fields.get("ROOT") or None
    return {
        "available": fields.get("AVAILABLE") == "1",
        "distro": fields.get("DISTRO") or None,
        "root": root,
        "binary": "/opt/ros/%s/bin/ros2" % fields["DISTRO"] if fields.get("DISTRO") else None,
        "rmw": fields.get("RMW") or None,
    }

