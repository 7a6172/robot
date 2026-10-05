"""Validation for the example catalog (Phase 7, 0.4.0).

The examples are *documentation you can run*. This module keeps them honest:

* the **catalog structure** is complete — every example is indexed, and the
  command-coverage matrix accounts for **every** command in the live CLI;
* the **CI-tier examples are actually runnable** — parsed, planned and, where
  cheap, executed end to end;
* **unsafe examples stay unsafe** — no example or test executes a destructive,
  physical or environment-mutating command.

The examples deliberately do **not** become pytest fixtures. A test that rewrote
`examples/01-python-project` into a fixture would stop it being a readable example,
which is its purpose. So these tests *read* and *run* the examples as they ship.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

from caasi.core import manifest as manifests
from caasi.core import workload as workload_core

EXAMPLES = pathlib.Path(__file__).resolve().parent.parent / "examples"

#: Examples whose prerequisites are commonly absent here. They are still checked for
#: structure, but not executed.
OPT_IN = {"05-ros2-turtlesim", "06-isaac-lab-cartpole"}


def _example_dirs() -> list[pathlib.Path]:
    return sorted(
        p for p in EXAMPLES.iterdir() if p.is_dir() and p.name[0].isdigit()
    )


def _readme(name: str) -> str:
    path = EXAMPLES / name / "README.md"
    assert path.is_file(), f"{name} has no README.md"
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The catalog is indexed and complete
# ---------------------------------------------------------------------------


def test_the_catalog_has_the_expected_examples() -> None:
    names = [p.name for p in _example_dirs()]
    assert names == [
        "01-python-project",
        "02-targets-and-selection",
        "03-ros2-demo-nodes",
        "04-container",
        "05-ros2-turtlesim",
        "06-isaac-lab-cartpole",
        "07-control-plane-end-to-end",
    ]


def test_every_example_is_indexed_in_the_readme() -> None:
    """An example nobody can find is not an example."""
    index = (EXAMPLES / "README.md").read_text(encoding="utf-8")
    for name in [p.name for p in _example_dirs()]:
        assert name in index, f"{name} is missing from examples/README.md"


def test_every_example_has_a_readme() -> None:
    for path in _example_dirs():
        assert (path / "README.md").is_file(), f"{path.name} has no README.md"


def test_every_example_states_what_caasi_provides() -> None:
    """The caasi-vs-ecosystem distinction is the point of the catalog."""
    for path in _example_dirs():
        text = (path / "README.md").read_text(encoding="utf-8")
        assert "caasi provides" in text.lower(), f"{path.name} omits the boundary"
    cookbook = (EXAMPLES / "cookbook" / "README.md").read_text(encoding="utf-8")
    assert "provides" in cookbook.lower()


# ---------------------------------------------------------------------------
# Coverage: every live command is accounted for
# ---------------------------------------------------------------------------


def _live_command_paths() -> list[str]:
    """Every command path in the live CLI, extracted from the app itself."""
    import typer.main
    from typer.core import TyperGroup

    from caasi.cli.main import app

    root = typer.main.get_command(app)
    found: list[str] = []

    def walk(cmd, prefix: str, depth: int) -> None:
        try:
            names = sorted(cmd.list_commands(None))
        except Exception:  # noqa: BLE001
            names = []
        for name in names:
            sub = cmd.get_command(None, name)
            if sub is None:
                continue
            found.append(f"{prefix} {name}".strip())
            if isinstance(sub, TyperGroup) and depth < 2:
                walk(sub, f"{prefix} {name}", depth + 1)

    walk(root, "caasi", 0)
    return found


def test_coverage_matrix_accounts_for_every_live_command() -> None:
    """The matrix is an audit: a command missing from it is a silent omission."""
    matrix = (EXAMPLES / "COVERAGE.md").read_text(encoding="utf-8")
    documented = set(re.findall(r"^\| `(caasi[^`]*)`", matrix, re.MULTILINE))
    live = set(_live_command_paths())

    missing = sorted(live - documented)
    assert not missing, f"commands absent from COVERAGE.md: {missing}"

    stale = sorted(documented - live)
    assert not stale, f"COVERAGE.md documents commands that no longer exist: {stale}"


def test_coverage_matrix_states_the_live_totals() -> None:
    """The stated counts must match the CLI, or the audit is not an audit."""
    matrix = (EXAMPLES / "COVERAGE.md").read_text(encoding="utf-8")
    live = set(_live_command_paths())
    roots = {c.split()[1] for c in live}

    # The matrix states the totals it was generated from; they must match the CLI.
    assert f"{len(roots)} root commands" in matrix
    assert f"{len(live)} command paths" in matrix


# ---------------------------------------------------------------------------
# Unsafe commands are documented, never executed
# ---------------------------------------------------------------------------

#: Commands no example or test may run: destructive, physical, or environment-mutating.
NEVER_EXECUTED = (
    "caasi run delete",
    "caasi project remove",
    "caasi teleop start",
    "caasi teleop record",
    "caasi setup",
    "caasi nav launch",
    "caasi moveit launch",
    "caasi motion execute",
)


def test_unsafe_commands_are_listed_as_never_executed() -> None:
    """They must be *named* as unsafe rather than quietly absent."""
    matrix = (EXAMPLES / "COVERAGE.md").read_text(encoding="utf-8")
    for command in NEVER_EXECUTED:
        row = [ln for ln in matrix.splitlines() if ln.startswith(f"| `{command}`")]
        assert row, f"{command} is missing from the coverage matrix"
        assert "not executed" in row[0], f"{command} is not marked 'not executed'"


def test_no_example_script_runs_an_unsafe_command() -> None:
    """Nothing shipped in the catalog invokes a destructive or physical command."""
    offenders: list[str] = []
    for path in EXAMPLES.rglob("*"):
        if not path.is_file() or path.suffix not in (".md", ".py", ".yaml", ".sh"):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for command in NEVER_EXECUTED:
            # A mention in prose is expected; an *invocation* is not.
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith(("#", ">", "|", "*", "<!--")):
                    continue
                if stripped.startswith(command) or f"$ {command}" in stripped:
                    offenders.append(f"{path.relative_to(EXAMPLES)}: {stripped[:60]}")
    assert not offenders, "examples invoke unsafe commands:\n  " + "\n  ".join(offenders)


def test_no_example_invents_a_dry_run_the_cli_lacks() -> None:
    """The CLI has no --dry-run on the destructive commands; do not pretend otherwise."""
    matrix = (EXAMPLES / "COVERAGE.md").read_text(encoding="utf-8")
    for command in ("caasi run delete", "caasi project remove"):
        row = [ln for ln in matrix.splitlines() if ln.startswith(f"| `{command}`")][0]
        assert "no --dry-run" in row, f"{command} should say it has no --dry-run"


# ---------------------------------------------------------------------------
# The examples are real caasi projects
# ---------------------------------------------------------------------------


def test_ci_examples_are_valid_projects() -> None:
    """Every non-opt-in example that declares a manifest must be a valid project."""
    checked = 0
    for path in _example_dirs():
        if path.name in OPT_IN:
            continue
        manifest_path = path / "caasi.yaml"
        if not manifest_path.is_file():
            continue
        manifest = manifests.read(path)
        assert manifest.schema >= 1
        assert manifest.name, f"{path.name} has no project name"
        for directory in manifest.project_layout.values():
            assert (path / directory).is_dir(), (
                f"{path.name}: declared layout directory '{directory}' is missing"
            )
        checked += 1
    assert checked >= 2, "expected at least two manifest-bearing examples"


def test_every_declared_workload_parses() -> None:
    """A workload in an example must load and use only the known step vocabulary."""
    for path in EXAMPLES.rglob("workloads/*.yaml"):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict), f"{path} is not a mapping"
        workload = workload_core.parse_workload(data, path=path)
        assert workload.name
        for step in workload.steps:
            assert step.name in workload_core.KNOWN_STEPS


def test_examples_declare_their_prerequisites() -> None:
    """A user must be able to tell whether they can run an example."""
    for path in _example_dirs():
        text = (path / "README.md").read_text(encoding="utf-8")
        assert "prerequisite" in text.lower(), f"{path.name} does not state prerequisites"


def test_opt_in_examples_declare_that_they_are_not_ci_validated() -> None:
    """Opt-in/manual examples must not appear to be validated when they are not."""
    for name in OPT_IN:
        text = _readme(name).lower()
        assert "not validated" in text or "not ci-validated" in text, (
            f"{name} does not state that it is not automatically validated"
        )


def test_tier_claims_in_the_matrix_are_from_the_known_set() -> None:
    matrix = (EXAMPLES / "COVERAGE.md").read_text(encoding="utf-8")
    allowed = {"CI", "opt-in", "manual", "CI/opt-in"}
    for line in matrix.splitlines():
        if not line.startswith("| `caasi"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        assert cells[3] in allowed, f"unknown tier '{cells[3]}' in: {line[:70]}"


# ---------------------------------------------------------------------------
# The CI-tier examples actually run
# ---------------------------------------------------------------------------


def test_example_01_runs_end_to_end(isolated_env, tmp_path) -> None:
    """The backbone example must genuinely work, not merely look right."""
    import subprocess
    import sys

    project = EXAMPLES / "01-python-project"
    script = project / "scripts" / "analyse.py"
    assert script.is_file()

    # Mirror the example's real layout (scripts/ inside a project root), in a
    # scratch copy, so validating never pollutes the shipped example tree.
    work = tmp_path / "project"
    (work / "scripts").mkdir(parents=True)
    copy = work / "scripts" / "analyse.py"
    copy.write_text(script.read_text(encoding="utf-8"), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(copy)], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr

    # The script resolves its project root from its own location, so the declared
    # output lands there -- which is what the experiment's `outputs:` path expects.
    out = work / "mean.out"
    assert out.is_file(), "the example did not produce its declared output"
    assert out.read_text().startswith("mean=")


def test_example_07_package_is_a_real_ros2_package() -> None:
    """The build step needs something genuine to build."""
    pkg = EXAMPLES / "07-control-plane-end-to-end" / "src" / "demo_pkg"
    assert (pkg / "package.xml").is_file()
    assert (pkg / "CMakeLists.txt").is_file()
    cmake = (pkg / "CMakeLists.txt").read_text(encoding="utf-8")
    assert "ament_cmake" in cmake


def test_examples_do_not_duplicate_upstream_projects() -> None:
    """The catalog references canonical examples; it must not vendor them."""
    total = sum(
        1
        for path in EXAMPLES.rglob("*")
        if path.is_file() and path.suffix in (".py", ".cpp", ".hpp", ".xml", ".txt")
    )
    # A generous ceiling: if this is exceeded, something upstream was copied in.
    assert total < 30, f"the catalog has grown to {total} source files; is it vendoring?"
