"""Run manager: experiments as tracked, detachable background processes.

Each run lives in ``<paths.runs>/<run-id>/`` containing:

- ``manifest.yaml`` — metadata (command, cwd, pid, backend, timestamps)
- ``run.sh``        — wrapper that records the child's exit code
- ``stdout.log`` / ``stderr.log``

The CLI process never stays attached to a run; status is derived from the
wrapper's ``exit_code`` file plus PID liveness.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
import shlex
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..core.config import Config
from . import layout as caasi_layout
from . import targets as targets_core

TERMINAL_OK = "succeeded"
TERMINAL_FAIL = "failed"
STOPPED = "stopped"
RUNNING = "running"
PAUSED = "paused"
LOST = "lost"
#: The wrapper is gone but something it started is still alive. Reporting this as
#: "stopped" is how a leaked node survives unnoticed.
STALE = "stale"


@dataclass
class RunRecord:
    run_id: str
    name: str
    backend: str
    kind: str
    command: list[str]
    cwd: str
    created: str
    pid: int | None
    paused: bool = False
    stopped: bool = False
    extra: dict[str, Any] = field(default_factory=dict)
    directory: Path | None = None
    target: str = "local"
    target_transport: str = "local"
    pgid: int | None = None
    destination: str | None = None
    deployment_id: str | None = None
    build_id: str | None = None
    git_revision: str | None = None
    project: str | None = None
    remote_run_dir: str | None = None

    def to_dict(self, config: Config | None = None) -> dict[str, Any]:
        data = {
            "id": self.run_id,
            "name": self.name,
            "backend": self.backend,
            "kind": self.kind,
            "command": self.command,
            "cwd": self.cwd,
            "created": self.created,
            "pid": self.pid,
            "paused": self.paused,
            "stopped": self.stopped,
            "directory": str(self.directory) if self.directory else None,
            "status": effective_status(self, config),
            "target": self.target,
        }
        if self.pgid is not None:
            data["pgid"] = self.pgid
        if self.target_transport != "local":
            data["target_transport"] = self.target_transport
        if self.destination:
            data["destination"] = self.destination
        if self.deployment_id:
            data["deployment_id"] = self.deployment_id
        if self.build_id:
            data["build_id"] = self.build_id
        if self.git_revision:
            data["git_revision"] = self.git_revision
        if self.project:
            data["project"] = self.project
        if self.remote_run_dir:
            data["remote_run_dir"] = self.remote_run_dir
        return data


def runs_dir(config: Config) -> Path:
    path = config.expanded_path_for("paths.runs") or Path.home() / ".caasi" / "runs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _now() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip()).strip("-").lower()
    return slug or "run"


def new_run_id(name: str) -> str:
    return f"{_dt.datetime.now():%Y%m%d-%H%M%S}-{_slug(name)}"


def _manifest_path(run_dir: Path) -> Path:
    return run_dir / "manifest.yaml"


def _write_manifest(run_dir: Path, data: dict[str, Any]) -> None:
    _manifest_path(run_dir).write_text(
        yaml.safe_dump(data, sort_keys=False), encoding="utf-8"
    )


def _read_manifest(run_dir: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(_manifest_path(run_dir).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _wrapper_path(run_dir: Path) -> Path:
    return run_dir / "run.sh"


def _write_wrapper(run_dir: Path) -> Path:
    wrapper = _wrapper_path(run_dir)
    wrapper.write_text(
        "#!/usr/bin/env bash\n"
        '"$@"\n'
        "ec=$?\n"
        f'echo "$ec" > "{run_dir / "exit_code"}"\n'
        'exit "$ec"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    return wrapper


def _exit_code_of(run_dir: Path) -> int | None:
    try:
        text = (run_dir / "exit_code").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    except OSError:
        return False
    return True


def _reap(pid: int | None) -> None:
    """Reap the run if it is still our child (e.g. same-process tests)."""
    if not pid:
        return
    while True:
        try:
            reaped, _ = os.waitpid(pid, os.WNOHANG)
        except (ChildProcessError, OSError):
            return
        if reaped == 0:
            return


def remote_effective_status(record: RunRecord, config: Config | None = None) -> str:
    """Check the live or terminal status of a run on a remote SSH target."""
    # Only the run directory is required. An ad-hoc managed command has no deployment
    # `destination`, and requiring one made every such run report "lost" even while it
    # was demonstrably running (found by starting one and checking its status).
    if not record.remote_run_dir:
        return LOST

    cfg = config or Config({}, [])
    target = targets_core.find_target(cfg, record.target)
    if not target:
        return LOST

    ssh_prefix = targets_core.target_ssh_prefix(target)
    run_dir = record.remote_run_dir.rstrip("/")
    pid = record.pid
    pgid = record.pgid or record.pid

    # Paths must expand '~' on the target, same helper as the writer: quoting them whole
    # made every status check look in a literal '~' directory and report "lost".
    exit_f = targets_core.remote_path_expr(run_dir + "/exit_code")
    check_cmd = (
        f"if [ -f {exit_f} ]; then "
        f"  echo 'EXIT:'$(cat {exit_f}); "
        f"elif [ -n '{pid}' ] && kill -0 '{pid}' 2>/dev/null; then "
        f"  echo 'RUNNING'; "
        f"else "
        f"  echo 'DEAD'; "
        f"fi; "
        # A wrapper can exit while the program it started keeps running. Report that
        # separately, so a leaked node is visible instead of looking cleanly stopped.
        f"if [ -n '{pgid}' ] && kill -0 -- -'{pgid}' 2>/dev/null; then echo 'GROUP:ALIVE'; "
        f"else echo 'GROUP:DEAD'; fi"
    )
    try:
        res = subprocess.run(
            ssh_prefix + [check_cmd],
            capture_output=True,
            text=True,
            # One probe = one SSH round-trip; budget from the target's own link.
            timeout=max(5.0, float(target.ssh_timeout)),
        )
    except Exception:
        return "unreachable"

    if res.returncode != 0:
        return "unreachable"

    # The probe answers two questions in one round-trip: how the wrapper ended, and whether
    # anything in its process group is still alive.
    lines = [ln.strip() for ln in res.stdout.strip().splitlines() if ln.strip()]
    out = lines[0] if lines else ""
    group_alive = any(ln == "GROUP:ALIVE" for ln in lines[1:])
    if out.startswith("EXIT:"):
        # The wrapper finished, but if anything it started is still running the run is not
        # over: reporting "succeeded" here is exactly how a leaked node stays invisible.
        if group_alive:
            return STALE
        code_str = out.split(":", 1)[1].strip()
        try:
            code = int(code_str)
            if record.directory:
                try:
                    (record.directory / "exit_code").write_text(str(code), encoding="utf-8")
                except OSError:
                    pass
            # An explicit stop wins: since the wrapper records its exit status via an
            # EXIT trap, a stopped run also has an exit code, and reporting it as
            # succeeded/failed would lose the fact that we stopped it. If descendants
            # outlived the wrapper the truth is "stale", not "stopped".
            if record.stopped:
                return STALE if group_alive else STOPPED
            return TERMINAL_OK if code == 0 else TERMINAL_FAIL
        except ValueError:
            return TERMINAL_FAIL
    elif out == "RUNNING":
        return RUNNING
    elif out == "DEAD":
        if group_alive:
            return STALE
        if record.stopped:
            return STOPPED
        return LOST

    return LOST


def sandbox_effective_status(record: RunRecord) -> str:
    """Check status of a run in a local deployed sandbox."""
    if not record.remote_run_dir:
        return LOST
    remote_path = Path(record.remote_run_dir)
    exit_file = remote_path / "exit_code"
    if exit_file.is_file():
        try:
            code = int(exit_file.read_text(encoding="utf-8").strip())
            if record.directory and not (record.directory / "exit_code").is_file():
                try:
                    (record.directory / "exit_code").write_text(str(code), encoding="utf-8")
                except OSError:
                    pass
            # An explicit stop wins over the exit status recorded by the wrapper.
            if record.stopped:
                return STOPPED
            return TERMINAL_OK if code == 0 else TERMINAL_FAIL
        except ValueError:
            return TERMINAL_FAIL
    _reap(record.pid)
    if pid_alive(record.pid):
        return RUNNING
    if record.stopped:
        return STOPPED
    return LOST


def effective_status(record: RunRecord, config: Config | None = None) -> str:
    exit_code = _exit_code_of(record.directory) if record.directory else None
    if exit_code is not None:
        return TERMINAL_OK if exit_code == 0 else TERMINAL_FAIL

    if record.target_transport == "ssh":
        return remote_effective_status(record, config)
    if record.remote_run_dir:
        # Any run executing in a DEPLOYED run directory is a sandbox run, whatever
        # the target is called. Keying this on `target != "local"` skipped runs
        # whose target is named `local` but which execute in the deployment (the
        # normal case for a locally-deployed target), leaving them to fall through
        # to LOST even when the run had finished successfully. The run directory
        # is the reliable discriminator; the target's name is not.
        return sandbox_effective_status(record)

    if pid_alive(record.pid):
        return PAUSED if record.paused else RUNNING
    if record.stopped:
        return STOPPED
    return LOST


def start_run(
    config: Config,
    *,
    name: str,
    command: list[str],
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    backend: str = "python",
    kind: str = "run",
    extra: dict[str, Any] | None = None,
) -> RunRecord:
    """Launch *command* as a detached, tracked run. Returns the record."""
    base = runs_dir(config)
    base_id = new_run_id(name)
    run_id = base_id
    run_dir = base / run_id
    counter = 2
    while run_dir.exists():  # same-second launches (e.g. `run restart`) stay unique
        run_id = f"{base_id}-{counter}"
        run_dir = base / run_id
        counter += 1
    run_dir.mkdir(parents=True)
    _write_wrapper(run_dir)

    work_dir = str(Path(cwd).expanduser()) if cwd else os.getcwd()
    merged_env = {**os.environ, **(env or {})}

    from . import project, rosenv
    proj_root = project.find_project_root(Path(work_dir)) or project.find_project_root()
    if proj_root is not None:
        merged_env.setdefault("CAASI_PROJECT_ROOT", str(proj_root))

    if backend == "ros":
        if not rosenv.is_sourced(project_root=proj_root):
            ros_s_env = rosenv.sourced_env(project_root=proj_root)
            merged_env = {**merged_env, **ros_s_env, **(env or {})}

    stdout = open(run_dir / "stdout.log", "w", encoding="utf-8")
    stderr = open(run_dir / "stderr.log", "w", encoding="utf-8")
    try:
        proc = _popen(run_dir, command, work_dir, merged_env, stdout, stderr)
    finally:
        stdout.close()
        stderr.close()

    manifest = {
        "id": run_id,
        "name": name,
        "backend": backend,
        "kind": kind,
        "command": [str(part) for part in command],
        "cwd": work_dir,
        "created": _now(),
        "pid": proc.pid,
        "paused": False,
        "stopped": False,
        "extra": extra or {},
    }
    _write_manifest(run_dir, manifest)
    return load_run(config, run_id)  # type: ignore[return-value]


def _popen(run_dir, command, work_dir, merged_env, stdout, stderr):
    import subprocess

    return subprocess.Popen(
        ["bash", str(_wrapper_path(run_dir)), *[str(part) for part in command]],
        cwd=work_dir,
        env=merged_env,
        stdout=stdout,
        stderr=stderr,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )


def load_run(config: Config, run_id: str) -> RunRecord | None:
    run_dir = runs_dir(config) / run_id
    if not run_dir.is_dir():
        return None
    data = _read_manifest(run_dir)
    if not data.get("id"):
        return None
    return RunRecord(
        run_id=str(data.get("id")),
        name=str(data.get("name", "")),
        backend=str(data.get("backend", "python")),
        kind=str(data.get("kind", "run")),
        command=list(data.get("command") or []),
        cwd=str(data.get("cwd", "")),
        created=str(data.get("created", "")),
        pid=data.get("pid"),
        paused=bool(data.get("paused", False)),
        stopped=bool(data.get("stopped", False)),
        extra=dict(data.get("extra") or {}),
        directory=run_dir,
        target=str(data.get("target", "local")),
        target_transport=str(data.get("target_transport", "local")),
        pgid=data.get("pgid"),
        destination=data.get("destination"),
        deployment_id=data.get("deployment_id"),
        build_id=data.get("build_id"),
        git_revision=data.get("git_revision"),
        project=data.get("project"),
        remote_run_dir=data.get("remote_run_dir"),
    )


def list_runs(config: Config) -> list[RunRecord]:
    base = runs_dir(config)
    records = []
    for child in sorted(base.iterdir(), reverse=True):
        if not child.is_dir() or not _manifest_path(child).is_file():
            continue
        record = load_run(config, child.name)
        if record:
            records.append(record)
    return records


def find_run(config: Config, query: str) -> RunRecord | None:
    """Resolve *query*: exact id, unique id prefix, run name, or 'latest'."""
    query = query.strip()
    if query in ("latest", "last", "newest"):
        runs = list_runs(config)
        return runs[0] if runs else None

    exact = load_run(config, query)
    if exact:
        return exact

    matches = [
        r
        for r in list_runs(config)
        if r.run_id.startswith(query) or r.name == query
    ]
    return matches[0] if len(matches) == 1 else None


def _update_manifest(record: RunRecord, **fields: Any) -> None:
    if not record.directory:
        return
    data = _read_manifest(record.directory)
    data.update(fields)
    _write_manifest(record.directory, data)


def _signal_group(record: RunRecord, sig: int) -> bool:
    if not record.pid:
        return False
    try:
        os.killpg(record.pid, sig)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        try:
            os.kill(record.pid, sig)
            return True
        except OSError:
            return False


def _wait_gone(record: RunRecord, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _reap(record.pid)
        if not pid_alive(record.pid):
            return True
        time.sleep(0.1)
    _reap(record.pid)
    return not pid_alive(record.pid)


def remote_stop_run(record: RunRecord, config: Config, timeout: float = 5.0) -> bool:
    """Terminate a remote process group over SSH.

    Returns True when the tested process is confirmed gone. A kill may succeed
    while confirmation cannot complete (slow link); in that case the run is
    still recorded as stopped — the signal was delivered — and the return value
    is False to signal "signalled, not confirmed". It must never be recorded as
    ``lost``, which would read as "state unknown" and is the mis-report this
    guards against.
    """
    target = targets_core.find_target(config, record.target)
    if not target:
        return False

    ssh_prefix = targets_core.target_ssh_prefix(target)
    # Every step of this routine is one SSH round-trip. Budget per call from the
    # target's own link latency: a relayed/VPN target needs far more than the
    # 5s that suited a local container.
    per_call = max(5.0, float(target.ssh_timeout))
    pgid = record.pgid or record.pid
    pid = record.pid
    if not pid:
        return True

    # Check if already dead
    # Check the whole process group when one is known: the wrapper can exit while the
    # program it started keeps running, and a pid-only check then reports "stopped" for a
    # process that is still alive and still holding its ports.
    if pgid:
        check_alive = (
            f"if kill -0 -{pgid} 2>/dev/null || kill -0 {pid} 2>/dev/null; "
            f"then echo 'ALIVE'; else echo 'DEAD'; fi"
        )
    else:
        check_alive = f"kill -0 {pid} 2>/dev/null && echo 'ALIVE' || echo 'DEAD'"
    try:
        res = subprocess.run(ssh_prefix + [check_alive], capture_output=True,
                             text=True, timeout=per_call)
        if res.returncode == 0 and res.stdout.strip() == "DEAD":
            _update_manifest(record, stopped=True, paused=False)
            record.stopped = True
            record.paused = False
            return True
    except subprocess.TimeoutExpired:
        # Cannot even read current state; fall through and still deliver the signal.
        pass

    # 1. Send SIGTERM to remote process group
    kill_term = f"kill -TERM -{pgid} 2>/dev/null || kill -TERM {pid} 2>/dev/null"
    signal_sent = False
    try:
        subprocess.run(ssh_prefix + [kill_term], capture_output=True, timeout=per_call)
        signal_sent = True
    except subprocess.TimeoutExpired:
        pass

    # 2. Wait up to timeout for process to terminate
    deadline = time.monotonic() + timeout
    stopped = False
    while time.monotonic() < deadline:
        try:
            res = subprocess.run(
                ssh_prefix + [check_alive],
                capture_output=True,
                text=True,
                timeout=per_call,
            )
        except subprocess.TimeoutExpired:
            time.sleep(0.2)
            continue
        if res.returncode == 0 and res.stdout.strip() == "DEAD":
            stopped = True
            break
        time.sleep(0.2)

    # 3. If still alive after timeout, send SIGKILL to process group
    if not stopped:
        kill_kill = f"kill -KILL -{pgid} 2>/dev/null || kill -KILL {pid} 2>/dev/null"
        try:
            subprocess.run(ssh_prefix + [kill_kill], capture_output=True, timeout=per_call)
            signal_sent = True
        except subprocess.TimeoutExpired:
            pass
        time.sleep(0.2)
        try:
            res = subprocess.run(
                ssh_prefix + [check_alive],
                capture_output=True,
                text=True,
                timeout=per_call,
            )
            stopped = (res.stdout.strip() == "DEAD")
        except subprocess.TimeoutExpired:
            stopped = False

    # 4. Update manifest on target and host
    if record.remote_run_dir:
        # Expanded on the target: inside the python -c string a literal '~' is not a home
        # directory, so the update silently did nothing.
        dest_manifest = targets_core.remote_path_expr(
            record.remote_run_dir + "/manifest.yaml").strip('"').replace(
            '"$HOME"', os.environ.get("HOME", "~"))
        update_remote = (
            f"python3 -c 'import yaml; "
            f"p=\"{dest_manifest}\"; "
            f"d=yaml.safe_load(open(p)); d[\"stopped\"]=True; yaml.safe_dump(d, open(p,\"w\"))' 2>/dev/null || true"
        )
        try:
            subprocess.run(ssh_prefix + [update_remote], capture_output=True, timeout=per_call)
        except subprocess.TimeoutExpired:
            pass

    # A delivered signal is enough to record the run as stopped ONLY when no descendant
    # survived. If something is still alive after SIGKILL, saying "stopped" would hide a
    # leaked process, so the run is recorded as stopped but reported stale by status.
    _update_manifest(record, stopped=True, paused=False)
    record.stopped = True
    record.paused = False
    return stopped


def sandbox_stop_run(record: RunRecord, timeout: float = 5.0) -> bool:
    """Terminate a process group in a local sandbox."""
    pgid = record.pgid or record.pid
    pid = record.pid
    if not pid:
        return True

    _reap(pid)
    if not pid_alive(pid):
        _update_manifest(record, stopped=True, paused=False)
        record.stopped = True
        record.paused = False
        return True

    try:
        if pgid:
            os.killpg(pgid, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
    except OSError:
        pass

    deadline = time.monotonic() + timeout
    stopped = False
    while time.monotonic() < deadline:
        _reap(pid)
        if not pid_alive(pid):
            stopped = True
            break
        time.sleep(0.1)

    if not stopped:
        try:
            if pgid:
                os.killpg(pgid, signal.SIGKILL)
            else:
                os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
        _reap(pid)
        stopped = not pid_alive(pid)

    _update_manifest(record, stopped=True, paused=False)
    if record.remote_run_dir:
        target_man = Path(record.remote_run_dir) / "manifest.yaml"
        if target_man.is_file():
            try:
                data = yaml.safe_load(target_man.read_text(encoding="utf-8"))
                data["stopped"] = True
                target_man.write_text(yaml.safe_dump(data), encoding="utf-8")
            except Exception:
                pass

    record.stopped = True
    record.paused = False
    return stopped


def survivors_alive(record: RunRecord, config: Config | None = None) -> bool:
    """True when the wrapper is gone but something it started is still running.

    A pid-only check answers "is the wrapper alive", which is the wrong question: the
    wrapper exits as soon as the program it launched returns or detaches, so a leaked node
    outlives it. This asks about the process *group* instead.
    """
    if not record.pid:
        return False
    pgid = record.pgid or record.pid
    if record.target == "local" or record.target_transport == "local":
        try:
            os.killpg(pgid, 0)
            return True
        except (ProcessLookupError, PermissionError, OSError):
            return False
    cfg = config or Config({}, [])
    target = targets_core.find_target(cfg, record.target)
    if target is None:
        return False
    probe = (
        f"kill -0 -- -{pgid} 2>/dev/null && echo 'ALIVE' || echo 'DEAD'"
    )
    try:
        res = subprocess.run(
            targets_core.target_ssh_prefix(target) + [probe],
            capture_output=True,
            text=True,
            timeout=max(5.0, float(target.ssh_timeout)),
        )
    except Exception:
        return False
    return res.stdout.strip() == "ALIVE"


def stop_run(record: RunRecord, timeout: float = 5.0, config: Config | None = None) -> bool:
    """Terminate the run's process group. Returns True if it stopped."""
    status = effective_status(record, config)
    if status in (TERMINAL_OK, TERMINAL_FAIL, STOPPED):
        # The wrapper has finished, but saying "stopped" without looking further is how a
        # leaked descendant is concealed. Only report a clean stop when nothing survives.
        if not survivors_alive(record, config):
            return True
        # Something outlived the wrapper: fall through and actually stop it.

    cfg = config or Config({}, [])
    if record.target != "local" and record.target_transport == "ssh":
        return remote_stop_run(record, cfg, timeout=timeout)
    elif record.target != "local" and record.target_transport == "local" and record.remote_run_dir:
        return sandbox_stop_run(record, timeout=timeout)

    if record.paused:
        _signal_group(record, signal.SIGCONT)
        time.sleep(0.1)
    _signal_group(record, signal.SIGTERM)
    if not _wait_gone(record, timeout):
        _signal_group(record, signal.SIGKILL)
        _wait_gone(record, timeout)
    _update_manifest(record, stopped=True, paused=False)
    record.stopped = True
    record.paused = False
    return not pid_alive(record.pid)


