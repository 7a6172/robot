# Phase 7: R8 Architecture Review — Multi-Target Execution, Allocation and Scheduling

**Status:** Review only. **No design implemented, no code changed.**
**Date:** October 2026
**Requirement under review:** **R8** — future multi-target control plane
**Prior art:** [`architecture-gap-assessment.md`](architecture-gap-assessment.md), [`traceability.md`](traceability.md), [`stage-f3-report.md`](stage-f3-report.md)

---

## 1. What was demonstrated, and what R8 asks

Proven end to end:

```text
target selection  →  deploy → build → run → collect  →  target-aware tool invocation
```

R8 asks for the eventual: multiple developers, robots and servers; **resource
availability, queues, scheduling and target allocation**.

**The review's central question:** *what does caasi actually need next?* Not what
the long-term vision contains — R8 is explicitly a *future* requirement, and the
standing rule is that deferral is not closure but also not licence to build.

---

## 2. Evidence from the two real heterogeneous targets

| | `local` (GPU workstation) | `u24-307` (CPU-only remote) |
| :--- | :--- | :--- |
| Transport | `local` | `ssh` / Tailscale (~440 ms) |
| GPUs | 1 × RTX 3080 (10 GB) | **0** |
| CUDA / Isaac | 13.0 / present | none / absent |
| ROS 2 | jazzy | jazzy |
| Docker | yes | no |

Neither machine is hardcoded anywhere: both are ordinary configured targets, and
everything below is expressed in terms of *facts a target reports*, not these two.

---

## 3. The finding: most of R8's preconditions already exist

This is the review's headline. Four of the six things a scheduler would need are
**already solved**, and none required new state.

| Scheduler precondition | Status | Evidence |
| :--- | :--- | :--- |
| **What work needs** | **solved (F1)** | `requires` on the manifest and the workload, merged |
| **What a target offers** | **solved (F1)** | live discovery: GPU, CUDA, ROS distro, arch, docker |
| **Does target X satisfy work Y** | **solved (F1)** | `target select` — requirement-driven, per-target verdicts, `unverified` preserved |
| **What is currently running where** | **solved (already)** | **live occupancy is derivable from existing `RunRecord`s** — verified: `local` → 24 succeeded / 3 failed / 6 stopped, `u24-307` → 5 / 3 / 1 |
| **Where results go** | **solved (E1/R9)** | per-artifact routing, independent of the execution target |
| **Provenance across the chain** | **solved, one gap** | `target → deployment → build → run → artifacts` complete; **workload identity is not recorded** (§6) |

**The occupancy result matters most.** A scheduling system is usually justified by
needing to know what is busy — and that fact is *already recorded*. Any future
allocator can be a **query over existing records**, not new state.

**Consequence:** the missing piece is not "a scheduler". It is narrow: a way to
express *"run this workload where it fits"* as an explicit, inspectable decision
rather than a hand-typed target name.

---

## 4. The four categories

### 4.1 Already solved by F1–F3

Requirement declaration and merging; live target fact discovery; per-target
compatibility with a three-valued verdict; the composed
`deploy → build → run → collect` chain; independent artifact destinations;
deployment/build/run/artifact provenance; target-aware tool invocation.

### 4.2 Genuinely missing

**M1. Workload identity is absent from provenance.** A composed run records
`kind="workload"` but **not the workload's name**. Verified on a real run:
`name: hello2` (the *experiment*), `kind: workload`, and `ros2-build` — the workload
— appears nowhere in the record. Provenance chains backwards to the run and the
deployment, but the **first link is missing**: you cannot ask *"which workload
produced this?"* once more than one exists.

**Evidence, from a real composed run** (`ros2-build` on `u24-307`) — the recorded
manifest in full:

```yaml
name: hello2                 # the EXPERIMENT, not the workload
kind: workload               # says it was a workload; not which one
target: u24-307
deployment_id: deploy-builddemo-20261005-174509-ae558435
build_id: build-u24-307-1791222349-ec5ecb
git_revision: ae558435…
project: builddemo
extra:
  experiment: experiments/hello2.yaml
```

The chain reaches the experiment, target, deployment, build and run — but the
workload name **`ros2-build` appears nowhere**. Provenance can answer *"what
produced this artifact?"* as far as the experiment, and no further.

This is small, is a *correctness* gap rather than a feature, and it gets worse as
soon as anything tracks several workloads — which is the threshold where R8 starts
to matter. **It should be closed before R8 work**, because every later allocator
would otherwise key on an incomplete provenance chain.

**M2. There is no way to express "run this where it fits".** Today `--target` is
required and must be typed by hand. Deciding among several satisfying targets is
manual. This is the actual gap R8 names — but see §5: the missing piece is an
**explicit selector**, not a scheduler.

**M3. No notion of target busyness as a first-class query.** Occupancy is
*derivable*, but nothing exposes it. A `target states`-style read-only view is the
missing ergonomic layer — and note that **the inputs already exist**, so this is a
presentation gap, not a state gap.

### 4.3 Useful but premature

