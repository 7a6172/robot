# Caasi — Durable End-Goal Requirements

**Status:** Standing architectural contract. These requirements persist across
sessions and are **not** optional merely because they are deferred.

**Relationship to other documents:** [`plan/vision/caasi.md`](../vision/caasi.md)
states *why* caasi exists and the philosophy behind it. This document states the
**concrete end-goal requirements** that follow, so they cannot be lost while
individual phases are implemented. [`architecture-gap-assessment.md`](architecture-gap-assessment.md)
measures current progress against them. `current.md` records what is done.

**How to use this document:** before starting a stage, check the new work against
these requirements. Before closing a stage, state which requirement it advances.
A deferred requirement is still a requirement — deferral means "not yet", never
"no longer needed".

---

## R1. The workstation is the control plane

caasi should eventually manage the **whole lifecycle** across local machines,
robots, simulation servers, GPU servers and other configured targets, from one
workstation.

**The developer should not have to:**

- manually `ssh` to a target,
- manually source environments,
- manually discover the right commands,
- manually configure each target,
- manually coordinate deployment, build, run and collection,

**when caasi can already know how to do it.** Any step a developer must perform by
hand *because caasi does not know it yet* is a gap, not a design choice.

## R2. Target-aware existing tools

caasi should **expose existing tools cleanly**, when doing so removes
configuration and coordination work, **without reimplementing them**.

The canonical example:

```bash
caasi rviz2 --target robot-01
```

This means: run the **normal local `rviz2`**, but use caasi's knowledge of
`robot-01` to supply the environment, discovery/DDS configuration and connection
details it needs.

**This is not an RViz implementation and not a special RViz subsystem.** It is a
**general pattern** for invoking an existing tool through caasi's target
knowledge. It applies equally to ROS 2 tools and other ecosystem tools wherever it
removes real setup work.

The invariant: **the tool being invoked remains the tool**. caasi supplies
context, then gets out of the way.

## R3. Existing tools remain the domain owners

caasi must **not** replace ROS 2/DDS, colcon/CMake, Isaac Sim/Lab, Docker/Podman,
systemd, nvidia-smi, RViz, or any comparable tool.

caasi should **coordinate, configure, invoke, track and record** them.

If an existing tool already solves something well, **prefer exposing it through a
clean caasi workflow over rebuilding it**.

**The architectural test, applied to any proposed feature:** *is caasi deciding and
recording, or is it re-implementing?* Deciding and recording is caasi's job.
Re-implementing is not.

## R4. Target-aware execution

The target model should eventually cover **robots, GPU/simulation servers, local
machines and other execution nodes** as instances of one concept.

**Deployment, target-native build, run, monitoring, logs, artifacts and provenance
should compose into a coherent workflow** rather than a set of commands the
developer must sequence by hand.

## R5. Workload abstraction

A workload abstraction should be designed **broadly enough** to cover:

- ROS 2 workloads,
- Isaac Sim / Isaac Lab workloads,
- GPU training and simulation,
- robot deployment,
- simple Python workloads,
- and comparable cases.

**Do not design it around OpenMover.** OpenMover is a real **proving ground**, not
the definition of caasi. The design must be general-purpose from the start.

## R6. Target selection

Target selection should be **requirement-driven and inspectable**.

- Advisory / read-only is an acceptable starting point.
- It must **show why** each target is compatible, incompatible, or **unverified**.
- **Do not introduce hidden automatic target-selection policy yet.**

"Unverified" is a first-class verdict and must never be silently rendered as
compatible or incompatible — an absent measurement is not evidence.

## R7. Lifecycle composition

Eventually a coherent workload operation should compose the already-proven steps:

```text
target resolution → compatibility check → deploy → build → run → monitor → collect → provenance
```

**The individual lower-level commands must remain available.** Composition is an
addition, never a replacement: an operator debugging a problem needs the steps
individually.

## R8. Future multi-target control plane

Eventually caasi should support multiple developers, robots and servers, **resource
availability, queues, scheduling and target allocation**, and related execution
management.

**Do not design or implement this now.** It must come **after** the
single-workload / single-target model is proven. Designing it early would fix
abstractions before there is evidence to choose them well.

## R9. Result and artifact flow

**Execution target and artifact destination remain independently configurable.**

Results may:

- stay on the target,
- return to the workstation,
- or eventually go to another configured destination.

**Provenance must connect the whole chain**, so any result can be traced back to
the workload, revision, deployment, build and run that produced it.

## R10. Small monitoring web UI

Eventually caasi should provide a small, lightweight **web interface**, initially
ROS 2-focused.

Constraints, which are requirements rather than preferences:

- It is **strictly monitoring / observation-only**.
- **The CLI remains the control interface.**
- **No web buttons for deploy, build, run, stop, restart**, or any other control
  action.
- It must **reuse existing caasi state and core functionality**, not create a
  second control plane.
- GPU and system monitoring may be added later **under the same observation-only
  philosophy**.

This requirement is where the "one control plane" boundary is easiest to violate:
a web UI that mutates state would create a second, divergent control path.

---

## Cross-cutting principles

These apply to every requirement above.

### The architectural test

> **If OpenMover disappeared tomorrow and was replaced by another ROS 2 / Isaac
> project, would this still make sense?**

If the answer is no, the design is too specific and must be generalised.

### Evidence discipline

- Distinguish **existing capability**, **observed gap**, **measured behaviour**, and
  **future design**. Never present one as another.
- Never turn "not tested" into "equivalent".
- Never loosen a tolerance after seeing a result.
- State what **cannot** be claimed, and why, at the same time as what can.

### Absence is explicit

An unavailable capability, an unverified target, or a missing measurement must be
**reported with a reason**, never as an empty success or a silent default. This
already governs target runtimes, target selection and artifact classification, and
must continue to.

### Nothing destructive on a persistent target

Observation, deployment and collection must never destroy a long-lived
installation or its rollback point.

---

## Status snapshot

Updated as requirements are advanced. See
[`architecture-gap-assessment.md`](architecture-gap-assessment.md) for the
detailed gap analysis.

| Req. | Subject | Status |
| :--- | :--- | :--- |
| R1 | Workstation as control plane | **Partial** — every operation is proven individually; nothing yet coordinates them |
| R2 | Target-aware existing tools | **Designed as a general pattern, not implemented** — thin declarative `invoke` + environment, `rviz2` as the first example only. See `workload-and-selection-design.md` §6 |
| R3 | Domain owners | **Held throughout** — no domain re-implemented; E3/E4 invoke and verify only |
| R4 | Target-aware execution | **Mostly proven** — deploy/build/run/observe/collect work per target; composition missing |
| R5 | Workload abstraction | **Designed, not implemented** — `Experiment` is local-only; the proposed `Workload` carries requirements/steps/outputs. See `workload-and-selection-design.md` §3 |
| R6 | Target selection | **Designed, not implemented** — `find_target` resolves by name only; the matching semantics and the Check Contract ladder exist but are unused for choice. See `workload-and-selection-design.md` §4 |
| R7 | Lifecycle composition | **Designed, not implemented** — steps exist as independent commands; composition proposed as a fixed operation sequence, not a workflow engine. See `workload-and-selection-design.md` §5 |
| R8 | Multi-target control plane | **Deliberately deferred** — correct to defer until the single-target model is proven |
| R9 | Result/artifact flow | **Partial** — independent routing exists; other destinations not yet |
| R10 | Monitoring web UI | **Deliberately deferred** — must be observation-only and reuse core state |
