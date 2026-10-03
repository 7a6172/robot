"""Real-subprocess smoke tests for caasi's background run machinery.

These tests execute actual OS processes without mocks to verify:
- Detached process launching via wrapper script run.sh
- Output streaming into stdout.log and stderr.log
- Asynchronous PID tracking and liveness detection
- State transitions (running -> succeeded / failed / stopped)
- Process exit code capture
- Cancellation via SIGTERM and process group reaping
- Process tree cleanup without leaving orphan processes
"""

from __future__ import annotations

import os
import signal
import sys
import time

import pytest

from caasi import state
from caasi.cli.main import app
from caasi.core import runs


def _wait_status(record: runs.RunRecord, wanted: tuple[str, ...], timeout: float = 6.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if runs.effective_status(record) in wanted:
            return True
        time.sleep(0.05)
    return False


def _wait_file(path, timeout: float = 6.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file() and path.stat().st_size > 0:
            return True
        time.sleep(0.05)
    return False


@pytest.fixture
def cfg():
    return state.cfg()


@pytest.mark.smoke
def test_real_subprocess_success_lifecycle(cfg):
    """Test successful process lifecycle: launch -> running -> succeeded -> exit code 0."""
    script = (
        "import sys, time\n"
        "sys.stdout.write('real stdout start\\n')\n"
        "sys.stdout.flush()\n"
        "sys.stderr.write('real stderr warning\\n')\n"
        "sys.stderr.flush()\n"
        "time.sleep(0.2)\n"
        "sys.stdout.write('real stdout done\\n')\n"
        "sys.stdout.flush()\n"
    )
    cmd = [sys.executable, "-u", "-c", script]

    record = runs.start_run(
        cfg,
        name="real-success-run",
        command=cmd,
        backend="python",
        kind="test",
    )

    # 1. PID tracking
    assert record.pid is not None
    assert record.pid > 0
    assert isinstance(record.pid, int)

    # 2. Files created
    run_dir = record.directory
    assert run_dir is not None and run_dir.is_dir()
    assert (run_dir / "manifest.yaml").is_file()
    assert (run_dir / "run.sh").is_file()
    assert (run_dir / "stdout.log").is_file()
    assert (run_dir / "stderr.log").is_file()

    # 3. State transition to terminal success
    assert _wait_status(record, (runs.TERMINAL_OK,), timeout=5.0)
    assert runs.effective_status(record) == runs.TERMINAL_OK

    # 4. Exit code file
    exit_code_path = run_dir / "exit_code"
    assert exit_code_path.is_file()
    assert exit_code_path.read_text(encoding="utf-8").strip() == "0"
    assert runs._exit_code_of(run_dir) == 0

    # 5. Output capture verification
    stdout_content = (run_dir / "stdout.log").read_text(encoding="utf-8")
    stderr_content = (run_dir / "stderr.log").read_text(encoding="utf-8")
    assert "real stdout start" in stdout_content
    assert "real stdout done" in stdout_content
    assert "real stderr warning" in stderr_content

    # 6. PID liveness and cleanup
    runs._reap(record.pid)
    assert not runs.pid_alive(record.pid)


@pytest.mark.smoke
def test_real_subprocess_failure_lifecycle(cfg):
    """Test failing process lifecycle: exit code capture and stderr recording."""
    script = (
        "import sys\n"
        "sys.stderr.write('fatal runtime error in real process\\n')\n"
        "sys.stderr.flush()\n"
        "sys.exit(42)\n"
    )
    cmd = [sys.executable, "-u", "-c", script]

    record = runs.start_run(
        cfg,
        name="real-fail-run",
        command=cmd,
        backend="python",
        kind="test",
    )

    run_dir = record.directory
    assert run_dir is not None

    # State transition to terminal fail
    assert _wait_status(record, (runs.TERMINAL_FAIL,), timeout=5.0)
    assert runs.effective_status(record) == runs.TERMINAL_FAIL

    # Exit code verification
    assert runs._exit_code_of(run_dir) == 42
    assert (run_dir / "exit_code").read_text(encoding="utf-8").strip() == "42"

    # Stderr verification
    stderr_content = (run_dir / "stderr.log").read_text(encoding="utf-8")
    assert "fatal runtime error in real process" in stderr_content

    # PID cleanup
    runs._reap(record.pid)
    assert not runs.pid_alive(record.pid)


@pytest.mark.smoke
def test_real_subprocess_cancellation_sigterm(cfg):
    """Test process cancellation: active process stopped cleanly via SIGTERM."""
    script = (
        "import time, sys\n"
        "sys.stdout.write('running worker\\n')\n"
        "sys.stdout.flush()\n"
        "time.sleep(30)\n"
    )
    cmd = [sys.executable, "-u", "-c", script]

    record = runs.start_run(
        cfg,
        name="real-cancel-run",
        command=cmd,
        backend="python",
        kind="test",
    )

    run_dir = record.directory
    assert run_dir is not None

    # Verify process started and is running
    assert runs.pid_alive(record.pid)
    assert runs.effective_status(record) == runs.RUNNING

    # Wait for initial output to be flushed
    assert _wait_file(run_dir / "stdout.log", timeout=3.0)
    assert "running worker" in (run_dir / "stdout.log").read_text(encoding="utf-8")

    # Cancel via runs.stop_run (sends SIGTERM, waits, falls back to SIGKILL if necessary)
    stopped = runs.stop_run(record, timeout=3.0)
    assert stopped is True

    # Verify process is terminated
    assert not runs.pid_alive(record.pid)

    # Verify status changed to stopped
    reloaded = runs.load_run(cfg, record.run_id)
    assert reloaded is not None
    assert reloaded.stopped is True
    assert runs.effective_status(reloaded) == runs.STOPPED


@pytest.mark.smoke
def test_real_subprocess_process_tree_termination(cfg):
    """Test that stopping a run terminates the entire process group, not just parent."""
    # Parent spawns a child sleep process in the same process group, writes child pid, then sleeps
    script = (
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "sys.stdout.write(f'{child.pid}\\n')\n"
        "sys.stdout.flush()\n"
        "time.sleep(60)\n"
    )
    cmd = [sys.executable, "-u", "-c", script]

    record = runs.start_run(
        cfg,
        name="real-tree-run",
        command=cmd,
        backend="python",
        kind="test",
    )

    run_dir = record.directory
    assert run_dir is not None

    # Wait for parent to write child pid
    stdout_file = run_dir / "stdout.log"
    assert _wait_file(stdout_file, timeout=5.0)

    # Read child pid
    child_pid_str = stdout_file.read_text(encoding="utf-8").strip().splitlines()[0]
    child_pid = int(child_pid_str)

    # Both parent and child should initially be alive
    assert runs.pid_alive(record.pid)
    assert runs.pid_alive(child_pid)

    # Stop run
    stopped = runs.stop_run(record, timeout=3.0)
    assert stopped is True

    # Both parent and child should be gone
    assert not runs.pid_alive(record.pid)
    assert not runs.pid_alive(child_pid)


@pytest.mark.smoke
def test_real_subprocess_cli_integration(runner):
    """Verify CLI commands (status, logs, stop) work against real running and completed processes."""
    cfg = state.cfg()

    # Launch a real short run
    record = runs.start_run(
        cfg,
        name="cli-smoke-run",
        command=[sys.executable, "-u", "-c", "import sys; print('cli message'); sys.stderr.write('cli err\\n')"],
        backend="python",
        kind="test",
    )
    _wait_status(record, (runs.TERMINAL_OK,), timeout=5.0)

    # Test 'caasi run list'
    res_list = runner.invoke(app, ["run", "list"])
    assert res_list.exit_code == 0
    assert record.run_id in res_list.output
    assert "succeeded" in res_list.output

    # Test 'caasi run status'
    res_status = runner.invoke(app, ["run", "status", record.run_id])
    assert res_status.exit_code == 0
    assert record.name in res_status.output
    assert "succeeded" in res_status.output

    # Test 'caasi run logs'
    res_logs = runner.invoke(app, ["run", "logs", record.run_id])
    assert res_logs.exit_code == 0
    assert "cli message" in res_logs.output

    # Test 'caasi run logs --stream stderr'
    res_err_logs = runner.invoke(app, ["run", "logs", record.run_id, "--stream", "stderr"])
    assert res_err_logs.exit_code == 0
    assert "cli err" in res_err_logs.output
