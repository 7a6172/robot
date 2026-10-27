"""Remote/generic execution: contract, classification and CLI behaviour.

Uses the *local* transport of the same code path, which runs the identical snippet, so
setup checks, argv handling, environment propagation and outcome classification are all
exercised without a robot or network. The SSH-specific piece (prefixing the ssh command)
is covered by asserting the snippet shape, since a real SSH dependency in the unit suite
would make CI need a target.

Outcomes are asserted, not just exit codes: "ssh returned 0" must never be mistaken for
"the remote command succeeded".
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from caasi.cli.main import app
from caasi.core import execution
from caasi.core.targets import Target

runner = CliRunner()


def _local(name: str = "local") -> Target:
    return Target(name=name, transport="local")


def _run(argv, **kw) -> execution.ExecResult:
    return execution.run_on_target(_local(), execution.ExecRequest(argv=argv, **kw))


# ------------------------------------------------------------------ happy path

def test_command_runs_and_reports_ok():
    r = _run(["echo", "hello"])
    assert r.outcome == execution.OUTCOME_OK
    assert r.returncode == 0
    assert "hello" in r.stdout
    assert r.ran and r.ok


def test_arguments_with_spaces_survive():
    r = _run(["printf", "[%s]", "a b c"])
    assert r.stdout == "[a b c]"


def test_unicode_arguments_survive():
    r = _run(["echo", "héllo — 机器人"])
    assert "héllo — 机器人" in r.stdout


def test_shell_metacharacters_in_arguments_are_not_interpreted():
    """An argument is data; it must not become a second command."""
    r = _run(["echo", "x; echo INJECTED"])
    assert "INJECTED\n" not in r.stdout.replace("x; echo INJECTED", "")
    assert "x; echo INJECTED" in r.stdout


# ------------------------------------------------------------ exit status honesty

def test_nonzero_exit_is_preserved_and_not_reported_ok():
    r = _run(["bash", "-c", "exit 3"])
    assert r.outcome == execution.OUTCOME_NONZERO
    assert r.returncode == 3
    assert not r.ok
    assert r.ran, "the command did run; it just failed"


def test_stderr_is_captured_separately():
    r = _run(["bash", "-c", "echo out; echo err >&2"])
    assert "out" in r.stdout
    assert "err" in r.stderr
    assert "err" not in r.stdout


# ------------------------------------------------------------------ environment

def test_environment_variables_are_applied():
    r = _run(["bash", "-c", 'echo "$GREETING"'], env={"GREETING": "hi there"})
    assert r.stdout.strip() == "hi there"


def test_working_directory_is_applied(tmp_path):
    r = _run(["bash", "-c", "pwd"], cwd=str(tmp_path))
    assert r.stdout.strip() == str(tmp_path)


def test_missing_working_directory_is_a_setup_failure(tmp_path):
    r = _run(["pwd"], cwd=str(tmp_path / "does-not-exist"))
    assert r.outcome == execution.OUTCOME_SETUP
    assert execution.MARK_CWD_FAILED in r.stderr


# -------------------------------------------------------- setup failure honesty

def test_missing_ros_setup_fails_loudly():
    """The old snippet silently skipped a missing setup script; that hid breakage."""
    r = _run(["ros2", "pkg", "list"], ros_setup="/nonexistent/setup.bash")
    assert r.outcome == execution.OUTCOME_SETUP
    assert execution.MARK_SETUP_FAILED in r.stderr
    assert r.returncode == execution.EXIT_SETUP_FAILED


def test_missing_overlay_fails_loudly():
    r = _run(["echo", "never"], ros_setup=None, overlay_setup="/nope/install/setup.bash")
    assert r.outcome == execution.OUTCOME_SETUP
    assert "overlay" in r.stderr


def test_setup_is_not_skipped_when_it_succeeds(tmp_path):
    """A valid setup script must actually run before the command.

    Asserted through a file the script creates rather than an exported variable: that
    keeps the check independent of the surrounding environment, so a failure here can
    only mean the script did not run.
    """
    marker = tmp_path / "marker"
    setup = tmp_path / "setup.bash"
    setup.write_text(f'touch "{marker}"\n')
    r = _run(["true"], ros_setup=None, overlay_setup=str(setup))
    assert r.outcome == execution.OUTCOME_OK
    assert marker.exists(), "the setup script was not sourced before the command"


# -------------------------------------------------------------------- timeouts

def test_timeout_is_reported_as_a_timeout_not_a_failure():
    r = _run(["sleep", "5"], timeout=0.5)
    assert r.outcome == execution.OUTCOME_TIMEOUT
    assert r.timed_out
    assert not r.ran


# ------------------------------------------------------------ snippet shape

def test_snippet_passes_arguments_positionally():
    """Only the snippet is interpreted by the shell; the argv is reached via "$@".'"""
    snippet = execution.build_snippet(execution.ExecRequest(argv=["echo", "x"]))
    assert snippet.rstrip().endswith('exec "$@"')


