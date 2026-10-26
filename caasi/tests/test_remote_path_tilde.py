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