- **Capacity/limit accounting** (CPUs, VRAM, memory). Limits already exist as
  *declared constraints* in `requires` and are matched against discovered facts
  (`gpu: {count, memory_gb}` is implemented and tested). What is premature is
  modelled **capacity booking** — tracking totals and reserving against them —
  because modelling capacity implies enforcement, which implies a scheduler.
- **Concurrency control on a target.** Two workloads on one machine is a real
  scenario, but nothing yet needs admission control, and adding it invents policy
  before there is evidence to choose it.
- **Resource reservations/leases.** Requires a queue to be meaningful; a queue
  requires the single-target model to be shown insufficient first.
- **Submit-and-forget.** Attractive, and F2 already runs detached primitives — but
  "submit" implies somewhere to submit *to*, and that is the scheduler itself.

### 4.4 Deferred until a real multi-target use case requires it

**Queues. Scheduling. Automatic allocation. Multi-target execution in one
operation. Resource claims. Cross-target artifact aggregation. Fleet management.**

**Why queues specifically are deferrable, argued rather than assumed:**

1. **A queue solves contention.** There is no observed contention: one developer,
   two targets, ad-hoc runs. Queues would add a stateful daemon, ordering
   semantics, fairness policy, persistence and failure recovery — for a problem
   that has not occurred.
2. **The occupancy input already exists**, so if contention *were* observed, the
   cheapest answer is a query that says *"target X is busy with run Y"* — which
   lets the operator choose. That is strictly less machinery than a queue and
   strictly more honest, because it does not silently reorder anyone's work.
3. **A queue without a scheduler is meaningless**, and a scheduler without evidence
   of contention would be designed against a guess.
4. **The prohibition is explicit.** Fleet orchestration, job scheduling, resource
   queues and automatic target selection are all on the standing excluded list.
   Nothing here argues to reverse that; the evidence argues the opposite.

---

## 5. The minimum abstraction

**Recommendation: an explicit, inspectable *selection* step — not an allocator.**

```text
caasi workload run <name> --target <t>       # today: explicit, unchanged
caasi workload run <name> --where <policy>   # proposed: explicit policy, still inspectable
```

where `<policy>` is a small, named, reviewable rule — not a hidden algorithm:

| Policy | Meaning |
| :--- | :--- |
| `--target <t>` | exactly as today (default; unchanged) |
| `--where any` | among targets satisfying the requirements, pick one — **and say which and why** |
| `--where idle` | as `any`, but prefer a target with no live runs |
| `--where prefer:<tag>` | among satisfying targets, prefer a tag (`gpu`, `cpu-only`, …) |

Design rules that keep this *not* a scheduler:

1. **Selection stays a query** — the same verdict machinery F1 already provides,
   extended from *"can this target?"* to *"which of these can?"*.
2. **The choice is always explained** — the report names the chosen target and the
   eliminated ones with reasons. No silent selection.
3. **`--target` remains the default and remains required** when no policy is given.
   Nothing existing changes behaviour.
4. **No queue, no waiting, no ordering.** If no target satisfies the requirements,
   it **fails with the reasons** — it does not enqueue and wait.
5. **Unverified is never treated as compatible.** A target whose facts are
   unmeasured is not silently preferred or excluded without saying so — the rule
   already established in F1.
6. **No new state.** Choosing among targets reads existing records (facts, runs).

This is the smallest thing that answers *"what happens when multiple targets
satisfy a workload?"* and *"can I submit without hand-picking?"* **without** the
scheduler that R8 might eventually need.

**What it deliberately is not:** it does not wait, retry, order, reserve, preempt
or aggregate. Each of those is a scheduling concern requiring a queue, and each
needs evidence this stage does not have.

---

## 6. The open questions, answered

The review asked specific questions; each has a concrete answer.

| Question | Answer |
| :--- | :--- |
| **Target availability/state** | Discovery is **live per call** (no caching, no staleness risk). Occupancy is derivable from `RunRecord`s. Nothing needs to be added except *exposure*. |
| **Workload requirements / resource requests** | Requirements exist and merge correctly, and **declared resource constraints already work**: `gpu: {count: 1, memory_gb: 8}` is matched against discovered GPUs (including a memory shortfall, reported as a warning not an incompatibility). What is absent is **capacity *booking*** — reserving quantities against a target's total — which is premature (§4.3). |
| **Selection vs automatic allocation** | Selection exists and is inspectable. **Automatic allocation is not needed** — a policy flag preserves explicitness while removing typing. |
| **Multiple targets satisfy** | Today: the operator reads the table and types a name. Proposed: an explained choice. |
| **No target available** | **Today: fail with the per-target reasons** (F1/F2 already do this. Compose refuses.). Proposed: unchanged — **fail, never silently queue**. |
| **Are queues required?** | **No, not yet** (§4.4). No observed contention; the input for detecting it already exists; a queue is meaningless without a scheduler and a scheduler would be designed against a guess. |
| **CPU/GPU capacity** | Discovery reports what exists. **Capacity *accounting* is premature**; declared constraints suffice. |
| **Concurrent workloads** | Possible today (nothing prevents two runs on one target) and **nothing yet needs admission control**. Detect first via occupancy; control only if evidence demands it. |
| **Submit-and-forget** | F2's synchronous semantics are correct for composed work. Submit-and-forget needs a *destination to submit to*, i.e. the queue — so it is **downstream of the queue decision, not a reason for it**. |
| **Deployment/build/run composition** | **Solved (F2)**, unchanged by any of this. |
| **Artifact destinations independent of execution target** | **Solved (E1/R9)** — per-artifact routing, verified. |
| **Provenance across the chain** | Complete **except workload identity** (§4.2 M1) — the one thing to fix first. |
| **Multi-robot / multi-GPU-server** | The model already scales: a target is a configured object, facts are discovered, requirements are matched. Nothing assumes one robot or one server. |
| **What stays manual vs automatic** | **Manual (stays):** which work to run; approving an update; rollback; anything destructive. **Automatic (proposed):** nothing — even `--where` requires the operator to *ask for* a policy. |

