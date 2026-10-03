"""Tests for the `caasi test` CLI command."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from caasi.cli.main import app
from caasi.cli import test_cmd


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_test_help_displayed(runner: CliRunner):
    """Verify `caasi test --help` shows options and descriptions."""
    result = runner.invoke(app, ["test", "--help"])
    assert result.exit_code == 0
    assert "--suite" in result.output
    assert "--filter" in result.output
    assert "--coverage" in result.output
    assert "--verbose" in result.output
    assert "--json" in result.output
    assert "Run caasi's self-test and verification suite" in result.output


def test_test_default_runs_full_suite(runner: CliRunner):
    """Verify default invocation without --suite runs the full test suite."""
    with patch("caasi.cli.test_cmd.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = runner.invoke(app, ["test"])

        assert result.exit_code == 0
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        pytest_args = cmd[3:]

        # Pytest invocation checks
        assert "-m" not in pytest_args  # Full suite has no marker restriction
        assert any("tests" in str(arg) for arg in pytest_args)
        assert not any("--cov" in str(arg) for arg in pytest_args)  # Coverage is strictly opt-in


def test_test_suite_smoke_marker(runner: CliRunner):
    """Verify --suite smoke passes -m smoke to pytest."""
    with patch("caasi.cli.test_cmd.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = runner.invoke(app, ["test", "--suite", "smoke"])

        assert result.exit_code == 0
        cmd = mock_run.call_args[0][0]
        pytest_args = cmd[3:]
        assert "-m" in pytest_args
        assert pytest_args[pytest_args.index("-m") + 1] == "smoke"


def test_test_suite_unit_marker(runner: CliRunner):
    """Verify --suite unit passes -m 'not smoke' to pytest."""
    with patch("caasi.cli.test_cmd.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = runner.invoke(app, ["test", "--suite", "unit"])

        assert result.exit_code == 0
        cmd = mock_run.call_args[0][0]
        pytest_args = cmd[3:]
        assert "-m" in pytest_args
        assert pytest_args[pytest_args.index("-m") + 1] == "not smoke"


def test_test_suite_invalid_choice(runner: CliRunner):
    """Verify invalid suite option is rejected."""
    result = runner.invoke(app, ["test", "--suite", "nonexistent"])
    assert result.exit_code != 0
    assert "Invalid value for '--suite'" in result.output or "not one of" in result.output


def test_test_filter_flag(runner: CliRunner):
    """Verify -k / --filter passes expression to pytest."""
    with patch("caasi.cli.test_cmd.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = runner.invoke(app, ["test", "--filter", "test_runs"])

        assert result.exit_code == 0
        cmd = mock_run.call_args[0][0]
        assert "-k" in cmd
        assert cmd[cmd.index("-k") + 1] == "test_runs"


def test_test_coverage_opt_in(runner: CliRunner):
    """Verify --coverage adds pytest-cov arguments."""
    with patch("caasi.cli.test_cmd.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = runner.invoke(app, ["test", "--coverage"])

        assert result.exit_code == 0
        cmd = mock_run.call_args[0][0]
        assert "--cov=caasi" in cmd
        assert "--cov-report=term-missing" in cmd


def test_test_verbose_flag(runner: CliRunner):
    """Verify -v / --verbose passes -v to pytest."""
    with patch("caasi.cli.test_cmd.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = runner.invoke(app, ["test", "-v"])

        assert result.exit_code == 0
        cmd = mock_run.call_args[0][0]
        assert "-v" in cmd


def test_test_local_checkout_safety_pipx(runner: CliRunner, monkeypatch):
    """Verify execution is refused if running in a pipx installation."""
    monkeypatch.setattr("sys.prefix", "/home/user/.local/share/pipx/venvs/caasi")
    result = runner.invoke(app, ["test"])
    assert result.exit_code == 1
    assert "pipx installation" in result.output or "pipx" in result.stderr


def test_test_local_checkout_safety_missing_tests(runner: CliRunner, tmp_path, monkeypatch):
    """Verify execution is refused if the package does not have a repo tests directory."""
    fake_caasi = tmp_path / "lib" / "python3.12" / "site-packages" / "caasi" / "__init__.py"
    fake_caasi.parent.mkdir(parents=True)
    fake_caasi.write_text("")
    monkeypatch.setattr("caasi.__file__", str(fake_caasi))

    result = runner.invoke(app, ["test"])
    assert result.exit_code == 1
    assert "Tests directory not found" in result.output or "Tests directory not found" in result.stderr


def test_test_json_output(runner: CliRunner):
    """Verify --json produces valid structured output without human log banners."""
    fake_stdout = "================== 847 passed in 184.43s ==================\n"
    with patch("caasi.cli.test_cmd.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=fake_stdout, stderr="")
        result = runner.invoke(app, ["test", "--json", "--suite", "smoke"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["suite"] == "smoke"
        assert data["passed"] is True
        assert data["exit_code"] == 0
        assert "checkout" in data
        assert "tests_dir" in data
        assert "847 passed in 184.43s" in data["summary"]


def test_test_failure_propagates_exit_code(runner: CliRunner):
    """Verify nonzero exit code from pytest propagates to CLI exit code."""
    with patch("caasi.cli.test_cmd.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=3, stdout="failures", stderr="failed tests")
        result = runner.invoke(app, ["test"])
        assert result.exit_code == 3
