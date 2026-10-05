# Phase 7 Stage F2 Report: Workload Steps and Lifecycle Composition

**Status:** Completed & Empirically Verified — **accepted as complete** (G3 closed, G5 closed with F1). G1/G2 remain pending F1 acceptance; G4 outstanding.
**Date:** October 2026
**Addresses gaps:** **G3** (lifecycle is independent commands), completes **G5** (workload object)
**Requirements:** R1, R4, R5, R7 (and R4a/R4b heterogeneous + workstation-initiated)
**Design:** [`stage-f2-design.md`](stage-f2-design.md)
**Traceability:** [`traceability.md`](traceability.md)

---

## 1. What was implemented

### 1.1 `steps` — a closed vocabulary of existing operations

```yaml
workload:
  name: ros2-build
  requires:
    ros2: {version: jazzy}
  steps:
    - deploy
    - build
    - run: {config: experiments/hello2.yaml}
    - collect
  outputs:
    - {path: "*.out", kind: metrics, destination: workstation}
```

`KNOWN_STEPS = ("deploy", "build", "run", "collect")`. Two spellings are accepted —
bare (for steps needing no configuration) and single-key mapping (name + options)
— and **an unknown step is rejected at parse time**, because silently skipping a
step the author wrote would run a different sequence than the declaration says.

There is no conditional, loop, expression, retry or branch vocabulary. A workload
needing control flow is a program, invoked via `run` (R3).

### 1.2 `caasi.core.compose`

`compose()` runs the steps in order through a `StepRunner` whose four functions are
**thin wrappers over the existing core operations** — the same functions the CLI
commands call. Every step failure stops the chain (`_Stopped`), naming the failed
step and preserving the ids already produced.

`wait_for_terminal()` gives the composition layer **synchronous** semantics without
changing the primitive: `runs.start_target_run` remains detached, and only
composition waits.

### 1.3 `caasi workload` (new command group)

```bash
caasi workload list [--json]
caasi workload inspect <name> [--json]
caasi workload run <name> --target <t> [--dry-run] [--json] [--skip-check]
```

`--target` is **required** and has no default.

---

## 2. Explicit reporting requested

### 2.1 G1–G5 status and evidence

| Gap | Status | Evidence |
| :--- | :--- | :--- |
| **G1** nothing decides a target | **Open**, awaiting F1 acceptance | F1 delivered advisory, requirement-driven, inspectable `target select`; F2 reuses its verdicts as the composition gate |
| **G2** `check` is local-only | **Open**, awaiting F1 acceptance | F1 made fact sourcing target-aware, reusing the Check Contract ladder |
| **G3** lifecycle is independent commands | **CLOSED by F2** | four-step composition validated end to end on the real `u24-307`, and the individual commands still work unchanged |
| **G4** legacy `remotes:` shim | **Open — outstanding cleanup** | untouched by F2; still tracked as retirement work |
| **G5** no workload object | **CLOSED by F1+F2** | F1 gave the minimal model; F2 added `steps`/`outputs`; exercised on a general Python workload, a ROS 2 workload and the real OpenMover project |

Per the standing rule, G3 and G5 are claimed closed **only because the evidence
below is recorded**; G1/G2 remain open pending explicit acceptance, and G4 is
unaffected.

### 2.2 Which parts of F2 are actually implemented

| Designed | Implemented | Notes |
| :--- | :--- | :--- |
| closed `steps` vocabulary | **yes** | unknown steps rejected at parse time |
| unknown steps rejected at parse time | **yes** | with the known list in the error |
| execute through existing operations | **yes** | same core functions as the CLI |
| preserve individual commands | **yes** | verified; composed runs appear in `run list` |
| stop on failure, identify the step | **yes** | exit 1; names the step and the error |
| same provenance as the manual path | **yes** | verified via `run artifacts` on a composed run |
| `--target` explicit and required | **yes** | no default, no forwarding |
| no auto-select / forward / allocate | **yes** | an incompatible target stops the run |
| no queues / scheduling / retries / DAG | **yes** | no such vocabulary exists |
| preserve output/artifact semantics | **yes** | reuses `parse_outputs` + `RoutingPolicy` |
| `--dry-run` | **yes** | plan + compatibility verdict, touches nothing |

### 2.3 Real-machine validation

