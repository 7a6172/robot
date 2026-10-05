# Phase 7 Stage F2 Design: Workload Steps and Lifecycle Composition

**Status:** Design. Implementation follows after this is reviewed.
**Addresses gaps:** **G3** (lifecycle is independent commands), completes **G5** (workload object)
**Requirements:** R1 (workstation as control plane), R4, R5, R7
**Parent:** [`workload-and-selection-design.md`](workload-and-selection-design.md) §5, §10
**Traceability:** [`traceability.md`](traceability.md)

---

## 1. Objective

Compose the already-proven operations into one coherent workload operation, while
**keeping every lower-level command available** (R7):

```text
target resolution → compatibility check → deploy → build → run → collect → provenance
```

Nothing new executes anything. `steps` names operations caasi already has.

---

## 2. Heterogeneous real targets (standing evidence requirement)

**Durable evidence for the broader control-plane goal:** caasi must work across
**heterogeneous targets**, including CPU-only robots and GPU-capable compute
machines. These are the two reference machines, and they are a genuinely
heterogeneous pair — measured, not assumed:

| | **`u24-307`** — CPU-only robot/target | **`u24-z690p`** — GPU workstation |
| :--- | :--- | :--- |
| Transport | `ssh` over Tailscale | `local` |
| OS / arch | Linux 6.8, x86_64 | Ubuntu 24.04.5, x86_64 |
| ROS 2 | jazzy | jazzy |
| Python | 3.12.3 | 3.12.3 |
| **GPUs** | **0** | **1 (RTX 3080, 10 GB)** |
| CUDA | **none** | 13.0 |
| Docker | no | yes |
| Isaac Sim / Lab | not detected | present |
| Discovered capabilities | `ros2:jazzy` | `cuda, docker, gpu, isaac_lab, isaac_sim, ros2:jazzy` |

`u24-307` stands for the CPU-only robot/target that will commonly exist;
`u24-z690p` stands for a GPU-capable compute/simulation target.

### 2.1 What must be demonstrable (no automatic forwarding)

The same workload requirement evaluated against **both** real targets:

| Workload | `u24-307` (CPU-only) | `u24-z690p` (GPU) |
| :--- | :--- | :--- |
| CPU-only | satisfies it | satisfies it |
| GPU-required | **incompatible** (zero GPUs) | **ready**, when other requirements are met |
| ROS 2 | per discovered facts | per discovered facts |
| Isaac / CUDA | per discovered facts | per discovered facts |

The architectural distinction this stage must preserve:

```text
workload → evaluate targets → u24-307   incompatible
                            → u24-z690p  ready        ✅ F1/F2
```

```text
u24-307 → automatically forward → u24-z690p          ❌ NOT this
```

That second arrow is **target allocation / scheduling**, explicitly deferred
(R8). F2 must make it *possible later* without implementing it now.

### 2.2 Where the workload actually runs

**Initiated from the workstation; executed on the selected target.** The developer
must not need to be physically or interactively logged into the target.

This already holds for execution and must remain true: remote runs go over
**non-interactive SSH** (`BatchMode=yes`, driven by `target.ssh_timeout`). F2
composition inherits this property rather than re-adding it — and validation must
exercise it, since "run it on the remote target from here" is the whole point of
R1.

---

## 3. Workload `steps`

`steps` is a **fixed, ordered vocabulary of existing operations** — not a
workflow engine.

```yaml
workload:
  name: bringup
  requires:
    gpu: {count: 1}
  steps:
    - deploy: {}
    - build: {packages: [openmover]}
    - run:    {command: "ros2 launch openmover bootloader.launch.py"}
  outputs:
    - {path: "runs/*/map.json", kind: map}
```

Rules, each preventing a specific drift:

| Rule | Prevents |
| :--- | :--- |
| Unknown step names are **rejected** at parse time | silent no-ops |
| `steps` is an **ordered list**, not a graph | a DAG engine by accident |
| No conditionals, loops or expressions | a scripting language |
| Omitted steps are **skipped, not inferred** | hidden policy |
| `deploy`/`build`/`run` reuse the **existing core functions** | a parallel path |

