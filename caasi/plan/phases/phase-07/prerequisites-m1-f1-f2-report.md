# Phase 7 Report: M1 Workload Identity, F1 Ladder Consolidation, F2 Local Contract

**Status:** Completed & Empirically Verified
**Date:** October 2026
**Origin:** [`r8-architecture-review.md`](r8-architecture-review.md) — the three prerequisites for any future `--where` stage
**Traceability:** [`traceability.md`](traceability.md)

Three narrowly-scoped changes, each approved before implementation. **No `--where`
work, no queue, no scheduler, no reservation.**

---

## 1. M1 — workload identity in provenance

### 1.1 The defect

A composed run recorded `kind: workload` and the **experiment** name, but not the
**workload** name. Verified on a real run before the fix:

```yaml
name: hello2          # the EXPERIMENT, not the workload
kind: workload        # says a workload ran; not which one
extra: {experiment: experiments/hello2.yaml}
```

`ros2-build` — the workload — appeared nowhere. So once more than one workload
existed, provenance could not answer *"which workload produced this?"*, and two
workloads sharing one experiment were indistinguishable.

### 1.2 The fix

The run step now records workload identity on the run record, in both the
config-driven and command-driven branches:

```yaml
extra:
  workload: beta
  workload_config: /tmp/m1test/workloads/beta.yaml
  experiment: experiments/job.yaml
```

### 1.3 Validation

Deliberately built as **two workloads sharing one experiment** (`alpha`, `beta`,
both running `experiments/job.yaml`) — the case the old provenance could not
answer. The run records `workload: beta`, and the recorded
`workload_config` distinguishes it from `alpha`. Verified on real composed runs on
**both** targets:

```text
workload → experiment → deployment → build → run → artifacts
```

The chain's first link now exists. It is recorded explicitly rather than inferred
from the experiment filename or from `kind: workload`, as required.

---

## 2. F1 consolidation — one requirement ladder

### 2.1 The defect

The F1 design intended `target select` to be *another entry point of the existing
CheckEngine*, but `check.py` was left unchanged and the ladder was re-implemented in
`selection.py`. The paths agreed for default projects but **diverged under
`check.strict`**: `caasi check` reported `incompatible` (exit 3) where
`target select` reported a `warning` (exit 0) for the same requirement.

### 2.2 The fix

One shared ladder, `check.evaluate_requirement(name, entry, detected, tested)`, now
used by **both** entry points:

- `ProjectRequirementsChecker` passes facts **detected on this machine**;
- `selection.evaluate_requirements` passes facts **discovered on a target**.

Only the *fact source* differs. The `detected` value is supplied by the caller,
which is what lets one ladder serve a machine that is not this one.

`check.strict` is now **read and propagated** — through `select_target`, `select_all`,
`target select`, and the composition gate — instead of being hardcoded.

Two target-specific distinctions were preserved deliberately, because they concern
*where a fact came from* rather than how it is judged:

- **not-measured vs absent** — a component never probed is `untested` (absence of
  evidence is not evidence of absence); a probed component that is missing is
  `missing`;
- **present without a version** — reported as uncomparable, with a note naming the
  cause.

### 2.3 Validation — the divergence is gone

Same fact (`ros2: jazzy`), same requirement, both paths:

| `check.strict` | `caasi check` | `caasi target select` | Agree |
| :--- | :--- | :--- | :--- |
| `false` | `warning` | `warning` | ✅ |
| `true` | `incompatible` | `incompatible` | ✅ |
| `false` (satisfied) | `ready` | `ready` | ✅ |
| `true` (satisfied) | `ready` | `ready` | ✅ |

**No new selection semantics were added**, as instructed. The `compose` gate and
`unmeasured_requirements` also honour `check.strict`, so composition cannot disagree
with `check` either.

**Note on the change in note wording:** consolidation means selection now emits the
Check Contract's i18n notes (e.g. *"detected jazzy, outside required 'humble' — not
tested by Caasi"*) instead of the second copy's hand-written prose. The **verdicts
are unchanged**; only the phrasing became the contract's. One F1 test was updated to
assert the shared wording — it was asserting the duplicate's text.

---

## 3. F2 — local build/run destination contract

### 3.1 The defect

