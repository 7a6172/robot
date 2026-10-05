# Phase 7: Traceability — Requirements → Gaps → Stages → Evidence

**Status:** Standing traceability record. Kept current as stages complete.

**Purpose:** G1–G5 are the **architectural gaps** identified by the
[gap assessment](architecture-gap-assessment.md). F1–F3 are the **implementation
stages** that address them. A gap is **not** closed, renamed or removed by being
implemented in stages — the mapping below is the permanent link between the two
views, and between them and the [durable requirements](durable-requirements.md).

**Reading the table.** A gap remains *open* until **all** its stages are complete
**and** the stage's evidence has been recorded. Implementing a stage does not
close a gap by itself — the closure of G3 and G5 below is claimed only because the
F2 evidence is recorded, and G1/G2 await explicit acceptance of the F1 evidence.

---

## 1. The traceability chain

```text
end-goal requirement (R1–R10)  →  architectural gap (G1–G5)
                               →  implementation stage (F1–F3)
                               →  validation / evidence
```

| End-goal req. | Architectural gap | Stage | Status |
| :--- | :--- | :--- | :--- |
| **R1** workstation as control plane | G1, G2, G3 | F1, F2 | **F1+F2 complete** (G1/G2 accepted) |
| **R2** target-aware existing tools | *(no gap — new capability)* | F3 | **Implemented** — [`stage-f3-report.md`](stage-f3-report.md), with one recorded environmental limitation (DDS over Tailscale) |
| **R3** domain owners | *(cross-cutting; held throughout)* | all | **Held** |
| **R4** target-aware execution | G2, G3 | F1, F2 | **F1+F2 complete** |
| **R5** workload abstraction | **G5** | **F1, F2** | **F1+F2 complete** |
| **R6** target selection | **G1, G2** | **F1** | **Accepted** — G1 closed; G2 closed on capability, with a recorded consolidation item |
| **R7** lifecycle composition | **G3** | **F2** | **F2 complete** |
| **R8** multi-target control plane | *(deliberately deferred)* | — | Deferred |
| **R9** result/artifact flow | *(partial; no gap)* | — | Partial |
| **R10** monitoring web UI | *(deliberately deferred)* | — | Deferred |

---

## 2. Gap-by-gap record

### G1 — Nothing decides a target → **F1**

`find_target` resolves by name or unique prefix only. No capability- or
requirement-driven selection exists, even though the ingredients all do.

**Addressed by F1** via `caasi target select`:

- **requirement-driven** — a project/workload's `requires` are matched against a
  target's discovered facts;
- **advisory** — it reports verdicts and does not choose;
- **inspectable** — every verdict carries the fact and the reason;
- **no hidden automatic choice** — execution still names an explicit target, and an
  undiscovered fact is reported as `untested` rather than guessed.

**Status: CLOSED** (accepted — see
[`stage-f1-acceptance-review.md`](stage-f1-acceptance-review.md)).

F1's evidence shows requirement-driven verdicts from real targets including
`untested`/`missing` cases, verified live against `u24-307`, and inspection confirms
there is no ranking, scoring or preference logic: `select_all` returns a **set** of
verdicts, never a choice, and `compose` uses `select_target` only as a **gate** on
an already-named target. The prohibition on hidden policy therefore remains
satisfied.

### G2 — `check` is local-only → **F1**

`check.detect()` sources detected facts from `config` and `shell.which()` — the
local machine. "Can this project work on *that target*" has no answer.

**Addressed by F1** via target-aware fact sourcing:

- detected facts come from a `Target` inspection (`TargetEnvironment`,
  `TargetResources`) instead of only the local machine;
- **the existing `CheckEngine` / Check Contract is reused**, not replaced — the
  verdict ladder, §57 evidence-not-guarantees, and the exit policy stay owned by
  the one engine. `target select` is a new **entry point**, not a new semantics.

**Status: CLOSED on capability** (accepted) — **with a recorded consolidation
item**. See [`stage-f1-acceptance-review.md`](stage-f1-acceptance-review.md).

Demonstrated live against `u24-307`: §57 out-of-range → `untested` (not
`incompatible`), `missing`, and `unmeasured` all behave per the contract, with facts
sourced from the target's own discovery.

**The caveat, recorded rather than smoothed over:** the design intended
`target select` to be *another entry point of the existing CheckEngine*, but
`check.py` was left unchanged and the requirement ladder is now **implemented
twice**. For projects without `check.strict` the paths agree. With
`check.strict: true` they **diverge**: `caasi check` escalates a warning to
`incompatible` (exit 3) while `target select` calls `summarize(..., strict=False)`
unconditionally and reports only a warning (exit 0).