def test_snippet_quotes_paths_and_env_values():
    snippet = execution.build_snippet(
        execution.ExecRequest(
            argv=["true"],
            overlay_setup="/a b/setup.bash",
            env={"K": "v with space"},
        )
    )
    assert "'/a b/setup.bash'" in snippet
    assert "'v with space'" in snippet


def test_ros_setup_path_follows_the_reported_distro():
    """No assumed distro: the path comes from what the target reports."""
    t = Target(name="t", transport="local")
    assert execution.ros_setup_for(t, distro="humble") == "/opt/ros/humble/setup.bash"
    assert execution.ros_setup_for(t, distro="jazzy") == "/opt/ros/jazzy/setup.bash"


# ------------------------------------------------------------------------ CLI

def test_cli_requires_a_target():
    result = runner.invoke(app, ["exec", "--", "echo", "x"])
    assert result.exit_code != 0


def test_cli_unknown_target_fails_cleanly():
    result = runner.invoke(app, ["exec", "--target", "no-such-target", "--", "echo", "x"])
    assert result.exit_code == 1


def test_cli_rejects_malformed_env():
    result = runner.invoke(
        app, ["exec", "--target", "local", "-e", "NOEQUALS", "--", "echo", "x"]
    )
    assert result.exit_code == 1


def test_cli_runs_on_local_target_and_mirrors_exit_code():
    result = runner.invoke(app, ["exec", "--target", "local", "--", "bash", "-c", "exit 7"])
    assert result.exit_code == 7


def test_cli_json_reports_the_outcome():
    result = runner.invoke(
        app, ["exec", "--target", "local", "--json", "--", "echo", "hi"]
    )
    assert result.exit_code == 0
    assert '"outcome": "ok"' in result.stdout


def test_cli_help_documented():
    result = runner.invoke(app, ["exec", "--help"])
    assert result.exit_code == 0
    for flag in ("--target", "--cwd", "--env", "--ros", "--overlay", "--timeout"):
        assert flag in result.stdout


def test_ros_discovery_failure_is_not_reported_as_missing_ros(monkeypatch):
    """A probe that fails must not be described as a target without ROS.

    The conflation sent users to --ros-setup when the real cause was a failed query on a
    busy robot, which is exactly when the message matters.
    """
    import pytest

    from caasi.core import execution
    from caasi.core.targets import Target

    target = Target(name="r1", transport="ssh", host="h", user="u")

    def boom(*args, **kwargs):
        raise RuntimeError("probe timed out after 30.0s")

    monkeypatch.setattr(execution.targets_core, "discover_target", boom)
    with pytest.raises(execution.RosDiscoveryError, match="probe timed out"):
        execution.ros_setup_for(target)


def test_target_without_ros_still_returns_none(monkeypatch):
    """Discovering a target successfully and finding no ROS is a different answer."""
    from caasi.core import execution
    from caasi.core.targets import Target

    class Inspection:
        environment = None

    monkeypatch.setattr(
        execution.targets_core, "discover_target", lambda *a, **k: Inspection())
    target = Target(name="r1", transport="ssh", host="h", user="u")
    assert execution.ros_setup_for(target) is None
