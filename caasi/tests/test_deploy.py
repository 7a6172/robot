"""Tests for target deployment engine, incremental synchronization, and provenance (Phase 7 Stage B)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from caasi.cli.main import app
from caasi.core.config import Config
from caasi.core.deploy import (
    DEFAULT_EXCLUDE_PATTERNS,
    DeploymentRecord,
    DeploymentSpec,
    create_deployment_spec,
    execute_deployment,
    get_deployment_status,
    list_local_deployments,
    preflight_target,
    resolve_deployment_destination,
    verify_deployment,
)
from caasi.core.targets import Target, TargetEnvironment, TargetInspection, TargetResources

runner = CliRunner()


@pytest.fixture
def sample_project(tmp_path: Path) -> Path:
    proj = tmp_path / "my_robot_proj"
    proj.mkdir()
    (proj / "caasi.yaml").write_text(
        "schema: 1\nname: my_robot\nversion: 1.2.0\ncomponents: {ros2: true}\nrequires: {ros2: {version: jazzy}}\n",
        encoding="utf-8",
    )
    (proj / "caasi.lock").write_text("schema: 1\n", encoding="utf-8")
    src = proj / "src" / "pkg_a"
    src.mkdir(parents=True)
    (src / "package.xml").write_text("<package><name>pkg_a</name></package>", encoding="utf-8")
    (src / "file.py").write_text("print('hello')", encoding="utf-8")

    # Excluded files
    build = proj / "build"
    build.mkdir()
    (build / "temp.o").write_text("dummy", encoding="utf-8")
    tests = proj / "tests"
    tests.mkdir()
    (tests / "test_dummy.py").write_text("assert True", encoding="utf-8")

    return proj


def test_deployment_spec_and_destination_resolution(sample_project: Path) -> None:
    target = Target(name="local", transport="local", deployment_root="/opt/deploy")
    cfg = Config({}, [])
    spec = create_deployment_spec(sample_project, target, cfg)

    assert spec.project_name == "my_robot"
    assert spec.project_version == "1.2.0"
    assert spec.destination_path == "/opt/deploy/my_robot"
    assert "build" in spec.exclude_patterns
    assert "install" in spec.exclude_patterns


def test_preflight_target_compatible(sample_project: Path) -> None:
    target = Target(name="local", transport="local")
    cfg = Config({}, [])

    fake_insp = TargetInspection(
        target=target,
        reachable=True,
        status="online",
        environment=TargetEnvironment(ros_distro="jazzy"),
        discovered_capabilities=["ros2", "ros2:jazzy"],
    )

    with patch("caasi.core.deploy.discover_target", return_value=fake_insp):
        comp, insp, issues = preflight_target(target, sample_project, cfg)

    assert comp is True
    assert issues == []


def test_preflight_target_unreachable(sample_project: Path) -> None:
    target = Target(name="offline", transport="ssh", host="192.0.2.1")
    cfg = Config({}, [])

    fake_insp = TargetInspection(
        target=target,
        reachable=False,
        status="unreachable",
        error="Connection timed out",
    )

    with patch("caasi.core.deploy.discover_target", return_value=fake_insp):
        comp, insp, issues = preflight_target(target, sample_project, cfg)

    assert comp is False
    assert any("unreachable" in i for i in issues)


def test_preflight_target_incompatible(sample_project: Path) -> None:
    target = Target(name="no-ros", transport="local")
    cfg = Config({}, [])

    fake_insp = TargetInspection(
        target=target,
        reachable=True,
        status="online",
        environment=TargetEnvironment(),
        discovered_capabilities=[],
    )

    with patch("caasi.core.deploy.discover_target", return_value=fake_insp):
        comp, insp, issues = preflight_target(target, sample_project, cfg)

    assert comp is False
    assert any("requires ROS 2" in i for i in issues)


def test_deploy_dry_run_leaves_destination_untouched(sample_project: Path, tmp_path: Path) -> None:
    dest = tmp_path / "dry_run_dest"
    target = Target(name="local", transport="local")
    cfg = Config({}, [])

    spec = create_deployment_spec(sample_project, target, cfg, destination_override=str(dest))

    record = execute_deployment(spec, dry_run=True, config=cfg)
    assert record.status == "dry_run"
    assert record.file_count > 0
    assert not dest.exists()


def test_deploy_real_and_verification(sample_project: Path, tmp_path: Path) -> None:
    dest = tmp_path / "real_deploy_dest"
    target = Target(name="local", transport="local")
    cfg = Config({}, [])

    spec = create_deployment_spec(sample_project, target, cfg, destination_override=str(dest))

    # Real materialization
    record = execute_deployment(spec, dry_run=False, config=cfg)
    assert record.status == "verified"
    assert dest.is_dir()
    assert (dest / "caasi.yaml").is_file()
    assert (dest / "src" / "pkg_a" / "file.py").is_file()
    assert (dest / ".caasi-deployment.json").is_file()

    # Excluded files must not be copied
    assert not (dest / "build").exists()
    assert not (dest / "tests").exists()

    # Verify status reading
    status = get_deployment_status(target, str(dest), cfg)
    assert status is not None
    assert status.project_name == "my_robot"
    assert status.status == "verified"

    # Verify local deployment history
    deployments = list_local_deployments(sample_project, "local")
    assert len(deployments) == 1
    assert deployments[0].deployment_id == record.deployment_id


def test_deployment_status_resolves_default_destination(
    sample_project: Path, tmp_path: Path
) -> None:
    """`--status` must find a deployment created with the DEFAULT destination.

    Phase 7 Stage D found that the read path used the bare ``deployment_root``
    while the write path appended the project name, so a live, verified
    deployment was reported as absent. Both paths must agree.
    """
    cfg = Config({}, [])
    root = tmp_path / "deploy-root"
    root.mkdir()
    target = Target(name="local", transport="local", deployment_root=str(root))

    # Deploy using the default destination (no override) -> <root>/<project_name>
    spec = create_deployment_spec(sample_project, target, cfg)
    assert spec.destination_path == str(root / "my_robot")
    record = execute_deployment(spec, dry_run=False, config=cfg)
    assert record.status == "verified"

    # Reading WITHOUT an explicit destination must find it.
    status = get_deployment_status(target, None, cfg, project_root=sample_project)
    assert status is not None, "default destination was not resolved correctly"
    assert status.deployment_id == record.deployment_id
    assert status.project_name == "my_robot"
    assert status.status == "verified"


def test_deployment_status_missing_deployment_returns_none(
    sample_project: Path, tmp_path: Path
) -> None:
    """A project with no deployment yet must report absent, not raise."""
    cfg = Config({}, [])
    root = tmp_path / "empty-root"
    root.mkdir()
    target = Target(name="local", transport="local", deployment_root=str(root))
    # Nothing deployed under the resolved destination -> None (no crash).
    assert get_deployment_status(target, None, cfg, project_root=sample_project) is None
    # An explicit destination that does not exist behaves the same way.
    assert get_deployment_status(target, str(root / "does-not-exist"), cfg) is None


def test_incremental_synchronization(sample_project: Path, tmp_path: Path) -> None:
    dest = tmp_path / "incremental_dest"
    target = Target(name="local", transport="local")
    cfg = Config({}, [])
    spec = create_deployment_spec(sample_project, target, cfg, destination_override=str(dest))

    # First deployment
    rec1 = execute_deployment(spec, dry_run=False, config=cfg)
    assert rec1.status == "verified"
    first_transferred = rec1.transferred_bytes

    # Second deployment with zero changes
    rec2 = execute_deployment(spec, dry_run=False, config=cfg)
    assert rec2.status == "verified"
    # Unchanged files should transfer 0 regular file payload
    assert rec2.transferred_bytes < first_transferred

    # Modify one file in sample project
    (sample_project / "src" / "pkg_a" / "file.py").write_text("print('updated')", encoding="utf-8")
    rec3 = execute_deployment(spec, dry_run=False, config=cfg)
    assert rec3.status == "verified"
    assert any("file.py" in f for f in rec3.changed_files)


def test_verify_deployment_failure(tmp_path: Path) -> None:
    empty_dest = tmp_path / "empty_dir"
    empty_dest.mkdir()
    target = Target(name="local", transport="local")

    ok, err = verify_deployment(target, str(empty_dest))
    assert ok is False
    assert "Missing project manifest" in str(err)


# CLI command tests


def test_cli_deploy_dry_run(sample_project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(sample_project)
    dest = tmp_path / "cli_dest"
    res = runner.invoke(app, ["--config", "/dev/null", "deploy", "local", "--dry-run", "--dest", str(dest)])
    assert res.exit_code == 0
    assert "DRY RUN" in res.output
    assert not dest.exists()


def test_cli_deploy_real_and_status(sample_project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(sample_project)
    dest = tmp_path / "cli_real_dest"
    # Deploy
    res1 = runner.invoke(app, ["--config", "/dev/null", "deploy", "local", "--dest", str(dest)])
    assert res1.exit_code == 0
    assert "VERIFIED" in res1.output

    # Check status
    res2 = runner.invoke(app, ["--config", "/dev/null", "deploy", "local", "--status", "--dest", str(dest)])
    assert res2.exit_code == 0
    assert "Active Deployment on local:" in res2.output
    assert "my_robot" in res2.output


def test_cli_deploy_list(sample_project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(sample_project)
    dest = tmp_path / "cli_list_dest"
    runner.invoke(app, ["--config", "/dev/null", "deploy", "local", "--dest", str(dest)])

    res = runner.invoke(app, ["--config", "/dev/null", "deploy", "--list"])
    assert res.exit_code == 0
    assert "Recorded Deployments" in res.output
    assert "local" in res.output


def test_cli_deploy_target_offline(sample_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(sample_project)
    res = runner.invoke(app, ["--config", "/dev/null", "deploy", "nonexistent-target"])
    assert res.exit_code == 1
    assert "No target matching 'nonexistent-target'" in res.output


def test_cli_deploy_permission_denied(sample_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(sample_project)
    # Attempting to deploy to a root directory without write permissions
    res = runner.invoke(app, ["--config", "/dev/null", "deploy", "local", "--dest", "/root/forbidden_deploy"])
    assert res.exit_code == 1
    assert "Failed to create destination directory" in res.output or "Permission denied" in res.output
