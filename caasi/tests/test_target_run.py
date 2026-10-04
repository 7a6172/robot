"""Tests for target-native remote run execution and lifecycle management (Phase 7 Stage C2)."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from caasi.cli.main import app
from caasi.core import build as build_core, deploy as deploy_core, runs, targets as targets_core
from caasi.core.config import Config
from caasi.core.deploy import DeploymentRecord
from caasi.core.targets import Target, TargetEnvironment, TargetInspection, TargetResources

runner = CliRunner()


@pytest.fixture
def mock_config(tmp_path: Path) -> Config:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True)
    return Config({"paths": {"runs": str(runs_dir)}}, [])


@pytest.fixture
def sample_experiment_project(tmp_path: Path) -> tuple[Path, Path]:
    proj = tmp_path / "openmover_proj"
    proj.mkdir()
    (proj / "caasi.yaml").write_text(
        "schema: 1\nname: openmover\nversion: 1.0.0\ncomponents: {ros2: true}\n",
        encoding="utf-8",
    )
    src = proj / "src" / "sample_pkg"
    src.mkdir(parents=True)
    (src / "package.xml").write_text("<package><name>sample_pkg</name></package>", encoding="utf-8")

    scripts_dir = proj / "scripts"
    scripts_dir.mkdir()
    script = scripts_dir / "test_task.py"
    script.write_text(
        "import sys, time\nprint('TASK STARTED')\nsys.stdout.flush()\ntime.sleep(10)\nprint('TASK DONE')\n",
        encoding="utf-8",
    )

    exp_dir = proj / "experiments"
    exp_dir.mkdir()
    exp_file = exp_dir / "test_exp.yaml"
    exp_file.write_text(
        "name: test_exp\n"
        "backend: python\n"
        "script: ../scripts/test_task.py\n"
        "cwd: ..\n"
        "env:\n"
        "  FOO: bar\n",
        encoding="utf-8",
    )
    return proj, exp_file


def test_target_run_unreachable_target(
    sample_experiment_project: tuple[Path, Path], mock_config: Config
) -> None:
    _, exp_file = sample_experiment_project
    target = Target(name="offline_box", transport="ssh", host="192.0.2.1")

    with patch.object(
        targets_core,
        "discover_target",
        return_value=TargetInspection(
            target=target,
            reachable=False,
            status="unreachable",
            error="Connection timed out",
        ),
    ):
        with pytest.raises(RuntimeError, match="Target 'offline_box' is unreachable"):
            runs.start_target_run(target, mock_config, exp_file)


def test_target_run_missing_deployment(
    sample_experiment_project: tuple[Path, Path], mock_config: Config
) -> None:
    _, exp_file = sample_experiment_project
    target = Target(name="ready_box", transport="ssh", host="192.0.2.2")

    with patch.object(
        targets_core,
        "discover_target",
        return_value=TargetInspection(target=target, reachable=True, status="online"),
    ), patch.object(deploy_core, "get_deployment_status", return_value=None):
        with pytest.raises(RuntimeError, match="No active deployment found on target 'ready_box'"):
            runs.start_target_run(target, mock_config, exp_file)


def test_target_run_missing_or_failed_build(
    sample_experiment_project: tuple[Path, Path], mock_config: Config
) -> None:
    _, exp_file = sample_experiment_project
    target = Target(name="deployed_box", transport="ssh", host="192.0.2.3", deployment_root="/home/user")

    mock_dep = DeploymentRecord(
        deployment_id="dep-123",
        project_name="openmover",
        project_version="1.0.0",
        git_revision="abc",
        target_name="deployed_box",
        target_transport="ssh",
        destination_path="/home/user/openmover",
        deployed_at="2026-10-04T00:00:00Z",
        status="active",
    )

    # 1. Missing build
    with patch.object(
        targets_core,
        "discover_target",
        return_value=TargetInspection(target=target, reachable=True, status="online"),
    ), patch.object(
        deploy_core, "get_deployment_status", return_value=mock_dep
    ), patch.object(
        build_core, "get_last_build_status", return_value=None
    ):
        with pytest.raises(RuntimeError, match="No completed build found on target 'deployed_box'"):
            runs.start_target_run(target, mock_config, exp_file)

    # 2. Failed build
    mock_failed_build = build_core.TargetBuildRecord(
        build_id="build-failed-1",
        project_name="openmover",
        git_revision="abc",
        target_name="deployed_box",
        target_transport="ssh",
        destination_path="/home/user/openmover",
        built_at="2026-10-04T00:00:00Z",
        status="failed",
        returncode=2,
        duration_seconds=1.0,
        workers=2,
        command=["colcon", "build"],
    )
    with patch.object(
        targets_core,
        "discover_target",
        return_value=TargetInspection(target=target, reachable=True, status="online"),
    ), patch.object(
        deploy_core, "get_deployment_status", return_value=mock_dep
    ), patch.object(
        build_core, "get_last_build_status", return_value=mock_failed_build
    ):
        with pytest.raises(RuntimeError, match="Last build on target 'deployed_box' failed with exit code 2"):
            runs.start_target_run(target, mock_config, exp_file)


def test_target_run_ssh_launch_and_provenance(
    sample_experiment_project: tuple[Path, Path], mock_config: Config
) -> None:
    proj, exp_file = sample_experiment_project
    target = Target(name="remote_host", transport="ssh", host="robot.local", user="zar", deployment_root="/opt")

    mock_dep = DeploymentRecord(
        deployment_id="dep-999",
        project_name="openmover",
        project_version="1.0.0",
        git_revision="abc",
        target_name="remote_host",
        target_transport="ssh",
        destination_path="/opt/openmover",
        deployed_at="2026-10-04T00:00:00Z",
        status="active",
    )
    mock_build = build_core.TargetBuildRecord(
        build_id="build-remote_host-001",
        project_name="openmover",
        git_revision="abc",
        target_name="remote_host",
        target_transport="ssh",
        destination_path="/opt/openmover",
        built_at="2026-10-04T00:00:00Z",
        status="success",
        returncode=0,
        duration_seconds=5.0,
        workers=4,
        command=["colcon", "build"],
    )

    ssh_calls: list[list[str]] = []

    def mock_subprocess_run(cmd, *args, **kwargs):
        ssh_calls.append(cmd)
        res = MagicMock()
        res.returncode = 0
        if any("nohup setsid" in str(arg) for arg in cmd):
            res.stdout = "PID:4321:4321\n"
        else:
            res.stdout = ""
        res.stderr = ""
        return res

    with patch.object(
        targets_core,
        "discover_target",
        return_value=TargetInspection(
            target=target,
            reachable=True,
            status="online",
            environment=TargetEnvironment(ros_distro="jazzy"),
        ),
    ), patch.object(
        deploy_core, "get_deployment_status", return_value=mock_dep
    ), patch.object(
        build_core, "get_last_build_status", return_value=mock_build
    ), patch(
        "subprocess.run", side_effect=mock_subprocess_run
    ):
        record = runs.start_target_run(target, mock_config, exp_file)

    assert record.run_id is not None
    assert record.target == "remote_host"
    assert record.target_transport == "ssh"
    assert record.pid == 4321
    assert record.pgid == 4321
    assert record.deployment_id == "dep-999"
    assert record.build_id == "build-remote_host-001"
    assert record.destination == "/opt/openmover"
    assert record.remote_run_dir == f"/opt/openmover/.caasi/runs/{record.run_id}"

    # Verify upload of wrapper script and setsid launch command
    assert any("mkdir -p" in " ".join(c) for c in ssh_calls)
    assert any("nohup setsid" in " ".join(c) for c in ssh_calls)

    # Verify host manifest was written
    host_manifest = mock_config.expanded_path_for("paths.runs") / record.run_id / "manifest.yaml"
    assert host_manifest.is_file()


def test_remote_effective_status_and_ssh_probe(mock_config: Config) -> None:
    target = Target(name="worker", transport="ssh", host="worker.lan")
    record = runs.RunRecord(
        run_id="run-test-probe",
        name="test_probe",
        backend="python",
        kind="experiment",
        command=["python3", "main.py"],
        cwd="/srv/app",
        created="2026-10-04T00:00:00Z",
        pid=5555,
        pgid=5555,
        target="worker",
        target_transport="ssh",
        destination="/srv/app",
        remote_run_dir="/srv/app/.caasi/runs/run-test-probe",
    )

    with patch.object(targets_core, "find_target", return_value=target):
        # 1. Process completed successfully (exit_code file = 0)
        with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="EXIT:0\n")):
            assert runs.effective_status(record, mock_config) == runs.TERMINAL_OK

        # 2. Process failed (exit_code file = 1)
        with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="EXIT:1\n")):
            assert runs.effective_status(record, mock_config) == runs.TERMINAL_FAIL

        # 3. Process still alive
        with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="RUNNING\n")):
            assert runs.effective_status(record, mock_config) == runs.RUNNING

        # 4. Process dead without exit code -> LOST
        with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="DEAD\n")):
            assert runs.effective_status(record, mock_config) == runs.LOST

        # 5. SSH connection error -> UNREACHABLE
        with patch("subprocess.run", return_value=MagicMock(returncode=255, stdout="")):
            assert runs.effective_status(record, mock_config) == "unreachable"


def test_remote_stop_run_process_group(mock_config: Config) -> None:
    target = Target(name="worker", transport="ssh", host="worker.lan")
    record = runs.RunRecord(
        run_id="run-test-stop",
        name="test_stop",
        backend="python",
        kind="experiment",
        command=["python3", "main.py"],
        cwd="/srv/app",
        created="2026-10-04T00:00:00Z",
        pid=7777,
        pgid=7777,
        target="worker",
        target_transport="ssh",
        destination="/srv/app",
        remote_run_dir="/srv/app/.caasi/runs/run-test-stop",
    )

    ssh_executed = []

    def mock_run(cmd, *args, **kwargs):
        ssh_executed.append(" ".join(cmd))
        res = MagicMock()
        res.returncode = 0
        if "kill -0" in " ".join(cmd):
            # First status check returns ALIVE, second check after SIGTERM returns DEAD
            res.stdout = "DEAD\n" if len(ssh_executed) > 2 else "ALIVE\n"
        return res

    with patch.object(targets_core, "find_target", return_value=target), patch(
        "subprocess.run", side_effect=mock_run
    ):
        stopped = runs.stop_run(record, config=mock_config)

    assert stopped is True
    assert record.stopped is True
    # Verify SIGTERM was sent to the negative PGID: kill -TERM -7777
    assert any("kill -TERM -7777" in c for c in ssh_executed)


def test_remote_stop_uses_target_ssh_budget(mock_config: Config) -> None:
    """Remote stop budgets each SSH round-trip from the target's own link latency.

    Phase 7 Stage D hit this against a real machine over a Tailscale relay: the
    5s-per-call budget expired mid-stop even though the kill landed, so the run
    was mis-reported as `lost`.
    """
    target = Target(name="slow", transport="ssh", host="slow.lan", ssh_timeout=20.0)
    record = runs.RunRecord(
        run_id="run-test-slow-stop", name="slow_stop", backend="python",
        kind="experiment", command=["python3", "main.py"], cwd="/srv/app",
        created="2026-10-04T00:00:00Z", pid=8888, pgid=8888,
        target="slow", target_transport="ssh", destination="/srv/app",
        remote_run_dir="/srv/app/.caasi/runs/run-test-slow-stop",
    )
    observed: list[float] = []

    def mock_run(cmd, *args, **kwargs):
        observed.append(kwargs.get("timeout"))
        res = MagicMock()
        res.returncode = 0
        res.stdout = "DEAD\n" if "kill -0" in " ".join(cmd) else ""
        return res

    with patch.object(targets_core, "find_target", return_value=target), patch(
        "subprocess.run", side_effect=mock_run
    ):
        runs.stop_run(record, config=mock_config)

    # Every SSH call must be given the target's budget, not a hardcoded 5s.
    assert observed, "no SSH calls were made"
    assert all(t is not None and t >= 20.0 for t in observed), observed


def test_remote_stop_records_stopped_when_confirmation_times_out(mock_config: Config) -> None:
    """A delivered kill must never be recorded as `lost` just because the
    follow-up probe could not complete inside its budget.

    This is the exact Stage D mis-report: the tested process tree WAS terminated
    on the target, but caasi reported status `lost`.
    """
    target = Target(name="slow", transport="ssh", host="slow.lan", ssh_timeout=20.0)
    record = runs.RunRecord(
        run_id="run-test-timeout-stop", name="timeout_stop", backend="python",
        kind="experiment", command=["python3", "main.py"], cwd="/srv/app",
        created="2026-10-04T00:00:00Z", pid=9999, pgid=9999,
        target="slow", target_transport="ssh", destination="/srv/app",
        remote_run_dir="/srv/app/.caasi/runs/run-test-timeout-stop",
    )
    calls = {"n": 0}

    def mock_run(cmd, *args, **kwargs):
        calls["n"] += 1
        joined = " ".join(cmd)
        if "kill -0" in joined:
            # Every status probe is too slow to complete: the transport cannot
            # confirm anything.
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout", 5.0))
        res = MagicMock()
        res.returncode = 0
        res.stdout = ""
        return res

    with patch.object(targets_core, "find_target", return_value=target), patch(
        "subprocess.run", side_effect=mock_run
    ):
        stopped = runs.stop_run(record, config=mock_config)

    # Confirmation failed, so the return value is False ("signalled, unconfirmed")...
    assert stopped is False
    # ...but the run must be recorded as stopped, never as lost.
    assert record.stopped is True
    assert record.paused is False


def test_local_sandbox_lifecycle_and_process_group_cleanup(
    sample_experiment_project: tuple[Path, Path], tmp_path: Path, mock_config: Config
) -> None:
    """Verify end-to-end detached launch, tracking, logs, and process group cleanup in local sandbox."""
    proj, exp_file = sample_experiment_project
    sandbox_dest = tmp_path / "openmover"
    sandbox_dest.mkdir()

    target = Target(
        name="test_sandbox",
        transport="local",
        deployment_root=str(tmp_path),
    )

    # Set up mock deployment and build records on the target
    mock_dep = DeploymentRecord(
        deployment_id="dep-local-001",
        project_name="openmover",
        project_version="1.0.0",
        git_revision="abc",
        target_name="test_sandbox",
        target_transport="local",
        destination_path=str(sandbox_dest),
        deployed_at="2026-10-04T00:00:00Z",
        status="active",
    )
    mock_build = build_core.TargetBuildRecord(
        build_id="build-local-001",
        project_name="openmover",
        git_revision="abc",
        target_name="test_sandbox",
        target_transport="local",
        destination_path=str(sandbox_dest),
        built_at="2026-10-04T00:00:00Z",
        status="success",
        returncode=0,
        duration_seconds=2.0,
        workers=2,
        command=["colcon", "build"],
    )

    # Mirror scripts into sandbox
    (sandbox_dest / "scripts").mkdir(parents=True)
    # Create a script that spawns a background child process to test complete process group cleanup
    (sandbox_dest / "scripts" / "test_task.py").write_text(
        "import sys, time, subprocess\n"
        "print('SANDBOX TASK STARTED')\n"
        "sys.stdout.flush()\n"
        "# Spawn child process in same process group\n"
        "sub = subprocess.Popen(['sleep', '60'])\n"
        "print(f'CHILD_PID:{sub.pid}')\n"
        "sys.stdout.flush()\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    (sandbox_dest / "experiments").mkdir(parents=True)
    (sandbox_dest / "experiments" / "test_exp.yaml").write_text(
        exp_file.read_text(encoding="utf-8"), encoding="utf-8"
    )

    with patch.object(
        targets_core,
        "discover_target",
        return_value=TargetInspection(target=target, reachable=True, status="online"),
    ), patch.object(
        deploy_core, "get_deployment_status", return_value=mock_dep
    ), patch.object(
        build_core, "get_last_build_status", return_value=mock_build
    ):
        record = runs.start_target_run(target, mock_config, exp_file)

    assert record.target == "test_sandbox"
    assert record.target_transport == "local"
    assert record.pid is not None
    assert record.pgid is not None

    # Wait for child process to start and capture child PID from log
    time.sleep(1.0)
    stdout_content = runs.read_run_log(record, mock_config, stream="stdout")
    assert "SANDBOX TASK STARTED" in stdout_content

    child_pid = None
    for line in stdout_content.splitlines():
        if "CHILD_PID:" in line:
            child_pid = int(line.split("CHILD_PID:")[1].strip())
            break

    assert child_pid is not None

    # Verify both leader and child are alive in the same process group
    assert runs.pid_alive(record.pid)
    assert runs.pid_alive(child_pid)
    assert os.getpgid(child_pid) == record.pgid

    # Check status
    assert runs.effective_status(record, mock_config) == runs.RUNNING

    # Inspect run files
    files = runs.inspect_run_files(record, mock_config)
    paths = [f["path"] for f in files]
    assert "run.sh" in paths
    assert "pid" in paths
    assert "pgid" in paths
    assert "stdout.log" in paths

    # Stop run and verify complete process group termination (zero orphan processes!)
    stopped = runs.stop_run(record, timeout=3.0, config=mock_config)
    assert stopped is True

    # Give OS a brief slice to reap
    time.sleep(0.3)
    assert not runs.pid_alive(record.pid)
    assert not runs.pid_alive(child_pid), f"Child PID {child_pid} was orphaned after run stop!"

    assert runs.effective_status(record, mock_config) == runs.STOPPED


def test_cli_run_target_commands(
    sample_experiment_project: tuple[Path, Path], tmp_path: Path
) -> None:
    """Verify CLI run start, list, status, logs, inspect, and stop with --target."""
    proj, exp_file = sample_experiment_project
    cfg_file = tmp_path / "caasi.toml"
    cfg_file.write_text(
        f'paths.runs = "{tmp_path}/runs"\n'
        f'[[targets]]\nname = "sim_node"\ntransport = "ssh"\nhost = "sim.lan"\n',
        encoding="utf-8",
    )

    mock_record = runs.RunRecord(
        run_id="20261004-120000-test-exp",
        name="test_exp",
        backend="python",
        kind="experiment",
        command=["python3", "task.py"],
        cwd="/srv/sim",
        created="2026-10-04T00:00:00Z",
        pid=8888,
        pgid=8888,
        target="sim_node",
        target_transport="ssh",
        destination="/srv/sim",
        deployment_id="dep-cli-1",
        build_id="build-cli-1",
        remote_run_dir="/srv/sim/.caasi/runs/20261004-120000-test-exp",
        directory=tmp_path / "runs" / "20261004-120000-test-exp",
    )
    mock_record.directory.mkdir(parents=True)
    runs._write_manifest(mock_record.directory, mock_record.to_dict())

    # 1. Test CLI run list with --target filter
    with patch("caasi.state.cfg", return_value=Config({"paths": {"runs": str(tmp_path / "runs")}}, [])):
        res = runner.invoke(app, ["run", "list", "--target", "sim_node"])
        assert res.exit_code == 0
        assert "sim_node" in res.stdout
        assert "test_exp" in res.stdout

        # 2. Test CLI run status
        with patch.object(runs, "effective_status", return_value="running"):
            res = runner.invoke(app, ["run", "status", "20261004-120000-test-exp"])
            assert res.exit_code == 0
            assert "Target" in res.stdout
            assert "sim_node (ssh)" in res.stdout
            assert "Deployment" in res.stdout
            assert "dep-cli-1" in res.stdout
            assert "Build" in res.stdout
            assert "build-cli-1" in res.stdout

        # 3. Test CLI run inspect
        with patch.object(
            runs,
            "inspect_run_files",
            return_value=[{"path": "stdout.log", "size": 1024}],
        ):
            res = runner.invoke(app, ["run", "inspect", "20261004-120000-test-exp"])
            assert res.exit_code == 0
            assert "stdout.log" in res.stdout
            assert "Remote Directory" in res.stdout

        # 4. Test CLI run logs
        with patch.object(
            runs, "read_run_log", return_value="[12:00:01] [sim] Initialization complete\n"
        ):
            res = runner.invoke(app, ["run", "logs", "20261004-120000-test-exp"])
            assert res.exit_code == 0
            assert "Initialization complete" in res.stdout

        # 5. Test CLI run stop
        with patch.object(runs, "stop_run", return_value=True):
            res = runner.invoke(app, ["run", "stop", "20261004-120000-test-exp"])
            assert res.exit_code == 0
            assert "stopped" in res.stdout
