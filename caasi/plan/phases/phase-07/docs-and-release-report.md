# Phase 7: 0.4.0 Documentation Checkpoint and Release Assessment

**Status:** Completed & Verified
**Date:** October 2026
**Plan:** [`docs-checkpoint-plan.md`](docs-checkpoint-plan.md)

---

## 1. Documentation: what was done

The **existing static HTML site was extended**, not replaced. No framework, no build
step, no parallel docs system; the visual language, shared assets and data-driven
sidebar are unchanged.

### 1.1 Five new pages

| Page | Content |
| :--- | :--- |
| **`targets.html`** | the target model; `list/inspect/check/select/occupancy/runtime`; the three verdict states; `--where` policies and the explained decision report; **the deployment prerequisite for `run`**; occupancy as an observation; runtimes |
| **`workloads.html`** | the workload model; the closed step vocabulary; the composed chain; failure behaviour; run prerequisites (stated plainly); the individual steps |
| **`lifecycle.html`** | `deploy`; target-native `build`; `runtime install/enable/start/status/verify/update/rollback`; the environment-vs-service split; revision identity and the **honest rollback** |
| **`examples.html`** | the catalog as a user-facing section; prerequisites; **CI / opt-in / manual** tiers; the command index; links to `COVERAGE.md` |
| **`limitations.html`** | the three-way distinction: **environmental limitations**, **deliberately deferred** capability (with reasons), and **current boundaries**; plus what would justify revisiting each |

### 1.2 Navigation

Two new sidebar groups — **Control plane** (after Projects) and **Examples &
reference** (before Advanced) — keeping the existing 11 groups and their order. The
`index.html` **command map** gained six cards.

### 1.3 Version: 0.4.0 throughout

All 16 pre-existing pages now carry the `v0.4.0` badge and footer.

**20 `0.3.0` references remain, and all are deliberate historical migration notes**
(*"New in v0.3.0: opt-in keys"*, *"the root `synth` group was removed in 0.3.0"*,
*"Up to 0.2.0 → Since 0.3.0"*). These describe **what changed in that release** and
are correct as history. What was removed is every reference that presented 0.3.0 as
the *current* version — the CLI example output in `environment.html` and
`index.html`.

### 1.4 Existing pages updated (not replaced)

| Page | Change |
| :--- | :--- |
| `index.html` | quickstart extended through the 0.4.0 chain; **command map completed**; version output corrected |
| `remote.html` | **`caasi target` now leads**; the legacy `remote` group marked **deprecated** with the reason it is retained |
| `runs.html` | the **deployment prerequisite** stated where a reader hits `run` |
| `ros.html` | remote observation (`--target`/`--domain`) and target-aware tool invocation |
| `configuration.html` | `tools:` documented as serving **both** the version registry and target-aware invocation |
| `observability.html` | links the occupancy query and `target runtime` |
| `environment.html` | stale CLI version output corrected |

### 1.5 The boundary, stated where it matters

Rather than repeating a boilerplate paragraph on every page, the
**caasi-manages / ecosystem-owns / caasi-delegates / supported-vs-opt-in-vs-deferred**
distinction appears in full on `targets.html` and `limitations.html`, and as a short
contextual note elsewhere (e.g. `lifecycle.html` states "caasi is not a supervisor"
where that is the point).

---

## 2. Release hardening — verification performed

| # | Check | Result |
| :--- | :--- | :--- |
| 1 | **Render / HTML check** | **21/21 pages** structurally clean — span-balanced, tags nested, **zero broken internal links** |
| 2 | **No stale 0.3.0** | 20 remain, **all historical migration notes** (verified individually); no page presents 0.3.0 as current |
| 3 | **Command map vs live CLI** | **all 57 root commands** named in the docs command map; cross-checked against the live CLI and `COVERAGE.md` (253 paths) |
| 4 | **Example links resolve** | verified by the link checker; `examples.html` links into the catalog and to `COVERAGE.md` |
| 5 | **Full test suite** | **1250 passed, 1 failed** |
| 6 | **Fresh install** | clean venv → `pip install` → **`caasi-0.4.0`**, three declared dependencies, CLI functional, 0.4.0 commands work |
| 7 | **Upgrade** | PyPI **0.3.0 → 0.4.0 in place**, no uninstall; the 0.4.0 surface works afterwards |
| 8 | **Known failure unrelated** | **confirmed** — see §3 |
| 9 | **Changelog / release report** | 0.4.0 section completed with the workload/selection, local-semantics, documentation and fixed sections |

