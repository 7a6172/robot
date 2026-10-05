"""Tests for target-native build foundation (Phase 7 Stage C1)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from caasi.cli.main import app
from caasi.core import build as build_core
from caasi.core.config import Config
from caasi.core.deploy import DeploymentRecord
from caasi.core.targets import Target, TargetEnvironment, TargetInspection, TargetResources

runner = CliRunner()


@pytest.fixture
def sample_project(tmp_path: Path) -> Path:
    proj = tmp_path / "test_robot_proj"
    proj.mkdir()
    (proj / "caasi.yaml").write_text(
        "schema: 1\nname: test_robot\nversion: 1.0.0\ncomponents: {ros2: true}\n",
        encoding="utf-8",
    )
    src = proj / "src" / "sample_pkg"
    src.mkdir(parents=True)
    (src / "package.xml").write_text("<package><name>sample_pkg</name></package>", encoding="utf-8")
    return proj


def test_derive_target_workers() -> None:
    # Explicit jobs override
    assert build_core.derive_target_workers(None, requested_jobs=5) == 5

    # 16 GiB RAM (16777216 KiB), 8 CPUs -> (16 - 2) / 6 = 2 workers
    res = TargetResources(cpu_count=8, memory_total_kib=16 * 1024 * 1024)
    assert build_core.derive_target_workers(res) == 2

    # 64 GiB RAM (67108864 KiB), 16 CPUs -> (64 - 2) / 6 = 10 workers
    res_large = TargetResources(cpu_count=16, memory_total_kib=64 * 1024 * 1024)
    assert build_core.derive_target_workers(res_large) == 10

    # 64 GiB RAM, 4 CPUs -> CPU bound (4 workers)
    res_cpu_bound = TargetResources(cpu_count=4, memory_total_kib=64 * 1024 * 1024)
    assert build_core.derive_target_workers(res_cpu_bound) == 4

    # 4 GiB RAM, 4 CPUs -> (4 - 2) / 6 = 0 -> bounded minimum 1 worker
    res_low = TargetResources(cpu_count=4, memory_total_kib=4 * 1024 * 1024)
    assert build_core.derive_target_workers(res_low) == 1

    # Empty resources -> falls back safely to default_parallel_workers()
    assert build_core.derive_target_workers(None) >= 1


def test_execute_target_build_local(sample_project: Path) -> None:
    target = Target(name="local", transport="local", deployment_root=".")
    cfg = Config({}, [])

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = ["Starting >>> sample_pkg\n", "Finished <<< sample_pkg [1.0s]\n"]
    mock_proc.wait.return_value = 0

    with patch("subprocess.Popen", return_value=mock_proc):
        result = build_core.execute_target_build(
            target=target,
            project_root=sample_project,
            config=cfg,
        )

    assert result.ok
    assert result.returncode == 0
    assert result.target_name == "local"
    assert result.build_id is not None
    assert result.build_id.startswith("build-local-")

    # Verify provenance record saved on host
    records = build_core.list_build_records(sample_project, "local")
    assert len(records) == 1
    assert records[0].status == "success"
    assert records[0].project_name == "test_robot"


def test_execute_target_build_unreachable_target(sample_project: Path) -> None:
    target = Target(name="offline-robot", transport="ssh", host="192.0.2.1")
    cfg = Config({}, [])

    fake_insp = TargetInspection(
        target=target,
        reachable=False,
        status="unreachable",
        error="SSH connection timed out",
    )

    with patch("caasi.core.targets.discover_target", return_value=fake_insp):
        with pytest.raises(build_core.BuildError, match="Target 'offline-robot' is unreachable"):
            build_core.execute_target_build(
                target=target,
                project_root=sample_project,
                config=cfg,
            )


def test_execute_target_build_missing_deployment(sample_project: Path) -> None:
    target = Target(name="remote-robot", transport="ssh", host="192.168.1.50")
    cfg = Config({}, [])

    fake_insp = TargetInspection(
        target=target,
        reachable=True,
        status="online",
        environment=TargetEnvironment(ros_distro="jazzy"),
        resources=TargetResources(cpu_count=8, memory_total_kib=32 * 1024 * 1024),
    )

    with patch("caasi.core.targets.discover_target", return_value=fake_insp), \
         patch("caasi.core.deploy.get_deployment_status", return_value=None):
        with pytest.raises(build_core.BuildError, match="No active deployment found"):
            build_core.execute_target_build(
                target=target,
                project_root=sample_project,
                config=cfg,
            )


def test_execute_target_build_remote_ssh_success(sample_project: Path) -> None:
    target = Target(
        name="robot-orin",
        transport="ssh",
        host="192.168.1.100",
        user="orin",
        deployment_root="/home/orin/deployments",
    )
    cfg = Config({}, [])

    fake_insp = TargetInspection(
        target=target,
        reachable=True,
        status="online",
        environment=TargetEnvironment(ros_distro="jazzy", ros_root="/opt/ros/jazzy"),
        resources=TargetResources(cpu_count=12, memory_total_kib=32 * 1024 * 1024),
    )

    fake_deployment = DeploymentRecord(
        deployment_id="dep-test-12345",
        project_name="test_robot",
        project_version="1.0.0",
        git_revision="abc1234",
        target_name="robot-orin",
        target_transport="ssh",
        destination_path="/home/orin/deployments/test_robot",
        deployed_at="2026-10-04T00:00:00Z",
        status="verified",
    )

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = ["Starting >>> sample_pkg\n", "Finished <<< sample_pkg [3.5s]\n"]
    mock_proc.wait.return_value = 0

    captured_cmds = []

    def mock_popen(cmd, **kwargs):
        captured_cmds.append(cmd)
        return mock_proc

    lines_seen = []

    with patch("caasi.core.targets.discover_target", return_value=fake_insp), \
         patch("caasi.core.deploy.get_deployment_status", return_value=fake_deployment), \
         patch("subprocess.Popen", side_effect=mock_popen), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)

        result = build_core.execute_target_build(
            target=target,
            project_root=sample_project,
            config=cfg,
            packages_select=["sample_pkg"],
            clean=True,
            line_callback=lines_seen.append,
        )

    assert result.ok
    assert result.returncode == 0
    assert result.target_name == "robot-orin"
    assert result.deployment_id == "dep-test-12345"
    assert result.workers == 5  # (32 - 2) / 6 = 5 workers
    assert len(lines_seen) == 2

    # Verify executed remote SSH command structure
    assert len(captured_cmds) == 1
    remote_cmd_args = captured_cmds[0]
    assert remote_cmd_args[0] == "ssh"
    assert "orin@192.168.1.100" in remote_cmd_args
    remote_bash_str = remote_cmd_args[-1]
    assert "cd /home/orin/deployments/test_robot" in remote_bash_str
    assert "rm -rf build install log" in remote_bash_str
    assert ". /opt/ros/jazzy/setup.bash" in remote_bash_str
    assert "colcon build --parallel-workers 5 --symlink-install --packages-select sample_pkg" in remote_bash_str

    # Verify host build record
    records = build_core.list_build_records(sample_project, "robot-orin")
    assert len(records) == 1
    assert records[0].status == "success"
    assert records[0].deployment_id == "dep-test-12345"
    assert records[0].target_name == "robot-orin"


def test_execute_target_build_remote_compilation_failure(sample_project: Path) -> None:
    target = Target(name="robot-orin", transport="ssh", host="192.168.1.100")
    cfg = Config({}, [])

    fake_insp = TargetInspection(
        target=target,
        reachable=True,
        status="online",
        environment=TargetEnvironment(ros_distro="jazzy"),
        resources=TargetResources(cpu_count=8, memory_total_kib=16 * 1024 * 1024),
    )

    fake_deployment = DeploymentRecord(
        deployment_id="dep-fail-123",
        project_name="test_robot",
        project_version="1.0.0",
        git_revision="abc1234",
        target_name="robot-orin",
        target_transport="ssh",
        destination_path="/tmp/deploy/test_robot",
        deployed_at="2026-10-04T00:00:00Z",
        status="verified",
    )

    mock_proc = MagicMock()
    mock_proc.returncode = 2
    mock_proc.stdout = ["Starting >>> sample_pkg\n", "stderr: compilation error in main.cpp\n", "Failed <<< sample_pkg\n"]
    mock_proc.wait.return_value = 2

    with patch("caasi.core.targets.discover_target", return_value=fake_insp), \
         patch("caasi.core.deploy.get_deployment_status", return_value=fake_deployment), \
         patch("subprocess.Popen", return_value=mock_proc), \
         patch("subprocess.run"):
        result = build_core.execute_target_build(
            target=target,
            project_root=sample_project,
            config=cfg,
        )

    assert not result.ok
    assert result.returncode == 2
    assert "compilation error" in result.output

    # Provenance record reflects failure
    records = build_core.list_build_records(sample_project, "robot-orin")
    assert len(records) == 1
    assert records[0].status == "failed"
    assert records[0].returncode == 2


def test_execute_target_build_local_sandbox(sample_project: Path, tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    deployed_proj = sandbox / "test_robot"
    deployed_proj.mkdir()
    (deployed_proj / "caasi.yaml").write_text("schema: 1\nname: test_robot\n", encoding="utf-8")
    (deployed_proj / "src" / "pkg").mkdir(parents=True)
    (deployed_proj / ".caasi-deployment.json").write_text(
        json.dumps({
            "deployment_id": "dep-local-sandbox",
            "project_name": "test_robot",
            "project_version": "1.0.0",
            "git_revision": "rev1",
            "target_name": "sandbox-target",
            "target_transport": "local",
            "destination_path": str(deployed_proj),
            "deployed_at": "2026-10-04T00:00:00Z",
            "status": "verified",
        }),
        encoding="utf-8",
    )

    target = Target(name="sandbox-target", transport="local", deployment_root=str(sandbox))
    cfg = Config({}, [])

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = ["Finished <<< pkg\n"]
    mock_proc.wait.return_value = 0

    with patch("subprocess.Popen", return_value=mock_proc):
        result = build_core.execute_target_build(
            target=target,
            project_root=sample_project,
            config=cfg,
        )

    assert result.ok
    assert result.target_name == "sandbox-target"
    assert result.deployment_id == "dep-local-sandbox"
    assert (deployed_proj / ".caasi-build.json").is_file()


def test_cli_build_target_unknown(sample_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(sample_project)
    result = runner.invoke(app, ["build", "--target", "nonexistent-target"])
    assert result.exit_code != 0
    assert "No target matching 'nonexistent-target'" in result.output


def test_cli_build_target_local(sample_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(sample_project)

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = ["Finished <<< sample_pkg\n"]
    mock_proc.wait.return_value = 0

    with patch("subprocess.Popen", return_value=mock_proc):
        result = runner.invoke(app, ["build", "--target", "local"])

    assert result.exit_code == 0
    assert "Building workspace" in result.output
    assert "Build completed successfully" in result.output


def test_cli_build_target_remote_json(sample_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(sample_project)

    fake_target = Target(name="orin-node", transport="ssh", host="192.168.1.100")
    fake_build_result = build_core.BuildResult(
        returncode=0,
        command=["colcon", "build"],
        root="/home/orin/deployments/test_robot",
        workers=4,
        duration=3.21,
        target_name="orin-node",
        build_id="build-test-999",
        deployment_id="dep-test-888",
    )

    with patch("caasi.core.targets.find_target", return_value=fake_target), \
         patch("caasi.core.build.execute_target_build", return_value=fake_build_result):
        result = runner.invoke(app, ["build", "--target", "orin-node", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["ok"] is True
    assert data["target_name"] == "orin-node"
    assert data["build_id"] == "build-test-999"
    assert data["deployment_id"] == "dep-test-888"


# ---------------------------------------------------------------------------
# Local build/run destination contract (Phase 7 F2 follow-up)
#
# PRE-EXISTING DEFECT, reported in the F2 report and fixed here. `target: local`
# is a DEPLOYED target like any other -- `deploy` puts it in
# ~/.caasi/deployments/local/<project>, `run` requires that deployment and
# executes there -- but `build` recorded in the PROJECT ROOT, so `build` then
# `run` on the local target failed with "No completed build found".
#
# The discriminator is now whether a deployment EXISTS, not whether the target is
# named `local`.
# ---------------------------------------------------------------------------


def _fake_successful_build():
    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = ["Finished <<< sample_pkg [1.0s]\n"]
    proc.wait.return_value = 0
    return proc


def test_local_build_uses_the_deployment_when_one_exists(sample_project: Path, tmp_path: Path) -> None:
    """A deployed local target builds AT the deployment, which is where run looks."""
    from caasi.core import deploy as deploy_core

    deployment = tmp_path / "deployments" / "test_robot"
    deployment.mkdir(parents=True)
    (deployment / "src").mkdir()
    (deployment / "src" / "keep").write_text("x")

    target = Target(name="local", transport="local", deployment_root=str(tmp_path / "deployments"))
    cfg = Config({}, [])

    fake_inspection = MagicMock()
    fake_inspection.reachable = True
    fake_inspection.resources = None
    fake_inspection.environment = MagicMock(ros_root=None, ros_distro="jazzy")

    def _fake_execute_build(root, **kwargs):
        # Emulate a successful build, writing the record the way the real path does.
        res = MagicMock()
        res.ok = True
        res.returncode = 0
        res.duration = 1.0
        res.workers = 1
        res.command = ["colcon", "build"]
        res.packages = ["sample_pkg"]
        res.output = ""
        return res

    real_deployment = MagicMock()
    real_deployment.deployment_id = "deploy-test-1"

    with patch.object(deploy_core, "get_deployment_status", return_value=real_deployment), \
         patch.object(build_core.targets_core, "discover_target", return_value=fake_inspection), \
         patch.object(build_core, "execute_build", side_effect=_fake_execute_build):
        result = build_core.execute_target_build(
            target=target, project_root=sample_project, config=cfg,
        )

    # The record belongs to the DEPLOYMENT, not the project root. This is the
    # assertion that matters: it is exactly where `run` looks for it.
    assert (deployment / ".caasi-build.json").is_file()
    assert not (sample_project / ".caasi-build.json").is_file()


def test_local_build_without_a_deployment_still_builds_the_workspace(
    sample_project: Path,
) -> None:
    """The standalone local-workspace build is preserved, not replaced."""
    target = Target(name="local", transport="local", deployment_root=".")
    cfg = Config({}, [])

    with patch("subprocess.Popen", return_value=_fake_successful_build()):
        result = build_core.execute_target_build(
            target=target, project_root=sample_project, config=cfg,
        )

    assert result.ok
    assert (sample_project / ".caasi-build.json").is_file()


def test_deployment_presence_not_the_target_name_selects_the_path() -> None:
    """The fix removes a special case rather than adding a lookup fallback."""
    import inspect as _inspect

    source = _inspect.getsource(build_core.execute_target_build)
    assert "local_deployment" in source
    # The old name-based discriminator must no longer decide the path alone.
    assert "is_local_workspace = (local_deployment is None)" in source
