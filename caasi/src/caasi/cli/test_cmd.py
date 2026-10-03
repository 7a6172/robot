"""Root ``caasi test`` — self-test and verification toolkit for caasi.

Executes caasi's test suite against the local development checkout.
Guarantees deterministic execution against the active checkout, supports
tiered test selection (full, unit, smoke), opt-in coverage, test filtering,
and machine-readable JSON reporting.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from enum import Enum
from pathlib import Path
from typing import Optional

import typer

from .. import state
from ..i18n import _
from ..utils import output


class TestSuite(str, Enum):
    FULL = "full"
    UNIT = "unit"
    SMOKE = "smoke"


def locate_test_checkout() -> tuple[Path, Path, Path]:
    """Locate the checkout repository root, tests directory, and pyproject.toml.

    Ensures caasi is running from a local checkout repository rather than an
    external installation or pipx environment without test sources.
    """
    import caasi

    caasi_init = Path(caasi.__file__).resolve()

    # Reject accidental pipx execution
    if "pipx" in sys.prefix.lower() or "pipx" in str(caasi_init).lower():
        output.fail(
            _(
                "test.pipx_detected",
                package=str(caasi_init),
                prefix=sys.prefix,
            )
        )
        raise typer.Exit(1)

    repo_root = caasi_init.parents[2]
    tests_dir = repo_root / "tests"
    pyproject_file = repo_root / "pyproject.toml"

    if not (tests_dir.is_dir() and pyproject_file.is_file()):
        output.fail(
            _(
                "test.not_local_checkout",
                path=str(tests_dir),
                package=str(caasi_init),
            )
        )
        raise typer.Exit(1)

    return repo_root, tests_dir, pyproject_file


def _build_pytest_command(
    repo_root: Path,
    tests_dir: Path,
    pyproject_file: Path,
    suite: TestSuite,
    filter_expr: Optional[str] = None,
    verbose: bool = False,
    coverage: bool = False,
    no_color: bool = False,
) -> list[str]:
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(tests_dir),
        "-c",
        str(pyproject_file),
        "-p",
        "no:launch_ros",
        "-p",
        "no:launch_testing",
    ]

    if suite == TestSuite.SMOKE:
        cmd.extend(["-m", "smoke"])
    elif suite == TestSuite.UNIT:
        cmd.extend(["-m", "not smoke"])

    if filter_expr:
        cmd.extend(["-k", filter_expr])

    if verbose:
        cmd.append("-v")

    if coverage:
        cmd.extend(["--cov=caasi", "--cov-report=term-missing"])

    if no_color:
        cmd.append("--color=no")

    return cmd


def test_command(
    suite: TestSuite = typer.Option(
        TestSuite.FULL,
        "--suite",
        "-s",
        help=_("test.flag.suite"),
        case_sensitive=False,
    ),
    filter_expr: Optional[str] = typer.Option(
        None,
        "--filter",
        "-k",
        help=_("test.flag.filter"),
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help=_("test.flag.verbose"),
    ),
    coverage: bool = typer.Option(
        False,
        "--coverage",
        help=_("test.flag.coverage"),
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help=_("flag.json"),
    ),
) -> None:
    """Run caasi's self-test and verification suite."""
    repo_root, tests_dir, pyproject_file = locate_test_checkout()

    wants_json_output = output.wants_json(json_output)

    cmd = _build_pytest_command(
        repo_root,
        tests_dir,
        pyproject_file,
        suite,
        filter_expr=filter_expr,
        verbose=verbose,
        coverage=coverage,
        no_color=wants_json_output,
    )

    start_time = time.monotonic()

    if wants_json_output:
        proc = subprocess.run(
            cmd,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
        duration = round(time.monotonic() - start_time, 2)
        summary_match = re.search(r"(=+\s+.*in\s+[\d\.]+s.*=*)", proc.stdout)
        summary = summary_match.group(1).strip("=").strip() if summary_match else ""

        result_data = {
            "suite": suite.value,
            "passed": proc.returncode == 0,
            "exit_code": proc.returncode,
            "checkout": str(repo_root),
            "tests_dir": str(tests_dir),
            "duration_seconds": duration,
            "summary": summary,
            "coverage": coverage,
        }
        if proc.returncode != 0:
            result_data["error"] = proc.stderr.strip() or proc.stdout.strip()

        output.echo_json(result_data)
        if proc.returncode != 0:
            raise typer.Exit(proc.returncode)
        return

    output.echo(
        f"[bold]{_('test.running_suite', suite=suite.value)}[/bold] [dim]({repo_root})[/dim]"
    )
    if coverage:
        output.echo(f"  [dim]{_('test.coverage_notice')}[/dim]")

    proc = subprocess.run(cmd, cwd=str(repo_root))
    if proc.returncode != 0:
        raise typer.Exit(proc.returncode)
