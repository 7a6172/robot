# Phase 7 Stage E Addendum: Management & Observability as a Third Concept

**Status:** Architecture discovery addendum (no implementation)
**Parent:** [`stage-e-discovery.md`](stage-e-discovery.md)
**Date:** October 2026

---

## 0. Why this addendum exists

The parent discovery contrasted two **lifecycles** (temporary compute vs persistent
robot). A third concept is distinct from both and must not be conflated with
either:

| Concept | Question it answers | Time scale |
| :--- | :--- | :--- |
| **Deployment lifecycle** | what is installed on the target, and is it durable? | long-lived |
| **Execution lifecycle** | is a run currently executing, and how did it end? | bounded |
| **Observability / management** | what state are the targets, deployments and runtimes in *right now*? | continuous, cross-target |

The crucial consequence: **`deploy` is not the end of the lifecycle.** A
deployment can remain active for months, and caasi must stay useful during that
time — not only at the moment of `deploy`.

This reframes the scope. Rather than "deploy, then optionally collect results",
the model is:

```text
targets → deployments → runtime state → logs / metrics / diagnostics
```

across potentially many targets, continuously, long after the original `deploy`
command exited.

---

## 1. The governing principle

> **caasi owns management and observability; domain systems own runtime semantics.**

This is *already* the documented product intent, not a new direction. From
`plan/vision/caasi.md`:

- **§8**: "Caasi should not become another ROS implementation." It lists nodes,
  topics, services, actions, parameters, launch, graphs, composition,
  middleware, lifecycle and distributed systems as things ROS 2 already provides.
- **§9**: the intended relationship is ROS 2 as the layer *below* caasi, with
  caasi supplying "project organization, environment, resource management,
  execution, remote execution, scheduling, monitoring, provenance, artifacts".
- **§16**: "Caasi should not replace the tools it manages… ROS 2 → robotics
  middleware, Isaac Sim → simulation, Docker → containerization, Git → source
  control. Caasi connects and manages these systems."

So the boundary is settled: **caasi must not build a generic ROS management
replacement.** ROS 2 remains the source of truth for ROS runtime state; caasi
queries, aggregates and exposes it.

---

## 2. Existing capability — the discovery pass found more than expected

This is important for scope: a substantial part of the observability layer
**already exists**.

### 2.1 A thin ROS 2 delegation primitive already exists

**Existing capability.** `caasi.core.ros.run_ros2(args)` runs `ros2 <args>` as a
subprocess, wrapped through `rosenv` so it works in an unsourced shell. The
module docstring states the intent directly:

> "``ros2`` CLI via subprocess, so caasi stays a thin orchestration layer."

This is exactly the "thin adapter over existing native interfaces" the
architecture calls for. It is not a stub — it is the established pattern.

### 2.2 A ROS 2 observability surface already exists

**Existing capability.** `caasi ros` already exposes query commands, all
delegating to `ros2`:

| Command | Purpose |
| :--- | :--- |
| `caasi ros graph` | text summary of the ROS 2 graph |
| `caasi ros list` | topics, nodes, services, actions |
| `caasi ros node` | inspect a node |
| `caasi ros topic` | inspect a topic (`--echo` to stream) |
| `caasi ros service` | inspect / call services |
| `caasi ros doctor` | `ros2 doctor` diagnostics |
| `caasi ros status` | ROS 2 environment status |

Plus `caasi native ros` as an explicit escape hatch to raw `ros2`.

### 2.3 A local resource monitor already exists

**Existing capability.** `caasi.core.monitor` (self-described as "Layer 7") and
`caasi monitor` sample CPU, RAM, GPU/VRAM and top processes from `/proc` and
`nvidia-smi`, plus per-run runtime and throughput. It is careful to report
unmeasurable values as `None` rather than fabricating them.

### 2.4 Target discovery already aggregates per-target facts

**Existing capability.** `caasi target check|inspect` reports reachability,
latency, hardware, OS, ROS distro and capabilities — proven against the real
`u24-307` in Stage D.

### 2.5 The gap, measured precisely

**Observed gap.** Every one of the surfaces in §2.2 and §2.3 is **local-only**.
Verified directly:

