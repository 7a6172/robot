"""Tests for caasi build and project overlay chaining."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from caasi.cli.main import app
from caasi.core import build as build_core
from caasi.core import manifest as manifests
from caasi.core import ros as ros_core
from caasi.core import rosenv


def test_system_ram_gb():
    ram = build_core.system_ram_gb()
    assert isinstance(ram, float)
    assert ram > 0.0


def test_default_parallel_workers(monkeypatch):
    # 8 GB RAM, 16 CPUs -> (8 - 2) / 6 = 1 worker
    monkeypatch.setattr(build_core, "system_ram_gb", lambda: 8.0)
    monkeypatch.setattr(os, "cpu_count", lambda: 16)
    assert build_core.default_parallel_workers() == 1

    # 16 GB RAM, 16 CPUs -> (16 - 2) / 6 = 2 workers
    monkeypatch.setattr(build_core, "system_ram_gb", lambda: 16.0)
    assert build_core.default_parallel_workers() == 2

    # 32 GB RAM, 16 CPUs -> (32 - 2) / 6 = 5 workers
    monkeypatch.setattr(build_core, "system_ram_gb", lambda: 32.0)
    assert build_core.default_parallel_workers() == 5

    # 48 GB RAM, 16 CPUs -> (48 - 2) / 6 = 7 workers
    monkeypatch.setattr(build_core, "system_ram_gb", lambda: 48.0)
    assert build_core.default_parallel_workers() == 7

    # 128 GB RAM, 8 CPUs -> bounded by CPUs (8)
    monkeypatch.setattr(build_core, "system_ram_gb", lambda: 128.0)
    monkeypatch.setattr(os, "cpu_count", lambda: 8)
    assert build_core.default_parallel_workers() == 8


def test_find_build_root_with_caasi_yaml(tmp_path):
    proj_dir = tmp_path / "my_project"
    proj_dir.mkdir()
    (proj_dir / "caasi.yaml").write_text("schema: 1\nname: test\n", encoding="utf-8")
    sub_dir = proj_dir / "src" / "pkg1"
    sub_dir.mkdir(parents=True)

    assert build_core.find_build_root(sub_dir) == proj_dir


def test_find_build_root_fallback_to_src(tmp_path):
    ws_dir = tmp_path / "workspace"
    (ws_dir / "src").mkdir(parents=True)
    assert build_core.find_build_root(ws_dir) == ws_dir


def test_clean_workspace(tmp_path):
    build_dir = tmp_path / "build"
    install_dir = tmp_path / "install"
    log_dir = tmp_path / "log"
    build_dir.mkdir()
    install_dir.mkdir()
    log_dir.mkdir()

    removed = build_core.clean_workspace(tmp_path)
    assert set(removed) == {"build", "install", "log"}
    assert not build_dir.exists()
    assert not install_dir.exists()
    assert not log_dir.exists()


def test_execute_build_missing_src(tmp_path):
    with pytest.raises(build_core.BuildError, match="not found"):
        build_core.execute_build(tmp_path)


def test_execute_build_mocked(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "CMakeLists.txt").write_text("", encoding="utf-8")

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = ["Starting >>> pkg1\n", "Finished <<< pkg1 [1.2s]\n"]
    mock_proc.wait.return_value = 0

    seen_lines = []

    with patch("subprocess.Popen", return_value=mock_proc):
        result = build_core.execute_build(
            root=tmp_path,
            packages_select=["pkg1"],
            jobs=4,
            symlink_install=True,
            line_callback=seen_lines.append,
        )

    assert result.ok
    assert result.returncode == 0
    assert result.workers == 4
    assert "--packages-select" in result.command
    assert "pkg1" in result.command
    assert "--symlink-install" in result.command
    assert "--parallel-workers" in result.command
    assert "4" in result.command
    assert len(seen_lines) == 2


def test_project_setup_file_discovery(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "caasi.yaml").write_text("schema: 1\nname: test\n", encoding="utf-8")
    assert rosenv.project_setup_file(tmp_path) is None

    install_setup = tmp_path / "install" / "setup.bash"
    install_setup.parent.mkdir(parents=True)
    install_setup.write_text("#!/bin/bash\n", encoding="utf-8")

    assert rosenv.project_setup_file(tmp_path) == install_setup
    assert rosenv.project_setup_file() == install_setup


def test_project_overlay_chaining(tmp_path, fake_ros_sourced, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "caasi.yaml").write_text("schema: 1\nname: test\n", encoding="utf-8")
    install_setup = tmp_path / "install" / "setup.bash"
    install_setup.parent.mkdir(parents=True)
    install_setup.write_text("#!/bin/bash\n", encoding="utf-8")

    # In fake_ros_sourced, base ROS is in COLCON_PREFIX_PATH/AMENT_PREFIX_PATH,
    # but the project overlay prefix is NOT yet in the environment.
    assert rosenv.is_sourced(project_root=tmp_path) is False

    # Wrapping should include both the ROS setup and project setup
    wrapped = rosenv.wrap(["ros2", "launch", "foo"], project_root=tmp_path)
    assert wrapped[:2] == ["bash", "-c"]
    assert str(fake_ros_sourced["setup"]) in wrapped[2]
    assert str(install_setup) in wrapped[2]

    # Source hint includes both
    hint = rosenv.source_hint(project_root=tmp_path)
    assert str(fake_ros_sourced["setup"]) in hint
    assert str(install_setup) in hint


def test_cli_build_help():
    runner = CliRunner()
    result = runner.invoke(app, ["build", "--help"])
    assert result.exit_code == 0
    assert "--packages-select" in result.output or "-p" in result.output
    assert "--jobs" in result.output or "-j" in result.output
    assert "--symlink-install" in result.output


def test_cli_build_missing_src(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "caasi.yaml").write_text("schema: 1\nname: test\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(app, ["build"])
    assert result.exit_code != 0
    assert "not found" in result.output or "Error" in result.output
