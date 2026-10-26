"""Tests for the `caasi ros` commands (fake ros2 distro, no real ROS needed)."""

from __future__ import annotations

import json
import pathlib
import textwrap

import pytest
import yaml

from caasi.cli.main import app
from caasi.core import ros as ros_core

FAKE_ROS2 = textwrap.dedent(
    """\
    #!/usr/bin/env bash
    # Fake ros2 CLI used by the test-suite.
    cmd="$1"; shift || true
    case "$cmd" in
      topic)
        sub="$1"; shift || true
        case "$sub" in
          list) echo "/scan"; echo "/tf";;
          info)
            if [ "$1" = "/scan" ]; then
              echo "Type: sensor_msgs/msg/LaserScan"
              echo "Publisher count: 1"
            else
              echo "Unknown topic" >&2; exit 1
            fi;;
          echo) echo "echo $*";;
        esac;;
      node)
        sub="$1"; shift || true
        case "$sub" in
          list) echo "/talker"; echo "/move_group"; echo "/bt_navigator"; echo "/controller_manager";;
          info)
            if [ "$1" = "/talker" ]; then
              echo "Subscribers:"
              echo "  /chat: std_msgs/msg/String"
            else
              echo "Unknown node" >&2; exit 1
            fi;;
        esac;;
      service)
        sub="$1"; shift || true
        case "$sub" in
          list) echo "/talker/get_parameters";;
          info)
            if [ "$1" = "/talker/get_parameters" ]; then
              echo "Service Clients:"
              echo "  /talker: rcl_interfaces/srv/ListParameters"
            else
              echo "Unknown service" >&2; exit 1
            fi;;
          call) echo "calling $*";;
        esac;;
      action)
        sub="$1"; shift || true
        [ "$sub" = "list" ] && echo "/navigate_to_position";;
      pkg)
        sub="$1"; shift || true
        if [ "$sub" = "prefix" ]; then
          case "$1" in
            nav2_bringup|moveit_ros_move_group|ros2controlcli) echo "{prefix}";;
            *) echo "Package not found" >&2; exit 1;;
          esac
        fi;;
      launch) echo "launch $*";;
      control)
        sub="$1"; shift || true
        if [ "$sub" = "list_controllers" ]; then
          echo "joint_state_broadcaster joint_state_broadcaster/JointStateBroadcaster active"
          echo "diff_drive_controller diff_drive_controllers/DiffDriveController active"
        fi;;
      doctor) echo "All 5 checks passed";;
      *) echo "unknown command" >&2; exit 1;;
    esac
    """
)

NAV_PARAMS = textwrap.dedent(
    """\
    amcl:
      ros__parameters:
        robot_model_type: nav2_amcl::DifferentialMotionModel
    bt_navigator:
      ros__parameters:
        global_frame: map
    planner_server:
      ros__parameters:
        planner_plugins: ["GridBased"]
    """
)


@pytest.fixture
def fake_ros(tmp_path, monkeypatch):
    """A fake ROS distro tree with a scripted ros2 binary."""
    root = tmp_path / "ros-root"
    distro = root / "testing"
    (distro / "bin").mkdir(parents=True)
    (distro / "setup.bash").write_text("", encoding="utf-8")

    prefix = tmp_path / "prefix"
    params_dir = prefix / "share" / "nav2_bringup" / "params"
    params_dir.mkdir(parents=True)
    (params_dir / "nav2_params.yaml").write_text(NAV_PARAMS, encoding="utf-8")

    script = distro / "bin" / "ros2"
    script.write_text(FAKE_ROS2.format(prefix=prefix), encoding="utf-8")
    script.chmod(0o755)

    monkeypatch.setattr(ros_core, "ROS_ROOT", root)
    return {"root": root, "distro": distro, "prefix": prefix, "binary": str(script)}


def configure_runs(tmp_path, monkeypatch):
    cfg_file = tmp_path / "caasi-test.yaml"
    cfg_file.write_text(
        yaml.safe_dump({"paths": {"runs": str(tmp_path / "runs")}}), encoding="utf-8"
    )
    monkeypatch.setenv("CAASI_CONFIG", str(cfg_file))
    return tmp_path / "runs"


def wait_for_run(runs_base, timeout=10.0):
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if runs_base.is_dir():
            for run_dir in runs_base.glob("*"):
                if (run_dir / "exit_code").is_file():
                    return run_dir
        time.sleep(0.05)
    raise AssertionError("run did not finish in time")