```text
caasi ros graph    --target flags: 0
caasi ros list     --target flags: 0
caasi ros node     --target flags: 0
caasi ros topic    --target flags: 0
caasi ros doctor   --target flags: 0
```

and `grep -n "target\|ssh\|remote" caasi/core/monitor.py` returns **nothing**.

So caasi can already *inspect* a local ROS 2 graph and a local machine, and it
can already *reach* a remote target, but it cannot yet inspect a **remote**
target's runtime state. That is a narrow, well-defined gap — not a missing
subsystem.

---

## 3. The three concepts, kept separate

```text
┌───────────────────────────────────────────────────────────────────────┐
│ DEPLOYMENT LIFECYCLE   (long-lived, per target)                        │
│   deploy → configure → enable → operate → update/redeploy              │
│   Terminal states: installed/enabled (durable) | releasable (ephemeral)│
├───────────────────────────────────────────────────────────────────────┤
│ EXECUTION LIFECYCLE    (bounded, per run)                              │
│   start → (running | paused) → stop/succeed/fail                       │
│   Owns: process supervision, PID/PGID, exit code, stdout/stderr        │
├───────────────────────────────────────────────────────────────────────┤
│ OBSERVABILITY / MGMT   (continuous, cross-target)                      │
│   targets → deployments → runtime state → logs/metrics/diagnostics     │
│   Owns: reachability, active version, runtime queries, aggregates      │
└───────────────────────────────────────────────────────────────────────┘
```

**Why they must not be conflated:**

- A deployment outlives any run. `deploy` then `run start`/`run stop` many times
  is normal; the deployment's identity and version do not change.
- Observability outlives both. Querying robot-01's ROS graph is meaningful with
  no run in flight and no deploy in progress.
- Their failure semantics differ. A failed *run* is a result. A failed
  *deployment* is an installation problem. An unreachable *target* is a transport
  problem. Collapsing them would make each indistinguishable from the others.

The existing model already keeps these separate (`DeploymentRecord`,
`RunRecord`, `TargetInspection`). The addendum's contribution is naming
observability as a **first-class third concern** with its own scope, rather than
letting it be implied by `run status`.

---

## 4. Worked example: five robots

```text
                       caasi / server
              ┌──────┬──────┬──────┬──────┐
           robot-01 robot-02 …   robot-04 robot-05
              │                                 │
            ROS 2 DDS  ◀──── peer communication ──▶  ROS 2 DDS
```

What caasi should provide, and what it must delegate:

| caasi provides (management/observability) | ROS 2 owns (runtime semantics) |
| :--- | :--- |
| which 5 targets exist and are reachable | DDS discovery between them |
| which project version is active on each | node/topic/service/action semantics |
| "is robot-03 running the expected version?" | QoS policies and lifecycle nodes |
| a consistent cross-target summary | parameter storage and dynamic reconfig |
| retrieve a target's graph/topic list on request | topic content and timing |
| retrieve logs / metrics / diagnostics | diagnostics semantics (`/diagnostics`) |
| which targets have a run in flight | intra-robot execution and scheduling |

**Key point:** caasi does not need to poll all five continuously to be useful. A
useful first version is **query-on-demand**: "show me the state of the fleet" or
"show robot-03's ROS graph", executed when asked, with the results aggregated
into one consistent view. Continuous sampling is a later optimisation.

---

## 5. Generalising beyond ROS 2

The user's requirement is explicit: stay general. The same shape must work for
non-ROS runtimes, selected per target by **discovered capability** — which
`Target.discovered_capabilities` already provides (Stage A reports
`ros2`, `ros2:jazzy` today).

| Runtime | Native query mechanism caasi should delegate to | caasi's role |
| :--- | :--- | :--- |
| **ROS 2** | `ros2 node/topic/service/graph/doctor` | delegate, normalise, aggregate |
| **Plain Python / Isaac Lab job** | process state, log files, run manifest | read run records + logs |
| **Container workload** | `docker ps/inspect/logs` | delegate to the container runtime |
| **systemd service** | `systemctl show/is-active`, `journalctl` | delegate to init |
| **Bare process** | `/proc`, run PID/PGID (already used) | read directly |