If a workload needs real control flow, it is a program, and the workload invokes
it via `run` (R3 — don't re-implement).

---

## 4. Composition semantics

```bash
caasi workload run <name> --target <target> [--json] [--dry-run]
```

**Sequence and failure behaviour:**

```text
1. resolve workload + merge requirements (project ⊕ workload)
2. evaluate the NAMED target               (reuse F1 selection)
     - incompatible  → stop, report why, change nothing
     - unmeasured    → proceed with a recorded warning (not a blocker)
3. deploy   → record deployment_id
4. build    → record build_id            (skipped when not declared)
5. run      → record run_id
6. collect  → collect declared outputs    (when declared)
7. record the composed provenance
```

**A failing step stops the chain** and reports which link failed, with the ids
already produced. No silent partial success: an operator must be able to see that
`deploy` succeeded and `build` failed, and to resume or debug with the individual
commands (R7).

**Provenance is not duplicated.** Composition records the *same* `RunRecord` /
deployment / build / artifact records the manual path records — it does not invent
a parallel "workflow record". A composed run must be indistinguishable in
provenance terms from one run by hand, so `caasi run logs`, `run artifacts` and
`check run` keep working on it unchanged.

---

## 5. What F2 must NOT do

- **No automatic target selection.** The target is named. `--target` is required;
  there is no defaulting to a "best" target.
- **No forwarding.** An incompatible target is reported, never silently replaced.
- **No scheduling, queues, allocation or resource claims** (R8).
- **No multi-target execution.** One workload, one target.
- **No retry/resume orchestration** beyond reporting failure at a step.
- **No web UI** (R10).

---

## 6. Designed so later allocation stays possible

Stated explicitly, because the requirement is *"do not prevent those capabilities
later"*:

| Later capability | What F2 provides so it is not blocked |
| :--- | :--- |
| Target allocation | F1's per-target verdicts are already a **set** of evaluated targets; allocation becomes "pick from the compatible set" |
| Forwarding | the chain is a sequence of steps over a **named** target, so re-running it against another target is already possible |
| Queues / scheduling | steps and their ids are recorded, so a queued item is a workload + requirements, which already exist |
| Multi-target | nothing in the model assumes a single global target; `Target` is per-operation |

The deliberate non-decision: F2 does **not** add a "choose target" function,
because adding one now would fix an allocation policy before there is evidence to
choose it well (R8).

---

## 7. Validation plan

Against the **two real machines**, never synthetic GPU fixtures where a real
machine can answer:

1. **`target select` matrix** — one CPU-only workload and one GPU-required
   workload against `u24-307` and `u24-z690p`; expect the documented table in
   §2.1, with `u24-307` reported `incompatible` for the GPU workload *because it
   reports zero GPUs*.
2. **ROS 2 workload** — evaluated per discovered facts on both.
3. **Isaac/CUDA workload** — evaluated per discovered facts (expected: unavailable
   on `u24-307`, available on the workstation).
4. **Composed run on the CPU-only target** — a real workload executed on
   `u24-307` **initiated from the workstation over non-interactive SSH**, proving
   no interactive login is needed.
5. **Failure at a step** — a deliberately broken step; confirm the chain stops,
   reports the failing link, and the individual commands still work afterwards.
6. **Incompatible target refused** — the GPU workload named against `u24-307`;
   confirm it stops before deploying anything.

Evidence for the heterogeneous-target requirement is recorded as **durable**:
this is the standing proof that caasi spans CPU-only robots and GPU compute.

---

## 8. Risks

| Risk | Mitigation |
| :--- | :--- |
| Composition becomes a second execution path | steps call the same core functions as the CLI |
| Composition invents parallel provenance | records the same record types; `run logs`/`artifacts` must keep working |
| Partial success reported as success | a failing step stops and reports; exit non-zero |
| Hidden target choice creeps in | `--target` required; no default; incompatibility reported not worked around |
| `steps` grows conditionals | fixed vocabulary; unknown steps rejected; control flow means "call a program" |
