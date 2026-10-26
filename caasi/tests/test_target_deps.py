"""`caasi target deps` — operation-aware dependency inspection.

Facts are injected rather than gathered, so every state is asserted without a robot. The
real-target run is separate evidence; these tests are the contract.

The safety property matters as much as the reporting: inspection must be read-only, so one
test asserts the probe contains no mutating command.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from caasi.cli.main import app
from caasi.core import deps
from caasi.core.deps import _Facts
from caasi.core.targets import Target

runner = CliRunner()


def _facts(os_name="Ubuntu 24.04.5 LTS", distros=("jazzy",),
           executables=None, packages=None, families=None, error="") -> _Facts:
    return _Facts(
        os=os_name,
        distros=list(distros),
        executables=dict(executables or {}),
        packages=dict(packages or {}),
        families=dict(families or {}),
        error=error,
    )


@pytest.fixture
def inject(monkeypatch):
    """Make inspect_target_deps see fixed facts instead of running anything."""
    def _apply(facts):
        monkeypatch.setattr(deps, "gather_facts", lambda *a, **k: facts)
    return _apply


T = Target(name="probe", transport="ssh", host="h", user="u")


# ------------------------------------------------------------- happy path

def test_compatible_target_reports_ok(inject):
    inject(_facts(executables={"colcon": "/usr/bin/colcon", "ros2": "/opt/ros/jazzy/bin/ros2"},
                  packages={"joint_state_publisher": "/opt/ros/jazzy/share/joint_state_publisher",
                            "robot_state_publisher": "/opt/ros/jazzy/share/robot_state_publisher"}))
    report = deps.inspect_target_deps(
        T, scope="bringup", requires={"ros2": {"version": "jazzy"}}
    )
    assert report.reachable and report.ok
    states = {r.dependency.name: r.state for r in report.results}
    assert states["ros2"] == deps.STATE_INSTALLED
    assert states["joint_state_publisher"] == deps.STATE_INSTALLED
    assert report.counts()[deps.STATE_MISSING] == 0


# ------------------------------------------------------------- missing cases

def test_missing_required_is_reported_with_remediation(inject):
    inject(_facts(packages={}))
    report = deps.inspect_target_deps(T, scope="bringup", requires={})
    missing = [r for r in report.results if r.state == deps.STATE_MISSING]
    assert missing, "required bringup packages should be missing here"
    r = missing[0]
    assert r.dependency.required
    assert r.install_command and r.install_command.startswith("sudo apt install -y ros-jazzy-")
    assert r.install_verified, "distro + Ubuntu means the command is verified"
    assert not report.ok


def test_missing_optional_does_not_fail_the_operation(inject):
    """Simulation-only requirements must not block a hardware bringup."""
    inject(_facts(executables={"colcon": "/usr/bin/colcon"},
                  packages={"joint_state_publisher": "/x", "robot_state_publisher": "/y"}))
    report = deps.inspect_target_deps(
        T, scope="bringup", requires={"isaac_sim": {"version": ">=5.0"}}
    )
    isaac = next(r for r in report.results if r.dependency.name == "isaac_sim")
    assert not isaac.dependency.required
    assert isaac.state == deps.STATE_OPTIONAL_ABSENT
    assert report.ok, "an absent optional dependency must not fail bringup"


def test_simulation_scope_makes_simulation_dependencies_required(inject):
    inject(_facts(executables={"colcon": "/usr/bin/colcon"}))
    report = deps.inspect_target_deps(T, scope="sim", requires={})
    names = {r.dependency.name: r for r in report.results}
    assert names["ros_gz_sim"].dependency.required
    assert names["ros_gz_sim"].state == deps.STATE_MISSING
    assert not report.ok


def test_incompatible_ros_distribution_is_distinguished(inject):
    """A named distro is an identity, not a version range: jazzy vs humble is a mismatch."""
    inject(_facts(distros=("humble",)))
    report = deps.inspect_target_deps(
        T, scope="project", requires={"ros2": {"version": "jazzy"}}
    )
    ros = next(r for r in report.results if r.dependency.name == "ros2")
    assert ros.state == deps.STATE_INCOMPATIBLE
    assert "humble" in ros.note and "jazzy" in ros.note
    assert not report.ok


def test_target_without_ros_reports_missing_not_installed(inject):
    inject(_facts(distros=(), executables={"ros2": ""}))
    report = deps.inspect_target_deps(
        T, scope="project", requires={"ros2": {"version": "jazzy"}}
    )
    ros = next(r for r in report.results if r.dependency.name == "ros2")
    assert ros.state == deps.STATE_MISSING
    assert report.ros_distro is None
    assert not report.ok


def test_metapackage_satisfied_by_components_is_not_missing(inject):
    """nav2 is usually not installed itself while its components are."""
    inject(_facts(packages={}, families={"nav2": ["nav2_costmap_2d", "nav2_util"]}))
    report = deps.inspect_target_deps(T, scope="project", requires={"nav2": {}})
    nav = next(r for r in report.results if r.dependency.name == "nav2")
    assert nav.state == deps.STATE_INSTALLED
    assert "component" in nav.note


# ------------------------------------------------------- inspection failures

def test_failed_inspection_reports_unknown_not_installed(inject):
    inject(_facts(error="ssh: connection timed out"))
    report = deps.inspect_target_deps(T, scope="bringup", requires={"ros2": {"version": "jazzy"}})
    assert not report.reachable
    assert report.error
    assert all(r.state == deps.STATE_UNKNOWN for r in report.results)
    assert not report.ok, "a failed inspection must never read as all-installed"


def test_unknown_scope_is_rejected():
    with pytest.raises(ValueError):
        deps.inspect_target_deps(T, scope="nonsense", requires={})


# ------------------------------------------------------------- safety guard

def test_probe_is_read_only():
    """No install/remove/update verb may appear in the inspection command."""
    script = deps._probe_script(["joint_state_publisher"], ["colcon", "ros2"])
    lowered = script.lower()
    for verb in ("apt install", "apt-get install", "apt remove", "apt purge",
                 "apt update", "dpkg -i", "rm -", "reboot", "systemctl start"):
        assert verb not in lowered, f"inspection must not run '{verb}': {script}"
    # and it must actually gather the facts we claim to report
    assert "CAASI_OS=" in script and "CAASI_PKG:" in script and "CAASI_EXE:" in script


def test_install_command_is_not_verified_when_environment_is_unknown(inject):
    """No distro means no derivable package name, so nothing is claimed as verified."""
    inject(_facts(os_name="SomeLinux 1.0", distros=(), packages={}))
    report = deps.inspect_target_deps(T, scope="bringup", requires={})
    for r in report.results:
        assert r.install_verified is False


# ---------------------------------------------------------------------- CLI

def test_cli_json_exit_zero_when_compatible(inject, monkeypatch):
    inject(_facts(executables={"colcon": "/usr/bin/colcon"},
                  packages={"joint_state_publisher": "/x", "robot_state_publisher": "/y",
                            "ros2": "/opt/ros/jazzy/bin/ros2"}))
    result = runner.invoke(app, ["target", "deps", "local", "--for", "bringup", "--json"])
    assert result.exit_code == 0
    assert '"ok": true' in result.stdout


def test_cli_exit_one_when_required_missing(inject):
    inject(_facts(packages={}, executables={}))
    result = runner.invoke(app, ["target", "deps", "local", "--for", "sim"])
    assert result.exit_code == 1


def test_cli_exit_one_when_inspection_failed(inject):
    inject(_facts(error="unreachable"))
    result = runner.invoke(app, ["target", "deps", "local", "--for", "project"])
    assert result.exit_code == 1
