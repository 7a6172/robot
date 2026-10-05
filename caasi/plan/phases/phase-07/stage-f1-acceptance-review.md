# Phase 7: F1 Acceptance Review

**Status:** Review complete. Verdicts recorded below.
**Date:** October 2026
**Scope:** Whether the F1 evidence supports closing G1 and G2, or whether a genuine
gap remains. **No implementation was changed to reach these verdicts.**

---

## 1. What was reviewed

F1 was checked against the **agreed definitions** of G1 and G2 (as recorded in
[`architecture-gap-assessment.md`](architecture-gap-assessment.md)) and against
the R1–R10 traceability chain — not against the F1 report's own summary.

---

## 2. G1 — nothing decides a target

**Agreed closure basis:** requirement-driven, advisory, inspectable selection with
no hidden automatic choice.

| Criterion | Evidence | Verdict |
| :--- | :--- | :--- |
| **Requirement-driven** | `evaluate_requirements` merges the project's `requires:` with an optional workload's and matches each against the target's facts via `requirements.satisfies` | **met** |
| **Inspectable** | every `RequirementVerdict` carries `required`, `detected`, `verdict` and a `note`; the CLI prints a per-target verdict *and why*, and `--json` exposes the same | **met** |
| **Advisory** | `select_all` returns a **list** of reports — a set of verdicts, not a choice; `select_target` evaluates one *already-named* target | **met** |
| **No hidden policy** | no ranking, scoring, preference or "best target" logic exists in the module; `compose` calls `select_target` only as a **gate** on a named target, never to choose one | **met** |
| **Genuinely connected** | the matcher was previously reachable only from `check.py`; `requirements.satisfies` now has a second caller in `selection.py` | **met** |

**Live re-verification on the real remote target `u24-307`** (not a fixture):
out-of-range → `untested`, missing component → `missing`, unprobed component →
`untested`. All as specified.

**Verdict: G1 — CLOSED.**

---

## 3. G2 — target-aware compatibility / check

**Agreed closure basis:** target-aware fact sourcing reusing the existing
CheckEngine / Check Contract, with remote-target evaluation including the §57 case
demonstrated.

| Criterion | Evidence | Verdict |
| :--- | :--- | :--- |
| **Target-aware fact sourcing** | `target_facts()` derives facts from a `TargetInspection` (`TargetEnvironment` / `TargetResources`), never from the local machine | **met** |
| **Remote evaluation demonstrated** | verified live against `u24-307`: §57 out-of-range → `untested` (not `incompatible`), `missing` and `unmeasured` all correct | **met** |
| **Check Contract vocabulary reused** | `check_core.summarize` and `check_core._version_spec` are called directly; the verdict names are the contract's (`compatible`/`untested`/`missing`/`incompatible`) | **partly met** |
| **The engine itself was extended** | **No.** `check.py` remains local-only; F1 added a *separate* module | **not met as designed** |

### 3.1 The genuine remaining gap

The F1 **design** stated the intent explicitly:

> *"Concretely, F1 is: teach the engine to source detected facts from a `Target`
> inspection instead of only `config`/`shell.which`, then add a `target` scope and a
> read-only command that renders the resulting report per target."*

The **implementation did not do that.** Instead:

- `check.py` is **unchanged** and still answers only for the local machine;
- `selection.py` **re-implements** the requirement ladder that
  `check.ProjectRequirementsChecker._requirement_item` already contains;
- the two share only `_version_spec`, `summarize` and the verdict names, so the
  ladder is **duplicated**, not shared.

**Measured extent:** `selection.py` constructs a verdict **11** times against
`check.py`'s **7** `CheckItem` constructions in the equivalent ladder — the extra
ones being the GPU paths, for which the contract has no equivalent. The note text
also uses different conventions: the contract uses i18n keys
(`check.note.out_of_range`), while `selection.py` writes hardcoded English prose.

