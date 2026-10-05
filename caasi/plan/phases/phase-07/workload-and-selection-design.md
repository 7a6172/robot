# Phase 7: Workload Abstraction and Target Selection — Design Proposal

**Status:** Design only. **No implementation.** Stops for review.
**Date:** October 2026
**Requirements:** [`durable-requirements.md`](durable-requirements.md) (R1, R4, R5, R6, R7)
**Gaps addressed:** G1 (nothing decides a target), G2 (`check` is local-only), G3
(lifecycle not sequenced), G5 (no workload object)

---

## 1. Design constraint

The test, applied throughout:

> **If OpenMover disappeared tomorrow and was replaced by another ROS 2 / Isaac
> project, would this still make sense?**

So the design is validated against **six generalized cases** (§7), only one of
which is OpenMover, and none of which is special-cased.

---

## 2. The central finding

The assessment found that the pieces exist and are unconnected. Designing against
the six cases confirms **exactly where** the seam is:

**`check.detect()` reads detected facts from `config` and `shell.which()` — i.e.
from the local machine.**

```python
def detect(config, name):
    detector = _DETECTORS.get(raw) or _DETECTORS.get(key)
    if detector is not None:
        return str(detector(config))      # local facts
    found = shell.which(raw) or shell.which(key)
    return "present" if found else None   # local PATH
```

Everything else already generalizes:

| Existing piece | Reusable as-is? |
| :--- | :--- |
| `requirements.satisfies()` | **Yes** — three-valued verdict, `None` = UNVERIFIED |
| `check` verdict ladder (`compatible`/`untested`/`missing`/`incompatible`) + §57 doctrine | **Yes** — already the right words *and* the right caution |
| `TargetEnvironment` / `TargetResources` (discovered per target) | **Yes** — the facts exist for remote targets |
| `manifest.requires:` (what a project needs) | **Yes** |
| `manifest.tested:` (environments actually verified) | **Yes** |
| `RunRecord` provenance spine | **Yes** — linking already solved |
| `deploy` / `build` / `run` / `artifacts` per target | **Yes** |

**Therefore the design is not "build a matcher". It is: make the *already-correct*
matching logic read facts from a target instead of only the local machine, and give
it an object to match against.** That is a small, unifying change.

---

## 3. The workload model

### 3.1 One object, not two

Today the vocabulary is split: `Experiment` (local-only: a script, a backend, env)
and the manifest (`requires:`, `tested:`). A workload is the thing that has
**requirements**, **steps**, and **outputs**, and can be pointed at a target.

```yaml
# caasi.yaml (manifest) — the project
schema: 1
name: openmover
version: 0.4.0
requires:
  ros2: {version: jazzy}
  isaac_sim: {version: ">=5.0"}
tested:
  - os: linux
    arch: x86_64
    ros_distro: jazzy

# workloads/<name>.yaml — the work (or the existing experiments/ layout)
workload:
  name: bringup
  # what it needs beyond the project's own requirements (optional)
  requires:
    gpu: {count: 1, memory_gb: ">=8"}
  # the steps, each an EXISTING caasi operation
  steps:
    - deploy
    - build: {packages: [openmover]}
    - run:  {command: "ros2 launch openmover bootloader.launch.py"}
  outputs:
    - {path: runs/*/map.json, kind: map}
    - {path: "*.log", kind: logs, destination: target}   # R9: stays on target
```

**Why this shape:** `steps` names operations caasi *already has*, so the workload
declares composition rather than a new execution engine. Nothing here is ROS- or
OpenMover-specific — §7 shows a Python workload and a GPU training workload using
the same fields.

### 3.2 The workload is not a script runner