def pause_run(record: RunRecord) -> bool:
    if effective_status(record) != RUNNING:
        return False
    if _signal_group(record, signal.SIGSTOP):
        _update_manifest(record, paused=True)
        record.paused = True
        return True
    return False


def resume_run(record: RunRecord) -> bool:
    if effective_status(record) != PAUSED:
        return False
    if _signal_group(record, signal.SIGCONT):
        _update_manifest(record, paused=False)
        record.paused = False
        return True
    return False


def delete_run(record: RunRecord) -> bool:
    status = effective_status(record)
    if status in (RUNNING, PAUSED):
        return False
    if record.directory and record.directory.is_dir():
        shutil.rmtree(record.directory, ignore_errors=True)
    return True


def log_path(record: RunRecord, stream: str = "stdout") -> Path | None:
    if record.directory:
        path = record.directory / f"{stream}.log"
        if path.is_file():
            return path
    if record.remote_run_dir and record.target_transport == "local":
        path = Path(record.remote_run_dir) / f"{stream}.log"
        if path.is_file():
            return path
    return None


def read_run_log(
    record: RunRecord,
    config: Config | None = None,
    stream: str = "stdout",
    lines: int = 50,
) -> str:
    """Read trailing log lines from local or remote run."""
    cfg = config or Config({}, [])
    if record.target != "local" and record.target_transport == "ssh":
        target = targets_core.find_target(cfg, record.target)
        if not target or not record.remote_run_dir:
            return ""
        ssh_prefix = targets_core.target_ssh_prefix(target)
        log_file = f"{record.remote_run_dir.rstrip('/')}/{stream}.log"
        # Expand ~ on the target: a quoted '~/...' is a directory literally named "~".
        cmd = ssh_prefix + [
            f"tail -n {max(lines, 1)} {targets_core.remote_path_expr(log_file)} 2>/dev/null"
        ]
        # One tail over SSH; budget from the target's link latency.
        res = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=max(10.0, float(target.ssh_timeout) * 2))
        return res.stdout if res.returncode == 0 else ""
    elif record.target != "local" and record.target_transport == "local" and record.remote_run_dir:
        log_file = Path(record.remote_run_dir) / f"{stream}.log"
        if not log_file.is_file():
            return ""
        try:
            content = log_file.read_text(encoding="utf-8", errors="replace")
            all_lines = content.splitlines()
            return "\n".join(all_lines[-max(lines, 1):])
        except OSError:
            return ""

    path = log_path(record, stream)
    if not path or not path.is_file():
        return ""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        all_lines = content.splitlines()
        return "\n".join(all_lines[-max(lines, 1):])
    except OSError:
        return ""