The unifying claim is deliberately modest:

> caasi knows **how to ask** a given kind of target for runtime state, using that
> platform's own interface, and presents the answers consistently.

This is an **adapter registry keyed by capability**, mirroring the existing
capability-driven target model — not a new abstraction layer with its own
semantics.

**Explicitly out of scope:** reimplementing DDS discovery, parsing ROS message
content itself, building a bespoke metrics store, or creating a robot fleet
supervisor that competes with systemd or the container runtime.

---

## 6. Resulting revision to the proposed staging

The parent discovery proposed Stage E1 = result collection, deferring persistent
runtime. This addendum adds a **third workstream** and suggests ordering that
respects the distinction:

| Workstream | Scope | Depends on |
| :--- | :--- | :--- |
| **E1 — Result collection** | output declaration, inventory, routing, provenance | existing spine |
| **E2 — Remote observability** | make existing local query surfaces target-aware; per-runtime adapters | Stage A targets + existing `ros`/`monitor` code |
| **F — Persistent runtime** | install/configure, enable, durability, update/rollback | real robot evidence |

### Recommended order: **E1 → E2 → F**

Rationale for putting E2 second (rather than first):

1. **E1 is already designed and bounded**, and completes the half-built compute
   path proven on real hardware. Lowest risk, highest immediate completeness.
2. **E2 is mostly plumbing, not design.** The query commands exist and the
   delegation primitive exists; the missing piece is making them target-aware.
   But it is broader in surface area (many commands), so it benefits from
   following the smaller, well-understood E1.
3. **F still requires real robot evidence** and remains last for the reason
   already recorded: guessing the domain supervisor and configuration model now
   would hard-code assumptions the mandate forbids.

### Smallest first E2 slice (if E2 is chosen first instead)

If observability is judged more urgent than result collection, the minimum
useful slice is small and worth naming:

- add `--target` to the existing `caasi ros` query commands, reusing
  `run_ros2` + `target_ssh_prefix` + the remote overlay-sourcing that
  `run.sh` already performs;
- add `caasi target state <target>` as the single aggregation point for
  reachability + active deployment + build + running runs.

Both reuse existing code paths. Neither requires a new subsystem.

---

## 7. What this changes in the parent discovery

| Parent statement | Revision |
| :--- | :--- |
| Two lifecycles contrasted (A compute, B persistent) | Now **three concerns**: deployment lifecycle, execution lifecycle, and observability/management |
| "Terminal state" language implied `deploy` is an endpoint | Corrected: a deployment is **long-lived**; `deploy` is a transition, not the end |
| Observability mentioned only as result collection | Observability is its own concept spanning targets, deployments and runtimes, and is **not** limited to collecting outputs |
| Stage E1 = result collection only | Result collection remains the recommended first step, but **remote observability is now an explicit, sequenced workstream (E2)** rather than being folded into "results" |

Everything else in the parent discovery stands, including the boundary principle
(caasi orchestrates *what/whether*, domain owns *how*), the rejection of a new
top-level `Job` entity, and the deferral of persistent-runtime work.

---

## 8. Evidence summary

| Claim | Class | How established |
| :--- | :--- | :--- |
| Thin ROS 2 delegation primitive exists | Existing capability | `ros.run_ros2`, docstring states the intent |
| A ROS 2 query surface already exists | Existing capability | `caasi ros graph\|list\|node\|topic\|service\|doctor\|status` |
| Raw escape hatch exists | Existing capability | `caasi native ros` |
| Local resource monitor exists (CPU/RAM/GPU) | Existing capability | `caasi.core.monitor`, `caasi monitor` |
| Every query surface is **local-only** | Observed gap | 0 `--target` flags on all five `ros` query commands; no remote references in `monitor.py` |
| Delegation-not-replacement is already the documented intent | Existing design | vision §8, §9, §16 |
| Capability-driven runtime selection is already possible | Existing capability | `Target.discovered_capabilities` (Stage A; reports `ros2`, `ros2:jazzy`) |
| No systemd/container-runtime adapters exist yet | Observed gap | 0 systemd-unit references; no `restart` handling in container path |

**No implementation performed. No reference tree modified.**
