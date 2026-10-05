# Phase 7: Architecture and End-Goal Gap Assessment

**Status:** Standing architectural record. G1–G5 below are the reference gaps and
**remain live** as implementation proceeds in stages F1–F3.

> **G1–G5 are the architectural gaps. F1–F3 are implementation stages.**
> They are two views of the same work and are **never** substituted for one
> another: gaps are not removed or renamed because implementation was divided
> into stages, and implementing a stage does not by itself close a gap. See
> [`traceability.md`](traceability.md) for the
> requirement → gap → stage → evidence mapping.
**Date:** October 2026
**Scope:** Where caasi stands against its stated end goal, and the smallest next
architectural step.

---

## 1. The end goal, restated

> The workstation is the control plane for projects, robots, simulation machines
> and temporary compute resources. caasi should let the developer describe/submit
> work, determine an appropriate target, deploy/build/execute it, continuously
> observe it, retrieve the requested results, preserve provenance, and manage
> long-lived deployments over time — while ROS2, systemd, Docker, Isaac, colcon,
> etc. remain the underlying authorities.

Two halves are named there, and it is worth separating them because **they are in
very different states**:

- **The target-operation half** — deploy, build, execute, observe, collect,
  lifecycle, provenance. This is essentially *complete and validated*.
- **The control-plane half** — *describe/submit work*, *determine an appropriate
  target*, and run the chain *as one step*. This is where the gaps are.

The assessment below is therefore mostly about the seam between them.

---

## 2. What is already proven

Each of these was validated against a real target or real workload, not merely
implemented.

| Capability | Evidence |
| :--- | :--- |
| **Project management** | manifest with components/requires/layout; `project` namespace; component-aware validation |
| **Target discovery** | `target list/check/inspect`; capability and resource discovery; per-target `ssh_timeout` fix validated against a relayed target |
| **Deployment** | `deploy` with provenance and post-deploy verification; `verified` vs `verification_failed` distinguished |
| **Target-native build** | `build` on the target via colcon; build identity recorded |
| **Remote execution** | `run` with `target`/`deployment_id`/`build_id`/`git_revision` recorded in `RunRecord` |
| **Remote ROS 2 observability** | `ros … --target`, with `--domain` required so an empty graph cannot be mistaken for a valid observation |
| **Runtime observability** | `target runtime` for process/systemd/container/ros2, each via its native interface, absence reported with a reason |
| **Artifact inventory / routing / collection** | E1 core, reachable as `caasi run artifacts --collect`; declaration-as-filter; small-file hashing; collected for succeeded, failed **and** stopped runs |
| **Provenance** | deployment, build, run and artifact records, cross-linked by id |
| **Persistent deployment lifecycle** | install/enable/start/status/verify/update/rollback on a real systemd target, with revision identity and an honest rollback |

**The provenance spine is genuinely good.** `RunRecord` already carries `target`,
`target_transport`, `destination`, `deployment_id`, `build_id`, `git_revision`,
`project`. Linking is solved. What is missing later in this document is *deciding*
and *sequencing* — not recording.

---

## 3. Implemented but only partially validated

Honest accounting of what exists but has not met enough reality yet.

| Item | What is missing |
| :--- | :--- |
| **Reboot durability** | All preconditions for a user unit were configured and observed (`Linger=yes`, `default.target.wants` symlink, `UnitFileState=enabled`), but the machine was never rebooted. Untested, unclaimed. Needs a target that may be rebooted. |
| **System-scope units** | Only user scope has been exercised. Needs privileges. |
| **Real robot lifecycle** | The lifecycle mechanism is proven; running the actual robot stack as a managed service on hardware is not. Needs robot hardware. |
| **Container adapter / podman** | Container adapter validated **locally** against real Docker; no reachable target here has a container runtime. Podman covered by test only. |
| **Multi-target anything** | Nothing has ever been exercised against more than one target in a single operation. |
| **Temporary compute lifecycle** | Deployment + run + collection work; the *whole lifecycle* of a temporary resource (which should be releasable and disposable) has never been run end to end against a real temporary machine. |
| **`Experiment.outputs` in remote runs** | Declared outputs parse and drive collection, but the remote-run path has been exercised on a simple workload, not a full simulation. |

---

## 4. Genuinely missing

This is the substance of the assessment. Ordered by architectural weight.

### G1. Nothing decides a target — work names one

