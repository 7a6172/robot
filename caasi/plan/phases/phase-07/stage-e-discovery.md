# Phase 7 Stage E Discovery: Two Target Lifecycles

**Status:** Discovery / Architecture Proposal (no implementation)
**Date:** October 2026
**Predecessor:** Stage D (real remote target validation, [`stage-d-report.md`](stage-d-report.md))
**Companion:** [`stage-e-investigation.md`](stage-e-investigation.md) (artifact/result routing evidence)
**Mandate:** find the cleanest generalized architecture; do not hard-code OpenMover behaviour

---

## 0. Evidence classes

| Class | Meaning |
| :--- | :--- |
| **Existing capability** | Inspected in code, and exercised where practical |
| **Observed gap** | Demonstrated by direct inspection or measurement |
| **Measured behaviour** | A number or state obtained by running something |
| **Future design** | Proposed only; not implemented |

Two machines were used as evidence: the workstation `u24-z690p` and the real
remote target `u24-307` (from Stage D).

---

## 1. The two lifecycles

The user's framing, restated as the thing the architecture must represent:

### A — Compute / simulation target (temporary)

```text
submit job → deploy/prepare → build if needed → execute
           → produce requested outputs → collect/transfer outputs → optional cleanup
```

The target is a **transient resource**. Its deployment exists to serve the job.
What matters afterwards is the **results**. The machine may be released.

### B — Persistent deployment target (robot)

```text
deploy → build → install → configure → enable/autostart
       → operate → update/redeploy → possibly rollback
```

The target is an **operational installation**. Successful deployment means the
robot comes up correctly *without* the workstation, and *after reboot*. We do not
collect the deployment back.

**These have opposite terminal states.** A ends by extracting results and
possibly erasing the target; B ends by leaving a durable runtime behind. An
architecture that models only one will be wrong for the other.

---

## 2. Q1 — What is the current model of `deployment` vs `run`?

### 2.1 `deployment` = a *materialization event*

**Existing capability.** `DeploymentSpec` (frozen) + `DeploymentRecord`
(`caasi/core/deploy.py`):

```text
DeploymentRecord: deployment_id, project_name, project_version, git_revision,
                  target_name, target_transport, destination_path, deployed_at,
                  status, target_environment, file_count, total_bytes,
                  transferred_bytes, duration_seconds, changed_files, errors, warnings
```

Semantics, as implemented:

- One **content synchronization** of project source to a target destination.
- Excludes development content (`DEFAULT_EXCLUDE_PATTERNS`: `build`, `install`,
  `log`, `.git`, `.caasi/runs`, …).
- Writes two-sided provenance (`<dest>/.caasi-deployment.json` + host record).
- `status` ∈ `verified | active | dry_run | failed | verification_failed`.

**Crucially: there is no terminal or retired state, and no way to remove a
deployment.** Once made, a deployment is implicitly permanent.

### 2.2 `run` = an *execution event*

**Existing capability.** `RunRecord`:

```text
RunRecord: run_id, name, backend, kind, command, cwd, created, pid, paused,
           stopped, extra, directory, target, target_transport, pgid,
           destination, deployment_id, build_id, git_revision, project,
           remote_run_dir
```

- `kind` today ∈ `experiment | ros | capture | import` (**measured** across 33
  local run manifests).
- Carries the full provenance chain to deployment and build.
- `backend` ∈ `sim | lab | python`.

### 2.3 The coupling between them

**Observed gap (structural).** `start_target_run` **hard-requires** an active
deployment, and additionally a successful build when ROS packages are present:

```python
deployment = deploy_core.get_deployment_status(target, dest, config)
if not deployment:
    raise RuntimeError("No active deployment found on target ...")

last_build = build_core.get_last_build_status(target, dest, config)
if has_ros and (not last_build or last_build.status != "success"):
    raise RuntimeError("No completed build found on target ...")
```

So the current model is a **strict linear chain with one direction of
dependency**:

```text
deployment ──required by──▶ build ──required by──▶ run
```

This is exactly right for workflow **B** and an unnecessary constraint for
workflow **A** (a self-contained job, or a container image that *is* the
environment, needs no project deployment at all).

