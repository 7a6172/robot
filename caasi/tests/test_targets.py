"""Tests for execution target model, capability discovery, and CLI commands (Phase 7 Stage A)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from caasi.cli.main import app
from caasi.core.config import Config
from caasi.core.targets import (
    Target,
    TargetEnvironment,
    TargetInspection,
    TargetResources,
    check_socket_reachable,
    detect_mismatches,
    discover_target,
    find_target,
    list_targets,
    target_ssh_prefix,
)

runner = CliRunner()


def test_target_defaults_and_serialization() -> None:
    t = Target(name="local", transport="local", tags=["workstation"])
    d = t.to_dict()
    assert d["name"] == "local"
    assert d["transport"] == "local"
    assert d["tags"] == ["workstation"]
    assert d["declared_capabilities"] == []
    assert d["declared_resources"] == {}


def test_target_list_includes_default_local() -> None:
    cfg = Config({}, [])
    targets = list_targets(cfg)
    names = [t.name for t in targets]
    assert "local" in names
    local = [t for t in targets if t.name == "local"][0]
    assert local.transport == "local"
    assert "local" in local.tags


def test_target_list_loads_from_config() -> None:
    cfg = Config({}, [])
    cfg.set(
        "targets",
        {
            "robot-orin": {
                "transport": "ssh",
                "host": "192.168.1.100",
                "user": "robot",
                "port": 2222,
                "deployment_root": "/opt/robot",
                "tags": ["robot", "orin"],
                "capabilities": ["ros2", "lidar"],
                "resources": {"arch": "aarch64", "gpu": True},
            }
        },
    )
    targets = list_targets(cfg)
    names = [t.name for t in targets]
    assert "local" in names
    assert "robot-orin" in names
    orin = [t for t in targets if t.name == "robot-orin"][0]
    assert orin.transport == "ssh"
    assert orin.host == "192.168.1.100"
    assert orin.port == 2222
    assert orin.deployment_root == "/opt/robot"
    assert orin.declared_capabilities == ["ros2", "lidar"]
    assert orin.declared_resources["arch"] == "aarch64"


def test_target_list_imports_legacy_remotes() -> None:
    cfg = Config({}, [])
    cfg.set(
        "remotes",
        {
            "gpu-box": {
                "host": "10.0.0.5",
                "user": "cuda_user",
                "port": 22,
                "path": "/home/cuda_user/experiments",
            }
        },
    )
    targets = list_targets(cfg)
    names = [t.name for t in targets]
    assert "gpu-box" in names
    gpu_box = [t for t in targets if t.name == "gpu-box"][0]
    assert gpu_box.transport == "ssh"
    assert gpu_box.host == "10.0.0.5"
    assert gpu_box.deployment_root == "/home/cuda_user/experiments"
    assert "remote" in gpu_box.tags


def test_find_target() -> None:
    cfg = Config({}, [])
    cfg.set("targets.edge-node-1.host", "192.168.1.10")
    assert find_target(cfg, "local") is not None
    assert find_target(cfg, "local").name == "local"
    assert find_target(cfg, "edge-node-1") is not None
    # Prefix match
    assert find_target(cfg, "edge-") is not None
    assert find_target(cfg, "edge-").name == "edge-node-1"
    assert find_target(cfg, "nonexistent") is None


def test_detect_mismatches_all_matching() -> None:
    target = Target(
        name="jetson",
        declared_capabilities=["ros2", "cuda"],
        declared_resources={"arch": "aarch64", "gpu": True, "ros_distro": "jazzy"},
    )
    res = TargetResources(gpus=[{"name": "Orin GPU"}])
    env = TargetEnvironment(arch="aarch64", cuda_version="12.6", ros_distro="jazzy")
    disc_caps = ["ros2", "ros2:jazzy", "cuda", "gpu"]

    mismatches = detect_mismatches(target, res, env, disc_caps)
    assert mismatches == []


def test_detect_mismatches_discrepancies() -> None:
    target = Target(
        name="jetson",
        declared_capabilities=["ros2", "lidar"],
        declared_resources={"arch": "aarch64", "gpu": True, "cuda": "12.6", "ros_distro": "jazzy"},
    )
    res = TargetResources(gpus=[])  # No GPU
    env = TargetEnvironment(arch="x86_64", cuda_version=None, ros_distro="humble")
    disc_caps = ["ros2", "ros2:humble"]

    mismatches = detect_mismatches(target, res, env, disc_caps)
    assert any("lidar" in m for m in mismatches)
    assert any("Architecture mismatch" in m for m in mismatches)
    assert any("GPU mismatch" in m for m in mismatches)
    assert any("CUDA mismatch" in m for m in mismatches)
    assert any("ROS distro mismatch" in m for m in mismatches)


def test_discover_local_target() -> None:
    target = Target(name="local", transport="local")
    cfg = Config({}, [])
    insp = discover_target(target, cfg)
    assert insp.reachable is True
    assert insp.status == "online"
    assert insp.latency_ms is not None
    assert insp.resources is not None
    assert insp.environment is not None
    assert insp.environment.arch is not None
    assert isinstance(insp.discovered_capabilities, list)


def test_check_socket_unreachable() -> None:
    # Reserved test-net IP that refuses or drops packets quickly
    reachable, lat = check_socket_reachable("192.0.2.1", port=2222, timeout=0.1)
    assert reachable is False
    assert lat is None


def test_discover_remote_unreachable() -> None:
    target = Target(name="offline-box", transport="ssh", host="192.0.2.1", port=2222)
    insp = discover_target(target, timeout=0.2)
    assert insp.reachable is False
    assert insp.status == "unreachable"
    assert "Could not connect" in str(insp.error)


def test_discover_remote_success_mocked() -> None:
    target = Target(
        name="remote-box",
        transport="ssh",
        host="192.168.1.50",
        user="testuser",
        declared_capabilities=["ros2"],
    )
    fake_json = json.dumps({
        "system": {"os": "Linux", "kernel": "6.8.0", "arch": "x86_64", "hostname": "remote-node"},
        "hardware": {"cpu_model": "AMD EPYC", "cpu_count": 16, "memory_total_kib": 32000000},
        "gpu": {"devices": [{"name": "RTX 4090", "memory_total_mib": 24576, "driver_version": "550.54"}]},
        "drivers": {"cuda": "12.4", "nvidia": "550.54"},
        "python": {"version": "3.11.2"},
        "ros": {"distro": "jazzy", "root": "/opt/ros/jazzy", "rmw": "rmw_cyclonedds_cpp"},
        "docker": {"installed": True},
    })

    with patch("caasi.core.targets.check_socket_reachable", return_value=(True, 2.5)):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=fake_json, stderr="")
            insp = discover_target(target, timeout=1.0)

    assert insp.reachable is True
    assert insp.status == "online"
    assert insp.latency_ms == 2.5
    assert insp.resources.cpu_count == 16
    assert len(insp.resources.gpus) == 1
    assert insp.environment.ros_distro == "jazzy"
    assert "ros2" in insp.discovered_capabilities
    assert "cuda" in insp.discovered_capabilities
    assert insp.mismatches == []


def test_target_ssh_prefix() -> None:
    t = Target(name="box", transport="ssh", host="myhost", user="user1", port=2222, identity="~/.ssh/id")
    prefix = target_ssh_prefix(t)
    assert prefix[0] == "ssh"
    assert "-p" in prefix
    assert "2222" in prefix
    assert "-i" in prefix
    assert "user1@myhost" in prefix


def test_target_ssh_prefix_defaults_to_three_second_connect_timeout() -> None:
    """A target that does not configure ssh_timeout keeps the previous budget."""
    t = Target(name="box", transport="ssh", host="myhost")
    assert t.ssh_timeout == 3.0
    assert "ConnectTimeout=3" in target_ssh_prefix(t)


def test_target_ssh_prefix_honours_slow_link_budget() -> None:
    """A relayed/VPN target can raise its SSH budget in configuration.

    Phase 7 Stage D exposed this against a real machine reached over a Tailscale
    relay where the SSH round-trip was ~5-6s: the fixed 3s budget made the target
    permanently unreachable to caasi.
    """
    t = Target(name="slow", transport="ssh", host="remote", ssh_timeout=20.0)
    assert "ConnectTimeout=20" in target_ssh_prefix(t)


def test_ssh_timeout_parsed_from_config() -> None:
    cfg = Config({}, [])
    cfg.set(
        "targets",
        {
            "slow-node": {"transport": "ssh", "host": "remote", "ssh_timeout": 15.5},
            "plain-node": {"transport": "ssh", "host": "remote2"},
        },
    )
    targets = {t.name: t for t in list_targets(cfg)}
    assert targets["slow-node"].ssh_timeout == 15.5
    assert targets["plain-node"].ssh_timeout == 3.0  # default preserved


def test_discover_target_uses_target_timeout_when_none_given() -> None:
    """Without an explicit timeout, discovery budgets from the target itself."""
    seen: dict[str, float] = {}

    def fake_run(cmd, **kwargs):
        seen["timeout"] = kwargs.get("timeout")
        raise OSError("stop here - only the timeout value is under test")

    t = Target(name="slow", transport="ssh", host="remote", ssh_timeout=12.0)
    with (
        patch("caasi.core.targets.check_socket_reachable", return_value=(True, 1.0)),
        patch("caasi.core.targets.subprocess.run", side_effect=fake_run),
    ):
        discover_target(t)
    assert seen["timeout"] == 12.0


def test_discover_target_explicit_timeout_still_wins() -> None:
    """An explicit timeout overrides the target's configured budget."""
    seen: dict[str, float] = {}

    def fake_run(cmd, **kwargs):
        seen["timeout"] = kwargs.get("timeout")
        raise OSError("stop here")

    t = Target(name="slow", transport="ssh", host="remote", ssh_timeout=12.0)
    with (
        patch("caasi.core.targets.check_socket_reachable", return_value=(True, 1.0)),
        patch("caasi.core.targets.subprocess.run", side_effect=fake_run),
    ):
        discover_target(t, timeout=4.0)
    assert seen["timeout"] == 4.0


