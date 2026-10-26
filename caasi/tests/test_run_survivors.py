"""A run is only over when nothing it started is still running.

The wrapper exits as soon as the program it launched returns or detaches. A pid-only check
therefore answered "is the wrapper alive", reported `stopped`/`succeeded`, and left a node
running and holding its ports. Both halves are tested here: the status must say `stale`, and
`stop` must actually stop the survivors instead of returning early.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time

import pytest

from caasi.core import runs
from caasi.core.runs import RunRecord


def _record(tmp_path, **kw) -> RunRecord:
    return RunRecord(
        run_id="r1",
        name="r1",
        backend="command",
        kind="command",
        command=["bash", "-c", "sleep 30 &"],
        cwd=str(tmp_path),
        created="",
        pid=None,
        target="local",
        target_transport="local",
        directory=tmp_path,
        **kw,
    )


@pytest.fixture
def survivor(tmp_path):
    """A process group whose wrapper has exited but whose child is still running."""
    proc = subprocess.Popen(
        ["bash", "-c", "sleep 60 & echo $!; wait $! >/dev/null 2>&1 &"],
        start_new_session=True,
    )
    time.sleep(0.6)
    pgid = proc.pid
    proc.wait(timeout=5)  # the wrapper is gone; the child lives in the same group
    rec = _record(tmp_path)
    rec.pid = pgid
    rec.pgid = pgid  # type: ignore[attr-defined]
    yield rec
    try:
        os.killpg(pgid, signal.SIGKILL)
    except OSError:
        pass


def test_survivors_alive_detects_a_group_that_outlived_its_wrapper(survivor):
    assert runs.survivors_alive(survivor) is True
    os.killpg(survivor.pgid, signal.SIGKILL)
    time.sleep(0.5)
    assert runs.survivors_alive(survivor) is False


def test_status_is_stale_not_succeeded_when_the_group_survives(monkeypatch, tmp_path):
    rec = _record(tmp_path)
    rec.target = "remote"
    rec.target_transport = "ssh"
    rec.remote_run_dir = "~/caasi/data/runs/r1"
    rec.pid = 111
    rec.pgid = 111
    rec.directory = None

    class Res:
        returncode = 0
        # Wrapper exited cleanly, yet the group is still there.
        stdout = "EXIT:0\nGROUP:ALIVE\n"

    monkeypatch.setattr(runs.targets_core, "find_target", lambda cfg, name: type(
        "T", (), {"ssh_timeout": 5.0, "transport": "ssh"}
    )())
    monkeypatch.setattr(runs.targets_core, "target_ssh_prefix", lambda t: ["true"])
    monkeypatch.setattr(runs.subprocess, "run", lambda *a, **k: Res())

    assert runs.remote_effective_status(rec, runs.Config({}, [])) == runs.STALE


def test_status_still_reports_success_when_nothing_survives(monkeypatch, tmp_path):
    rec = _record(tmp_path)
    rec.target = "remote"
    rec.target_transport = "ssh"
    rec.remote_run_dir = "~/caasi/data/runs/r1"
    rec.pid = 111
    rec.pgid = 111
    rec.directory = None

    class Res:
        returncode = 0
        stdout = "EXIT:0\nGROUP:DEAD\n"

    monkeypatch.setattr(runs.targets_core, "find_target", lambda cfg, name: type(
        "T", (), {"ssh_timeout": 5.0, "transport": "ssh"}
    )())
    monkeypatch.setattr(runs.targets_core, "target_ssh_prefix", lambda t: ["true"])
    monkeypatch.setattr(runs.subprocess, "run", lambda *a, **k: Res())

    assert runs.remote_effective_status(rec, runs.Config({}, [])) == runs.TERMINAL_OK


def test_stop_does_not_return_early_while_a_descendant_lives(monkeypatch, tmp_path):
    rec = _record(tmp_path)
    monkeypatch.setattr(runs, "effective_status", lambda r, c=None: runs.TERMINAL_OK)
    monkeypatch.setattr(runs, "survivors_alive", lambda r, c=None: True)
    called = {}
    monkeypatch.setattr(
        runs, "sandbox_stop_run",
        lambda r, timeout=5.0: called.setdefault("stopped", True) or True,
    )
    # A sandboxed remote run is the path that used to return early.
    rec.target = "remote"
    rec.remote_run_dir = "~/caasi/data/runs/r1"
    runs.stop_run(rec, config=runs.Config({}, []))
    assert called.get("stopped") is True, "a surviving descendant must actually be stopped"


def test_stop_returns_immediately_when_nothing_survives(monkeypatch, tmp_path):
    rec = _record(tmp_path)
    monkeypatch.setattr(runs, "effective_status", lambda r, c=None: runs.TERMINAL_OK)
    monkeypatch.setattr(runs, "survivors_alive", lambda r, c=None: False)
    monkeypatch.setattr(runs, "sandbox_stop_run", lambda *a, **k: pytest.fail("must not run"))
    assert runs.stop_run(rec, config=runs.Config({}, [])) is True