---

## 3. Q2 — What existing capabilities support each workflow?

### 3.1 Capabilities that serve workflow A (compute/job) — partial

| Capability | Status | Evidence |
| :--- | :--- | :--- |
| Remote target discovery + reachability | **Exists** | Stage A; `caasi target check u24-307` (Stage D) |
| Remote deployment of project source | **Exists** | Stage B; 835 files / 40.4 MiB to `u24-307` |
| Target-native build | **Exists** | Stage C1; 185.83 s, workers derived from target |
| Detached remote execution | **Exists** | Stage C2 + Stage D; survived SSH SIGKILL |
| Log capture + retrieval | **Exists** | `caasi run logs`, remote `stdout/stderr.log` |
| Run status / inspect | **Exists** | `caasi run status|inspect` (depth-2 remote file listing) |
| Provenance chain | **Exists** | `deployment_id → build_id → run_id` on both sides |
| Experiment declarations (`args`, `env`, `backend`) | **Exists** | `Experiment` dataclass |
| **Result/output collection** | **MISSING** | Stage E investigation G-E2: host had **no record** of outputs created on the target |
| **Output declaration** | **MISSING** | G-E3: no `outputs:` in experiment schema |
| **Routing policy** | **MISSING (designed)** | proposal §5 `artifact_routing`; 0 occurrences in `src/` |
| **Teardown / release of a temporary target** | **MISSING** | no teardown/undeploy function anywhere |
| Container-backed job execution | **Partial** | `container run` = `docker run --rm [--gpus]`, local only; no mounts, no remote, no restart policy |

**Assessment.** Workflow A is ~70 % present: everything up to *execution and
logs* works on a real remote machine. The **collection** half is absent, and
there is no way to release a temporary target.

### 3.2 Capabilities that serve workflow B (persistent robot) — mostly absent

| Capability | Status | Evidence |
| :--- | :--- | :--- |
| Deploy project source to target | **Exists** | Stage B |
| Build on target | **Exists** | Stage C1 |
| Overlay `setup.bash` produced on target | **Exists** | Measured: `.../openmover/install/setup.bash` (1139 B) |
| Overlay sourced *during a caasi run* | **Exists** | `run.sh` wrapper sources underlay + overlay inline |
| **Overlay referenced persistently (shell env)** | **MISSING** | Measured on `u24-307`: `grep caasi-deployments ~/.bashrc ~/.profile` → **no match** |
| **Service/supervisor unit (systemd etc.)** | **MISSING** | Verified: **0** systemd-unit references in `src/` (the 17 `service` hits are all ROS 2 middleware `ros2 service`, not init units); no user units and no `~/.config/autostart` entry on `u24-307` |
| **Container restart policy / durable mode** | **MISSING** | no `restart` handling in `containers.py` / `container_cmd.py` |
| **Boot resilience** | **MISSING** | Nothing would start the stack after reboot |
| **Configuration/state materialization** | **MISSING** | No notion of target-side config beyond deployed files |
| **Update / redeploy semantics** | **Partial** | re-deploy re-syncs files; no lifecycle notion of "update" |
| **Rollback** | **MISSING** | no prior-version retention or revert |
| **Deployment retirement** | **MISSING** | `DeploymentRecord.status` has no retired state |

**Assessment.** Workflow B is ~30 % present. caasi can *put software and a build*
onto a robot, and can *source the overlay for the duration of a caasi-launched
process* — but it cannot make the robot **an operational, self-starting
installation**. That is the defining outcome of workflow B.

**The ROS 1 `install.sh` reference is the exact precedent.** Its persistent
aspect is not the package installation; it is the appended shell environment,
which `grep` shows precisely:

```text
echo "source /opt/ros/noetic/setup.bash"                                    >> ~/.bashrc
echo "source ~/openmover_robot/cartographer_ws/install_isolated/setup.bash --extend" >> ~/.bashrc
echo "source ~/openmover_robot/openmover_ws/devel/setup.bash --extend"      >> ~/.bashrc
echo 'export PYTHONPATH=$PYTHONPATH:.../scripts/hal'                        >> ~/.bashrc
echo "export DISABLE_ROS1_EOL_WARNINGS=1"                                   >> ~/.bashrc
```