# CLI command tests


def test_cli_target_list() -> None:
    res = runner.invoke(app, ["target", "list"])
    assert res.exit_code == 0
    assert "local" in res.output


def test_cli_target_list_json() -> None:
    res = runner.invoke(app, ["target", "list", "--json"])
    assert res.exit_code == 0
    data = json.loads(res.output)
    assert isinstance(data, list)
    assert any(t["name"] == "local" for t in data)


def test_cli_node_alias() -> None:
    res = runner.invoke(app, ["node", "list"])
    assert res.exit_code == 0
    assert "local" in res.output


def test_cli_target_inspect_local() -> None:
    res = runner.invoke(app, ["target", "inspect", "local"])
    assert res.exit_code == 0
    assert "local" in res.output
    assert "ONLINE" in res.output


def test_cli_target_inspect_json() -> None:
    res = runner.invoke(app, ["target", "inspect", "local", "--json"])
    assert res.exit_code == 0
    data = json.loads(res.output)
    assert data["target"]["name"] == "local"
    assert data["status"] == "online"
    assert "resources" in data
    assert "environment" in data


def test_cli_target_check_local() -> None:
    res = runner.invoke(app, ["target", "check", "local"])
    assert res.exit_code == 0
    assert "ONLINE" in res.output
    assert "COMPATIBLE" in res.output


def test_cli_target_check_nonexistent() -> None:
    res = runner.invoke(app, ["target", "check", "nonexistent-device"])
    assert res.exit_code == 1
    assert "No target matching 'nonexistent-device'" in res.output
