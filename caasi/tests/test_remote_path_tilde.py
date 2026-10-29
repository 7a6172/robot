"""A leading ``~`` in a target path must be expanded on the *target*, never quoted whole.

Quoting it produced a literal ``~`` directory on the robot. That single mistake appeared in
four places and each one failed differently, which is why it is tested at each layer:

* deployment materialisation wrote into ``~/caasi/...`` -> a stray ``~`` tree
* ``build`` could not find a deployment that ``deploy`` had just verified
* a managed run started fine but ``run status`` reported ``lost``
* ``caasi exec --overlay '~/...'`` could not source a perfectly correct overlay

The helper every call site must use is ``targets.remote_path_expr``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from caasi.core import artifacts, build, execution, lifecycle, runs
from caasi.core.targets import Target, remote_path_expr


def test_remote_path_expr_expands_tilde_on_the_target():
    assert remote_path_expr("~/caasi/robots/r1") == '"$HOME"/caasi/robots/r1'
    # Anything else is quoted normally, so spaces and metacharacters stay safe.
    assert remote_path_expr("/opt/ros jazzy/setup.bash").startswith("'")


def test_remote_path_expr_leaves_no_literal_tilde():
    expr = remote_path_expr("~/caasi/robots/r1/install/setup.bash")
    assert "'~" not in expr, "a quoted tilde is exactly the bug this guards against"


@pytest.mark.parametrize("path", [
    "~/caasi/robots/r1/install/setup.bash",
    "~/caasi/robots/r1/src",
])
def test_exec_snippet_expands_tilde_in_setup_and_cwd(path):
    script = execution.build_snippet(
        execution.ExecRequest(argv=["true"], cwd=path, overlay_setup=path)
    )
    assert "'~" not in script, script
    assert '"$HOME"' in script


def test_managed_run_wrapper_expands_tilde():
    """The wrapper is what actually runs on the robot; a quoted tilde there fails late."""
    expr = remote_path_expr("~/caasi/data/runs/x/run.sh")
    assert "'~" not in expr and '"$HOME"' in expr


def test_managed_run_exit_code_is_recorded_by_a_trap():
    """A setup failure exited before the status write, so the run read as 'lost'."""
    src = Path(runs.__file__).read_text(encoding="utf-8")
    assert "trap 'echo $? > \"$RUN_DIR/exit_code\"' EXIT" in src


def test_run_status_probe_expands_tilde():
    """`run status` reported 'lost' purely because of a quoted tilde in its probe."""
    expr = remote_path_expr("~/caasi/data/runs/x/exit_code")
    assert "'~" not in expr
    assert '"$HOME"' in expr


def test_experiment_run_wrapper_expands_tilde_in_every_path():
    """`caasi run start` was the one call site still quoting '~' whole.

    The exec path was fixed, but the experiment/run-start wrapper kept ``cd "~/caasi/..."`` and
    ``mkdir -p '~/caasi/...'``, so the directory was created at a literal ``/home/<user>~/...``
    path, the wrapper cd'd into something that did not exist, exited, and every run reported
    ``lost``. Verified on the robot before and after.
    """
    src = Path(runs.__file__).read_text(encoding="utf-8")
    start = src.split("def start_target_run", 1)[1].split("\ndef ", 1)[0]
    # no path is quoted whole in the run-start path
    for pattern in (
        "cd \"{target_work_dir}\"",
        "mkdir -p '{target_run_dir}'",
        "> '{target_run_dir}/stdout.log'",
        "echo $PID > '{target_run_dir}/pid'",
    ):
        assert pattern not in start, f"quoted tilde path reintroduced: {pattern}"
    # and the helper is used for each of them
    for call in (
        "remote_path_expr(target_work_dir)",
        "remote_path_expr(target_run_dir)",
        "remote_path_expr(target_run_dir + \"/stdout.log\")",
        "remote_path_expr(target_run_dir + \"/pid\")",
    ):
        assert call in start, f"missing {call}"


def test_run_wrapper_expands_tilde_inside_arguments():
    """A script path is an argv element, and argv is never re-parsed by the shell.

    `python3 ~/caasi/robots/r1/scripts/x.py` reached Python with the literal ``~`` and failed with
    "can't open file '/home/<user>/~/caasi/...'". The wrapper therefore rewrites a leading ``~/``
    in every argument, using a *quoted* pattern -- in bash 5.2 ``${a#~/}`` does not strip the
    prefix (measured on the target), while ``${a#"~/"}`` does.
    """
    src = Path(runs.__file__).read_text(encoding="utf-8")
    assert 'case "$a" in' in src
    assert '"~/"*)' in src
    assert '$HOME/${{a#"~/"}}' in src, "the pattern must be quoted or the prefix is not stripped"
    assert "${a#~/}" not in src.replace('${a#"~"}', ''), "unquoted pattern does not strip in bash 5"


def test_run_logs_and_file_listing_expand_tilde():
    """`caasi logs` and the file inventory read the remote run directory.

    Both built their command with a single-quoted path and swallowed the error (``2>/dev/null``), so
    a run that had plainly succeeded showed no output at all. Measured on the robot: the provisioning
    run's log was empty before this fix and complete after it.
    """
    src = Path(runs.__file__).read_text(encoding="utf-8")
    assert "tail -n {max(lines, 1)} '{log_file}'" not in src, "quoted tilde in the log tail"
    assert "find '{run_dir}'" not in src, "quoted tilde in the file inventory"
    assert "remote_path_expr(log_file)" in src
    assert "remote_path_expr(run_dir)" in src


def test_the_target_side_manifest_is_written_through_the_home_directory():
    """A successful run still printed `bash: line 1: ~/.../manifest.yaml: No such file or directory`.

    The manifest write single-quoted the run directory, so on the robot the provenance file simply
    was not created -- the run worked, its record did not.
    """
    src = Path(runs.__file__).read_text(encoding="utf-8")
    assert "cat > '{target_run_dir}/manifest.yaml'" not in src
    assert "remote_path_expr(target_run_dir + '/manifest.yaml')" in src


def test_read_run_log_expands_tilde_in_the_command_it_sends(monkeypatch):
    """The command actually sent over SSH must name the home directory, not a literal tilde."""
    from types import SimpleNamespace

    from caasi.core.config import Config

    sent: list[str] = []

    def fake_run(cmd, **kwargs):
        sent.append(cmd[-1])
        return SimpleNamespace(returncode=0, stdout="line\n", stderr="")

    monkeypatch.setattr(runs.subprocess, "run", fake_run)
    config = Config({"targets": {"r1": {"host": "10.0.0.5", "user": "robot"}}}, [])
    record = SimpleNamespace(
        target="r1", target_transport="ssh",
        remote_run_dir="~/caasi/robots/p/.caasi/runs/x",
    )
    runs.read_run_log(record, config, stream="stdout", lines=5)
    assert sent, "no command was sent"
    assert "'~" not in sent[-1], sent[-1]
    assert '"$HOME"' in sent[-1], sent[-1]


def test_artifact_inventory_expands_tilde_and_reports_relative_paths():
    """`caasi run artifacts` listed nothing on a robot, for two reasons at once.

    The inventory shelled `find '~/caasi/artifacts/<run>'` -- a literal ``~`` directory -- and then
    computed each path relative to the *unexpanded* root, which could never match find's absolute
    output. `-printf '%s %P'` makes find do the relative work, so neither mistake can come back.
    """
    src = Path(artifacts.__file__).read_text(encoding="utf-8")
    assert 'find {shlex.quote(remote_root)}' not in src, "quoted tilde in the artifact inventory"
    assert "remote_path_expr(remote_root)" in src
    assert "'%s %P" in src or "%s %P" in src, "find must report paths relative to its own root"
    # hashing happens in the root, so names match the relative rows
    assert "cd {remote_path_expr(remote_root)} && sha256sum" in src


def test_a_config_file_written_to_a_target_expands_tilde():
    """`caasi sim/lab` config push used `mkdir -p '~'`, which is a real directory called `~`."""
    src = Path(lifecycle.__file__).read_text(encoding="utf-8")
    assert 'mkdir -p {shlex.quote' not in src
    assert "remote_path_expr(str(Path(path).parent))" in src
    assert "remote_path_expr(path)" in src


def test_the_remote_build_runs_in_the_home_directory_it_finds_on_the_target():
    src = Path(build.__file__).read_text(encoding="utf-8")
    assert 'steps = [f"cd {dest}"]' not in src
    assert "remote_path_expr(dest)" in src
    assert "remote_path_expr(ros_setup)" in src


def test_stopping_a_run_updates_the_manifest_on_the_targets_home():
    """The target-side manifest was updated through *this* machine's home directory.

    `$HOME` was substituted locally before the command was sent, so on the robot the path pointed at
    a directory that does not exist and the `|| true` hid it: a stopped run never said so. The path
    is now an argument the target's own shell expands.
    """
    src = Path(runs.__file__).read_text(encoding="utf-8")
    assert 'os.environ.get("HOME", "~")' not in src
    assert "p = sys.argv[1]" in src
    assert "remote_path_expr(\n            record.remote_run_dir" in src