That is workflow B's "install → configure" step, done by hand. caasi has **no
representation** for it.

---

## 4. Q3 — What is missing for temporary compute + result collection?

Four things, in dependency order:

1. **Output declaration** — a run must be able to say what it will produce.
   Without it, "requested outputs" cannot be distinguished from scratch files
   (Stage E G-E3).
2. **Result inventory** — what was actually produced, with identity (kind, size,
   hash), for both local and remote runs (G-E1).
3. **Routing/collection** — move the declared results to a configured
   destination (`workstation` or `target_local`), reusing the existing `rsync`
   transport (G-E2, G-E4).
4. **Release** — a way to express that a temporary target's deployment is
   finished. Today a deployment can never be retired, so a transient compute box
   accumulates permanent-looking state that caasi believes is still active.

**Not needed for A:** boot persistence, service units, rollback.

---

## 5. Q4 — What is missing for persistent deployment + startup/reboot lifecycle?

Five things:

1. **Install/configure step** — a target-side, idempotent act that makes the
   deployment *usable by the target itself*: persistent environment (the
   `install.sh` analogue), and any target-owned configuration. Distinct from
   "copy files" and from "build".
2. **Runtime enablement** — declaring what the robot's software stack *is*
   (which launch/entrypoint), and enabling it (systemd user/system unit,
   container restart policy, or another supervisor) without caasi becoming the
   supervisor.
3. **Verification of the persistent state** — "would this come up after reboot?"
   as a checkable property, analogous to how `deploy` verifies file
   materialization.
4. **Update semantics** — deploy a new revision over an operational install, with
   a defined handover (stop old, install new, start) rather than only
   re-syncing files.
5. **Rollback** — retain or reference the previous known-good revision.

**Not needed for B:** result collection as a primary concern; deployment teardown.

---

## 6. Q5 — Domain-owned vs caasi-orchestrated

This is the boundary question, and drawing it wrongly is how orchestrators become
monsters.

### Must remain domain-owned

| Concern | Owner | Why |
| :--- | :--- | :--- |
| Service definition, dependencies, restart policy | **systemd / container runtime** | caasi must not reimplement init |
| ROS 2 launch graphs, node composition, DDS config | **ROS 2** (`launch`, `ros2_control`) | Domain semantics; caasi must not parse launch files |
| Hardware bringup, drivers, device permissions | **Project / vendor** | Requires physical knowledge |
| Application configuration content | **Project** | caasi moves it, does not author it |
| Simulation engine / RL training internals | **Isaac Sim/Lab** | caasi launches, does not manage |

### Correctly caasi's to orchestrate

| Concern | Why caasi | Existing precedent |
| :--- | :--- | :--- |
| Target identity, reachability, capabilities | Spans all workflows | Stage A `Target` |
| Project → target materialization + provenance | Spans all workflows | Stage B `deploy` |
| Target-native build invocation | Project-agnostic, resource-aware | Stage C1 `build --target` |
| Execution supervision + lifecycle | Needs to work regardless of the domain's own supervisor | Stage C2/D `run` |
| **Result routing** | Spans all workflows; needs identity + provenance | Stage E |
| **Install/configure *invocation* + verification** | Needs to be repeatable, verifiable, target-agnostic | new in Stage E |
| **Enablement *declaration*** | caasi should know what the runtime is and that it is enabled, while delegating the mechanism | new in Stage E |
| Provenance across all of the above | The reason caasi exists | `provenance.py` |

### The line, stated once

> **caasi orchestrates *what* and *whether*; the domain owns *how*.**

caasi declares "this deployment's runtime is `systemd` unit `openmover.service`,
sourced overlay X, and it is enabled"; systemd decides how to run it. caasi
verifies that the unit exists and is enabled; it does not generate the unit's
internals beyond a template the project supplies.

This also implies caasi must **not** invent a bespoke supervisor. Where a domain
already has one (systemd for robots, the container runtime for jobs), caasi
*delegates and verifies*.

---

## 7. Q6 — What common abstraction should exist?