A deliberate boundary: caasi does **not** gain a scripting language, conditional
logic or a DAG. If a workload needs that, it is a program and the workload invokes
it (R3: don't re-implement). `steps` is a **sequence of known operations**, not a
workflow engine.

---

## 4. Target selection

### 4.1 Requirement-driven, inspectable, and honest

```
caasi target select <project-or-workload> [--json]
```

For each configured target, report a verdict using the **existing Check Contract
vocabulary — not a new one.** `core/check.py` already documents the exact ladder
this feature needs, including the doctrine that matters most here:

> §57 evidence-not-guarantees: a version outside a required range yields a
> **warning** with an explanatory note — CAASI does **not** assert incompatibility
> from version ranges alone. `incompatible` is reserved for positively failed
> functional probes.

Reusing that ladder verbatim:

| Evidence on the target | compatibility | result |
| :--- | :--- | :--- |
| requirement satisfied | `compatible` | ready |
| no requirement / no version declared | `untested` | warning |
| detected out of range | `untested` + note | warning |
| required thing **not detected** | `missing` | incompatible |
| functional probe failed | `incompatible` | incompatible |
| **fact could not be discovered** | `untested` + note | warning |

Target-specific additions on top of the contract, not replacements for it:

- **`unreachable`** — the target could not be inspected at all (a transport
  result, distinct from an *inspectable* target whose fact was not found).
- Exit policy reuses the existing uniform rule (`incompatible` → exit 3), so
  `target select` composes with existing tooling rather than inventing a code.

This is a strict improvement on a bespoke vocabulary: it is already the project's
stated contract, it is already implemented and tested, and it already encodes the
evidence discipline the durable requirements demand.

Example:

```console
$ caasi target select openmover
Requirements (from caasi.yaml + workload bringup)
  ros2       jazzy          isaac_sim  >=5.0        gpu        count>=1

● u24-307      compatible    ros2 Jazzy (24.04), isaac_sim 4.5.0
~ gpu-box      untested      gpu: not discoverable on this target (no probe result) - not evidence
~ robot-01     untested      ros2 humble detected, jazzy required (out of range; not asserted incompatible)
```

Design points, each tied to a requirement:

- **Advisory only** (R6): it prints a verdict and exits non-zero if nothing
  qualifies. It does **not** pick. Execution still takes an explicit target.
- **Shows why** (R6): every verdict carries the fact and the reason.
- **"Not measured" is never collapsed into a verdict** (R6, evidence
  discipline): an undiscovered fact yields `untested` with a note, per the Check
  Contract — it is neither compatibility nor incompatibility. Likewise an
  out-of-range version is **not** reported as `incompatible`, because §57 forbids
  asserting incompatibility from a version range alone.
- **Read-only** (R6): it inspects and reports; it changes nothing on any target.

### 4.2 The one real work item, and why it is small

`check` must become able to evaluate requirements against **a target's discovered
environment** rather than only the local one. `TargetEnvironment` already holds
`ros_distro`, `isaac_sim`, `cuda_version`, `docker`, `arch`; `TargetResources`
already holds `gpus`. This is a **fact-source change**, not new matching logic.

It is smaller still because `CheckEngine` is already documented and built as
*"one compatibility semantics behind every `check`"*, serving **multiple entry
points** today (root `check`, `sim check`, `container check`). `target select` is
therefore the next **entry point of an existing engine**, not a new subsystem:
the engine already owns scope naming, item folding, `check.strict` and the exit
policy, and it should keep owning them.

Concretely, F1 is: teach the engine to source detected facts from a `Target`
inspection instead of only `config`/`shell.which`, then add a `target` scope and a
read-only command that renders the resulting report per target.

### 4.3 Why this is not forbidden "automatic target selection"

The standing prohibition is about a **hidden policy** that chooses for the
operator. This design:

- requires the operator to name the target for execution,
- exposes the reasoning,
- refuses to guess when facts are missing.

It is a **compatibility query**, the same category as `check` — and `check`
already exists. R6 explicitly permits advisory/read-only first.

---

## 5. Lifecycle composition

Only after selection is proven (R7, and the staged order in R8):

```
caasi workload run <name> --target <target> [--json]
```

composing the already-proven steps and recording each link:

```text
resolve target → compatibility check → deploy → build → run → collect → provenance
```

Constraints:

- **Every step remains individually available** (R7). This verb is an addition.
- **Single target only** (R8). No queues, no scheduling, no allocation.
- It **records the same provenance** the manual path records; composition must not
  create a parallel record type.
- A step failing stops the chain and reports which link failed — no silent partial
  success.

---

## 6. Target-aware existing tools (R2)

This is an independent, small pattern, and it is the clearest demonstration of R2/R3:

```
caasi rviz2 --target robot-01
```

caasi supplies what the tool needs to reach the target — DDS/RMW configuration,
ROS domain, environment — then **`exec`s the real local `rviz2`**. Nothing about
RViz is reimplemented; there is no RViz subsystem.

**Design rule:** a target-aware tool wrapper is allowed only when it removes real
configuration or coordination work. The wrapper must be **thin and declarative**:

```
tools:
  rviz2:
    invoke: rviz2                  # the real tool
    environment:                   # what the target tells us it needs
      - ROS_DOMAIN_ID={{target.ros_domain_id}}
      - RMW_IMPLEMENTATION={{target.rmw}}
```

This is deliberately proposed as a **general mechanism with one example**, so
whoever implements it cannot build an RViz subsystem by accident. It is listed here
because it shares the target-knowledge plumbing with §4, not because it is the next
step.

---

## 7. The six cases, against one model

The model must make these instances of **one** thing. If any needed a special case,
the model would be wrong.

| Case | requirements | steps | outputs |
| :--- | :--- | :--- | :--- |
| **local Isaac Lab workload** | `isaac_lab >=2.0`, `gpu count>=1` | `run: python train.py` | `logs/`, `*.pt` → workstation |
| **remote CPU ROS 2 workload** | `ros2 jazzy`, `arch x86_64`, no GPU | `build`, `run: ros2 launch …` | `*.log`, bag files → target |
| **remote GPU sim/training** | `isaac_sim >=5.0`, `gpu count>=1, memory>=24` | `deploy`, `build`, `run` | checkpoints → workstation |
| **OpenMover deployment** | `ros2 jazzy`, `nav2` | `deploy`, `build`, `run` + **runtime lifecycle** (E4) | maps → workstation |
| **`rviz2 --target robot-01`** | `ros2 jazzy` on the *viewer* machine; network path to robot | *(tool invocation, not a workload)* | — |
| **simple Python workload** | `python >=3.10` | `run: python analyse.py` | `*.csv` → workstation |

**What the table demonstrates:**

- `requires` is the same field in all six; only its content differs — which is
  exactly the manifestation of R5 ("broadly enough").
- `steps` is a subset of the same operation vocabulary in all six.
- **Only one case uses any ROS-specific concept, and only as *data*** (`ros2 jazzy`
  is a requirement *value*, not a code path).
- The OpenMover case is **not special**: its only distinguishing feature is that it
  also uses the E4 lifecycle — and that is an *additional step in the same model*,
  not a different model.
- `rviz2 --target` is not a workload at all; it shares only the target-knowledge
  plumbing.

**The scope test passes:** replace OpenMover with any ROS 2 / Isaac project and the
model is unchanged.

---

## 8. Data model, concretely

Reusing what exists, adding two things:

| Concept | Status |
| :--- | :--- |
| `Target`, `TargetEnvironment`, `TargetResources` | **exists** |
| `requirements.satisfies()`, verdict vocabulary | **exists** |
| `manifest.requires:`, `manifest.tested:` | **exists** |
| `OutputDeclaration`, artifact routing | **exists** (E1) |
| `DeploymentRecord`, build identity, `RunRecord` | **exists** |
| `RuntimeDeclaration`, lifecycle | **exists** (E4) |
| **`Workload`** (name, requires, steps, outputs) | **new** — unifies `Experiment` + manifest requirements span |
| **`SelectReport`** (per-target verdict + reason + evidence) | **new** — purely a reporting type, no state |

`Workload` is the only genuinely new model, and it introduces **no new execution
machinery** — it names operations that already exist.

---

## 9. Proposed command surface

| Command | Kind | Purpose |
| :--- | :--- | :--- |
| `caasi target select <project>` | **read-only query** | per-target verdicts with reasons (R6) |
| `caasi target select <project> --json` | read-only | machine-readable, including `unverified` |
| `caasi workload list` / `inspect` | read-only | what work is declared |
| `caasi workload run <name> --target <t>` | **composes existing steps** | R7, single target only |
| `caasi <tool> --target <t>` | target-aware invocation | R2 pattern |

Existing commands are unchanged and remain the control interface.

---

## 10. Staged implementation order

Each stage is independently reviewable and stops for approval.

**Stage F1 — target-aware facts + `target select`** (smallest foundational step)
- make `CheckEngine` source detected facts from a target's discovered environment;
- add a `target` scope (a new **entry point** of the existing engine);
- the `Workload` model, carrying `requires` only (matching the manifest's);
- `caasi target select`, advisory, read-only, reusing the Check Contract ladder
  and its exit policy.
- *Why first:* it is G1/G2/G5 in one step, adds no authority, does not introduce a
  second compatibility semantics, and is the prerequisite for everything after.

**Stage F2 — workload steps + composition**
- `steps` and `outputs` on the workload;
- `caasi workload run --target` composing deploy/build/run/collect using existing
  provenance.
- *Only after F1 is proven.*

**Stage F3 — target-aware tool invocation (R2)**
- the general `caasi <tool> --target` pattern, with `rviz2` as the first example.
- *Independent of F2; can be done whenever.*

**Deferred (R8):** multi-target execution, queues, scheduling, allocation, resource
claims. **Not required** by F1–F3; the design review shows they can wait until the
single-workload/single-target model is proven.

**Deferred (R10):** observation-only web UI — a separate stage, and it must reuse
this state rather than create a second control plane.

---

## 11. Risks and boundaries

| Risk | Mitigation |
| :--- | :--- |
| `Workload` drifts into a scripting/DAG engine | `steps` is a fixed vocabulary of existing operations; no conditionals |
| `target select` drifts into a hidden scheduler | advisory, read-only, explicit target at execution, refuses to guess |
| Tool wrappers drift into subsystems | thin declarative `invoke` + environment; general mechanism, one example |
| `unverified` gets collapsed into a verdict | it is a first-class verdict in the type and in `--json` |
| OpenMover shapes the design | §7's six cases; scope test applied |

---

## 12. What this design does NOT do

- No scheduler, queue, allocation or resource claim (**R8**, prohibited).
- No hidden target selection (**R6**).
- No web UI (**R10**, deferred).
- No re-implementation of ROS 2, colcon, Isaac, Docker, systemd or RViz (**R3**).
- No parallel provenance model — composition records the same records the manual
  path does.
- No new execution engine: `steps` names operations caasi already has.

---

## 13. Recommendation

Begin with **Stage F1** only: make requirement evaluation target-aware and add an
advisory, read-only `caasi target select`.

It is the smallest step that advances R1, R4, R5 and R6; it adds no authority; it
reuses the matching semantics, verdict vocabulary and discovery facts that already
exist; and it is the prerequisite for composition (R7) and multi-target work (R8)
without committing to either.

Awaiting review before implementing.