**What agrees.** For unconfigured projects the two are **consistent**: the verdicts
match, both apply §57, and both call the same `requirements.satisfies`. That is why
the F1 evidence is sound.

**One concrete divergence exists, and it is observable.** With `check.strict: true`,
`caasi check` escalates a warning to `incompatible`:

```text
check.summarize(items, strict=False) -> warning
check.summarize(items, strict=True)  -> incompatible
```

`selection.py` calls `check_core.summarize(items, strict=False)` **unconditionally**,
so for a project that sets `check.strict: true`, the same out-of-range requirement
is reported `incompatible` (exit 3) by `caasi check` but a mere `warning` (exit 0)
by `caasi target select` — including when `target select` is used as the
composition gate. That is a real behavioural difference produced by the
duplication, not merely a structural one.

**Why it still matters.** Two implementations of one semantics drift. The Check
Contract exists precisely to prevent that ("one compatibility semantics behind
every `check`"), and the design's whole argument for F1 being small was that
`target select` would be *another entry point of the existing engine*. As built, a
future change to the ladder (a new verdict, changed note wording, `check.strict`
propagation) must be made twice and can silently diverge. `check.strict` is a
**concrete, live example**: `selection.py` calls
`check_core.summarize(items, strict=False)` unconditionally, so a project
configured with `check.strict: true` receives strict escalation from `caasi check`
but **not** from `caasi target select`.

### 3.2 Decision

Two things were conflated in G2's definition:

1. **the capability** — can caasi evaluate a *project's requirements against a
   remote target's facts, honestly?* → **met and evidenced**;
2. **the implementation route** — *is it the same engine instance rather than a
   parallel path?* → **not met**.

The agreed closure basis for G2 named both ("target-aware fact sourcing" **and**
"reusing the existing CheckEngine"). Reporting honestly: **the capability is
delivered; the engine-extension route was not taken.**

**Verdict: G2 — capability CLOSED; engine-extension criterion NOT met.**

Per the instruction *"do not change F1 implementation merely to make the status
appear closed; if there is a genuine remaining gap, report it"*, this is reported
rather than papered over. It is also **not** fixed here, because consolidation is an
implementation change beyond a review.

**Recommended disposition** (not implemented): a small follow-up to move the
requirement ladder into one shared function that both `check.py` and
`selection.py` call — keeping `target select` as a second entry point as designed,
and propagating `strict`. That would make G2's definition fully met and remove the
`check.strict` divergence.

It does **not** block F3, and the capability works today for projects that do not
set `check.strict`.

---

## 4. G3, G4, G5

| Gap | Verdict | Basis |
| :--- | :--- | :--- |
| **G3** lifecycle composition | **CLOSED** | four-step composition validated end to end on the real `u24-307`; individual commands verified unchanged |
| **G4** `remotes:` shim | **OPEN — cleanup** | untouched; tracked as retirement work, requires a migration path |
| **G5** workload object | **CLOSED** | F1 gave the model, F2 added `steps`/`outputs`; exercised on general Python, ROS 2 and OpenMover workloads |

---

## 5. Summary

| Gap | Status |
| :--- | :--- |
| G1 target selection | **CLOSED** |
| G2 target-aware compatibility | **CLOSED** (capability) — with a reported structural gap: the Check Contract ladder is duplicated rather than shared |
| G3 lifecycle composition | **CLOSED** |
| G4 `remotes:` shim | **OPEN / cleanup** |
| G5 workload object | **CLOSED** |

**The one honest caveat, stated plainly:** G2 is closed on capability and evidence,
but its implementation route diverged from the design — `check.py` was not extended,
and the ladder now exists twice. For projects without `check.strict` the two paths
agree, which is why the F1 evidence stands. They are **not** identical, however:
`target select` does not honour `check.strict`, so it can report `warning` where
`caasi check` reports `incompatible`. That divergence is recorded as a
**consolidation item that F1 acceptance does not remove**.

No implementation was changed during this review.