The two workflows share a great deal and differ in exactly two places. The
cleanest model separates the **shared spine** from the **lifecycle variant**.

```text
Project
   │
   └─▶ Deployment ──▶ Target ──▶ Execute ──▶ Outcome
        (materialize)   (facts)   (build/run)   │
                                               ├── Result     (workflow A)
                                               └── Runtime    (workflow B)
```

### 7.1 The existing spine is already right

`project → deployment → target → build → run → provenance` needs **no change**.
It is correct for both workflows and is proven on a real remote machine
(Stage D). Any redesign here would discard verified work.

### 7.2 The genuine differences are two, and both are *post-execution*

| | Workflow A (compute) | Workflow B (persistent) |
| :--- | :--- | :--- |
| **What the deployment is for** | to serve a job | to become an installation |
| **Terminal state** | results collected; target releasable | runtime installed, enabled, durable |
| **Needs** | output declaration, inventory, routing, release | install/configure, enablement, verification, update/rollback |
| **Does not need** | boot persistence, rollback | result collection as primary concern |

### 7.3 Proposed common abstraction: a declared *lifecycle intent*

Rather than two parallel subsystems, introduce **one declared field** on the
deployment/experiment that selects the terminal behaviour, plus **two small
capability groups** that hang off the existing run/deployment records.

```yaml
# declared once, in caasi.yaml (target/project level) or per experiment
lifecycle: ephemeral      # A: compute/job  -> results, then releasable
# lifecycle: persistent   # B: robot        -> install, enable, durable
```

Everything before execution is shared and unchanged. After execution, the
declared lifecycle selects which outcome machinery applies:

- `ephemeral` ⇒ inventory + route declared outputs; mark deployment releasable.
- `persistent` ⇒ install/configure, enable runtime, verify durability.

**This is deliberately a *variant*, not an inheritance hierarchy.** Both variants
reuse the identical spine (`Target`, `deploy`, `build`, `run`, provenance) and
differ only in a post-execution step. That avoids conflating them while also
avoiding two divergent stacks.

### 7.4 Is a new top-level "Job" concept needed?

**Proposed: no.** A "job" is an `ephemeral` lifecycle applied to an execution —
not a different kind of object. Introducing `Job` alongside `Run` would duplicate
`RunRecord`, the provenance chain, the supervision code, and the CLI surface. The
existing `RunRecord.kind` (`experiment | ros | capture | import`) is already the
extension point if finer typing is wanted later.

**Recommendation:** keep `Run` as the unit of execution; express A vs B as
**lifecycle intent + post-execution behaviour**, not as a new entity.

### 7.5 What must *not* be shared

- A persistent runtime must never be silently collected/deleted by a result-routing
  step. The lifecycle declaration makes this explicit and enforceable.
- An ephemeral target's releasability must never be inferred as a licence to
  destroy data; "releasable" is a *recorded state*, not an automatic action.

---

## 8. Q7 — Smallest sensible next implementation stage

### Recommendation: **Stage E1 — result/output collection for the shared spine**

Rationale for choosing A first:

1. **It completes an existing, half-built path.** The execution half of workflow A
   is already verified end-to-end on real hardware (Stage D). Only collection is
   missing.
2. **It has a pre-existing design** to implement rather than invent
   (proposal §5 `artifact_routing`).
3. **It is bounded.** Declare → inventory → route → record. No new transport, no
   supervisor, no boot semantics.
4. **It leaves workflow B untouched and unconstrained**, which matters because
   B's correct design (systemd vs container vs vendor supervisor; which unit;
   what config) needs input that only a real robot deployment can provide.
5. **It is the risk-lower half.** Routing files is reversible; boot enablement on
   a robot is not.

### Proposed Stage E1 scope (concrete)

| Step | Deliverable | Reuses |
| :--- | :--- | :--- |
| **E1.1** | Artifact **inventory** for a finished run (local + remote): id, kind, size, path, optional hash | `inspect_run_files`, existing run dirs |
| **E1.2** | `outputs:` declaration on the experiment schema | `Experiment` dataclass, exclude vocabulary |
| **E1.3** | **Routing** to `workstation` / `target_local` with `--dry-run` | Stage B `rsync`, `artifact_routing` shape |
| **E1.4** | Artifact record joined to provenance; surfaced via `run inspect` (+ `run artifacts` if needed) | provenance bundle, `RunRecord` chain |
| **E1.5** | `lifecycle: ephemeral` declaration + deployment `releasable` marking (record only, **no deletion**) | `DeploymentRecord.status` |

