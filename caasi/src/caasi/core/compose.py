"""Workload composition (Phase 7 Stage F2).

Runs a workload's declared ``steps`` by calling the **existing** caasi operations,
in order, on an **explicitly named** target:

    compatibility check -> deploy -> build -> run -> collect

Boundaries held here, each of which prevents a specific drift:

* **No new execution machinery.** Every step delegates to the same core function
  the CLI command uses (``deploy.execute_deployment``,
  ``build.execute_target_build``, ``runs.start_target_run``, the artifact
  collection path). Composition adds sequencing and reporting, nothing else.
* **No target choice.** The target is a required argument. There is no ranking, no
  defaulting, and no forwarding to a "better" target -- an incompatible target
  stops the run and says why. Allocation and scheduling remain deferred (R8).
* **No workflow engine.** Steps come from a fixed vocabulary; there are no
  conditionals, loops, retries or branching.
* **Same provenance as the manual path.** The records produced are the records the
  individual commands produce, so ``run logs``, ``run artifacts`` and ``check run``
  keep working on a composed run unchanged. No parallel "workflow record" exists.
* **A failing step stops the chain** and is named, together with whatever the
  earlier steps already produced, so an operator can debug with the individual
  commands rather than being told only that "the workload failed".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import project as projects
from . import workload as workload_core
from .workload import Workload, WorkloadError

#: Step outcome states.
STEP_OK = "ok"
STEP_SKIPPED = "skipped"
STEP_FAILED = "failed"


@dataclass
class StepResult:
    """What one composed step did."""

    name: str
    status: str
    detail: str | None = None
    #: Ids the step produced, using the SAME names the manual path records them
    #: under, so composed provenance is interchangeable with hand-run provenance.
    produced: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "produced": dict(self.produced),
        }


@dataclass
class CompositionReport:
    """The outcome of composing a workload on one target."""

    workload: str
    target: str
    steps: list[StepResult] = field(default_factory=list)
    #: Filled when the chain stopped early.
    failed_step: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        """True only when nothing failed -- including a declaration error.

        Keyed on ``error`` rather than ``failed_step`` because a workload that
        declares no steps fails without any step ever running; keying on the step
        alone reported that as success.
        """
        return self.error is None and self.failed_step is None

    def produced(self) -> dict[str, Any]:
        """All ids produced across the steps (deployment_id, build_id, run_id...)."""
        merged: dict[str, Any] = {}
        for step in self.steps:
            merged.update(step.produced)
        return merged

    def to_dict(self) -> dict[str, Any]:
        return {
            "workload": self.workload,
            "target": self.target,
            "ok": self.ok,
            "failed_step": self.failed_step,
            "error": self.error,
            "steps": [s.to_dict() for s in self.steps],
            "provenance": self.produced(),
        }


# ---------------------------------------------------------------------------
# Compatibility gate
# ---------------------------------------------------------------------------


def check_target_compatibility(
    target,
    requirements: dict[str, Any],
    inspection,
    tested: list[Any] | None = None,
    config=None,
) -> tuple[bool, str | None]:
    """Gate composition on the same verdicts `caasi target select` reports.

    Returns ``(proceed, reason)``. A target that **contradicts** a requirement stops
    the run. A requirement that could not be **measured** does not: absence of
    evidence must not be converted into evidence of absence, so it proceeds with a
    warning rather than being treated as a failure.

    This is advisory-by-construction: it never swaps in a different target, it only
    decides whether the *named* target may proceed.
    """
    from . import selection as selection_core

    report = selection_core.select_target(
        target, requirements, inspection, tested, strict=_strict_of(config)
    )

    if not report.reachable:
        return False, f"target '{target.name}' is unreachable: {report.error or 'unknown'}"

    blocking = [v for v in report.verdicts if v.verdict in ("missing", "incompatible")]
    if blocking:
        first = blocking[0]
        return False, (
            f"target '{target.name}' does not satisfy '{first.name}'"
            + (f" ({first.note})" if first.note else "")
        )

    return True, None


def unmeasured_requirements(
    target,
    requirements: dict[str, Any],
    inspection,
    tested: list[Any] | None = None,
    config=None,
) -> list[str]:
    """Requirements that could not be measured, for reporting (never blocking)."""
    from . import selection as selection_core

    report = selection_core.select_target(
        target, requirements, inspection, tested, strict=_strict_of(config)
    )
    return [f"{v.name}: {v.note}" for v in report.verdicts if v.verdict == "untested"]


def _strict_of(config) -> bool:
    """The project's `check.strict` setting, if a config was supplied.

    Companion checks must agree with `caasi check` about the same requirement, so
    this is read rather than assumed.
    """
    if config is None:
        return False
    try:
        return bool(config.get("check.strict", False))
    except Exception:  # noqa: BLE001 - a config that cannot answer is not strict
        return False


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------


class _Stopped(Exception):
    """Internal: a step failed, so the chain must stop."""

    def __init__(self, step: str, detail: str):
        super().__init__(detail)
        self.step = step
        self.detail = detail


@dataclass
class StepRunner:
    """The operations a step delegates to.

    Injected so the composition logic stays testable without a target, and so it is
    obvious that every step is a call into an **existing** caasi operation rather
    than a reimplementation.
    """

    deploy: Callable[[dict[str, Any]], dict[str, Any]]
    build: Callable[[dict[str, Any]], dict[str, Any]]
    run: Callable[[dict[str, Any]], dict[str, Any]]
    collect: Callable[[dict[str, Any]], dict[str, Any]]


def compose(
    workload: Workload,
    target_name: str,
    runner: StepRunner,
    on_step: Callable[[StepResult], None] | None = None,
) -> CompositionReport:
    """Run the workload's steps in order, stopping at the first failure.

    ``on_step`` is called after each step so a caller can stream progress without
    affecting the outcome.
    """
    report = CompositionReport(workload=workload.name, target=target_name)

    if not workload.steps:
        report.error = (
            f"workload '{workload.name}' declares no steps, so there is nothing to run "
            f"(add a 'steps:' list with operations from: {', '.join(workload_core.KNOWN_STEPS)})"
        )
        return report

    for step in workload.steps:
        result = StepResult(name=step.name, status=STEP_OK)
        try:
            produced = getattr(runner, step.name)(step.options) or {}
            result.produced = produced
            detail = produced.get("detail")
            result.detail = str(detail) if detail else None
        except _Stopped as stop:
            result.status = STEP_FAILED
            result.detail = stop.detail
            report.steps.append(result)
            report.failed_step = stop.step
            report.error = stop.detail
            if on_step is not None:
                on_step(result)
            return report
        except WorkloadError as err:
            result.status = STEP_FAILED
            result.detail = str(err)
            report.steps.append(result)
            report.failed_step = step.name
            report.error = str(err)
            if on_step is not None:
                on_step(result)
            return report
        except Exception as err:  # noqa: BLE001 - any step failure stops the chain
            result.status = STEP_FAILED
            result.detail = str(err)
            report.steps.append(result)
            report.failed_step = step.name
            report.error = str(err)
            if on_step is not None:
                on_step(result)
            return report

        report.steps.append(result)
        if on_step is not None:
            on_step(result)

    return report


def stopped(step: str, detail: str) -> _Stopped:
    """Signal that *step* failed and the chain must stop."""
    return _Stopped(step, detail)


# ---------------------------------------------------------------------------
# The real step runners (thin wrappers over existing operations)
# ---------------------------------------------------------------------------


def _run_exit_code(record) -> int | None:
    """Read a run's recorded exit code, if the run directory has one.

    Local to composition so the existing ``RunRecord`` surface is not extended for
    a reporting detail.
    """
    directory = getattr(record, "directory", None)
    if not directory:
        return None
    try:
        text = (Path(directory) / "exit_code").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    try:
        return int(text)
    except ValueError:
        return None


#: How long to wait between status polls of a launched run. Deliberately modest:
#: each poll is one round-trip, and a long run should not spend its time polling.
RUN_POLL_INTERVAL = 2.0


def wait_for_terminal(
    record,
    config,
    poll_interval: float = RUN_POLL_INTERVAL,
    on_poll: Callable[[str], None] | None = None,
    timeout: float | None = None,
) -> str:
    """Block until a launched run reaches a terminal state, and return that state.

    The composition layer needs **synchronous** semantics even though the run
    primitive is deliberately detached: ``runs.start_target_run`` launches and
    returns immediately, so at that moment nothing is known about the outcome.

    Conflating "the process was launched" with "the run succeeded" is exactly the
    bug this exists to prevent: a script that fails instantly is still a
    successfully *launched* process. Composition therefore waits, and treats only
    ``succeeded`` as success -- ``failed`` and ``stopped`` both stop the chain.

    The primitive is unchanged: ``caasi run start`` remains detached and returns
    immediately. Only composition waits.
    """
    import time as _time

    from . import runs as runs_core

    started = _time.monotonic()
    while True:
        status = runs_core.effective_status(record, config)
        if on_poll is not None:
            on_poll(status)

        if status in (runs_core.TERMINAL_OK, runs_core.TERMINAL_FAIL, runs_core.STOPPED):
            return status

        if timeout is not None and (_time.monotonic() - started) > timeout:
            raise stopped(
                "run",
                f"run {record.run_id} did not reach a terminal state within {timeout:g}s "
                f"(last status: {status})",
            )

        _time.sleep(poll_interval)


def build_step_runner(
    *,
    project_root: Path,
    target,
    config,
    experiment_path: Path | None = None,
    backend: str | None = None,
    workload_outputs: list[Any] | None = None,
    workload_name: str | None = None,
    selection_policy: str | None = None,
    selection_reason: str | None = None,
    workload_config: str | None = None,
    on_poll: Callable[[str], None] | None = None,
    json_output: bool = False,
) -> StepRunner:
    """Wire the steps to the existing caasi operations.

    Each function here does argument translation and outcome interpretation only --
    the work is done by the same core function the corresponding CLI command calls,
    so a composed run and a hand-run sequence produce identical artefacts and
    records.
    """
    from . import build as build_core
    from . import deploy as deploy_core
    from . import experiment as experiment_core
    from . import manifest as manifests
    from . import runs as runs_core
    from . import selection as selection_core
    from . import targets as targets_core

    manifest = manifests.read(project_root)
    project_name = manifest.name or project_root.name
    destination = deploy_core.resolve_deployment_destination(target, project_name)

    # The last run/experiment the run step used, so collect can find its outputs.
    state: dict[str, Any] = {}

    def _inspect():
        return targets_core.discover_target(target, config=config)

    def _requirements() -> dict[str, Any]:
        return workload_core.combined_requirements(manifest.requires or {}, None)

    def do_deploy(options: dict[str, Any]) -> dict[str, Any]:
        inspection = _inspect()
        if not inspection.reachable:
            raise stopped("deploy", f"target '{target.name}' is unreachable: {inspection.error}")

        spec = deploy_core.create_deployment_spec(project_root, target, config)
        record = deploy_core.execute_deployment(spec, config=config)

        if record.status not in ("verified", "active"):
            raise stopped(
                "deploy",
                f"deployment finished with status '{record.status}' "
                f"(see the deploy output for details)",
            )
        return {
            "deployment_id": record.deployment_id,
            "git_revision": record.git_revision,
            "destination": record.destination_path,
            "detail": f"deployed {record.deployment_id} ({record.status})",
        }

    def do_build(options: dict[str, Any]) -> dict[str, Any]:
        packages = options.get("packages") or options.get("packages_select")
        result = build_core.execute_target_build(
            target=target,
            project_root=project_root,
            config=config,
            packages_select=list(packages) if packages else None,
        )
        # BuildResult reports success through `ok` (derived from the return code),
        # which is what the build command itself uses. Reading a non-existent
        # `status` attribute made a *successful* build look unknown and stopped a
        # chain that should have continued.
        if not getattr(result, "ok", False):
            raise stopped(
                "build",
                f"build failed (return code {getattr(result, 'returncode', '?')})",
            )
        return {
            "build_id": getattr(result, "build_id", None),
            "build_returncode": getattr(result, "returncode", None),
            "detail": f"built on {target.name}",
        }

    def do_run(options: dict[str, Any]) -> dict[str, Any]:
        config_path = options.get("config") or experiment_path
        if config_path is not None:
            state["experiment_path"] = config_path
        command = options.get("command")

        # Workload identity travels with the run, so provenance can answer "which
        # workload produced this?" without inferring it from the experiment filename
        # or from `kind: workload` -- neither of which identifies *which* workload.
        # The selected target is recorded for the same reason: a composed run has a
        # target that was chosen, and that choice is part of its provenance.
        provenance_extra: dict[str, Any] = {"workload": workload_name}
        if workload_config:
            provenance_extra["workload_config"] = str(workload_config)
        # How this target came to be chosen is part of the run's provenance, not
        # just console output -- otherwise a run selected by policy is
        # indistinguishable from one the operator named by hand.
        if selection_policy:
            provenance_extra["selected_by"] = selection_policy
            if selection_reason:
                provenance_extra["selection_reason"] = selection_reason
        if experiment_path is not None:
            provenance_extra["experiment"] = str(experiment_path)

        if config_path is not None:
            record = runs_core.start_target_run(
                target=target,
                config=config,
                config_path=Path(config_path),
                name=options.get("name"),
                backend=backend,
                kind="workload",
                extra=dict(provenance_extra),
            )
        elif command:
            record = runs_core.start_target_run(
                target=target,
                config=config,
                config_path=experiment_path or (project_root / "caasi.yaml"),
                name=options.get("name"),
                backend=backend,
                kind="workload",
                extra_args=None,
                extra={**provenance_extra, "command": command},
            )
        else:
            raise stopped(
                "run",
                "the run step needs a 'config' (experiment file) or a 'command'",
            )

        # Launch succeeded -- but that is NOT the same as the run succeeding.
        # Wait for a terminal state and judge on that.
        status = wait_for_terminal(record, config, on_poll=on_poll)
        state["run_id"] = record.run_id
        state["run"] = record
        state["run_status"] = status

        if status != runs_core.TERMINAL_OK:
            code = _run_exit_code(record)
            raise stopped(
                "run",
                f"run {record.run_id} {status}"
                + (f" (exit code {code})" if code is not None else ""),
            )

        return {
            "run_id": record.run_id,
            "run_target": record.target,
            "run_status": status,
            "detail": f"{record.run_id} succeeded on {record.target}",
        }

    def do_collect(options: dict[str, Any]) -> dict[str, Any]:
        """Collect the run's declared outputs.

        Deliberately mirrors ``caasi run artifacts --collect``: the same inventory
        call, the same declarations, the same routing policy, the same collection
        function and the same host destination. Collection therefore cannot behave
        differently merely because it was reached through composition.
        """
        record = state.get("run")
        if record is None:
            raise stopped("collect", "no run to collect from (the run step did not execute)")

        from . import artifacts as arts

        # Declarations come from the workload (where they belong) and fall back to
        # the experiment the run used, so a composed run collects by exactly the
        # same rules the manual path applies.
        #
        # Workload declarations arrive as raw YAML, so they go through the same
        # parser the experiment path uses -- an unparsed list would be accepted
        # silently and then match nothing, collecting the wrong files.
        declarations = arts.parse_outputs(workload_outputs) if workload_outputs else []
        if not declarations:
            # Fall back to the experiment the run step actually used, resolved
            # against the project root the way the run step resolved it.
            run_config = state.get("experiment_path") or experiment_path
            if run_config is not None:
                path = Path(run_config)
                if not path.is_absolute():
                    path = project_root / path
                try:
                    declarations = list(experiment_core.load_experiment(path).outputs)
                except Exception:  # noqa: BLE001 - best effort, as the CLI path is
                    declarations = []

        policy = arts.RoutingPolicy.from_config(config)

        # Results live in the run's WORKING directory (what the author sees), not
        # in the run directory, which holds caasi's bookkeeping and provenance.
        # Using the run directory inventories the wrong tree and silently finds
        # nothing -- and this is the same mistake the E1 stage made once already.
        root = record.cwd or record.remote_run_dir or str(record.directory or "")

        if not root:
            return {"detail": "no output location recorded for this run"}

        if record.target_transport == "ssh":
            inventory = arts.inventory_remote(
                target, root, record.run_id, declarations=declarations, policy=policy
            )
        else:
            inventory = arts.inventory_directory(
                Path(root), record.run_id, declarations=declarations, policy=policy
            )

        plan = arts.plan_collection(inventory)
        if not plan.to_fetch:
            # Nothing needs copying. On a local target the files are already on
            # this machine, so "left in place" is the correct and complete answer,
            # not a failure to collect -- saying so avoids reporting a successful
            # local run as though collection had done nothing.
            if record.target_transport != "ssh":
                return {
                    "artifacts_collected": len(inventory),
                    "artifacts_left_on_target": 0,
                    "detail": (
                        f"{len(inventory)} artifact(s) already on the workstation "
                        f"(local target, nothing to copy)"
                    ),
                }
            return {
                "artifacts_collected": 0,
                "artifacts_left_on_target": len(plan.to_leave),
                "detail": (
                    f"nothing routed to the workstation "
                    f"({len(plan.to_leave)} left in place)"
                ),
            }

        host_root = (Path(record.directory) / "artifacts") if record.directory else Path(root)
        arts.collect_artifacts(target, root, inventory, host_root)
        return {
            "artifacts_collected": len(plan.to_fetch),
            "artifacts_left_on_target": len(plan.to_leave),
            "detail": f"collected {len(plan.to_fetch)} artifact(s)",
        }

    return StepRunner(deploy=do_deploy, build=do_build, run=do_run, collect=do_collect)


def load_composition_context(project_root: Path, workload_name: str):
    """Resolve the workload and the requirements the compatibility gate should use."""
    workload = workload_core.find_workload(project_root, workload_name)
    if workload is None:
        known = ", ".join(w.name for w in workload_core.list_workloads(project_root)) or "-"
        raise WorkloadError(
            f"no workload matching '{workload_name}' (known: {known})"
        )
    from . import manifest as manifests

    manifest = manifests.read(project_root)
    requirements = workload_core.combined_requirements(manifest.requires or {}, workload)
    return workload, requirements, list(manifest.tested or [])


def find_project_root() -> Path | None:
    return projects.find_project_root()
