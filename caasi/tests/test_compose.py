"""Tests for Stage F2: workload steps and lifecycle composition.

The composition layer adds *sequencing and reporting* over operations that already
exist. These tests pin the properties that keep it from becoming something else:

* the step vocabulary is **closed** — an unknown step is rejected, not ignored;
* a failing step **stops** the chain and is named;
* "launched" is never confused with "succeeded";
* an incompatible target stops the run, while an **unmeasured** requirement does
  not (absence of evidence is not evidence of absence);
* the target is never chosen, defaulted or forwarded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from caasi.core import compose as C
from caasi.core import workload as W
from caasi.core.targets import Target, TargetEnvironment, TargetInspection, TargetResources


# ---------------------------------------------------------------------------
# Step vocabulary - closed by construction
# ---------------------------------------------------------------------------


def test_bare_step_is_accepted():
    steps = W.parse_steps(["deploy", "run", "collect"])
    assert [s.name for s in steps] == ["deploy", "run", "collect"]


def test_step_with_options_is_accepted():
    steps = W.parse_steps([{"build": {"packages": ["a", "b"]}}])
    assert steps[0].name == "build"
    assert steps[0].options == {"packages": ["a", "b"]}


def test_unknown_step_is_rejected():
    """Silently skipping a written step would run a different sequence."""
    with pytest.raises(W.WorkloadError) as err:
        W.parse_steps(["deploy", "teleport"])
    assert "unknown step 'teleport'" in str(err.value)


def test_unknown_step_lists_the_known_ones():
    with pytest.raises(W.WorkloadError) as err:
        W.parse_steps(["nope"])
    for name in W.KNOWN_STEPS:
        assert name in str(err.value)


def test_multi_key_step_is_rejected():
    with pytest.raises(W.WorkloadError):
        W.parse_steps([{"deploy": {}, "run": {}}])


def test_non_step_entry_is_rejected():
    with pytest.raises(W.WorkloadError):
        W.parse_steps([123])


def test_steps_must_be_a_list():
    with pytest.raises(W.WorkloadError):
        W.parse_steps("deploy")


def test_steps_are_ordered():
    """Order is the author's, and is preserved exactly."""
    steps = W.parse_steps(["run", "collect", "deploy"])
    assert [s.name for s in steps] == ["run", "collect", "deploy"]


def test_step_options_must_be_a_mapping():
    with pytest.raises(W.WorkloadError):
        W.parse_steps([{"build": ["a"]}])


def test_no_conditional_or_expression_steps_exist():
    """There is no vocabulary for control flow, by design."""
    for forbidden in ("if", "when", "loop", "foreach", "retry", "parallel"):
        assert forbidden not in W.KNOWN_STEPS


def test_workload_serialises_steps_as_mappings():
    workload = W.parse_workload({"name": "x", "steps": ["deploy", {"build": {"packages": ["a"]}}]})
    assert workload.to_dict()["steps"] == [
        {"name": "deploy", "options": {}},
        {"name": "build", "options": {"packages": ["a"]}},
    ]


# ---------------------------------------------------------------------------
# Composition - ordering, stopping, provenance
# ---------------------------------------------------------------------------


@dataclass
class _Runner:
    """A StepRunner stand-in that records calls and can be made to fail."""

    calls: list[str] = field(default_factory=list)
    fail_at: str | None = None
    events: dict[str, Any] = field(default_factory=dict)

    def _step(self, name: str, produced: dict) -> dict:
        self.calls.append(name)
        if self.fail_at == name:
            raise C.stopped(name, f"{name} failed on purpose")
        return produced

    def deploy(self, options):
        return self._step("deploy", {"deployment_id": "dep-1"})

    def build(self, options):
        return self._step("build", {"build_id": "bld-1"})

    def run(self, options):
        return self._step("run", {"run_id": "run-1"})

    def collect(self, options):
        return self._step("collect", {"artifacts_collected": 2})