E1.1 alone is useful and low-risk, so it is the natural first commit.

### Explicitly deferred to a later stage (Stage F: persistent runtime)

- install/configure step and persistent environment
- runtime enablement (systemd/container declaration + verification)
- reboot-resilience verification
- update/redeploy handover and rollback

**Justification for deferring:** these require evidence from a real robot or a
real deployment target. Designing them now would mean guessing at the domain
supervisor and configuration model — exactly the OpenMover-specific hard-coding
the mandate forbids.

### What must be decided before E1 implementation

1. Default routing for unclassified outputs (Stage E investigation §7 Q1).
2. Hash policy for large artifacts (same §7 Q2).
3. Whether `lifecycle` is declared per-project or per-experiment (or both, with
   per-experiment override).
4. Whether deployment `releasable` is a `status` value or a separate field
   (recommend: a separate field, since `status` describes the deployment act, not
   its intended longevity).

---

## 9. Answers in one table

| # | Question | Answer |
| :--- | :--- | :--- |
| 1 | Current deployment vs run model | deployment = materialization event (permanent, no terminal state); run = execution event requiring an active deployment (+ build if ROS) |
| 2 | Existing support | A: ~70 % (execution/logs verified remotely; collection absent). B: ~30 % (software + build land on target; no persistent runtime) |
| 3 | Missing for temporary compute | output declaration, result inventory, routing, target release |
| 4 | Missing for persistent robot | install/configure, runtime enablement, durability verification, update, rollback |
| 5 | Domain vs caasi | domain owns *how* (systemd/ROS/hardware/config content); caasi owns *what/whether* (identity, materialize, execute, route, verify, provenance) |
| 6 | Common abstraction | keep the existing spine unchanged; add a declared **lifecycle intent** (`ephemeral` \| `persistent`) selecting post-execution behaviour. **No** new top-level `Job` entity |
| 7 | Smallest next stage | **Stage E1: result/output collection** (inventory → declaration → routing → provenance), deferring persistent runtime to a later stage that has real robot evidence |

---

## 10. Evidence summary

| Claim | Class | How established |
| :--- | :--- | :--- |
| `DeploymentRecord` has no terminal/retired state | Existing capability | dataclass + status comment inspected |
| Deployment cannot be removed | Observed gap | no teardown/undeploy function in `src/` |
| A run hard-requires deployment (and build if ROS) | Existing capability | `start_target_run` preflight inspected |
| No `Job` entity exists; `run.kind` has 4 values | Existing capability + measured | 33 local run manifests counted |
| Overlay `setup.bash` is produced on the target | Measured | `.../openmover/install/setup.bash`, 1139 B on `u24-307` |
| Overlay is sourced only for a caasi-launched process | Existing capability | `run.sh` wrapper sources underlay + overlay inline |
| Overlay is **not** referenced persistently | Observed gap | `grep caasi-deployments ~/.bashrc ~/.profile` on `u24-307` → no match |
| Nothing would start the stack after reboot | Observed gap | no user units, no `~/.config/autostart` entry on `u24-307` |
| ROS 1 `install.sh` achieved persistence via shell environment | Measured | 5 `>> ~/.bashrc` lines (underlays, overlay, `PYTHONPATH`, env var) |
| Container path is thin and local-only | Existing capability | `docker run --rm [--gpus]`; no mounts, no remote, no restart policy |
| No systemd/init integration anywhere | Observed gap | 0 systemd-unit references in `src/`; no units on the target |
| `artifact_routing` designed but unimplemented | Existing design + observed gap | proposal §5 vs 0 occurrences in `src/` |
| Remote outputs invisible to host | Observed gap | Stage E investigation G-E2 (probe on `u24-307`) |

**No implementation performed. No reference tree modified.**