| Case | Result |
| :--- | :--- |
| **CPU-only workload on `u24-307`** | `deploy → run → collect` succeeded; artifact collected |
| **GPU-capable workload on `local`** | succeeded; GPU work delegated to `nvidia-smi` (never reimplemented) |
| **Remote execution initiated from the workstation** | proven — the artifact reads `host=u24-307 rclpy ok, ROS_DISTRO=jazzy`, over non-interactive SSH |
| **Full four-step composition on `u24-307`** | `✔ deploy ✔ build ✔ run ✔ collect`, `rc=0` |
| **Real OpenMover workload** | gate correctly **refused** it on `u24-307` (project requires `isaac_lab`, absent on the CPU-only target) — and a re-check confirmed nothing was deployed |
| **Simple/general workload (plain Python)** | proven not OpenMover-specific: the same model carried a framework-agnostic Python workload unchanged |
| **Failure path** | chain stopped at `run`, `collect` did not execute, exit 1; the script's own exit code 7 surfaced |
| **GPU workload on `local`** | `run_status=succeeded`; reported `1 artifact(s) already on the workstation (local target, nothing to copy)` |

The heterogeneous pair behaved exactly as required: the CPU-only machine was
**satisfiable** for CPU-only work and **incompatible** for GPU/Isaac work, entirely
from measured facts.

### 2.4 Provenance produced by the composed path

A composed run records the **same** records the manual path records — no parallel
workflow record exists:

```text
build_id=build-u24-307-1791222349-ec5ecb  build_returncode=0
deployment_id=deploy-builddemo-20261005-174509-ae558435
destination=/home/zar/caasi-deployments/builddemo
git_revision=ae558435adaf20e7c545d902bbc304b6e1d977dc
run_id=20261006-014615-hello2  run_status=succeeded  run_target=u24-307
artifacts_collected=1  artifacts_left_on_target=0
```

Verified by inspecting the composed run **through the existing commands**:
`caasi run list` shows composed runs alongside manual ones (including one recorded
`failed`), and `caasi run artifacts <composed-run-id>` lists the same artifacts with
the same routing. That is the "no parallel provenance model" requirement, tested
rather than asserted.

### 2.5 Defects discovered

**One fixed (pre-existing, exposed by F2):**

`runs.effective_status` returned **`lost`** for a run with `target: local` that
executed in the deployed sandbox (`remote_run_dir` set, `exit_code=0` on disk),
because the guard required `target != "local"`. Composition waits for a terminal
state, so it **hung**. The discriminator is now the **run directory**, not the
target's name. *Confirmed identical at HEAD — pre-existing, not an F2 regression.*
Fixed narrowly per decision; three regression tests added.

**Two found and fixed in F2's own code:**

1. **A launched run was treated as a succeeded run.** `start_target_run` is
   detached by design, so composition must wait; without that, a script that failed
   instantly was reported `✔ run` and the chain continued to `collect`. Composition
   now waits for a terminal state and treats only `succeeded` as success — `failed`
   and `stopped` both stop the chain. The primitive is unchanged.
2. **The build step read a non-existent attribute.** It checked `result.status`,
   but `BuildResult` reports success through **`ok`** (derived from the return
   code), which is what the build command itself uses. A *successful* build was
   therefore reported `unknown` and wrongly stopped the chain. Fixed; regression
   test added.

**Two found earlier in F2's collection wiring:**