def _workload(*steps: str) -> W.Workload:
    return W.parse_workload({"name": "w", "steps": list(steps)})


def test_steps_run_in_order():
    runner = _Runner()
    report = C.compose(_workload("deploy", "build", "run", "collect"), "t", runner)
    assert runner.calls == ["deploy", "build", "run", "collect"]
    assert report.ok is True


def test_only_declared_steps_run():
    """Omission is respected; nothing is inferred or inserted."""
    runner = _Runner()
    C.compose(_workload("deploy", "run"), "t", runner)
    assert runner.calls == ["deploy", "run"]


def test_a_failing_step_stops_the_chain():
    runner = _Runner(fail_at="build")
    report = C.compose(_workload("deploy", "build", "run"), "t", runner)
    assert report.ok is False
    assert report.failed_step == "build"
    assert runner.calls == ["deploy", "build"]
    # collect/run did not happen.
    assert "run" not in runner.calls


def test_failure_reports_the_error_text():
    runner = _Runner(fail_at="run")
    report = C.compose(_workload("run", "collect"), "t", runner)
    assert "failed on purpose" in report.error


def test_steps_before_the_failure_are_recorded():
    """An operator must see what already ran, to continue with the CLI."""
    runner = _Runner(fail_at="run")
    report = C.compose(_workload("deploy", "build", "run"), "t", runner)
    assert [s.name for s in report.steps] == ["deploy", "build", "run"]
    assert report.steps[0].status == C.STEP_OK
    assert report.steps[-1].status == C.STEP_FAILED


def test_provenance_ids_survive_a_later_failure():
    runner = _Runner(fail_at="run")
    report = C.compose(_workload("deploy", "build", "run"), "t", runner)
    produced = report.produced()
    assert produced["deployment_id"] == "dep-1"
    assert produced["build_id"] == "bld-1"


def test_unexpected_exception_also_stops_the_chain():
    class Boom(_Runner):
        def build(self, options):
            self.calls.append("build")
            raise RuntimeError("unexpected")

    runner = Boom()
    report = C.compose(_workload("deploy", "build", "run"), "t", runner)
    assert report.ok is False
    assert report.failed_step == "build"
    assert "unexpected" in report.error


def test_workload_without_steps_is_reported_not_run():
    runner = _Runner()
    report = C.compose(_workload(), "t", runner)
    assert report.ok is False
    assert "no steps" in report.error
    assert runner.calls == []


def test_report_serialises_for_json():
    runner = _Runner()
    report = C.compose(_workload("deploy", "collect"), "robot-01", runner)
    payload = report.to_dict()
    assert payload["target"] == "robot-01"
    assert payload["ok"] is True
    assert payload["provenance"]["deployment_id"] == "dep-1"
    assert [s["name"] for s in payload["steps"]] == ["deploy", "collect"]


def test_progress_callback_sees_each_step():
    runner = _Runner()
    seen: list[str] = []
    C.compose(_workload("deploy", "run"), "t", runner, on_step=lambda r: seen.append(r.name))
    assert seen == ["deploy", "run"]


def test_a_failing_step_is_also_reported_to_the_callback():
    runner = _Runner(fail_at="deploy")
    seen: list[str] = []
    C.compose(_workload("deploy", "run"), "t", runner, on_step=lambda r: seen.append(r.name))
    assert seen == ["deploy"]


# ---------------------------------------------------------------------------
# The compatibility gate
# ---------------------------------------------------------------------------


def _inspection(*, reachable=True, gpus=None, ros_distro=None, error=None):
    return TargetInspection(
        target=Target(name="t"),
        reachable=reachable,
        status="online" if reachable else "unreachable",
        environment=TargetEnvironment(ros_distro=ros_distro),
        resources=TargetResources(gpus=gpus if gpus is not None else []),
        discovered_capabilities=[],
        error=error,
    )


def test_gate_refuses_when_a_requirement_is_contradicted():
    proceed, reason = C.check_target_compatibility(
        Target(name="t"), {"gpu": {"count": 1}}, _inspection(gpus=[])
    )
    assert proceed is False
    assert "does not satisfy 'gpu'" in reason