For `target: local`: `build` ran in and recorded to the **project root**, while
`run` looked for the record at the **deployment destination**. So
`caasi build --target local` followed by `caasi run --target local` **already
failed**, independent of F2.

### 3.2 The decision (recorded in [`f2-local-build-run-contract.md`](f2-local-build-run-contract.md))

The contract was ambiguous between project-root, destination, and an explicit
distinction. **Caasi's existing behaviour already answers it**, so this was a
question of resolving an inconsistency rather than choosing a preference:

**`local` is a deployed target, exactly like a remote one.**

| Behaviour | Points at |
| :--- | :--- |
| `deploy` for `local` | `~/.caasi/deployments/local/<project>` — a **deployed copy** |
| `run` **requires** an active deployment | *"run 'caasi deploy local' first"* |
| `run` executes at | the **deployment destination** |

Two of three sides already agreed; the build's local-workspace path was the
outlier.

**Canonical contract:** `deploy → build → run` all operate on the deployment
destination for **every** target, `local` included.

### 3.3 The fix — smallest consistent correction

The discriminator changed from *"is this target named `local`?"* to *"does this
target have a deployment?"*. This **removes a special case** rather than adding a
lookup fallback (explicitly discouraged).

The standalone **local workspace build is preserved** for its real purpose — a
`colcon build` in one's own checkout with no deployment to belong to. It is not
deleted, because that workflow is legitimate.

### 3.4 Validation

| Case | Before | After |
| :--- | :--- | :--- |
| `build` then `run` on `--target local` | **failed** ("No completed build found") | **works**; record at the deployment, not the project root |
| Composed `deploy → build → run → collect` on `local` | impossible (stopped at `build`) | **all four steps succeed** |
| Standalone workspace build (no deployment) | records in the project root | **unchanged** |
| Remote (`ssh`) build | deployment path | **unchanged** |

The composed run on `local` now reports
`build_id=build-local-…, build_returncode=0`, a `deployment_id`, `run_status=succeeded`
and its collected artifact — the whole chain that previously could not complete.

**This matters before `--where`**, as required: `local` is now a valid target for
the same lifecycle semantics as remote targets, so a selection policy could
legitimately choose it.

---

## 4. Tests

| Area | Tests |
| :--- | :--- |
| M1 workload identity | 3 new — recorded in both branches; **two workloads sharing one experiment are distinguishable** |
| F1 consolidation | 3 new — check/select agree across `strict` values; the shared ladder is actually called; `strict` is not hardcoded |
| F2 local contract | 3 new — deployed local build records at the deployment; standalone workspace build preserved; the name-based discriminator no longer decides alone |
| Updated | 1 F1 test re-pointed at the shared contract's wording (it asserted the duplicate's prose) |

**Full suite: 1184 passed, 1 failed.** The failure is the pre-existing
`test_perception_cmd.py` terminal-width artifact, unrelated to these changes.

---

## 5. Files changed

| File | Change |
| :--- | :--- |
| `src/caasi/core/check.py` | **new** shared `evaluate_requirement`; local checker delegates to it |
| `src/caasi/core/selection.py` | delegates to the shared ladder; `strict` threaded, no longer hardcoded |
| `src/caasi/core/compose.py` | records workload identity; gate honours `check.strict` |
| `src/caasi/core/build.py` | deployment presence (not the target name) selects the build path |
| `src/caasi/cli/workload_cmd.py` | passes workload identity and config to the gate |
| `src/caasi/cli/target_cmd.py` | `target select` honours `check.strict` |
| `tests/test_compose.py`, `tests/test_target_build.py`, `tests/test_selection.py` | regression tests |

Reference trees unchanged: `openmover_robot` `f17c242a…`, `openmover_ws`
`1e09f5de…`, `caasi-workspace/openmover` 0 dirty. All fixtures removed; the local
`m1demo` deployment was removed.

---

## 6. Open items after this pass

| Item | Status |
| :--- | :--- |
| **F1 ladder consolidation** | **DONE** — divergence eliminated |
| **F2 local build/run contract** | **DONE** — semantics decided and implemented |
| **M1 workload identity** | **DONE** |
| **G4** `remotes:` retirement | **Still open** — independent cleanup, untouched |
| **DDS-over-Tailscale** | **Still open** — environmental, untouched |

The next stage (`--where`) is **not started**, per instruction. Its two
prerequisites are now satisfied.