def inspect_run_files(record: RunRecord, config: Config | None = None) -> list[dict[str, Any]]:
    """List run files and byte sizes across local or remote target."""
    cfg = config or Config({}, [])
    if record.target != "local" and record.target_transport == "ssh":
        target = targets_core.find_target(cfg, record.target)
        if not target or not record.remote_run_dir:
            return []
        ssh_prefix = targets_core.target_ssh_prefix(target)
        run_dir = record.remote_run_dir.rstrip("/")
        cmd = ssh_prefix + [
            f"find {targets_core.remote_path_expr(run_dir)} -maxdepth 2 -type f "
            f"-exec stat -c '%n %s' {{}} + 2>/dev/null"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=max(10.0, float(target.ssh_timeout) * 2))
        files = []
        if res.returncode == 0:
            for line in res.stdout.strip().splitlines():
                parts = line.rsplit(" ", 1)
                if len(parts) == 2:
                    p, s = parts[0], parts[1]
                    rel = p.replace(run_dir + "/", "")
                    files.append({"path": rel, "size": int(s) if s.isdigit() else 0})
        return sorted(files, key=lambda x: x["path"])
    elif record.target != "local" and record.target_transport == "local" and record.remote_run_dir:
        target_dir = Path(record.remote_run_dir)
        files = []
        if target_dir.is_dir():
            for item in sorted(target_dir.rglob("*")):
                if item.is_file():
                    files.append({
                        "path": str(item.relative_to(target_dir)),
                        "size": item.stat().st_size,
                    })
        return files

    files = []
    if record.directory and record.directory.is_dir():
        for item in sorted(record.directory.rglob("*")):
            if item.is_file():
                files.append(
                    {"path": str(item.relative_to(record.directory)), "size": item.stat().st_size}
                )
    return files