### 2.1 One defect found and fixed (in the docs)

The HTML link/structure checker caught a **missing `</span>`** in a `index.html` code
block — introduced by my own quickstart edit. Fixed, and all 21 pages re-verified.
Worth noting the checker earned its place: a visually fine page was structurally
broken.

---

## 3. The known test failure — confirmed pre-existing and unrelated

```
tests/test_perception_cmd.py::test_perception_segment_dry_run_passes_extra_args
```

**Cause:** terminal-width line wrapping. The assertion looks for
`"image_segmentation.launch.py model:=unet"`, but the output is wrapped at the
terminal width, producing `launch.py \nmodel:=unet`. The text is **present**; the
substring match fails on the newline.

**Evidence that it is unrelated to 0.4.0:**

1. the file under test, `src/caasi/cli/accelerated.py`, has **not been modified since
   the baseline commit** — before this work began;
2. it concerns Isaac ROS perception, which no 0.4.0 change touches;
3. it was reproduced and attributed in an earlier stage by stashing changes and
   running against the unmodified commit.

**Verdict: pre-existing environment artifact, not a regression.**

### 3.1 One apparent anomaly investigated and dismissed

After upgrading 0.3.0 → 0.4.0, `caasi doctor` exited non-zero in a bare virtualenv.
Checked against a **0.3.0-only install in the same kind of environment: both exit 1.**
It is correct reporting of a machine with no ROS/Isaac, **not a regression**.

---

## 4. Corrections to the earlier audit

Reported rather than quietly dropped:

- **`platform.html` is not mis-titled.** My checkpoint plan claimed it was
  "mis-titled/misrepresented". Inspection showed its `<title>`, `<h1>`, sidebar label
  and command-map card **all correctly say "Physics & Foundation Models"**. Only the
  *filename* is stale — invisible to readers. Renaming would touch **17 references
  across 8 files** for no reader benefit, so it was **left alone** and is recorded as
  a known cosmetic inconsistency.
- **`rqt` was initially missing from the command map** — caught by the automated
  cross-check (56/57), then added as a target-aware tools card.

---

## 5. Files changed

| Path | Change |
| :--- | :--- |
| `docs/targets.html` | **new** |
| `docs/workloads.html` | **new** |
| `docs/lifecycle.html` | **new** |
| `docs/examples.html` | **new** |
| `docs/limitations.html` | **new** |
| `docs/assets/sidebar.js` | two new groups |
| `docs/index.html` | badge, quickstart, 6 command-map cards, version output |
| `docs/{environment,configuration,runs,observability,ros,remote}.html` | targeted updates |
| `docs/*.html` (all 16) | badge + footer to 0.4.0 |
| `CHANGELOG.md` | 0.4.0 workload/selection, local semantics, documentation, fixed sections |

Reference trees unchanged: `openmover_robot` `f17c242a…`, `openmover_ws`
`1e09f5de…`, `caasi-workspace/openmover` 0 dirty.

---

## 6. What remains for 0.4.0

**Nothing blocking.** The capability set is complete and validated; documentation now
covers it; the install and upgrade paths are verified; the changelog is written; the
one test failure is proven pre-existing.

| Item | Status |
| :--- | :--- |
| Capability set | **complete** for the evidence gathered |
| Documentation | **complete** for the current CLI |
| Fresh install / upgrade | **verified** |
| Changelog | **complete** |
| Known test failure | **confirmed pre-existing and unrelated** |
| `platform.html` filename | **cosmetic inconsistency**, deliberately left |
| G4 `remotes:` retirement | **deferred** — prerequisites recorded in `limitations.html` |
| Web UI (R10) | **deferred** |
| Scheduling/queues (R8) | **deferred** pending evidence |

**Release readiness: 0.4.0 can be tagged.** The remaining items are deliberate
deferrals with recorded reasons, not unfinished work.

---

## 7. What would justify 0.5.0

Recorded so the next stage is evidence-driven, not roadmap-driven: **observed
contention** (queues), a **genuine multi-target workload**, a **second real project**,
**real artifact needs** (a third destination), or **real monitoring needs** (the web UI).