def test_gate_refuses_an_unreachable_target():
    proceed, reason = C.check_target_compatibility(
        Target(name="t"), {"ros2": {}}, _inspection(reachable=False, error="Could not connect")
    )
    assert proceed is False
    assert "unreachable" in reason


def test_gate_proceeds_when_requirements_are_met():
    proceed, reason = C.check_target_compatibility(
        Target(name="t"), {"ros2": {"version": "jazzy"}}, _inspection(ros_distro="jazzy")
    )
    assert proceed is True
    assert reason is None


def test_unmeasured_requirement_does_not_block():
    """Absence of evidence must not be converted into evidence of absence.

    `torch` is never probed by target discovery, so its outcome is `untested`.
    Treating that as a failure would refuse targets for facts nobody measured.
    """
    proceed, reason = C.check_target_compatibility(
        Target(name="t"), {"torch": {"version": ">=2.0"}}, _inspection(ros_distro="jazzy")
    )
    assert proceed is True
    assert reason is None


def test_unmeasured_requirements_are_reported_for_visibility():
    notes = C.unmeasured_requirements(
        Target(name="t"), {"torch": {"version": ">=2.0"}}, _inspection(ros_distro="jazzy")
    )
    assert len(notes) == 1
    assert "torch" in notes[0]


def test_out_of_range_does_not_block_either():
    """§57: a version range alone does not establish incompatibility."""
    proceed, _ = C.check_target_compatibility(
        Target(name="t"), {"ros2": {"version": "humble"}}, _inspection(ros_distro="jazzy")
    )
    assert proceed is True


def test_gate_never_suggests_another_target():
    """The gate answers yes/no about the NAMED target; it allocates nothing."""
    proceed, reason = C.check_target_compatibility(
        Target(name="robot-01"), {"gpu": {"count": 1}}, _inspection(gpus=[])
    )
    assert proceed is False
    assert "robot-01" in reason
    # No other target is named or recommended.
    assert "instead" not in (reason or "")
    assert "try" not in (reason or "").lower()


# ---------------------------------------------------------------------------
# Launched is not the same as succeeded
# ---------------------------------------------------------------------------


def test_wait_for_terminal_returns_on_success(monkeypatch):
    from caasi.core import runs as runs_core

    calls = {"n": 0}

    def fake_status(record, config):
        calls["n"] += 1
        return runs_core.RUNNING if calls["n"] < 3 else runs_core.TERMINAL_OK

    monkeypatch.setattr(runs_core, "effective_status", fake_status)
    assert C.wait_for_terminal(_fake_record(), None, poll_interval=0.0) == runs_core.TERMINAL_OK
    assert calls["n"] == 3


def test_wait_for_terminal_returns_on_failure(monkeypatch):
    from caasi.core import runs as runs_core

    monkeypatch.setattr(runs_core, "effective_status",
                        lambda record, config: runs_core.TERMINAL_FAIL)
    assert C.wait_for_terminal(_fake_record(), None, poll_interval=0.0) == runs_core.TERMINAL_FAIL


def test_wait_for_terminal_returns_on_stopped(monkeypatch):
    from caasi.core import runs as runs_core

    monkeypatch.setattr(runs_core, "effective_status",
                        lambda record, config: runs_core.STOPPED)
    assert C.wait_for_terminal(_fake_record(), None, poll_interval=0.0) == runs_core.STOPPED


def _fake_record(run_id="run-1"):
    return type("R", (), {"run_id": run_id, "directory": None})()


def test_wait_for_terminal_times_out_rather_than_hanging(monkeypatch):
    from caasi.core import runs as runs_core

    monkeypatch.setattr(runs_core, "effective_status",
                        lambda record, config: runs_core.RUNNING)
    with pytest.raises(C._Stopped) as err:
        C.wait_for_terminal(_fake_record(), None, poll_interval=0.0, timeout=0.01)
    assert "did not reach a terminal state" in err.value.detail