---

## 7. Explicitly out of scope (unchanged)

Fleet/resource orchestration; job scheduling; resource queues; **automatic target
selection as a hidden policy**; multi-target execution in one operation; Git-push
deployment triggers; automatic deployment; distributed execution graphs; generic
fleet supervisor; custom process manager; Docker implementation; systemd
replacement; metrics database; web UI (R10).

The `--where` proposal does **not** breach "automatic target selection" because it
is opt-in, named, explained, and never a default — the distinction is between a
*query the operator asks* and a *policy the system applies unbidden*.

---

## 8. Validation plan (for the proposed stage, when approved)

Against the two real machines, using facts rather than fixtures:

| Case | Expectation |
| :--- | :--- |
| `--where any`, GPU workload | selects `local` (the only satisfying target); **names `u24-307` as eliminated, with the reason "reports no GPUs"** |
| `--where any`, CPU-only workload | both satisfy; a choice is made and **explained** |
| `--where idle` with one target busy | prefers the idle target; **states the occupancy evidence** |
| `--where prefer:cpu-only` | honours the tag among satisfying targets |
| **No target satisfies** | **fails** with per-target reasons — **does not queue, does not wait** |
| Unverified requirement on a target | reported, never silently counted as compatible |
| `--target` alone (no policy) | **byte-for-byte today's behaviour** — no regression |
| Provenance | a run selected by policy records **which workload** and **why that target** |

The refusal case carries the weight, as in F3: the system must **fail loudly when
nothing fits** rather than queueing invisibly.

---

## 9. Should the four open items go before or after?

| Item | Recommendation | Reasoning |
| :--- | :--- | :--- |
| **F1 requirement-ladder consolidation** | **Before.** | The proposed `--where` extends *selection*, which is exactly the code that is currently duplicated. Building on the duplicate would **widen** the divergence while the `check.strict` bug remains live. Consolidate first, then extend one implementation. |
| **F2 local build/run destination semantics** | **Before, or explicitly scoped.** | Any `--where` policy could select `local`, and `local` + a `build` step is currently **broken** by this pre-existing mismatch. A selection feature that can choose a broken path compounds the defect. At minimum the semantics must be **decided**; the fix need not be large. |
| **G4 `remotes:` retirement** | **After.** | Independent of R8; it is cleanup. `list_targets` already imports the legacy entries, so it does not affect selection correctness. Retire it deliberately with a migration path, not as a side effect. |
| **DDS-over-Tailscale limitation** | **After, and probably permanently deferred.** | An **environmental** fact, not a caasi defect. It affects remote *GUI/tool* usage, not multi-target execution or scheduling. Working around it would breach the agreed boundary. Document and leave it. |

**Ordering conclusion:** the two **F1/F2 items are prerequisites**, not cleanup —
because the proposed stage extends exactly the code paths they affect. G4 and the
DDS limitation are independent and stay open.

---

## 10. Recommendation

1. **Close M1 (workload identity in provenance)** — small, a correctness gap, and it
   is the first link of the chain every later feature would rely on.
2. **Consolidate the F1 requirement ladder** and **decide the F2 `local`
   build/run destination semantics** — both are prerequisites for extending
   selection, per §9.
3. **Then implement the minimum abstraction: an explicit `--where` policy** over
   the existing verdict machinery — explained, opt-in, no queue, no waiting, no new
   state.
4. **Do not implement queues, scheduling, automatic allocation or multi-target
   execution.** The evidence does not support them yet, and the inputs for
   detecting when they are needed (facts, requirements, occupancy) already exist.

**The one-sentence finding:** caasi does not need a scheduler; it needs the
workload already recorded in its own provenance, and an *explicit, explained choice
among satisfying targets* — both of which are small, and both of which sit on top
of machinery F1–F3 already proved.

---

## 11. What this review did not do

No code changed. No F4 implemented. No queue, scheduler, allocator or multi-target
execution designed. The four open items remain exactly as recorded — none removed,
none treated as solved.
