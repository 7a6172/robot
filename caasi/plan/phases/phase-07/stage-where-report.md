# Phase 7 Report: `--where` Explicit Target Selection

**Status:** Completed & Empirically Verified
**Date:** October 2026
**Design:** [`where-selection-design.md`](where-selection-design.md)
**Origin:** [`r8-architecture-review.md`](r8-architecture-review.md) — the minimum R8 abstraction
**Traceability:** [`traceability.md`](traceability.md)

---

## 1. The boundary, held

> **`--where` answers "which currently suitable target should I use?" — a query the
> operator asks. A scheduler answers "when and where should this eventually run?" —
> a policy the system applies unbidden.**

Kept intact: no queue, no reservation, no waiting, no retry, no forwarding, no
scoring.

---

## 2. What was built

```bash
caasi workload run <name> --target <t>          # named explicitly, unchanged
caasi workload run <name> --where any
caasi workload run <name> --where idle
caasi workload run <name> --where prefer:<tag>
caasi workload run <name> --where any --dry-run
```

| Piece | Character |
| :--- | :--- |
| `caasi.core.where` | policy parsing, occupancy derivation, the decision + report |
| `SelectionDecision` | a **reporting type only** — no state |
| Provenance | `selected_by` + `selection_reason` on the existing run record |

**No new persistent state. No registry. No queue table.** The decision is computed
per invocation from facts that already exist, and recorded beside the run it
produced.

### 2.1 Reused, not rebuilt

- `selection.select_all` — already evaluates every target and already ranks nothing;
- `runs.list_runs` + `effective_status` — occupancy is **derived**, not tracked;
- `Target.tags` — already present and real (`cpu-only`, `workstation`, …);
- the shared Check Contract ladder from the F1 consolidation.

---

## 3. Required semantics — all verified

| Required | Status |
| :--- | :--- |
| `--target <t>` unchanged and deterministic | **verified** (case 9: no selection block, identical behaviour) |
| `--where any\|idle\|prefer:<tag>` explicit opt-in | **verified** |
| Omitting both is an error | **verified** (exit 1, actionable message) |
| `--target` and `--where` mutually exclusive | **verified** (exit 1) |
| Evaluate all candidates using existing machinery | **verified** — via `select_all` |
| `incompatible` ineligible | **verified** |
| Reachable `warning` eligible | **verified** |
| Unmeasured facts reported, never converted to absence | **verified** — printed as notes, target stays eligible |
| `lost` is unknown, neither busy nor free | **verified** — reported separately, not resolved |
| Deterministic target-name tie-break | **verified** — 3 consecutive runs chose identically |
| No scoring / weighting / cost model / hidden ranking | **verified** — enforced by a test that inspects the code, not the prose |
| No reservation or locking | **verified** — two simultaneous decisions may both see a target idle, by design |
| No queue | **verified** — no queue machinery exists or was added |
| No waiting | **verified** — "nothing fits" returns immediately |
| No automatic forwarding | **verified** — a failed target is never substituted |

---

## 4. Validation on the two real targets

| # | Case | Result |
| :--- | :--- | :--- |
| 1 | `--where prefer:gpu`, GPU workload | selected `local`; **eliminated `u24-307` with "target reports no GPUs"** |
| 2 | `--where prefer:cpu-only`, CPU workload | **selected `u24-307`** — it carries the tag; ordering explained as "matched" |
| 3 | `--where any`, both suitable | chose `local`; **identical across 3 runs** (deterministic name tie-break) |
| 4 | **Nothing fits** (4 GPUs, isaac ≥99) | **failed, exit 3**, both targets eliminated with per-target evidence, and **no deployment was created** |
| 5 | `--where idle`, one target busy | with a real 600 s run occupying `local`, **selected `u24-307`** — the occupancy preference demonstrably changed the outcome |
| 6 | `--where idle`, all busy | still selects (preference, **not** a gate); states the count |
| 7 | `lost` runs present | reported as *"unknown run state (neither busy nor free)"*, not counted as busy |
| 8 | Unmeasured requirement | eligible, **and the note is printed** |
| 9 | `--target` alone | **byte-for-byte today's behaviour** — no selection report |
| 10 | `--target` + `--where` | refused: *"mutually exclusive; give exactly one"* |
| 11 | Neither given | refused, naming both options |
| 12 | Provenance | recorded `selected_by: prefer:workstation` + `selection_reason` |
| 13 | Unreachable in the set | eliminated with the transport reason |

### 4.1 Case 4 in detail — the anti-scheduler property

```console
Selection for workload 'impossible'
  policy: any
  ordering: no eligible targets

  ✖ eliminated u24-307  does not satisfy 'gpu' — target reports no GPUs
  ✖ eliminated local    does not satisfy 'gpu' — target reports 1 GPU(s), 4 required

Error: no target satisfies this workload (nothing was deployed or queued)
```

