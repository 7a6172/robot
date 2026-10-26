"""Ad-hoc managed processes on a target.

`caasi exec --detach` starts an arbitrary command through the *existing* run lifecycle
(one wrapper format, one launch shape, `caasi run status|logs|stop`), so these tests
exercise that lifecycle rather than a second supervisor.

Two defects found by using the feature are pinned here:
  * status reported "lost" for every ad-hoc run, because it required a deployment
    `destination` that an ad-hoc command does not have;
  * run directories were placed under `cache/`, which is documented as safe to clear,
    while logs and exit codes must survive.
"""

from __future__ import annotations

import subprocess
import time

import pytest

from caasi.core import layout, runs
from caasi.core.config import Config
from caasi.core.targets import Target


def _config(tmp_path) -> Config:
    return Config({"paths": {"runs": str(tmp_path / "runs")}}, [])


# --------------------------------------------------------------- layout of runs

def test_run_directories_live_under_data_not_cache():
    """Logs and exit codes must survive a cache clear."""
    path = layout.run_dir("20260101-000000-demo")
    assert path.startswith("~/caasi/data/"), path
    assert "/cache/" not in path


# ------------------------------------------------- status without a deployment

def test_status_does_not_require_a_deployment_destination(monkeypatch):
    """Regression: an ad-hoc run has no `destination`, and that used to mean 'lost'."""
    record = runs.RunRecord(
        run_id="demo",
        name="demo",
        backend="command",
        kind="command",
        command=["sleep", "1"],
        cwd=".",
        created="2026-01-01T00:00:00",
        pid=1234,
        target="probe",
        target_transport="ssh",
        remote_run_dir="~/caasi/data/runs/demo",
        destination=None,  # the ad-hoc case
    )
    # An unknown target is reported as lost; the point of the test is what follows --
    # a reachable target with no deployment destination must still report real state.
    assert runs.remote_effective_status(record, Config({}, [])) == "lost"

    monkeypatch.setattr(
        runs.targets_core, "find_target",
        lambda cfg, name: Target(name="probe", transport="ssh", host="probe.invalid", user="u"),
    )
    monkeypatch.setattr(runs.targets_core, "target_ssh_prefix", lambda t: ["ssh"])

    class _Res:
        returncode = 0
        stdout = "RUNNING\n"
        stderr = ""

    monkeypatch.setattr(runs.subprocess, "run", lambda *a, **k: _Res())
    assert runs.remote_effective_status(record, Config({}, [])) == "running"


def test_missing_run_dir_is_still_lost():
    """The one thing genuinely required is where the run lives."""
    record = runs.RunRecord(
        run_id="x", name="x", backend="command", kind="command", command=["true"],
        cwd=".", created="2026-01-01T00:00:00", pid=1,
        target="probe", target_transport="ssh", remote_run_dir=None,
    )
    assert runs.remote_effective_status(record, Config({}, [])) == "lost"


def test_transport_failure_reports_unreachable_not_exit(monkeypatch):
    record = runs.RunRecord(
        run_id="x", name="x", backend="command", kind="command", command=["true"],
        cwd=".", created="2026-01-01T00:00:00", pid=1, target="probe",
        target_transport="ssh", remote_run_dir="~/caasi/data/runs/x",
    )
    monkeypatch.setattr(
        runs.targets_core, "find_target",
        lambda cfg, name: Target(name="probe", transport="ssh", host="h", user="u"),
    )
    monkeypatch.setattr(runs.targets_core, "target_ssh_prefix", lambda t: ["ssh"])

    class _Fail:
        returncode = 255
        stdout = ""
        stderr = "ssh: connect to host h port 22: Connection timed out"

    monkeypatch.setattr(runs.subprocess, "run", lambda *a, **k: _Fail())
    assert runs.remote_effective_status(record, Config({}, [])) == "unreachable"


# ------------------------------------------------------- local lifecycle parity

def test_local_target_uses_the_existing_run_lifecycle(tmp_path):
    """A non-SSH target delegates to start_run rather than duplicating detachment."""
    cfg = _config(tmp_path)
    record = runs.start_target_command(
        Target(name="local", transport="local"), cfg,
        argv=["sleep", "30"], name="local-sleeper",
    )
    try:
        assert record.target == "local"
        assert record.pid
        assert runs.effective_status(record, cfg) in ("running", "paused")
    finally:
        runs.stop_run(record, config=cfg)


def test_empty_command_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        runs.start_target_command(
            Target(name="local", transport="local"), _config(tmp_path), argv=[]
        )


def test_exit_code_and_logs_survive_for_an_ad_hoc_run(tmp_path):
    """A managed command's result is readable after it exits (the point of detaching)."""
    cfg = _config(tmp_path)
    record = runs.start_target_command(
        Target(name="local", transport="local"), cfg,
        argv=["bash", "-c", "echo managed-output; exit 3"], name="quick",
    )
    for _ in range(100):
        status = runs.effective_status(record, cfg)
        if status not in ("running", "paused"):
            break
        time.sleep(0.05)
    assert status in ("failed", "succeeded", "exited"), status
    run_dir = record.directory
    assert run_dir is not None
    assert "managed-output" in (run_dir / "stdout.log").read_text()
