# Phase 7 Design: `--where` — Explicit Target Selection

**Status:** Design only. **Nothing implemented.**
**Date:** October 2026
**Origin:** [`r8-architecture-review.md`](r8-architecture-review.md) — the minimum R8 abstraction, prerequisites now closed
**Prerequisites:** M1 (workload identity), F1 (one ladder), F2 (local contract) — all complete
**Requirement:** R8 (kept deliberately small)

---

## 1. The distinction this design protects

> **`--where` answers "which currently suitable target should I use?"**
> **A scheduler would answer "when and where should this workload eventually run?"**

`--where` is a **query the operator asks**. A scheduler is a **policy the system
applies unbidden**. Everything below follows from keeping that line.

---

## 2. What already exists (nothing here is new machinery)

| Input | Source | Status |
| :--- | :--- | :--- |
| What the work needs | project `requires:` ⊕ workload `requires:` | F1 |
| What a target offers | live `discover_target` | F1 |
| Does target X satisfy Y | `select_target` → `SelectReport` | F1 |
| **A set of evaluated targets** | `select_all` — returns reports, ranks nothing | F1 |
| **Occupancy** | `list_runs` + `effective_status` | already present |
| **Tags** | `Target.tags` (real: `cpu-only`, `workstation`, `remote`, `gpu`…) | already present |
| Provenance of the choice | M1 — workload identity on the run | M1 |

**`select_all` already computes exactly the set `--where` must choose from.** The
new work is a *decision over an existing result plus a report*, not new evaluation.

---

## 3. The policies

```bash
caasi workload run <name> --target <t>          # unchanged; explicit, the default
caasi workload run <name> --where any           # a suitable target, explained
caasi workload run <name> --where idle          # a suitable target with no live runs
caasi workload run <name> --where prefer:<tag>  # among suitable, prefer a tag
caasi workload run <name> --where any --dry-run  # show the choice, run nothing
```

`--target` and `--where` are **mutually exclusive**; omitting both is an error
(there is no implicit default).

**A note on the existing CLI contract.** `--target` is currently a *required* typer
option, so its requiredness moves from the parser into the command: `--target |
--where` becomes an explicit either/or validated in code, with a clear message when
neither or both are given. That keeps `--target` semantics identical for every
existing caller while making the new form expressible. **Case 9 in §8 is the
regression guard for exactly this.**

### 3.1 Evaluation order (each policy)

```text
1. evaluate every configured target          (select_all; requirements only)
2. keep the ELIGIBLE set:
       reachable AND status != incompatible
   — `warning` (unmeasured/out-of-range) is eligible, because absence of evidence
     is not evidence of absence; it is REPORTED, not silently dropped
3. order the eligible set by the policy:
       any           → name order (deterministic, no implicit preference)
       idle          → targets with no live runs first, then name order
       prefer:<tag>  → targets carrying <tag> first, then name order
4. choose the first
5. if eligible is empty → FAIL with every target's reason
```

### 3.2 The tie-break is stated, not hidden

Ordering is **lexicographic on the policy key, then on target name**. That is
deliberate: with two equally suitable targets, the choice must be *predictable* and
*explainable*, not dependent on dictionary iteration order. `name` is the one
ordering an operator can reason about and reproduce.

**This is not a ranking system.** There is no scoring, no weighting, no cost model,
no load balancing. `prefer:<tag>` is a filter-then-name-order, not a preference
score.

---

## 4. The report — the choice is never silent

Always printed (and present in `--json`), before anything runs:

```console
$ caasi workload run rosmodel --where prefer:gpu --dry-run

Selection for workload 'rosmodel'
  Requirements: isaac_sim >=5.0, gpu count>=1

  ✔ SELECTED   local       carries 'gpu'; satisfies all requirements
  ✖ eliminated u24-307     does not satisfy 'gpu' (target reports no GPUs)

  Notes
    · local: target reports no RMW_IMPLEMENTATION; leaving the local default in place
```

Per target, the report states:

| Field | Content |
| :--- | :--- |
| **verdict** | selected / eliminated |
| **reason** | why — the policy key that decided, or the failing requirement |
| **evidence** | the measured fact behind the reason (e.g. *"reports no GPUs"*) |
| **unmeasured notes** | any requirement that could not be measured, so `warning`-grade eligibility is visible rather than implicit |

`--json` exposes the same, so a script can read the decision rather than re-derive it.

**Nothing is chosen silently, and no eligible target is dropped without a printed
reason.**

---

## 5. Failure is the required behaviour when nothing fits

If no target is eligible:

```console
$ caasi workload run rosmodel --where any
✖ no target satisfies this workload
    u24-307   does not satisfy 'isaac_sim' (required component was not detected)
    local     unreachable: Connection timed out
```

Exit non-zero. **No queue. No waiting. No retry. No forwarding.**

