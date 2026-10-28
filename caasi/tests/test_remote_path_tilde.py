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

from caasi.core import execution, runs
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
