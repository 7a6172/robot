"""Generic command execution on a target, with optional ROS environment setup.

`caasi ros --target` already delegates `ros2 <args>` to a target's own CLI. That is the
right shape but it is ROS-specific: it cannot run `nvidia-smi`, a build tool, or a
diagnostic script. This module generalises the same mechanism so any command can run on
a target through one path, and `ros.remote_ros2` becomes a caller of it rather than a
second implementation.

Design notes that matter:

* **Structured argv, not a shell string.** Arguments are joined with ``shlex.join`` and
  handed to ``bash -c ... -- "$@"``, so boundaries survive spaces, quotes, Unicode and
  shell metacharacters. A shell is unavoidable because sourcing ROS setup scripts is a
  shell operation; the boundary is explicit and only our own snippet is ever interpreted.
* **Setup failure is not hidden.** The old snippet used ``test -f X && . X``, which
  *silently* skips a missing setup script and then reports whatever the command does --
  a missing overlay looked like a working environment. Now a missing or failing setup
  script aborts with a distinct exit code and marker.
* **Transport, setup and command failures are distinguishable.** ``ssh`` returns 255 for
  connection failures; our snippet returns 126/127 with markers for setup/ROS problems;
  anything else is the command's own exit status.
* **Timeouts are reported as timeouts.** A timeout is never reported as a failed command.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field

from ..utils import shell
from . import targets as targets_core

#: The remote shell could not prepare the environment (missing/failing setup script, bad
#: working directory). Distinct from the command's own exit status.
EXIT_SETUP_FAILED = 126
#: A ROS 2 environment was requested but no `ros2` is usable after setup.
EXIT_NO_ROS2 = 127
#: ssh's own exit status for a connection/authentication failure.
SSH_TRANSPORT_FAILURE = 255

MARK_SETUP_FAILED = "CAASI_SETUP_FAILED"
MARK_NO_ROS2 = "CAASI_NO_ROS2"
MARK_CWD_FAILED = "CAASI_CWD_FAILED"

DEFAULT_TIMEOUT = 60.0

#: How an execution ended. Callers should branch on this rather than on the exit code
#: alone, because 0 from ssh does not mean the remote command succeeded.
OUTCOME_OK = "ok"
OUTCOME_NONZERO = "nonzero"
OUTCOME_TIMEOUT = "timeout"
OUTCOME_TRANSPORT = "transport"
OUTCOME_SETUP = "setup"
OUTCOME_NO_ROS2 = "no_ros2"


@dataclass(frozen=True)
class ExecRequest:
    """What to run, and in which environment."""

    argv: list[str]
    cwd: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    #: Target-side path to a ROS setup script (e.g. /opt/ros/jazzy/setup.bash).
    ros_setup: str | None = None
    #: Target-side path to a workspace overlay (e.g. <ws>/install/setup.bash).
    overlay_setup: str | None = None
    timeout: float = DEFAULT_TIMEOUT


@dataclass
class ExecResult:
    """Outcome of an execution, including why it ended the way it did."""

    target: str
    argv: list[str]
    outcome: str
    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    #: Human-readable reason when something prevented the command from running or
    #: completing; empty when the command itself ran to completion.
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome == OUTCOME_OK

    @property
    def ran(self) -> bool:
        """True when the remote shell at least started the command."""
        return self.outcome in (OUTCOME_OK, OUTCOME_NONZERO)

    def summary(self) -> dict[str, object]:
        return {
            "target": self.target,
            "argv": list(self.argv),
            "outcome": self.outcome,
            "returncode": self.returncode,
            "timed_out": self.timed_out,
            "error": self.error,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


def build_snippet(request: ExecRequest) -> str:
    """Build the target-side shell that prepares the environment and execs the command.

    Only this snippet is interpreted by the remote shell; the command's own arguments are
    passed positionally after ``--`` and reached through ``"$@"``.
    """
    parts: list[str] = []

    def _source(label: str, path: str) -> None:
        # Expand a leading '~' on the target, not locally: quoting the path whole made
        # '~/caasi/...' a literal directory, so a correct-looking overlay silently could
        # not be sourced (found by passing one on the real robot).
        quoted = targets_core.remote_path_expr(path)
        # Missing or failing setup must abort rather than be skipped: silently ignoring
        # it made a broken overlay look like a working environment.
        parts.append(
            f'if [ ! -f {quoted} ]; then echo "{MARK_SETUP_FAILED} {label}: {path}" >&2; '
            f"exit {EXIT_SETUP_FAILED}; fi"
        )
        parts.append(
            f'. {quoted} || {{ echo "{MARK_SETUP_FAILED} {label}: {path}" >&2; '
            f"exit {EXIT_SETUP_FAILED}; }}"
        )

    if request.ros_setup:
        _source("ros", request.ros_setup)
    if request.overlay_setup:
        _source("overlay", request.overlay_setup)

    for key, value in request.env.items():
        parts.append(f"export {key}={shlex.quote(str(value))}")

    if request.ros_setup:
        # Only an explicit ROS environment implies the ROS CLI must exist. Sourcing a
        # workspace overlay alone does not: the overlay may be a plain environment
        # script, and requiring ros2 there made an ordinary command fail with a ROS
        # error (caught by the full test suite, which runs without ROS on PATH).
        parts.append(
            'if ! command -v ros2 >/dev/null 2>&1; then '
            f'echo "{MARK_NO_ROS2}" >&2; exit {EXIT_NO_ROS2}; fi'
        )

    if request.cwd:
        quoted = targets_core.remote_path_expr(request.cwd)
        parts.append(
            f'cd {quoted} || {{ echo "{MARK_CWD_FAILED}: {request.cwd}" >&2; '
            f"exit {EXIT_SETUP_FAILED}; }}"
        )

    parts.append('exec "$@"')
    return " ; ".join(parts)


def _classify(result: "shell.ShellResult", request: ExecRequest, target_name: str) -> ExecResult:
    """Turn a raw shell result into a stated outcome, never guessing success."""
    stderr = result.stderr or ""
    out = ExecResult(
        target=target_name,
        argv=list(request.argv),
        outcome=OUTCOME_NONZERO,
        returncode=result.returncode,
        stdout=result.stdout or "",
        stderr=stderr,
    )

    if result.returncode == -1:
        # shell.run_cmd uses -1 for its own timeouts and transport-level failures.
        lowered = stderr.lower()
        if "timed out" in lowered or "timeout" in lowered:
            out.outcome = OUTCOME_TIMEOUT
            out.timed_out = True
            out.error = "the command did not finish within the timeout"
        else:
            out.outcome = OUTCOME_TRANSPORT
            out.error = stderr.strip() or "transport failure before the command ran"
        return out

    if MARK_SETUP_FAILED in stderr or MARK_CWD_FAILED in stderr:
        out.outcome = OUTCOME_SETUP
        out.error = next(
            (line for line in stderr.splitlines()
             if MARK_SETUP_FAILED in line or MARK_CWD_FAILED in line),
            "environment setup failed",
        )
        return out

    if MARK_NO_ROS2 in stderr or result.returncode == EXIT_NO_ROS2:
        out.outcome = OUTCOME_NO_ROS2
        out.error = "no usable 'ros2' on the target after environment setup"
        return out

    if result.returncode == SSH_TRANSPORT_FAILURE:
        we_are_remote = request.timeout is not None  # always true; kept for clarity
        if we_are_remote and not out.stdout:
            out.outcome = OUTCOME_TRANSPORT
            out.error = stderr.strip() or "ssh exited 255 (connection or authentication)"
            return out

    out.outcome = OUTCOME_OK if result.returncode == 0 else OUTCOME_NONZERO
    return out


def run_on_target(target: "targets_core.Target", request: ExecRequest) -> ExecResult:
    """Run *request* on *target*, capturing output and classifying the outcome."""
    if target.transport != "ssh":
        # A non-SSH target has no separate transport: run the same snippet locally so the
        # semantics (setup checks, argv handling, exit codes) are identical.
        snippet = build_snippet(request)
        raw = shell.run_cmd(
            ["bash", "-c", snippet, "--", *request.argv], timeout=request.timeout
        )
        return _classify(raw, request, target.name)

    prefix = targets_core.target_ssh_prefix(target)
    snippet = build_snippet(request)
    remote_cmd = shlex.join(["bash", "-c", snippet, "--", *request.argv])
    raw = shell.run_cmd([*prefix, remote_cmd], timeout=request.timeout)
    return _classify(raw, request, target.name)


class RosDiscoveryError(RuntimeError):
    """The target could not be queried, which is not the same as having no ROS.

    Conflating the two told users "this target does not report a ROS distribution" when
    the real cause was a probe that failed on a busy or slow link, and the suggested fix
    (pass --ros-setup) hid the actual problem.
    """


def ros_setup_for(
    target: "targets_core.Target",
    distro: str | None = None,
    config=None,
) -> str | None:
    """Target-side ROS setup path, from an explicit distro or the target's own discovery.

    The distro comes from what the target reports about itself, not from an assumption
    about the OS: caasi must work with Humble, Jazzy or an unknown future distribution.
    Returns ``None`` when it cannot be determined, so the caller fails rather than caasi
    inventing a path -- guessing /opt/ros/jazzy would produce a setup error that looks
    like the user's fault.
    """
    name = distro
    if not name:
        # Reuse the existing discovery machinery instead of inventing a second probe.
        try:
            inspection = targets_core.discover_target(target, config)
        except Exception as err:
            # A failed probe is not a target without ROS; say which one it was.
            raise RosDiscoveryError(str(err)) from err
        name = inspection.environment.ros_distro if inspection.environment else None
    if not name:
        return None
    return f"/opt/ros/{name}/setup.bash"


def probe_ros_environment(target: "targets_core.Target", timeout: float = 30.0) -> ExecResult:
    """Report what ROS environment the target actually has, without assuming a distro.

    Named explicitly enough to be honest: this answers "what is there", not "is it the
    distro I expected".
    """
    return run_on_target(
        target,
        ExecRequest(
            argv=[
                "bash",
                "-lc",
                'echo "HOME=$HOME"; echo "ROS_DISTRO=${ROS_DISTRO:-}"; '
                'command -v ros2 || echo "ros2=absent"; '
                'ls -d /opt/ros/*/setup.bash 2>/dev/null || echo "no /opt/ros setup"',
            ],
            timeout=timeout,
        ),
    )