**Consolidation item (open):** move the ladder into one shared function called by
both paths and propagate `strict`. Does not block F3.

### G3 — Lifecycle is independent commands → **F2**

`deploy`, `build`, `run` and collection each exist, and the developer carries
`deployment_id` / `build_id` / `run_id` between them by hand.

**Addressed by F2** via workload steps and lifecycle composition, eventually
composing:

```text
deploy → build → run → collect
```

**while preserving the individual commands** — composition is an addition, and an
operator debugging a failure still needs each step separately (R7).

**Addressed and closed by F2** (see [`stage-f2-report.md`](stage-f2-report.md)):
composition demonstrated end to end on the real CPU-only target `u24-307`
(`deploy → build → run → collect`, all four steps), with the individual commands
shown still to work unchanged and composed runs appearing in `caasi run list`
exactly like manual ones.

**Status: CLOSED** — with the documented limitation that a `build` step on
`--target local` is blocked by a *pre-existing* build/run destination mismatch
(recorded in the F2 report, not caused by F2).

### G4 — Legacy `remotes:` shim → **outstanding cleanup (not F1)**

`remotes:` (`remotes.py`) coexists with the canonical `targets:` model. This is
already largely resolved in target's favour: `list_targets` documents `remotes:`
as **legacy** and **imports** those entries into `Target` objects.

**Not solved by F1.** F1 neither requires nor performs this cleanup.

**Tracked explicitly as a retirement/migration task**, to be removed **only when
the target model fully supersedes it without losing compatibility unnecessarily**:

- removal must not silently drop configured machines that still rely on
  `remotes:` (a migration path or a deprecation notice is required first);
- the `remote connect` / `remote run` CLI surface must be reconciled with the
  `target` commands, not just deleted;
- until then it stays visible here as an open architectural seam.

**Closes when:** the shim is retired with compatibility preserved or explicitly
migrated, and the two config vocabularies are unified.

### G5 — No workload object → **F1 / F2** (split deliberately)

Nothing expresses "the work, its requirements and its outputs" in a form that can
be pointed at a target: `Experiment` is local-only, `RunRecord` is execution-only.

The gap is addressed in **two stages**, and it is **not closed until both are
done**:

- **F1 introduces the minimal `Workload` model needed for requirements and
  selection** — name and `requires` only. Nothing more, because selection is all
  F1 needs.
- **F2 extends it with steps/outputs and execution** — the composition vocabulary
  and the declared outputs that drive collection.

**Addressed and closed by F1+F2**: F1 introduced the minimal model (name,
`requires`); F2 extended it with a closed `steps` vocabulary and `outputs`, and the
model has been exercised on a general Python workload, a ROS 2 workload and the
real OpenMover project.

**Status: CLOSED** — the model was deliberately *not* designed around OpenMover:
the same `Workload` carried a plain-Python workload and a ROS 2 build workload
unchanged.

---

## 3. Rules this record enforces

1. **G1–G5 are never removed or renamed because implementation is divided into
   F1–F3.** They are the architectural gaps; F1–F3 are how they are being closed.
2. **Implementing a stage does not close a gap.** A gap closes when its stage(s)
   are complete *and* evidence is recorded.
3. **A gap may span stages** (G5 spans F1+F2); a stage may address several gaps
   (F1 addresses G1, G2 and part of G5).
4. **A gap may be independent of all stages** (G4) and stays tracked as cleanup.
5. **R1–R10 remain the broader end-goal contract** ([durable-requirements.md](durable-requirements.md));
   this record only supplies the middle links.
6. **Deferral is not closure.** R8 and R10 are deliberately deferred and remain
   requirements.
7. **A closed gap may still carry a recorded item.** G2 is closed on capability
   but carries an open **consolidation item** (the duplicated requirement ladder
   and the `check.strict` divergence). Closing a gap does not erase a known
   follow-up; it records that the follow-up does not block the capability.
8. **An environmental limitation is not a capability gap.** R2 is implemented and
   verified, but cross-machine DDS discovery does not traverse the Tailscale link
   between the two reference machines. That is a network-topology fact, recorded
   as measured and **not** worked around — caasi implements no DDS discovery,
   tunnels or multicast relays. It would be a scope violation to "fix" it inside
   caasi, and a false claim to report it as working.
