# Phase 7: Traceability — Requirements → Gaps → Stages → Evidence

**Status:** Standing traceability record. Kept current as stages complete.

**Purpose:** G1–G5 are the **architectural gaps** identified by the
[gap assessment](architecture-gap-assessment.md). F1–F3 are the **implementation
stages** that address them. A gap is **not** closed, renamed or removed by being
implemented in stages — the mapping below is the permanent link between the two
views, and between them and the [durable requirements](durable-requirements.md).

**Reading the table.** A gap remains *open* until **all** its stages are complete
**and** the stage's evidence has been recorded. Implementing a stage does not
close a gap by itself.

---

## 1. The traceability chain

```text
end-goal requirement (R1–R10)  →  architectural gap (G1–G5)
                               →  implementation stage (F1–F3)
                               →  validation / evidence
```

| End-goal req. | Architectural gap | Stage | Status |
| :--- | :--- | :--- | :--- |
| **R1** workstation as control plane | G1, G2, G3 | F1, F2 | **F1 complete** |
| **R2** target-aware existing tools | *(no gap — new capability)* | F3 | Not started |
| **R3** domain owners | *(cross-cutting; held throughout)* | all | **Held** |
| **R4** target-aware execution | G2, G3 | F1, F2 | **F1 complete** |
| **R5** workload abstraction | **G5** | **F1, F2** | **F1 complete** (minimal model); F2 pending |
| **R6** target selection | **G1, G2** | **F1** | Planned |
| **R7** lifecycle composition | **G3** | **F2** | Not started |
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

**Closes when:** F1's evidence is recorded, showing verdicts from real targets
including at least one `untested`/`missing` case. **Not closed by** selection
existing alone — the prohibition on hidden policy is part of the gap remaining
closed.

### G2 — `check` is local-only → **F1**

`check.detect()` sources detected facts from `config` and `shell.which()` — the
local machine. "Can this project work on *that target*" has no answer.

**Addressed by F1** via target-aware fact sourcing:

- detected facts come from a `Target` inspection (`TargetEnvironment`,
  `TargetResources`) instead of only the local machine;
- **the existing `CheckEngine` / Check Contract is reused**, not replaced — the
  verdict ladder, §57 evidence-not-guarantees, and the exit policy stay owned by
  the one engine. `target select` is a new **entry point**, not a new semantics.

**Closes when:** requirement evaluation against a remote target's facts is
demonstrated, including the §57 case (out-of-range version reported `untested`,
**not** `incompatible`).

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

**Closes when:** composition is demonstrated end to end on a real target and the
individual commands are shown still to work unchanged. **F1 does not address this
gap at all.**

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

**Closes when:** F2 has extended the model and it has been exercised across the
generalized cases (R5), not only OpenMover.

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
