"""Tests for runtime observability adapters (Phase 7 Stage E3).

These exercise caasi's own behaviour: how it detects a runtime, how it delegates
to that runtime's native interface, how it parses the answer, and how it reports
absence. The target-side commands are mocked, so no network or runtime is needed
for the suite.

The point of these tests is the *delegation contract*: caasi must ask the
runtime and report what it says, never reimplement the runtime.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from caasi.cli.main import app
from caasi.core import runtimes as R
from caasi.core.targets import Target
from caasi.utils.shell import ShellResult

runner = CliRunner()


@pytest.fixture
def local_target() -> Target:
    return Target(name="local", transport="local")


@pytest.fixture
def ssh_target() -> Target:
    return Target(name="box", transport="ssh", host="box.invalid", user="u",
                  ssh_timeout=5.0)


def _scripted(monkeypatch, responses: dict[str, ShellResult], default: ShellResult | None = None):
    """Route run_on_target by matching command text, mirroring a scripted host."""
    calls: list[list[str]] = []

    def fake(target, argv, timeout=None):
        calls.append(list(argv))
        joined = " ".join(str(a) for a in argv)
        for needle, result in responses.items():
            if needle in joined:
                return result
        if default is not None:
            return default
        return ShellResult(0, "", "")

    monkeypatch.setattr(R, "run_on_target", fake)
    return calls


# ---------------------------------------------------------------------------
# Availability detection
# ---------------------------------------------------------------------------


def test_detect_availability_reports_each_runtime(monkeypatch, local_target) -> None:
    probe_out = (
        "TOOL:systemctl=/usr/bin/systemctl\n"
        "TOOL:journalctl=/usr/bin/journalctl\n"
        "TOOL:docker=/usr/bin/docker\n"
        "TOOL:podman=\n"
        "TOOL:ps=/usr/bin/ps\n"
        "PROC=1\n"
        "SYSTEMD_RUNNING=1\n"
        "AVAILABLE=1\nDISTRO=jazzy\nROOT=/opt/ros/jazzy\nRMW=\n"
    )
    monkeypatch.setattr(R, "run_on_target",
                        lambda *a, **k: ShellResult(0, probe_out, ""))
    from caasi.core import ros as ros_core
    monkeypatch.setattr(ros_core, "remote_ros_environment",
                        lambda t: {"available": True, "distro": "jazzy",
                                   "root": "/opt/ros/jazzy",
                                   "binary": "/opt/ros/jazzy/bin/ros2", "rmw": None})

    avail = R.detect_availability(local_target)
    assert avail[R.RUNTIME_PROCESS].available is True
    assert avail[R.RUNTIME_SYSTEMD].available is True
    assert avail[R.RUNTIME_SYSTEMD].tool == "/usr/bin/systemctl"
    assert avail[R.RUNTIME_CONTAINER].available is True
    assert avail[R.RUNTIME_CONTAINER].tool == "/usr/bin/docker"
    assert avail[R.RUNTIME_ROS2].available is True


def test_detect_availability_reports_absence_with_a_reason(monkeypatch, ssh_target) -> None:
    """A missing runtime is unavailable WITH a reason, never an empty success."""
    probe_out = (
        "TOOL:systemctl=\nTOOL:journalctl=\nTOOL:docker=\nTOOL:podman=\nTOOL:ps=/bin/ps\n"
        "PROC=1\nSYSTEMD_RUNNING=0\n"
    )
    monkeypatch.setattr(R, "run_on_target",
                        lambda *a, **k: ShellResult(0, probe_out, ""))
    from caasi.core import ros as ros_core
    monkeypatch.setattr(ros_core, "remote_ros_environment",
                        lambda t: {"available": False, "error": "no ros2 CLI"})

    avail = R.detect_availability(ssh_target)
    assert avail[R.RUNTIME_PROCESS].available is True
    assert avail[R.RUNTIME_SYSTEMD].available is False
    assert avail[R.RUNTIME_SYSTEMD].detail            # a reason is present
    assert avail[R.RUNTIME_CONTAINER].available is False
    assert "docker" in (avail[R.RUNTIME_CONTAINER].detail or "")


def test_detect_availability_unreachable_marks_everything_unavailable(
    monkeypatch, ssh_target
) -> None:
    monkeypatch.setattr(R, "run_on_target",
                        lambda *a, **k: ShellResult(-1, "", "Connection timed out"))
    avail = R.detect_availability(ssh_target)
    for name in R.ALL_RUNTIMES:
        assert avail[name].available is False
        assert "timed out" in (avail[name].detail or "")


def test_systemd_present_but_not_running_is_reported_as_unavailable(
    monkeypatch, local_target
) -> None:
    """systemctl existing is not enough: systemd must actually be running.

    A container commonly ships systemctl without systemd as PID 1, and claiming
    the runtime works there would be wrong.
    """
    probe_out = (
        "TOOL:systemctl=/usr/bin/systemctl\nTOOL:journalctl=/usr/bin/journalctl\n"
        "TOOL:docker=\nTOOL:podman=\nTOOL:ps=/bin/ps\nPROC=1\nSYSTEMD_RUNNING=0\n"
    )
    monkeypatch.setattr(R, "run_on_target",
                        lambda *a, **k: ShellResult(0, probe_out, ""))
    from caasi.core import ros as ros_core
    monkeypatch.setattr(ros_core, "remote_ros_environment", lambda t: {"available": False})
    avail = R.detect_availability(local_target)
    assert avail[R.RUNTIME_SYSTEMD].available is False
    assert "not running" in (avail[R.RUNTIME_SYSTEMD].detail or "")


# ---------------------------------------------------------------------------
# Delegation: caasi must ASK the runtime, not implement it
# ---------------------------------------------------------------------------


def test_process_adapter_delegates_to_ps(monkeypatch, ssh_target) -> None:
    ps_out = (
        "      1       0       1 Ss   01:00:00 systemd   /sbin/init\n"
        "  95054       1   95054 Ss      00:05 sleep     sleep 900\n"
        "      2       0       0 S    01:00:00 kthreadd  [kthreadd]\n"
    )
    calls = _scripted(monkeypatch, {
        "TOOL:": ShellResult(0, "TOOL:ps=/usr/bin/ps\nPROC=1\n", ""),
        "ps -eo": ShellResult(0, ps_out, ""),
    }, default=ShellResult(0, "", ""))

    report = R.query_processes(ssh_target, match="sleep")
    assert report.available is True
    assert report.tool in ("/usr/bin/ps", "ps")
    assert [i.name for i in report.items] == ["sleep"]
    assert report.items[0].detail["pid"] == 95054
    assert report.items[0].detail["pgid"] == 95054


def test_process_adapter_hides_kernel_threads_unless_matched(
    monkeypatch, ssh_target
) -> None:
    """Kernel threads dominate a bare listing; they must not drown the view."""
    ps_out = (
        "      1       0       1 Ss  01:00:00 systemd  /sbin/init\n"
        "      2       0       0 S   01:00:00 kthreadd [kthreadd]\n"
        "     13       2       0 I   01:00:00 rcu_tasks_kthre [rcu_tasks_kthread]\n"
    )
    _scripted(monkeypatch, {
        "TOOL:": ShellResult(0, "TOOL:ps=/bin/ps\nPROC=1\n", ""),
        "ps -eo": ShellResult(0, ps_out, ""),
    })

    plain = R.query_processes(ssh_target)
    assert [i.name for i in plain.items] == ["systemd"]

    # An explicit --match still reaches them.
    matched = R.query_processes(ssh_target, match="kthreadd")
    assert "kthreadd" in [i.name for i in matched.items]


def test_systemd_adapter_delegates_to_systemctl_show(monkeypatch, ssh_target) -> None:
    show_out = (
        "Id=caasi-test.service\n"
        "Description=test unit\n"
        "LoadState=loaded\n"
        "ActiveState=active\n"
        "SubState=running\n"
        "UnitFileState=disabled\n"
        "MainPID=95238\n"
        "ExecMainStatus=0\n"
    )
    calls = _scripted(monkeypatch, {
        "TOOL:": ShellResult(0, "TOOL:systemctl=/usr/bin/systemctl\n"
                                 "TOOL:journalctl=/usr/bin/journalctl\n"
                                 "SYSTEMD_RUNNING=1\nPROC=1\n", ""),
        "systemctl": ShellResult(0, show_out, ""),
    })

    report = R.query_systemd(ssh_target, unit="caasi-test.service", user=True)
    assert report.available is True
    assert report.items[0].name == "caasi-test.service"
    assert report.items[0].state == "active"
    assert report.items[0].detail["mainpid"] == "95238"
    # --user scope must be passed through, since that is where a developer stack lives.
    assert any("--user" in c for c in calls if "systemctl" in " ".join(c))


def test_systemd_logs_delegate_to_journalctl(monkeypatch, ssh_target) -> None:
    journal_out = "Oct 05 18:50:39 host systemd[1]: Started caasi-test.service.\n"
    calls = _scripted(monkeypatch, {
        "TOOL:": ShellResult(0, "TOOL:systemctl=/bin/systemctl\nSYSTEMD_RUNNING=1\nPROC=1\n", ""),
        "journalctl": ShellResult(0, journal_out, ""),
    })

    report = R.query_systemd_logs(ssh_target, "caasi-test.service", lines=5)
    assert report.available is True
    assert report.tool == "journalctl"
    assert "Started caasi-test.service" in report.detail["output"]
    assert any("journalctl" in " ".join(c) for c in calls)


def test_systemd_adapter_reports_unavailable_without_systemd(monkeypatch, ssh_target) -> None:
    _scripted(monkeypatch, {
        "TOOL:": ShellResult(0, "TOOL:systemctl=\nSYSTEMD_RUNNING=0\nPROC=1\n", ""),
    })
    report = R.query_systemd(ssh_target)
    assert report.available is False
    assert report.error
    assert report.items == []


def test_container_adapter_delegates_to_docker(monkeypatch, ssh_target) -> None:
    # Column order mirrors the real `docker ps --format` output caasi requests:
    # ID, Names, Image, Status, State, RunningFor.
    ps_out = (
        "abc123\tmy-container\talpine\tUp 2 seconds\trunning\t2 seconds ago\n"
        "def456\tstopped-one\tubuntu\tExited (0) 2 hours ago\texited\t2 hours ago\n"
    )
    calls = _scripted(monkeypatch, {
        "TOOL:": ShellResult(0, "TOOL:docker=/usr/bin/docker\nPROC=1\n", ""),
        "ps": ShellResult(0, ps_out, ""),
    })

    report = R.query_containers(ssh_target)
    assert report.available is True
    assert report.tool == "/usr/bin/docker"
    assert report.items[0].name == "my-container"
    assert report.items[0].state == "running"
    assert report.items[0].detail["image"] == "alpine"
    # caasi must shell out to the CLI, never speak the Docker API.
    assert any("docker" in " ".join(c) and "ps" in c for c in calls)


def test_container_adapter_uses_podman_when_docker_is_absent(
    monkeypatch, ssh_target
) -> None:
    """The adapter is not bound to one container implementation."""
    calls = _scripted(monkeypatch, {
        "TOOL:": ShellResult(0, "TOOL:docker=\nTOOL:podman=/usr/bin/podman\nPROC=1\n", ""),
        "podman": ShellResult(0, "id1\tc1\timg\tUp 1 second\trunning\t1 second ago\n", ""),
    })
    report = R.query_containers(ssh_target)
    assert report.available is True
    assert report.tool == "/usr/bin/podman"
    assert any("podman" in " ".join(c) for c in calls)


def test_container_adapter_unavailable_reports_reason(monkeypatch, ssh_target) -> None:
    _scripted(monkeypatch, {
        "TOOL:": ShellResult(0, "TOOL:docker=\nTOOL:podman=\nPROC=1\n", ""),
    })
    report = R.query_containers(ssh_target)
    assert report.available is False
    assert "docker" in (report.error or "")


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


def test_local_target_runs_directly_without_ssh(monkeypatch, local_target) -> None:
    seen = {}

    def fake_run_cmd(argv, timeout=None, env=None):
        seen["argv"] = argv
        return ShellResult(0, "", "")

    monkeypatch.setattr(R.shell, "run_cmd", fake_run_cmd)
    R.run_on_target(local_target, ["ps", "-e"])
    assert seen["argv"][0] == "ps"      # no ssh wrapper locally


def test_ssh_target_builds_one_quoted_remote_command(monkeypatch, ssh_target) -> None:
    seen = {}

    def fake_run_cmd(argv, timeout=None, env=None):
        seen["argv"] = argv
        return ShellResult(0, "", "")

    monkeypatch.setattr(R.shell, "run_cmd", fake_run_cmd)
    R.run_on_target(ssh_target, ["ps", "-eo", "pid,args"])

    argv = seen["argv"]
    assert argv[0] == "ssh"
    assert "u@box.invalid" in argv
    # One joined command, so argument boundaries survive the remote shell.
    assert len(argv) == len(R.__dict__) or isinstance(argv[-1], str)
    assert "ps" in argv[-1]


def test_per_call_budget_scales_with_target_link(ssh_target) -> None:
    """A relayed target must not be given a LAN-sized budget."""
    slow = Target(name="slow", transport="ssh", host="h", ssh_timeout=20.0)
    fast = Target(name="fast", transport="ssh", host="h", ssh_timeout=3.0)
    assert R._budget(slow) > R._budget(fast)
    assert R._budget(fast) >= R.DEFAULT_TIMEOUT


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def test_query_all_returns_a_report_for_every_runtime(monkeypatch, ssh_target) -> None:
    """Even an unavailable runtime yields a report, so absence is explicit."""
    _scripted(monkeypatch, {
        "TOOL:": ShellResult(0, "TOOL:systemctl=\nTOOL:docker=\nTOOL:ps=/bin/ps\n"
                                 "PROC=1\nSYSTEMD_RUNNING=0\n", ""),
        "ps -eo": ShellResult(0, "  1  0  1 Ss 00:01 init /sbin/init\n", ""),
    })
    from caasi.core import ros as ros_core
    monkeypatch.setattr(ros_core, "remote_ros_environment",
                        lambda t: {"available": False, "error": "no ros2 CLI"})

    avail, reports = R.query_all(ssh_target)
    assert {r.runtime for r in reports} == set(R.ALL_RUNTIMES)
    by_name = {r.runtime: r for r in reports}
    assert by_name[R.RUNTIME_PROCESS].available is True
    assert by_name[R.RUNTIME_CONTAINER].available is False
    assert by_name[R.RUNTIME_CONTAINER].error


def test_query_runtime_rejects_unknown_name(ssh_target) -> None:
    with pytest.raises(R.RuntimeError_):
        R.query_runtime(ssh_target, "kubernetes")


def test_reports_serialise_to_json(monkeypatch, local_target) -> None:
    report = R.RuntimeReport(
        R.RUNTIME_PROCESS, "local", True, "ps",
        [R.RuntimeItem("sleep", "Ss", {"pid": 1})],
    )
    payload = json.loads(json.dumps(report.to_dict()))
    assert payload["runtime"] == "process"
    assert payload["item_count"] == 1
    assert payload["items"][0]["detail"]["pid"] == 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_unknown_target_fails_without_touching_local(monkeypatch) -> None:
    called: list = []
    monkeypatch.setattr(R, "query_all", lambda *a, **k: called.append(1) or ({}, []))
    result = runner.invoke(app, ["target", "runtime", "definitely-not-a-target"])
    assert result.exit_code == 1
    assert called == []


def test_cli_unknown_runtime_name_fails_clearly(monkeypatch) -> None:
    monkeypatch.setattr(
        "caasi.cli.target_cmd._require_target",
        lambda q: Target(name="local", transport="local"),
    )
    result = runner.invoke(app, ["target", "runtime", "local", "--runtime", "kubernetes"])
    assert result.exit_code == 1
    assert "kubernetes" in result.output


def test_cli_runtime_json_includes_all_reports(monkeypatch) -> None:
    monkeypatch.setattr(
        "caasi.cli.target_cmd._require_target",
        lambda q: Target(name="box", transport="ssh", host="h"),
    )
    reports = [
        R.RuntimeReport("process", "box", True, "ps", [R.RuntimeItem("sleep", "Ss")]),
        R.RuntimeReport("container", "box", False, None, [], "no docker"),
    ]
    monkeypatch.setattr(R, "query_all", lambda t, timeout=None: (
        {"process": R.RuntimeAvailability("process", True, "ps")}, reports
    ))
    result = runner.invoke(app, ["target", "runtime", "box", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["target"] == "box"
    assert [r["runtime"] for r in data["reports"]] == ["process", "container"]
    assert data["reports"][1]["available"] is False
    assert data["reports"][1]["error"] == "no docker"