def no_ros2(monkeypatch, tmp_path):
    """Make ros2 undiscoverable (empty ROS_ROOT, no binary on PATH)."""
    empty = tmp_path / "empty-ros"
    empty.mkdir()
    monkeypatch.setattr(ros_core, "ROS_ROOT", empty)
    monkeypatch.setattr(ros_core.shell, "which", lambda name: None)


def test_ros_status(runner, fake_ros):
    result = runner.invoke(app, ["ros", "status", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["available"] is True
    assert data["distro"] == "testing"
    assert data["binary"] == fake_ros["binary"]
    assert data["topics"] == 2

    result = runner.invoke(app, ["ros", "status"])
    assert result.exit_code == 0
    assert "testing" in result.output


def test_ros_status_without_ros2(runner, tmp_path, monkeypatch):
    no_ros2(monkeypatch, tmp_path)
    result = runner.invoke(app, ["ros", "status", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["available"] is False
    assert data["distro"] is None


def test_ros_doctor(runner, fake_ros):
    result = runner.invoke(app, ["ros", "doctor"])
    assert result.exit_code == 0
    assert "All 5 checks passed" in result.output

    result = runner.invoke(app, ["--json", "ros", "doctor"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["returncode"] == 0
    assert "checks passed" in data["output"]


def test_ros_list_kinds(runner, fake_ros):
    result = runner.invoke(app, ["ros", "list", "topics"])
    assert result.exit_code == 0
    assert "/scan" in result.output and "/tf" in result.output

    result = runner.invoke(app, ["ros", "list", "nodes", "--json"])
    data = json.loads(result.output)
    assert "/talker" in data and "/move_group" in data

    result = runner.invoke(app, ["ros", "list", "services"])
    assert "/talker/get_parameters" in result.output

    result = runner.invoke(app, ["ros", "list", "actions"])
    assert "/navigate_to_position" in result.output


def test_ros_list_bad_kind(runner, fake_ros):
    result = runner.invoke(app, ["ros", "list", "params"])
    assert result.exit_code == 1
    assert "Unknown resource kind" in result.output


def test_ros_launch_dry_run(runner, fake_ros, tmp_path):
    launch_file = tmp_path / "demo.launch.py"
    launch_file.write_text("# launch", encoding="utf-8")
    result = runner.invoke(
        app, ["ros", "launch", str(launch_file), "--dry-run", "use_sim_time:=true"]
    )
    assert result.exit_code == 0
    assert "Dry run" in result.output
    assert "launch" in result.output and "use_sim_time:=true" in result.output

    result = runner.invoke(app, ["ros", "launch", str(tmp_path / "nope.launch.py")])
    assert result.exit_code == 1
    assert "No such launch file" in result.output


def test_ros_launch_tracked_run(runner, fake_ros, tmp_path, monkeypatch):
    runs_base = configure_runs(tmp_path, monkeypatch)
    result = runner.invoke(
        app,
        ["ros", "launch", "demo.launch.py", "--package", "demo_bringup", "--json"],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["kind"] == "ros" and data["backend"] == "ros"

    run_dir = wait_for_run(runs_base)
    assert (run_dir / "exit_code").read_text().strip() == "0"
    assert "launch demo_bringup demo.launch.py" in (run_dir / "stdout.log").read_text()


def test_ros_topic(runner, fake_ros):
    result = runner.invoke(app, ["ros", "topic", "/scan"])
    assert result.exit_code == 0
    assert "sensor_msgs/msg/LaserScan" in result.output

    result = runner.invoke(app, ["ros", "topic", "/nope", "--json"])
    assert result.exit_code == 1
    assert "Topic '/nope' not found" in result.output

    result = runner.invoke(app, ["ros", "topic", "/scan", "--json"])
    data = json.loads(result.output)
    assert data["topic"] == "/scan"


def test_ros_topic_echo_tracked_run(runner, fake_ros, tmp_path, monkeypatch):
    runs_base = configure_runs(tmp_path, monkeypatch)
    result = runner.invoke(app, ["ros", "topic", "/scan", "--echo"])
    assert result.exit_code == 0, result.output
    assert "Started run" in result.output

    run_dir = wait_for_run(runs_base)
    assert (run_dir / "exit_code").read_text().strip() == "0"
    manifest = yaml.safe_load((run_dir / "manifest.yaml").read_text())
    assert manifest["name"] == "echo-scan"


def test_ros_node(runner, fake_ros):
    result = runner.invoke(app, ["ros", "node", "/talker"])
    assert result.exit_code == 0
    assert "Subscribers:" in result.output

    result = runner.invoke(app, ["ros", "node", "/ghost"])
    assert result.exit_code == 1
    assert "Node '/ghost' not found" in result.output


def test_ros_service_list(runner, fake_ros):
    result = runner.invoke(app, ["ros", "service", "list"])
    assert result.exit_code == 0
    assert "/talker/get_parameters" in result.output

    result = runner.invoke(app, ["ros", "service", "list", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == ["/talker/get_parameters"]


def test_ros_service_info(runner, fake_ros):
    result = runner.invoke(app, ["ros", "service", "info", "/talker/get_parameters"])
    assert result.exit_code == 0
    assert "Service Clients:" in result.output

    result = runner.invoke(app, ["ros", "service", "info", "/talker/get_parameters", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["service"] == "/talker/get_parameters"
    assert "Service Clients:" in data["info"]

    result = runner.invoke(app, ["ros", "service", "info", "/ghost"])
    assert result.exit_code == 1
    assert "Service '/ghost' not found" in result.output


def test_ros_service_call(runner, fake_ros):
    result = runner.invoke(
        app,
        [
            "ros", "service", "call",
            "/talker/get_parameters",
            "rcl_interfaces/srv/ListParameters",
            "{name: x}",
        ],
    )
    assert result.exit_code == 0, result.output
    flat = " ".join(result.output.split())
    assert "calling /talker/get_parameters rcl_interfaces/srv/ListParameters {name: x}" in flat

    result = runner.invoke(
        app,
        [
            "ros", "service", "call",
            "/talker/get_parameters",
            "rcl_interfaces/srv/ListParameters",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["service"] == "/talker/get_parameters"
    assert data["type"] == "rcl_interfaces/srv/ListParameters"
    assert data["returncode"] == 0
    assert "calling" in data["stdout"]


def test_ros_service_requires_ros2(runner, tmp_path, monkeypatch):
    no_ros2(monkeypatch, tmp_path)
    result = runner.invoke(app, ["ros", "service", "list"])
    assert result.exit_code == 1
    assert "ros2 CLI not found" in result.output


def test_ros_graph(runner, fake_ros):
    result = runner.invoke(app, ["ros", "graph"])
    assert result.exit_code == 0
    assert "/talker" in result.output and "/scan" in result.output

    result = runner.invoke(app, ["ros", "graph", "--json"])
    data = json.loads(result.output)
    assert "/move_group" in data["nodes"]
    assert "/tf" in data["topics"]


def test_ros_requires_ros2(runner, tmp_path, monkeypatch):
    no_ros2(monkeypatch, tmp_path)
    for args in (["ros", "list", "topics"], ["ros", "graph"], ["ros", "topic", "/scan"]):
        result = runner.invoke(app, args)
        assert result.exit_code == 1
        assert "ros2 CLI not found" in result.output


# ---------------------------------------------------------------------------
# Remote target queries (--target)
#
# E2 makes the existing local query surface target-aware. These tests mock the
# SSH transport so no network is required; the behaviour under test is caasi's
# own: how it builds the remote invocation, and how it reports the outcome.
# ---------------------------------------------------------------------------

from caasi.core.targets import Target  # noqa: E402


@pytest.fixture
def remote_target(tmp_path, monkeypatch):
    """A configured SSH target, so --target resolves without network access."""
    cfg_file = tmp_path / "caasi-remote.yaml"
    cfg_file.write_text(
        yaml.safe_dump({
            "paths": {"runs": str(tmp_path / "runs")},
            "targets": {
                "probe-host": {
                    "transport": "ssh", "host": "probe.invalid", "user": "u",
                    "ssh_timeout": 5.0,
                }
            },
        }), encoding="utf-8",
    )
    monkeypatch.setenv("CAASI_CONFIG", str(cfg_file))
    return "probe-host"


def test_remote_query_builds_sourced_ssh_invocation(monkeypatch):
    """The remote call sources ROS then delegates to the target's own ros2."""
    seen: dict = {}

    def fake_run_cmd(args, timeout=None, env=None):
        seen["args"] = args
        seen["timeout"] = timeout
        from caasi.utils.shell import ShellResult
        return ShellResult(0, "/scan\n/tf\n", "")

    monkeypatch.setattr(ros_core.shell, "run_cmd", fake_run_cmd)
    target = Target(name="probe-host", transport="ssh", host="probe.invalid",
                    user="u", ssh_timeout=5.0)

    result = ros_core.remote_ros2(target, ["topic", "list"],
                                  ros_setup="/opt/ros/jazzy/setup.bash")
    assert result.ok
    joined = " ".join(seen["args"])
    # ssh transport
    assert "ssh" in seen["args"][0]
    assert "u@probe.invalid" in joined
    # delegates to the target's own ros2 rather than reimplementing anything: the
    # snippet execs the argv passed after "--", whose first element is ros2
    assert 'exec "$@"' in joined
    assert "ros2 topic list" in joined
    # sources the underlay so a non-interactive shell can find it
    assert "/opt/ros/jazzy/setup.bash" in joined


def test_remote_query_reports_missing_ros2_as_127(monkeypatch):
    """A target without ros2 produces the 127 + marker the CLI maps to a clear error."""
    def fake_run_cmd(args, timeout=None, env=None):
        from caasi.utils.shell import ShellResult
        return ShellResult(127, "", "CAASI_NO_ROS2\n")

    monkeypatch.setattr(ros_core.shell, "run_cmd", fake_run_cmd)
    target = Target(name="probe-host", transport="ssh", host="probe.invalid")
    result = ros_core.remote_ros2(target, ["topic", "list"])
    assert result.returncode == 127
    assert "CAASI_NO_ROS2" in result.stderr


def test_remote_query_passes_domain_id(monkeypatch):
    """A non-default ROS_DOMAIN_ID must reach the target's ros2 invocation."""
    seen: dict = {}

    def fake_run_cmd(args, timeout=None, env=None):
        seen["args"] = args
        from caasi.utils.shell import ShellResult
        return ShellResult(0, "/talker\n", "")

    monkeypatch.setattr(ros_core.shell, "run_cmd", fake_run_cmd)
    target = Target(name="probe-host", transport="ssh", host="probe.invalid")
    ros_core.remote_ros2(target, ["node", "list"], domain_id=42)
    assert "ROS_DOMAIN_ID=42" in " ".join(seen["args"])


def test_remote_query_unreachable_is_negative_returncode(monkeypatch):
    """A transport failure is rc -1, which the CLI reports as unreachable."""
    def fake_run_cmd(args, timeout=None, env=None):
        from caasi.utils.shell import ShellResult
        return ShellResult(-1, "", "timed out after 5.0s")

    monkeypatch.setattr(ros_core.shell, "run_cmd", fake_run_cmd)
    target = Target(name="probe-host", transport="ssh", host="probe.invalid")
    result = ros_core.remote_ros2(target, ["topic", "list"])
    assert result.returncode == -1


def test_cli_unknown_target_fails_without_querying_local(runner, monkeypatch):
    """A --target typo must not silently fall back to the workstation."""
    monkeypatch.setenv("CAASI_CONFIG", str(pathlib.Path("/nonexistent-cfg.yaml")))
    called: list = []
    monkeypatch.setattr(ros_core, "run_ros2",
                        lambda *a, **k: called.append(a) or _ok())
    result = runner.invoke(app, ["ros", "list", "topics", "--target", "typo-name"])
    assert result.exit_code == 1
    assert called == [], "local ros2 was invoked despite an unknown target"


def _ok():
    from caasi.utils.shell import ShellResult
    return ShellResult(0, "", "")


def test_cli_local_path_unchanged_without_target(runner, fake_ros):
    """Omitting --target keeps the original local behaviour exactly."""
    result = runner.invoke(app, ["ros", "list", "topics"])
    assert result.exit_code == 0
    assert "/scan" in result.output and "/tf" in result.output


def test_remote_status_json_includes_target(runner, remote_target, monkeypatch):
    """Remote status is labelled with the target it came from."""
    monkeypatch.setattr(ros_core, "remote_ros_environment",
                        lambda t: {"available": True, "distro": "jazzy",
                                   "root": "/opt/ros/jazzy",
                                   "binary": "/opt/ros/jazzy/bin/ros2",
                                   "rmw": None})
    monkeypatch.setattr(ros_core, "remote_ros2_lines", lambda *a, **k: ["/chatter"])
    result = runner.invoke(app, ["ros", "status", "--target", remote_target, "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["target"] == remote_target
    assert data["distro"] == "jazzy"
    assert data["topics"] == 1


def test_remote_status_unreachable_reports_error(runner, remote_target, monkeypatch):
    monkeypatch.setattr(ros_core, "remote_ros_environment",
                        lambda t: {"available": False, "error": "Connection timed out"})
    result = runner.invoke(app, ["ros", "status", "--target", remote_target])
    # An unreachable target is an error, not an empty success.
    assert result.exit_code == 1
    assert "unreachable" in result.output.lower()
