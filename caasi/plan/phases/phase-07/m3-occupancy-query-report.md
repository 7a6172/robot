# Phase 7 Report: M3 — Target Occupancy as a Read-Only Query

**Status:** Completed & Empirically Verified
**Date:** October 2026
**Origin:** [`r8-architecture-review.md`](r8-architecture-review.md) §4.2 M3 — the presentation gap identified there
**Traceability:** [`traceability.md`](traceability.md)

---

## 1. The gap

The R8 review recorded **M3**: occupancy was computed inside `--where`, but there
was **no way for an operator to ask what is running where**. `caasi target list`
showed transport, endpoint and tags — but not live runs — and
`occupancy_by_target` had exactly one caller.

**A presentation gap, not a state gap.** The inputs already existed; only exposure
was missing. That is why M3 is small and why it needed no new state.

---

## 2. What was built

```bash
caasi target occupancy            # every configured target
caasi target occupancy <target>   # one target
caasi target occupancy --json
```

**Read-only.** It reports; it changes nothing, holds nothing and reserves nothing.

| Piece | Character |
| :--- | :--- |
| `occupancy_by_target` | **extended** with per-run detail — still the *one* implementation |
| `caasi target occupancy` | a query and a rendering over that function |
| `occupancy_state()` | `occupied` / `unknown` / `idle` — three states, never conflated |

**No second occupancy implementation.** `--where idle` and `target occupancy` call
the same function, so they cannot disagree about what is busy — enforced by a test.

### 2.1 One implementation, extended rather than duplicated

The existing function returned only counts (`occupying`, `unknown`, `run_ids`).
The query needs *what* is running, so it was extended to carry per-run detail:

```python
"runs":         [{"run_id", "name", "kind", "backend", "status", "project", "deployment_id"}]
"unknown_runs": [...]
```

The counts are derived from the same pass, so `occupying == len(runs)` always —
also enforced by a test.

---

## 3. States — unknown is never collapsed into idle or busy

| State | Meaning |
| :--- | :--- |
| `occupied` | at least one `running` or `paused` run |
| `unknown` | no occupying run, but at least one whose state **could not be determined** |
| `idle` | no occupying run and no unknown run |

`lost` is reported as **unknown** and counted as neither busy nor free — the same
rule that governs unmeasured requirements and unmeasured run states everywhere else
in caasi. The output says so explicitly.

`paused` occupies: the process is still resident and still holding the target.

---

## 4. Validation on the real targets

### 4.1 The idle → occupied → idle transition (a real workload)

| Step | Command | Observed |
| :--- | :--- | :--- |
| 1 | `target occupancy local` | `○ idle` — no runs |
| 2 | `run start experiments/hold.yaml --target local` | real 900 s workload started |
| 3 | `target occupancy local` | **`● occupied` — `1 running`**, naming the run and its project |
| 4 | `run stop <run-id>` | stopped |
| 5 | `target occupancy local` | **`○ idle`** — back to no runs |

A stopped run correctly **stops occupying** the target. The run was independently
confirmed as `stopped` (not `lost`) and left **no orphaned process**.

### 4.2 The two surfaces agree

With `local` genuinely occupied by a running workload:

- `target occupancy local` → `● occupied`, `1 running`
- `workload run any --where idle --dry-run` → **selected `u24-307`**, with
  *"ordered by live run count… selected target has 0 occupying run(s)"*

**Both read the same occupied state and act consistently on it.** This is the
single-implementation property demonstrated on real data, not merely asserted.

### 4.3 Unknown state, on a real target

`u24-307` carries a long-standing run whose state cannot be determined. The query
reports it truthfully rather than guessing:

```console
┃ u24-307 ┃ ? unknown ┃ 1 unknown ┃
u24-307
  unknown  20261004-182424-target-smoke-stop  target-smoke-stop
           (state could not be determined; neither busy nor free)
```

This is exactly the distinction the design required: **unknown, not idle**.

### 4.4 Other cases

| Case | Result |
| :--- | :--- |
| `--json` | full per-target payload including per-run identity and unknown runs |
| Single-target form | `caasi target occupancy local` |
| Unknown target | clear error listing the configured targets |
| Never-used targets | reported with zero runs, not conflated with a busy one |

---

## 5. What M3 deliberately does not do

No reservations; no locks; no queues; no scheduling; no ranking; no allocation; no
persistent occupancy state; **no second occupancy implementation**. The JSON output
is a view, not a state store.

**The idle race is unchanged and still open by design:** two submissions can both
observe a target as idle. Exposing occupancy does not solve that — and must not be
mistaken for having solved it. It remains an observation and a preference, never a
reservation.

---

## 6. Limitations (open, recorded not worked around)

| Limitation | Character |
| :--- | :--- |
| **Idle race** | by design — occupancy is an observation; closing it needs reservations, which are out of scope |
| **`lost` runs persist** | a run whose state cannot be determined stays reported as unknown indefinitely; M3 reports it truthfully rather than cleaning it up, because cleanup is a separate concern and deleting run records is destructive |
| **Occupancy is per configured target** | run records naming a target no longer configured (e.g. a removed one) are not shown; the query reports *configured* targets |
| **DDS-over-Tailscale** | environmental, unrelated, untouched |
| **G4 `remotes:` shim** | cleanup, untouched |

---

## 7. Tests

**8 new tests** in `tests/test_where.py`: per-run detail is recorded; `paused`
occupies; terminal states do not; `lost` is recorded separately and never as busy;
counts and detail stay consistent; unreadable run state does not raise; **the
workload and target surfaces share one implementation**; and **no persistent
occupancy store exists** (checked against the module's *imports*, not its prose).

**Full suite: 1223 passed, 1 failed** — the pre-existing `test_perception_cmd.py`
terminal-width artifact.

---

## 8. Files changed

| File | Change |
| :--- | :--- |
| `src/caasi/core/where.py` | `occupancy_by_target` extended with per-run detail |
| `src/caasi/cli/target_cmd.py` | `caasi target occupancy` query |
| `src/caasi/i18n/en.py` | 9 new strings |
| `tests/test_where.py` | 8 new tests |

Reference trees unchanged: `openmover_robot` `f17c242a…`, `openmover_ws`
`1e09f5de…`, `caasi-workspace/openmover` 0 dirty. Fixtures and the temporary
workload were removed.

---

## 9. Next step

**Stopping for review.** Exposing occupancy does **not** justify scheduling, and
none was added. The justification recorded in the R8 review still stands:
**observed contention** and a real second-target use case — neither of which this
stage produced.