**Addressed by stage F1** via an advisory, requirement-driven, inspectable
`caasi target select`. **Status: CLOSED** (accepted) — verdicts from real targets,
no ranking or preference logic, and `select_all` returns a set rather than a
choice. See [traceability](traceability.md#g1--nothing-decides-a-target--f1) and
[the F1 acceptance review](stage-f1-acceptance-review.md).

`find_target` resolves **by exact name or unique prefix only**:

```python
def find_target(config, query):
    exact = [t for t in targets if t.name == query]
    if exact:
        return exact[0]
    matches = [t for t in targets if t.name.startswith(query)]
    return matches[0] if len(matches) == 1 else None
```

There is no capability- or requirement-driven selection anywhere. `deploy`,
`build` and `run` each take a target the developer already chose.

**Everything needed to fix this already exists and is unconnected:**
- the project declares `requires:` (`ros2: jazzy`, `isaac_sim: ">=5.0"`),
- targets report `discovered_capabilities` and discovered resources (GPU, CUDA, arch),
- `requirements.satisfies()` implements the matching semantics, including the
  crucial three-valued result where **`None` means UNVERIFIED** and absence of
  evidence is not treated as incompatibility,
- `detect_mismatches()` already compares declared capabilities against discovered
  facts for a *single* target.

So `requirements.satisfies` is currently called only from `check.py`, and only for
the **local machine**. The matcher exists; it has simply never been pointed at a
set of targets to *choose* among them. That is the single largest conceptual gap.

### G2. `caasi check` is local-only, so compatibility is asymmetric

**Addressed by stage F1** via target-aware fact sourcing. **Status: CLOSED on
capability** (accepted), **with a recorded consolidation item**: remote-target
evaluation including the §57 case is demonstrated live, but `check.py` was left
local-only and the requirement ladder is now implemented **twice**, so
`check.strict` is honoured by `caasi check` and **not** by `target select`. See
[traceability](traceability.md#g2--check-is-local-only--f1) and
[the F1 acceptance review](stage-f1-acceptance-review.md).

`check` answers *"can this project/run work on **this machine**"*. Given how the
tool now treats targets as first-class, the natural question — *"can this project
work on **that target**"* — has no command. E4 partially worked around this by
refusing operations with clear reasons, but incompatibility is discovered
**after** choosing a target, not before.

### G3. The lifecycle is a set of independent commands, not one sequence

**Addressed by stage F2** via workload steps and lifecycle composition, which
must preserve the individual commands. **Open — not addressed by F1 at all.** See
[traceability](traceability.md#g3--lifecycle-is-independent-commands--f2).

Everything in the chain exists, but nothing composes it:

```text
deploy → build → run → observe → collect
```

Each is a separate manual invocation, and the developer carries the state
(`deployment_id`, `build_id`, `run_id`) between them by hand. There is no single
entry point that takes a project plus a workload and produces results.

This is exactly the "individual target operations → higher-level work
orchestration" transition the user identified.

### G4. A legacy remote registry still exists alongside targets

**Not solved by F1.** Tracked explicitly as an **outstanding retirement/migration
task**, to be removed only when the target model fully supersedes it without
losing compatibility unnecessarily. See
[traceability](traceability.md#g4--legacy-remotes-shim--outstanding-cleanup-not-f1).

`remotes:` (`remotes.py`, "remote GPU machines", with `connect`/`run`) and
`targets:` (`targets.py`, the Phase 7 model) coexist. The relationship is already
mostly resolved in target's favour, which makes this smaller than it first
appears:

- `list_targets` documents `remotes:` as **legacy** and **imports** those entries,
  building `Target` objects from them;
- so there is one canonical model, and `remotes:` is a compatibility shim.

The residual seam is that the shim carries fields and a CLI surface (`remote
connect`, `remote run`) that coexist with the canonical `target` commands, and the
two have separate config vocabularies. It is a **retirement** task rather than a
duplication to reconcile — worth doing, because selection will want a single
authoritative list of "where work can go", but it is not a blocker.

### G5. No notion of *work* separate from a *run*

**Addressed by stages F1/F2** — F1 introduces the minimal `Workload` model needed
for requirements/selection; F2 extends it with steps/outputs and execution. The
gap is **not closed until both are done**. See
[traceability](traceability.md#g5--no-workload-object--f1--f2-split-deliberately).

`Experiment` is **local-only** (`VALID_BACKENDS = ("sim", "lab", "python")`; a
script path; no target, no deployment, no artifacts). `RunRecord` is
**execution-only** (a command, captured provenance).

Nothing expresses *"this is the work I want done, these are its requirements,
these are its outputs"* in a way that can be pointed at a target. That gap is why
G1 and G3 are hard: there is no object for selection and sequencing to operate on.

The vocabulary partly exists (`Experiment.outputs`, manifest `requires:`,
manifest `tested:`), but it is split across two models that do not meet.

---

## 5. Deliberately out of scope

Confirmed still excluded, and worth re-affirming since selection sits adjacent:

fleet/resource orchestration · job scheduling · resource queues · automatic target
selection *as a hidden policy* · multi-target execution in one operation ·
Git-push deployment triggers · automatic deployment · distributed execution
graphs · artifact routing in Stage D · remote GUI management · a generic fleet
supervisor · a custom process manager · a Docker implementation · a systemd
replacement · a metrics database.

Note the tension to resolve deliberately: **G1 is "determine an appropriate
target", which is in the stated end goal, while "automatic target selection" is on
the forbidden list.** These are reconcilable, but only by making selection
*explicit and inspectable* rather than a hidden scheduler — see §7.

---

## 6. Things that should NOT be added, because a domain tool owns them

The end goal says ROS 2, systemd, Docker, Isaac and colcon remain the
authorities. That is currently true, and it should stay true. Concretely, caasi
must **not** grow:

| Not caasi's job | Owner |
| :--- | :--- |
| Running/restarting/supervising services | **systemd** (E4 invokes and verifies only) |
| Container lifecycle, images, networking | **docker/podman** |
| Package build semantics, dependency resolution | **colcon / rosdep** |
| ROS graph, topics, nodes, launch | **ros2 / rclpy** (caasi's CLI "never speaks rclpy") |
| Simulation execution, physics, rendering | **Isaac Sim / Isaac Lab** |
| GPU driver and device state | **nvidia-smi / the kernel** |
| Environment/container definitions | **the images and the OS** |
| Capability *discovery* of a target | the target's own tools (E3's principle) |

The test for a proposed feature: *is caasi deciding and recording, or is it
re-implementing?* E3 and E4 both held this line; any orchestration work must too.

---

## 7. The smallest next architectural step

**Recommendation: introduce an explicit *workload* declaration and a
requirement-driven, inspectable target selection — and nothing beyond that.**

Concretely, the smallest step that unlocks the stated lifecycle is:

1. **A workload is declarable, not just runnable.** Extend the existing
   `Experiment` concept so it can carry what it needs and what it produces —
   requirements, target preference, declared outputs — instead of leaving those
   split between `Experiment` and the manifest. This is the object G3 needs.

2. **Selection becomes a query with a visible answer.** Given a project (plus
   workload) and a set of targets, produce a **ranked, explained** result:
   which targets satisfy the requirements, which do not, and **which are
   UNVERIFIED**. Reuse `requirements.satisfies` and `detect_mismatches` — the
   semantics already exist, including the three-valued verdict.
   - `caasi target select <project>`: a **read-only query** that prints the
     verdict per target and *why*, and exits non-zero if nothing qualifies.
   - No hidden policy, no scheduler, no automatic fallback. The developer still
     names the target for execution; selection **advises and validates**, it does
     not silently choose.

3. **Only then, sequencing — and explicitly.** Once selection exists, a single
   verb can run `deploy → build → run → collect` for a **named** target, recording
   each link in the existing provenance spine. Not multi-target, not queued, not
   automatic — just the chain that is presently four manual commands.

**Why this is the smallest step:**

- It adds **no new authority** — every operation it sequences already exists and
  is validated.
- It resolves G1/G2/G3/G5 with **one** object and **one** query, rather than three
  features.
- It stays clear of the out-of-scope list, because selection is an *inspectable
  query* and execution still takes an **explicit** target. That is the
  reconciliation of §5's tension.
- It is the prerequisite for multi-target work: you cannot sensibly reason about
  several targets before you can compare one project's requirements against one
  target's facts.
- It fixes the asymmetry in G2 by turning `check` into the target-aware question
  it should already be answering.

**Explicitly deferred:** multi-target *execution*, queues, scheduling, resource
claims, cross-target artifact aggregation. Those are only worth designing after
selection exists and has been used against a real second target (the user's
temporary GPU compute case is the natural first test, and it is also the case that
would finally exercise the ephemeral lifecycle end to end).

**Also worth doing alongside, not before:** G4, finishing the retirement of the
legacy `remotes:` shim. `list_targets` already imports those entries, so this is a
cleanup that gives selection a single authoritative list of "where work can go" —
boundary-tightening, not a new feature.

---

## 8. Summary

| # | Category | Count | Headline |
| :--- | :--- | :--- | :--- |
| 1 | Already proven | 10 | the entire target-operation half, validated against real targets |
| 2 | Partially validated | 8 | reboot durability, system scope, robot hardware, containers, anything multi-target |
| 3 | Genuinely missing | 5 | **G1** no target *decision*; **G2** check is local-only; **G3** lifecycle not sequenced; **G4** dual remote registries; **G5** no workload object |
| 4 | Out of scope | 13 | scheduling, queues, fleet, hidden selection policy, multi-target execution |
| 5 | Owned by others | 8 | systemd, docker, colcon, ros2, Isaac, nvidia-smi |

**The one-sentence finding:** caasi has completed the *target-operation* half of
its end goal and validated it well; what remains is the *control-plane* half, and
the single missing link is that nothing turns a project's declared requirements
into an inspected choice of target before the already-working operations run.

**Recommended next step, once approved:** a workload declaration plus a read-only,
requirement-driven `target select` that reports per-target verdicts including
UNVERIFIED — advisory and inspectable, with execution still taking an explicit
target. Implement nothing until reviewed.

**Stage mapping (see [traceability.md](traceability.md)):** F1 addresses G1, G2 and
the first half of G5; F2 addresses G3 and completes G5; F3 adds R2 (no gap — a new
capability); G4 is independent outstanding cleanup.

**Status after F1 acceptance:** **G1 CLOSED**, **G2 CLOSED on capability** (with a
consolidation item — the duplicated requirement ladder and the `check.strict`
divergence), **G3 CLOSED**, **G4 OPEN / cleanup**, **G5 CLOSED**.