def test_wait_polls_are_reported(monkeypatch):
    from caasi.core import runs as runs_core

    seq = iter([runs_core.RUNNING, runs_core.RUNNING, runs_core.TERMINAL_OK])
    monkeypatch.setattr(runs_core, "effective_status", lambda record, config: next(seq))
    seen: list[str] = []
    C.wait_for_terminal(_fake_record(), None, poll_interval=0.0, on_poll=seen.append)
    assert seen == [runs_core.RUNNING, runs_core.RUNNING, runs_core.TERMINAL_OK]


def test_exit_code_helper_reads_the_recorded_code(tmp_path):
    (tmp_path / "exit_code").write_text("7\n")
    record = type("R", (), {"directory": tmp_path})()
    assert C._run_exit_code(record) == 7


def test_exit_code_helper_is_none_without_a_directory():
    record = type("R", (), {"directory": None})()
    assert C._run_exit_code(record) is None


def test_exit_code_helper_is_none_when_missing(tmp_path):
    record = type("R", (), {"directory": tmp_path})()
    assert C._run_exit_code(record) is None


# ---------------------------------------------------------------------------
# Run status for a locally-deployed target
#
# PRE-EXISTING DEFECT, discovered during F2 (not an F2 regression): the status
# discriminator keyed on the target's NAME, so a run whose target is called
# `local` but which executes in the deployed sandbox fell through to LOST --
# even when it had finished successfully with exit_code=0. Composition waits for
# a terminal state, so it hung on such runs. Covered here as a regression.
# ---------------------------------------------------------------------------


def _run_record(tmp_path, *, target, transport, remote_dir=None, pid=None):
    from caasi.core.runs import RunRecord

    return RunRecord(
        run_id="20260101-000000-t",
        name="t",
        backend="python",
        kind="workload",
        command=["python3", "x.py"],
        cwd=str(tmp_path),
        created="2026-01-01T00:00:00+08:00",
        pid=pid,
        directory=tmp_path,
        target=target,
        target_transport=transport,
        remote_run_dir=str(remote_dir) if remote_dir else None,
    )


def test_local_target_sandbox_run_with_zero_exit_is_succeeded(tmp_path):
    """The defect: `target: local` + deployed run dir was reported as LOST."""
    from caasi.core import runs as runs_core

    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    (sandbox / "exit_code").write_text("0")

    record = _run_record(tmp_path, target="local", transport="local", remote_dir=sandbox)
    assert runs_core.effective_status(record, None) == runs_core.TERMINAL_OK


def test_local_target_sandbox_run_with_nonzero_exit_is_failed(tmp_path):
    from caasi.core import runs as runs_core

    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    (sandbox / "exit_code").write_text("7")

    record = _run_record(tmp_path, target="local", transport="local", remote_dir=sandbox)
    assert runs_core.effective_status(record, None) == runs_core.TERMINAL_FAIL


def test_a_run_without_a_deployed_dir_is_unaffected(tmp_path):
    """The ordinary local run still reports on its process, not the sandbox."""
    from caasi.core import runs as runs_core

    record = _run_record(tmp_path, target="local", transport="local", pid=None)
    assert runs_core.effective_status(record, None) == runs_core.LOST


def test_build_step_reads_the_real_build_result_api():
    """A successful build must not be reported as unknown.

    `BuildResult` exposes `ok` (derived from the return code); the step first read
    a non-existent `status` attribute, so a build that succeeded looked unknown and
    wrongly stopped the chain.
    """
    from caasi.core.build import BuildResult

    good = BuildResult(returncode=0, command=["colcon"], root="/x", workers=2, duration=1.0)
    assert good.ok is True
    assert not hasattr(good, "status") or getattr(good, "status", None) is None

    bad = BuildResult(returncode=1, command=["colcon"], root="/x", workers=2, duration=1.0)
    assert bad.ok is False
