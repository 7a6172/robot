"""Regression tests for remote path handling and deployment reliability.

These cover the class of bug found on a fresh robot: a `~` in the deployment root was
quoted, so the remote shell never expanded it. `mkdir -p '~/x'` happily creates a
*literal* `~` directory, the real destination never exists, and rsync then fails with
"mkdir ... No such file or directory" while verification reports missing files.

The tests are deliberately free of any real SSH: the property under test is the shape of
the command caasi builds, which is what decides whether the remote shell expands the
path.
"""

from __future__ import annotations

import shlex
import subprocess

import pytest

from caasi.core.targets import remote_path_expr


# --------------------------------------------------------------- path expression

@pytest.mark.parametrize(
    "path, expected",
    [
        ("~/caasi/robots/x", '"$HOME"/caasi/robots/x'),
        ("~", '"$HOME"'),
        ("~/", '"$HOME"'),
        ("/abs/path", "/abs/path"),
        ("relative/path", "relative/path"),
    ],
)
def test_tilde_is_expanded_by_the_target_not_quoted(path, expected):
    """A leading ~ must reach the remote shell as $HOME, never as a literal '~'."""
    assert remote_path_expr(path) == expected


def test_path_with_spaces_stays_a_single_argument():
    expr = remote_path_expr("~/a b/c d/meta.json")
    # Parse it the way a shell would: it must be one word.
    words = shlex.split(expr.replace('"$HOME"', "/home/u"))
    assert words == ["/home/u/a b/c d/meta.json"]


def test_absolute_path_with_spaces_is_quoted():
    assert remote_path_expr("/srv/my robots/meta.json") == "'/srv/my robots/meta.json'"


def test_metacharacters_cannot_inject_a_command():
    """A path is data. It must never be able to run something else."""
    expr = remote_path_expr("/tmp/x; rm -rf /")
    words = shlex.split(expr)
    assert words == ["/tmp/x; rm -rf /"], f"path was split into commands: {words}"


def test_no_unquoted_tilde_survives():
    """The specific regression: no expression may contain a bare quoted '~'."""
    for path in ("~/a/b", "~/x y/z"):
        expr = remote_path_expr(path)
        assert "'~" not in expr, f"tilde left quoted, remote shell cannot expand: {expr}"


# ------------------------------------------------------- shell semantics check

def test_expansion_behaves_as_the_remote_shell_would(tmp_path):
    """Execute locally with HOME overridden to prove the expansion semantics.

    This is the same shell the SSH command runs in, so it validates the shape of the
    expression rather than merely the string.
    """
    home = tmp_path / "fakehome"
    home.mkdir()
    expr = remote_path_expr("~/caasi/robots/x/deploy")
    res = subprocess.run(
        ["sh", "-c", f"mkdir -p {expr} && printf '%s' {expr}"],
        capture_output=True, text=True, env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
    )
    assert res.returncode == 0, res.stderr
    assert (home / "caasi/robots/x/deploy").is_dir()
    assert not (home / "~").exists(), "a literal '~' directory was created"


def test_literal_tilde_directory_is_not_created_with_spaces(tmp_path):
    home = tmp_path / "h2"
    home.mkdir()
    expr = remote_path_expr("~/a b/c")
    res = subprocess.run(
        ["sh", "-c", f"mkdir -p {expr}"],
        capture_output=True, text=True, env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
    )
    assert res.returncode == 0, res.stderr
    assert (home / "a b" / "c").is_dir()
    assert not (home / "~").exists()


# ------------------------------------------------------- change reporting (C3)

RSYNC_PUSH_OUTPUT = """\
<f.st...... src/openmover/config_defaults/modules.yaml
cd+++++++++ .caasi/builds/
>f+++++++++ config/new_file.yaml
*deleting   old/removed.txt

Number of files: 910 (reg: 723, dir: 186, link: 1)
Number of created files: 1
Number of regular files transferred: 2
Total file size: 42,921,330 bytes
Total transferred file size: 591 bytes
"""


def test_pushed_file_changes_are_reported():
    """A push itemizes as '<f...', which the parser used to ignore entirely."""
    from caasi.core.deploy import _parse_rsync_stats

    _, _, _, changed = _parse_rsync_stats(RSYNC_PUSH_OUTPUT)
    assert "src/openmover/config_defaults/modules.yaml" in changed, (
        f"a modified source file was not reported as changed: {changed}"
    )


def test_all_change_kinds_are_reported():
    from caasi.core.deploy import _parse_rsync_stats

    _, _, _, changed = _parse_rsync_stats(RSYNC_PUSH_OUTPUT)
    assert "config/new_file.yaml" in changed          # creation (>f+++++++++)
    assert "old/removed.txt" in changed               # deletion
    assert any(c.startswith(".caasi/builds") for c in changed)  # created directory


def test_stats_are_parsed_from_the_same_output():
    from caasi.core.deploy import _parse_rsync_stats

    files, total, transferred, _ = _parse_rsync_stats(RSYNC_PUSH_OUTPUT)
    assert files == 910
    assert total == 42921330
    assert transferred == 591


def test_no_change_output_reports_nothing():
    from caasi.core.deploy import _parse_rsync_stats

    _, _, transferred, changed = _parse_rsync_stats(
        "Number of files: 5 (reg: 5)\nTotal transferred file size: 0 bytes\n"
    )
    assert changed == []
    assert transferred == 0