3. **The build record was read from the wrong place**, and **the collection root
   was wrong**: `collect` inventoried the run *directory* (caasi's bookkeeping)
   instead of the run's **working** directory, silently finding nothing. This is
   the same mistake the E1 stage made once already — worth noting as a recurring
   trap.
4. **Workload `outputs` were passed unparsed**, so declarations matched nothing and
   the wrong files were collected (the experiment config rather than the result).

**One reported, deliberately NOT fixed (pre-existing, needs a design decision):**

For `target: local`, `build` records its provenance against the **project root**
— `build.execute_target_build` sets `destination_path=str(project_root)` on the
local-workspace path (`src/caasi/core/build.py`), writing `.caasi-build.json`
there. `run`, however, looks for that record at the **deployment destination**
(`build.get_last_build_status(target, dest, ...)` from
`runs.start_target_run`), i.e. `/home/zar/.caasi/deployments/local/<project>`.

Observed during validation on the real OpenMover project: the build wrote
`.caasi-build.json` into the project root of the fixture copy, while `run`
reported *"No completed build found on target 'local' at
'/home/zar/.caasi/deployments/local/openmover'"*.

So `caasi build --target local` followed by `caasi run --target local` **already
fails today**, independent of F2 — the two sides disagree about where a local
build record lives.
*Confirmed identical at HEAD.* Left unfixed per decision, because the correct
long-term contract is genuinely undecided — project-root builds, destination
builds, or an explicit project-vs-deployed distinction. No workaround logic was
added.

### 2.6 Does the model still support R1–R10 without premature implementation?

| Req. | Supported? | How F2 leaves it possible without implementing it |
| :--- | :--- | :--- |
| R1 workstation as control plane | **yes** | composition is driven entirely from the workstation; the remote artifact proves no interactive login is needed |
| R2 target-aware tools | **yes** | untouched; shares the target-knowledge plumbing F1 introduced |
| R3 domain owners | **yes** | every step delegates to an existing operation; nothing reimplemented |
| R4 target-aware execution | **yes** | deploy/build/run/collect composed per target |
| R4a heterogeneous targets | **yes** | demonstrated on the CPU-only and GPU machines |
| R4b workstation-initiated | **yes** | preserved and validated |
| R5 workload abstraction | **yes** | one model across Python, ROS 2 and OpenMover |
| R6 target selection | **yes** | F2 *consumes* F1's verdicts and never selects |
| R7 lifecycle composition | **yes** | delivered, with the individual commands intact |
| R8 multi-target control plane | **not implemented, not blocked** | the target is a parameter of the chain, so re-running against another target is already expressible; no queue/scheduler/allocator exists or is required |
| R9 result/artifact flow | **yes** | declaration-driven routing reused unchanged; destination stays independently configurable |
| R10 monitoring web UI | **not implemented, not blocked** | a read-only view over existing records is unaffected by this design |

**Nothing in F2 forecloses R8 or R10**, and neither was started.

---

## 3. What F2 does NOT do

- **No target selection, forwarding or allocation** — the target is named; an
  incompatible one stops the run and says why.
- **No queues, scheduling, retries or resource claims** (R8).
- **No multi-target execution** — one workload, one target.
- **No DAG or workflow engine** — a fixed ordered vocabulary only.
- **No `--detach`** — synchronous composition semantics are the agreed meaning.
- **No web UI** (R10), no F3 work.
- **No fix or workaround** for the pre-existing build/run destination mismatch.
- **No fix** for the legacy `remotes:` shim (G4).

---

## 4. Tests

**41 new tests** in `tests/test_compose.py`: the closed step vocabulary (bare and
mapping spellings, unknown-step rejection naming the known steps, multi-key and
non-mapping rejection, ordering preservation, absence of any control-flow
vocabulary); composition (ordering, omission respected, a failing step stopping
the chain, error text, earlier steps recorded, provenance surviving a later
failure, unexpected exceptions, no-steps reporting, JSON serialisation, progress
callbacks); the compatibility gate (contradicted requirement, unreachable target,
satisfied requirements, **unmeasured not blocking**, out-of-range not blocking,
and that it never suggests another target); terminal-state waiting (success,
failure, stopped, timeout rather than hanging, poll reporting, exit-code reading);
and the pre-existing status defect (local-target sandbox run with exit 0 →
`succeeded`, non-zero → `failed`, and ordinary local runs unaffected).

One F1 test was updated because F2 legitimately replaced its placeholder contract
(`steps` as raw passthrough → validated `Step` objects).

**Full suite: 1140 passed, 1 failed.** The failure is the pre-existing
`test_perception_cmd.py` terminal-width artifact, unrelated to this stage.

---

## 5. Files changed

| File | Change |
| :--- | :--- |
| `src/caasi/core/compose.py` | **new** — composition, compatibility gate, terminal-state waiting, real step runners |
| `src/caasi/cli/workload_cmd.py` | **new** — `caasi workload list|inspect|run` |
| `src/caasi/core/workload.py` | `Step` model and the closed `KNOWN_STEPS` vocabulary |
| `src/caasi/core/runs.py` | **pre-existing defect fix** — status discriminator uses the run directory, not the target name |
| `src/caasi/cli/main.py` | register the group; platform help panel |
| `src/caasi/i18n/en.py` | 25 new strings |
| `tests/test_compose.py` | **new** — 41 tests |
| `tests/test_selection.py` | one F1 test updated to the F2 contract |
| `plan/phases/phase-07/traceability.md` | G3/G5 closure with evidence |

Reference trees unchanged: `openmover_robot` `f17c242a…`, `openmover_ws`
`1e09f5de…`, `caasi-workspace/openmover` 0 dirty. Remote validation fixtures were
removed from `u24-307`; the canonical OpenMover **project** was never modified (a
copy was used).

---

## 6. Next step

**F3** (target-aware tool invocation, R2) is **not** started, per instruction.

Two items carry forward as deliberate open work, both pre-existing and neither
blocking F3:

- the **build/run destination mismatch** for `--target local`, which needs a
  decision on the intended contract before it can be fixed;
- **G4**, the legacy `remotes:` shim retirement.

Also open: G1/G2 await explicit acceptance of the F1 evidence.