This is the design's most important property: the system must **fail loudly and
immediately** rather than hold work it cannot place. A queue would turn "nothing
fits right now" into "something might happen later", which is precisely the
scheduling semantics this stage must not introduce.

---

## 6. Occupancy: a fact, used only where it is honest

`--where idle` uses `list_runs` + `effective_status`.

**Which states occupy a target:**

| State | Occupies? | Why |
| :--- | :--- | :--- |
| `running` | **yes** | the target is busy |
| `paused` | **yes** | still resident, resources still held |
| `succeeded` / `failed` / `stopped` | no | terminal; no longer holding the target |
| `lost` | no, but **reported** | unknown state — not counted as busy, and not hidden |

`lost` is worth stating explicitly: it is an **unknown**, and per the standing rule
an unknown must not be silently treated as either busy or free. It does not block
selection, and if a target has `lost` runs that is surfaced in the report.

**Occupancy is a preference, never a guarantee.** Two workloads submitted at once
can both see a target as idle — there is no reservation, and this design does not
add one. That race is *not* a defect to fix here; it is the exact boundary between
selection and scheduling, and closing it would require the queue.

---

## 7. What `--where` deliberately does not do

| Not done | Why |
| :--- | :--- |
| Wait for a target to become free | that is a queue |
| Reserve/hold a target | that is a reservation system |
| Retry elsewhere on failure | that is automatic forwarding |
| Run on several targets | multi-target execution is deferred (R8) |
| Reorder or batch work | that is scheduling |
| Score/rank/balance by load or cost | a hidden policy; `prefer:<tag>` is filter-then-name-order |
| Default to any policy | `--target`/`--where` must be given explicitly |
| Aggregate results across targets | deferred with multi-target |

---

## 8. Validation plan

Against the two real heterogeneous targets. **The refusal and explanation cases
carry the weight**, not the happy path.

| # | Case | Expectation |
| :--- | :--- | :--- |
| 1 | `--where prefer:gpu`, GPU workload | selects `local`; **eliminates `u24-307` naming "reports no GPUs"** |
| 2 | `--where prefer:cpu-only`, CPU-only workload | prefers `u24-307` (it carries the tag) |
| 3 | `--where any`, both suitable | a target is chosen and the choice is **explained**; deterministic across repeated runs |
| 4 | `--where any`, **nothing fits** (Isaac workload) | **fails** with per-target reasons, non-zero, **nothing deployed, nothing queued** |
| 5 | `--where idle` with a live run on one target | prefers the idle one, **stating the occupancy evidence** |
| 6 | `--where idle` with **all** targets busy | still selects (occupancy is a preference, **not** a gate) — and says so |
| 7 | `lost` runs present | not counted as busy; **reported** |
| 8 | Unmeasured requirement (`warning` grade) | eligible, **and the note is printed** — not silently accepted |
| 9 | `--target` alone | **byte-for-byte today's behaviour** — no regression |
| 10 | `--where` + `--target` together | refused, mutually exclusive |
| 11 | Neither given | refused, no implicit default |
| 12 | Provenance | the run records **which workload**, the **selected target**, and **why** |
| 13 | Unreachable target in the set | eliminated with the transport reason, not a crash |

**Case 4 is the anti-scheduler test** and must be checked explicitly: the failure
path must deploy nothing and leave nothing pending.

**Case 12 depends on M1**: the choice must be recorded, not merely printed. The
selection rationale joins the provenance chain that M1 completed.

---

## 9. Data model (small)

| Type | Status |
| :--- | :--- |
| `SelectReport`, `RequirementVerdict`, `select_all` | **exists** |
| **`SelectionDecision`** — `selected`, `policy`, `reason`, `eliminated[]`, `notes[]` | **new, purely a reporting type; no state** |
| Run provenance: `selected_by` / `selection_reason` | **new fields on the existing record**, alongside M1's workload identity |

No new persistent state. No registry. No queue table. The decision is computed per
invocation from facts that already exist and recorded beside the run it produced.

---

## 10. Scope boundary, restated

**In scope:** the three policies; eligibility from existing verdicts; occupancy as a
preference; an always-printed explained decision; failure when nothing fits; the
decision recorded in provenance; `--where` mutually exclusive with `--target`.

**Out of scope** (unchanged, and re-affirmed): queues; scheduling; reservations;
resource booking; automatic forwarding; retries; multi-target execution; resource
claims; fleet management; hidden ranking; web UI; **G4**; the DDS-over-Tailscale
limitation.

---

## 11. Recommendation

Implement exactly §3–§9: the three policies, over `select_all`, with an always-
explained decision, occupancy used only as a preference, and **failure rather than
queueing** when nothing fits.

The stage is small because the machinery is already there: `select_all` already
produces the candidate set, tags already exist, and occupancy is already derivable.
What is added is a **stated, inspectable decision over an existing result** — and
the discipline to stop there.

**Awaiting review before implementation.**