Exit **3**. Verified independently that **no deployment directory was created**.
Nothing waits, nothing is held, nothing is retried elsewhere.

### 4.2 Explaining the choice

Every decision names the selected target, the policy and the ordering rule, every
eliminated target with the failing requirement **and its measured evidence**, and
any unknown/unmeasured conditions:

```console
  policy: prefer:cpu-only
  ordering: targets carrying tag 'cpu-only' first, then target name (matched)
  ✔ SELECTED   u24-307
  ✖ eliminated local  suitable, but not chosen by this policy

  unknown run state (neither busy nor free)
      · u24-307: 1 run(s) in an unknown state
```

---

## 5. Defects found

**One, in this stage's own code:** `output.fail()` raises its own `Exit(1)`, so a
`raise typer.Exit(3)` after it was unreachable and "nothing fits" exited **1**
instead of 3. The printed message was already correct — only **measuring the exit
code** revealed it. **The identical trap occurred in F3**, which is worth noting as
a recurring hazard in this CLI helper.

**One introduced earlier and found here:** the F1 consolidation made *target*
verdicts inherit the local check's note wording — *"not detected on **this
machine**"* — which is **factually wrong for a remote target**. The shared ladder now
takes a `scope`, so a target verdict says *"not detected on this target"* while
`caasi check` keeps *"this machine"*. The ladder stays single; only the phrase
adapts. This is exactly the kind of wording leak consolidation makes possible, and
it was caught by reading real remote output rather than tests.

---

## 6. Concurrency: the idle race, documented not solved

Two workloads submitted at the same moment can both observe a target as idle and
both select it. **This is not a defect and was not fixed**, per the design:
occupancy is an **observation and a preference, never a reservation**.

Solving it belongs to a future allocation/scheduling layer, and closing it here
would require precisely the reservation machinery this stage must not add. Verified
that no reservation or lock exists today (`.caasi/lock.py` covers configuration
only) and that multiple runs per target are already normal — 36 recorded on `local`
— so nothing here pretends otherwise.

---

## 7. Tests

**31 new tests** in `tests/test_where.py`: policy parsing (including that an unknown
policy is rejected rather than silently defaulting, and that a bare tag is not read
as `prefer:`); eligibility (incompatible excluded, unmeasured eligible and reported,
unreachable eliminated with its transport reason); the nothing-fits path; determinism
and stated tie-breaks; `prefer:<tag>` precedence, fallback, and that a tag cannot
resurrect an ineligible target; occupancy (preference not gate, ties broken by name,
unknown state reported not resolved, and that no reservation is attempted); and
reporting (full serialisation, every target accounted for).

Two tests guard the boundary structurally: one inspects the **code** (not the
docstring) for scoring/weighting/balancing vocabulary, and one asserts the module
carries no threading/asyncio/queue/sleep machinery.

**Full suite: 1215 passed, 1 failed** — the pre-existing `test_perception_cmd.py`
terminal-width artifact.

---

## 8. Files changed

| File | Change |
| :--- | :--- |
| `src/caasi/core/where.py` | **new** — policies, occupancy, decision, report |
| `src/caasi/cli/workload_cmd.py` | `--where` option, either/or validation, decision report |
| `src/caasi/core/compose.py` | records `selected_by` / `selection_reason` |
| `src/caasi/core/selection.py` | asks for target-scoped notes |
| `src/caasi/core/check.py` | shared ladder takes a `scope` for accurate wording |
| `src/caasi/i18n/en.py` | 10 new strings; 2 existing ones corrected (stale `--target` help text), plus the target-scoped note |
| `tests/test_where.py` | **new** — 31 tests |

Reference trees unchanged: `openmover_robot` `f17c242a…`, `openmover_ws`
`1e09f5de…`, `caasi-workspace/openmover` 0 dirty. All fixtures removed (including
the `wdemo` deployment and the temporary long-running probe run, which was stopped).

---

## 9. What was NOT done

No queue; no reservation; no resource booking; no waiting; no retry; no automatic
forwarding; no multi-target execution; no scheduling; no ranking or scoring; no
fleet management; no web UI. **G4 untouched. DDS-over-Tailscale untouched.**
`.trae` / `.reasonix` ignore rules untouched.

---

## 10. Next step

**Stopping for review.** Not proceeding into queues, reservations, allocation or
scheduling.

If a future stage is warranted, the review already identified what would justify
it: **observed contention** (queues solve contention, and none has been seen) and a
real second-target use case. Until then, `--where` is the whole of the R8 capability
caasi needs.