def start_target_run(
    target: targets_core.Target,
    config: Config,
    config_path: Path,
    name: str | None = None,
    backend: str | None = None,
    kind: str = "experiment",
    extra_args: list[str] | None = None,
    extra: dict[str, Any] | None = None,
    force_headless: bool = False,
) -> RunRecord:
    """Launch an experiment as a tracked detached run on a target."""
    from . import (
        build as build_core,
        deploy as deploy_core,
        experiment,
        manifest as manifests,
        project as projects,
        provenance,
    )

    # 1. Reachability preflight
    inspection = targets_core.discover_target(target, config=config)
    if not inspection.reachable:
        raise RuntimeError(
            f"Target '{target.name}' is unreachable: {inspection.error or 'connection failed'}"
        )

    # 2. Project resolution
    proj_root = projects.find_project_root(config_path.parent) or projects.find_project_root()
    if not proj_root:
        raise RuntimeError("Not inside a Caasi project (no caasi.yaml found).")
    proj_manifest = manifests.read(proj_root)
    proj_name = proj_manifest.name or proj_root.name

    # 3. Deployment verification
    dest = deploy_core.resolve_deployment_destination(target, proj_name)
    deployment = deploy_core.get_deployment_status(target, dest, config)
    if not deployment:
        raise RuntimeError(
            f"No active deployment found on target '{target.name}' at '{dest}'. "
            f"Run 'caasi deploy {target.name}' first."
        )

    # 4. Build verification (if workspace contains ROS packages)
    has_ros = bool(proj_manifest.components.get("ros2") or (proj_root / "src").is_dir())
    last_build = build_core.get_last_build_status(target, dest, config)
    if has_ros:
        if not last_build:
            raise RuntimeError(
                f"No completed build found on target '{target.name}' at '{dest}'. "
                f"Run 'caasi build --target {target.name}' first."
            )
        if last_build.status != "success":
            raise RuntimeError(
                f"Last build on target '{target.name}' failed with exit code {last_build.returncode}. "
                f"Run 'caasi build --target {target.name}' first."
            )

    # 5. Load and validate experiment manifest
    exp = experiment.load_experiment(config_path)
    run_backend = backend or exp.backend
    run_name = name or exp.name

    # 6. Target relative path resolution
    config_abs = config_path.resolve()
    rel_cfg = (
        config_abs.relative_to(proj_root)
        if config_abs.is_relative_to(proj_root)
        else config_path.name
    )
    target_config_path = f"{dest.rstrip('/')}/{rel_cfg}"

    if exp.work_dir.is_relative_to(proj_root):
        rel_work = exp.work_dir.relative_to(proj_root)
        target_work_dir = f"{dest.rstrip('/')}/{rel_work}".rstrip("/.")
    else:
        target_work_dir = dest.rstrip("/")

    if exp.script_path.is_relative_to(proj_root):
        rel_script = exp.script_path.relative_to(proj_root)
        target_script = f"{dest.rstrip('/')}/{rel_script}"
    else:
        target_script = str(exp.script_path)

    args = list(exp.args) + list(extra_args or [])
    if force_headless and "--headless" not in args:
        args = ["--headless", "--no-window", *args]

    # Command on target
    target_cmd = ["python3", target_script, *args]

    # Sourcing statements
    ros_distro = inspection.environment.ros_distro if inspection.environment else "jazzy"
    ros_setup = f"/opt/ros/{ros_distro}/setup.bash"
    overlay_setup = f"{dest.rstrip('/')}/install/setup.bash"

    # Assemble run IDs and paths
    run_id = new_run_id(run_name)
    target_run_dir = f"{dest.rstrip('/')}/.caasi/runs/{run_id}"
    host_run_dir = runs_dir(config) / run_id
    host_run_dir.mkdir(parents=True, exist_ok=True)

    # 7. Generate target run.sh script
    env_exports = []
    for k, v in exp.env.items():
        env_exports.append(f"export {k}={shlex.quote(str(v))}")
    env_exports_str = "\n".join(env_exports)

    # A leading '~' does not expand inside quotes, and a deployment destination is written as
    # '~/caasi/robots/<robot>'. Quoting these paths whole therefore made the wrapper cd into a
    # directory that does not exist, exit immediately, and the run was reported as "lost".
    # remote_path_expr expands '~' through $HOME on the target, which is the only place the real
    # home is known; the rest of the path stays quoted.
    wrapper_content = f"""#!/usr/bin/env bash
RUN_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
trap 'echo $? > "$RUN_DIR/exit_code"' EXIT
cd {targets_core.remote_path_expr(target_work_dir)} || exit 126
[ -f {targets_core.remote_path_expr(ros_setup)} ] && . {targets_core.remote_path_expr(ros_setup)}
[ -f {targets_core.remote_path_expr(overlay_setup)} ] && . {targets_core.remote_path_expr(overlay_setup)}
export CAASI_PROJECT_ROOT={targets_core.remote_path_expr(dest)}
export CAASI_EXPERIMENT={targets_core.remote_path_expr(target_config_path)}
{env_exports_str}
# Arguments are not re-parsed, so a '~/...' inside "$@" is never expanded by the shell. A script
# path on the target is built from the deployment destination and therefore starts with '~', so
# expand a leading '~/' in every argument before running. No eval: each argument is handled as
# data, quoted, and only the prefix is rewritten.
args=()
for a in "$@"; do
  case "$a" in
    "~/"*) args+=("$HOME/${{a#"~/"}}") ;;
    *) args+=("$a") ;;
  esac
done
"${{args[@]}}"

"""

    # 8. Launch on target
    if target.transport == "ssh":
        ssh_prefix = targets_core.target_ssh_prefix(target)
        run_dir_expr = targets_core.remote_path_expr(target_run_dir)
        run_sh_expr = targets_core.remote_path_expr(target_run_dir + "/run.sh")
        upload_cmd = (
            f"mkdir -p {run_dir_expr} && "
            f"cat > {run_sh_expr} && "
            f"chmod 755 {run_sh_expr}"
        )
        res = subprocess.run(
            ssh_prefix + [upload_cmd],
            input=wrapper_content,
            text=True,
            capture_output=True,
            # Uploading the wrapper is one SSH round-trip; budget from the link.
            timeout=max(10.0, float(target.ssh_timeout) * 2),
        )
        if res.returncode != 0:
            raise RuntimeError(f"Failed to prepare run wrapper on target: {res.stderr.strip()}")

        quoted_cmd = shlex.join(target_cmd)
        out_log = targets_core.remote_path_expr(target_run_dir + "/stdout.log")
        err_log = targets_core.remote_path_expr(target_run_dir + "/stderr.log")
        pid_f = targets_core.remote_path_expr(target_run_dir + "/pid")
        pgid_f = targets_core.remote_path_expr(target_run_dir + "/pgid")
        launch_script = (
            f"nohup setsid {run_sh_expr} {quoted_cmd} "
            f"> {out_log} 2> {err_log} </dev/null &\n"
            f"PID=$!\n"
            f"echo $PID > {pid_f}\n"
            f"ps -o pgid= -p $PID 2>/dev/null | tr -d ' ' > {pgid_f}\n"
            f"echo \"PID:$PID:$(cat {pgid_f})\"\n"
        )
        res = subprocess.run(
            ssh_prefix + [launch_script],
            capture_output=True,
            text=True,
            # Launch is one SSH round-trip; budget from the target's link.
            timeout=max(10.0, float(target.ssh_timeout) * 2),
        )
        if res.returncode != 0 or "PID:" not in res.stdout:
            raise RuntimeError(
                f"Failed to launch remote process on target: {res.stderr.strip() or res.stdout.strip()}"
            )

        pid_line = [l for l in res.stdout.splitlines() if l.startswith("PID:")][0]
        parts = pid_line.split(":")
        pid = int(parts[1])
        pgid = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else pid

    else:
        # Local sandbox target
        sandbox_run_dir = Path(target_run_dir).expanduser().resolve()
        sandbox_run_dir.mkdir(parents=True, exist_ok=True)
        wrapper_path = sandbox_run_dir / "run.sh"
        wrapper_path.write_text(wrapper_content, encoding="utf-8")
        wrapper_path.chmod(0o755)

        stdout_file = open(sandbox_run_dir / "stdout.log", "w", encoding="utf-8")
        stderr_file = open(sandbox_run_dir / "stderr.log", "w", encoding="utf-8")
        proc = subprocess.Popen(
            [str(wrapper_path), *target_cmd],
            cwd=target_work_dir,
            stdout=stdout_file,
            stderr=stderr_file,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        stdout_file.close()
        stderr_file.close()
        pid = proc.pid
        pgid = os.getpgid(pid) if hasattr(os, "getpgid") else pid
        (sandbox_run_dir / "pid").write_text(str(pid), encoding="utf-8")
        (sandbox_run_dir / "pgid").write_text(str(pgid), encoding="utf-8")

    # 9. Record provenance on both sides
    git_stat = provenance.git_info(proj_root)
    git_rev = git_stat.get("head") or "unversioned"
    if git_stat.get("dirty"):
        git_rev = f"{git_rev}-dirty"

    manifest_data = {
        "id": run_id,
        "name": run_name,
        "backend": run_backend,
        "kind": kind,
        "command": target_cmd,
        "cwd": target_work_dir,
        "created": _now(),
        "pid": pid,
        "pgid": pgid,
        "target": target.name,
        "target_transport": target.transport,
        "destination": dest,
        "deployment_id": deployment.deployment_id,
        "build_id": last_build.build_id if last_build else None,
        "git_revision": git_rev,
        "project": proj_name,
        "remote_run_dir": target_run_dir,
        "paused": False,
        "stopped": False,
        "extra": {
            "experiment": str(rel_cfg),
            "headless": exp.headless or force_headless,
            **(extra or {}),
        },
    }

    target_manifest_yaml = yaml.safe_dump(manifest_data, sort_keys=False)
    if target.transport == "ssh":
        write_target_man = (
            f"cat > {targets_core.remote_path_expr(target_run_dir + '/manifest.yaml')}"
        )
        subprocess.run(
            ssh_prefix + [write_target_man],
            input=target_manifest_yaml,
            text=True,
            # Writing target-side provenance is one SSH round-trip.
            timeout=max(10.0, float(target.ssh_timeout) * 2),
        )
    else:
        (Path(target_run_dir) / "manifest.yaml").write_text(target_manifest_yaml, encoding="utf-8")

    _write_manifest(host_run_dir, manifest_data)
    record = load_run(config, run_id)
    if record:
        provenance.write_bundle(config, record)
        return record

    return RunRecord(
        run_id=run_id,
        name=run_name,
        backend=run_backend,
        kind=kind,
        command=target_cmd,
        cwd=target_work_dir,
        created=_now(),
        pid=pid,
        pgid=pgid,
        target=target.name,
        target_transport=target.transport,
        destination=dest,
        deployment_id=deployment.deployment_id,
        build_id=last_build.build_id if last_build else None,
        git_revision=git_rev,
        project=proj_name,
        remote_run_dir=target_run_dir,
        directory=host_run_dir,
    )



def start_target_command(
    target: targets_core.Target,
    config: Config,
    *,
    argv: list[str],
    work_dir: str | None = None,
    env: dict[str, str] | None = None,
    ros_setup: str | None = None,
    overlay_setup: str | None = None,
    name: str = "command",
    kind: str = "command",
    timeout: float | None = None,
) -> RunRecord:
    """Start an arbitrary command as a tracked, detached run on *target*.

    This is the managed counterpart to ``execution.run_on_target`` (bounded commands) and
    deliberately reuses the *same* machinery as experiment runs — one wrapper format, one
    launch shape, the same PID/PGID recording and the same ``caasi run status|logs|stop``
    lifecycle. There is no second supervisor.

    Differences from :func:`start_target_run`: no experiment manifest, no deployment or
    build preconditions, and no project requirement. Ad-hoc diagnostics often need to run
    *before* a project is deployed, and refusing them would push the user back to raw SSH.
    """
    if not argv:
        raise ValueError("start_target_command requires a command")

    # A local target already has a complete detached-run implementation; delegate instead
    # of writing a second one.
    if target.transport != "ssh":
        record = start_run(
            config,
            name=name,
            command=list(argv),
            cwd=work_dir,
            env=dict(env or {}),
            backend="command",
            kind=kind,
        )
        record.target = target.name
        record.target_transport = target.transport
        return record

    budget = max(10.0, float(target.ssh_timeout) * 2)
    run_id = new_run_id(name)
    target_run_dir = caasi_layout.run_dir(run_id)
    host_run_dir = runs_dir(config) / run_id
    host_run_dir.mkdir(parents=True, exist_ok=True)

    exports = "\n".join(
        f"export {k}={shlex.quote(str(v))}" for k, v in (env or {}).items()
    )
    # Sourcing failures are fatal here too: a managed process that silently ran without
    # its environment is worse than one that refuses to start.
    # Target-side '~' expansion, same helper as everywhere else: quoting these whole made
    # '~/caasi/...' a literal path, so a correct overlay could not be sourced.
    source_ros = (
        f'. {targets_core.remote_path_expr(ros_setup)} || exit 126' if ros_setup else ""
    )
    source_overlay = (
        f'. {targets_core.remote_path_expr(overlay_setup)} || exit 126'
        if overlay_setup else ""
    )
    cd_line = (f'cd {targets_core.remote_path_expr(work_dir)} || exit 126'
               if work_dir else "")

    # The EXIT trap records the status even when the process aborts early (a failed
    # setup exits before "$@" runs). Without it such a run left no exit_code and was
    # reported as "lost" rather than failed.
    wrapper = f"""#!/usr/bin/env bash
RUN_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
trap 'echo $? > "$RUN_DIR/exit_code"' EXIT
{cd_line}
{source_ros}
{source_overlay}
{exports}
# Arguments are not re-parsed, so a '~/...' inside "$@" is never expanded by the shell. A script
# path on the target is built from the deployment destination and therefore starts with '~', so
# expand a leading '~/' in every argument before running. No eval: each argument is handled as
# data, quoted, and only the prefix is rewritten.
args=()
for a in "$@"; do
  case "$a" in
    "~/"*) args+=("$HOME/${{a#"~/"}}") ;;
    *) args+=("$a") ;;
  esac
done
"${{args[@]}}"

"""

    ssh_prefix = targets_core.target_ssh_prefix(target)
    # remote_path_expr expands a leading '~' on the target; quoting the path whole would
    # create a literal '~' directory and every later status check would report "lost".
    rd = targets_core.remote_path_expr(target_run_dir)
    run_sh = targets_core.remote_path_expr(target_run_dir + "/run.sh")
    upload = f"mkdir -p {rd} && cat > {run_sh} && chmod 755 {run_sh}"
    res = subprocess.run(
        ssh_prefix + [upload], input=wrapper, text=True, capture_output=True,
        timeout=budget,
    )
    if res.returncode != 0:
        raise RuntimeError(f"Failed to prepare run wrapper on target: {res.stderr.strip()}")

    quoted = shlex.join([str(a) for a in argv])
    out_log = targets_core.remote_path_expr(target_run_dir + "/stdout.log")
    err_log = targets_core.remote_path_expr(target_run_dir + "/stderr.log")
    pid_f = targets_core.remote_path_expr(target_run_dir + "/pid")
    pgid_f = targets_core.remote_path_expr(target_run_dir + "/pgid")
    launch = (
        f"nohup setsid {run_sh} {quoted} "
        f"> {out_log} 2> {err_log} </dev/null &\n"
        f"PID=$!\n"
        f"echo $PID > {pid_f}\n"
        f"ps -o pgid= -p $PID 2>/dev/null | tr -d ' ' > {pgid_f}\n"
        f'echo "PID:$PID:$(cat {pgid_f})"\n'
    )
    res = subprocess.run(ssh_prefix + [launch], capture_output=True, text=True,
                         timeout=budget)
    if res.returncode != 0 or "PID:" not in res.stdout:
        raise RuntimeError(
            f"Failed to launch remote process on target: "
            f"{res.stderr.strip() or res.stdout.strip()}"
        )
    pid_line = [line for line in res.stdout.splitlines() if line.startswith("PID:")][0]
    fields = pid_line.split(":")
    pid = int(fields[1])
    pgid = int(fields[2]) if len(fields) > 2 and fields[2].isdigit() else pid

    record = RunRecord(
        run_id=run_id,
        name=name,
        backend="command",
        kind=kind,
        command=list(argv),
        cwd=work_dir or ".",
        created=_now(),
        pid=pid,
        pgid=pgid,
        target=target.name,
        target_transport=target.transport,
        remote_run_dir=target_run_dir,
        destination=None,
        project=None,
    )
    _write_manifest(host_run_dir, record.to_dict(config))
    (host_run_dir / "run.sh").write_text(wrapper, encoding="utf-8")
    record.directory = host_run_dir
    return record
