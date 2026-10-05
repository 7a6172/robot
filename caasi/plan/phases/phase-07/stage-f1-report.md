# Phase 7 Stage F1 Report: Workload Model and Target-Aware Selection

**Status:** Completed & Empirically Verified
**Date:** October 2026
**Addresses gaps:** **G1** (nothing decides a target), **G2** (`check` is local-only), and the first half of **G5** (no workload object)
**Requirements:** R1, R4, R5, R6
**Design:** [`workload-and-selection-design.md`](workload-and-selection-design.md) §4, §10
**Traceability:** [`traceability.md`](traceability.md)

---

## 1. Objective

Close the gap between "caasi can operate on a target you already chose" and
"caasi can answer **can this work run there?**" — requirement-driven, inspectable
and advisory, reusing the existing Check Contract rather than inventing a second
compatibility semantics.

---

## 2. What was implemented

### 2.1 `caasi.core.selection` (new)

Supplies the missing half of the Check Contract: **the same verdict ladder, the
same §57 caution, the same exit policy — but with facts sourced from a target's
own discovery instead of the local machine.**

| Piece | Purpose |
| :--- | :--- |
| `target_facts(inspection)` | maps a target's discovered facts onto the contract's names |
| `PROBED_FACTS` | the bounded set discovery actually asks about |
| `evaluate_requirements()` | mirrors `ProjectRequirementsChecker._requirement_item` exactly |
| `select_target()` / `select_all()` | per-target verdicts, advisory only |
| `SelectReport` / `RequirementVerdict` | reporting types; no state, no side effects |

The deliberate design property: **no new compatibility semantics.** The ladder,
the notes and the doctrine are the Check Contract's.

### 2.2 `caasi.core.workload` (new — minimal, intentionally)

Stage F1 introduces only what selection needs:

- `Workload` — `name` and `requires`;
- `steps` / `outputs` **parse and are recorded but not acted on**, so a workload
  written for F2 loads today without a second migration;
- `combined_requirements()` — workload requirements **extend** the project's, and
  the workload wins on collision (it is the more specific statement of this work).

Nothing here is ROS- or project-specific: `requires` entries are ordinary
requirement specs.

### 2.3 `caasi target select`

```bash
caasi target select [WORKLOAD] [--json]
```

Reports, for **every** configured target, whether it satisfies the merged
requirements, and **why**. Advisory and read-only: it chooses nothing, and
execution still names a target explicitly.

---

## 3. Design decisions

1. **Reuse the Check Contract.** The assessment found `check.py` already owns
   "one compatibility semantics behind every `check`", already serving several
   entry points. `target select` is another entry point of the same ladder, not a
   parallel vocabulary. This is why F1 is small.

2. **§57 is honoured on remote targets too.** A version outside a required range
   is a `warning` with an explanation and exit code **0** — never asserted as
   incompatible from a version range alone.

3. **Absence is measured, not assumed.** Three distinct outcomes, which the
   implementation keeps apart:

   | Situation | Verdict |
   | :--- | :--- |
   | target was asked, and has it | `compatible` (or `untested` if out of range) |
   | target was asked, and does **not** have it | `missing` — a real absence |
   | target was **never asked** | `untested` — not evidence of absence |

4. **`unreachable` is a transport result, not a verdict.** A target that could not
   be inspected reports its reason and is not evaluated at all, rather than being
   silently scored.

5. **Exit policy follows the contract** (`incompatible` → 3), so `target select`
   composes with existing tooling.

---

## 4. A defect found by validating against real targets

The GPU path initially reported **`untested` ("not measured")** for `u24-307`,
which has **no GPUs**. But that target *was* inspected and definitively reported
zero GPUs.

Collapsing the two told an operator **"unknown"** when the true answer was
**"none"** — the opposite of the evidence discipline the design requires. Fixed by
preserving the measured empty list and distinguishing it from a missing
inspection.

This was only visible against real machines: no unit fixture would have shown it,
because the bug was in what the *real* discovery returns for a machine that
genuinely lacks a GPU.

A second, smaller defect was found the same way: a workload file using the
`workload:` block spelling parsed to **empty** `requires` — silently reading "this
work needs nothing". The parser now accepts that spelling *and* **rejects unknown
keys**, so a typo is reported instead of quietly weakening the requirement set.

---

## 5. Validation

### 5.1 Against real targets

Targets: **`u24-307`** (remote, ROS 2 Jazzy, **no GPU**) and **`local`**
(RTX 3080, 10 GB, Isaac Sim/Lab, docker, jazzy).

| Case | Result |
| :--- | :--- |
| `ros2 jazzy` + `python >=3.10` | both targets `ready`, each requirement `compatible` with the detected version |
| `ros2 humble` (§57) | both `warning`, note *"detected jazzy is outside the required range"*, **exit 0** |
| `isaac_sim >=5.0` | both `incompatible`, **exit 3** |
| `gpu count>=1, memory_gb 8` | **`u24-307` `incompatible`** ("target reports no GPUs"); **`local` `ready`** (RTX 3080) |
| `torch >=2.0` (never probed) | both `warning`, *"not measured (not evidence of absence)"*, **exit 0** |
| unreachable target | own verdict: *"Could not connect to 192.0.2.99:22"* |
| unknown workload name | exit 1, names the known workloads |
| no requirements declared | exit 1, explains how to declare them |

### 5.2 The decisive result

Merging the project's `ros2: jazzy` with a workload's `gpu: count>=1, memory_gb 8`:

```console
┏━━━━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Target  ┃ Verdict        ┃ Why                         ┃
┡━━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ u24-307 │ ✖ incompatible │ gpu: target reports no GPUs │
│ local   │ ● ready        │ 2 compatible                │
└─────────┴────────────────┴─────────────────────────────┘
```

**This is the capability the stage exists to add:** *"where can this workload go,
and why?"* — answered per target, with reasons, from real discoverable facts.

### 5.3 The real OpenMover project

The canonical project's actual `requires:` (`ros2 jazzy`, `isaac_sim >=5.0`,
`isaac_lab >=2.0`, `nav2`) were evaluated against both targets, without modifying
the project. Result: `ros2 compatible`; `isaac_sim`/`isaac_lab` `missing`; **`nav2`
`untested`** — because target discovery does not probe ROS packages, so it is
honestly reported as unmeasured rather than a false "missing".

### 5.4 Generalization

The command is **not** OpenMover-specific. It reads `requires:` from any project
manifest and any workload declaration; the OpenMover case above is simply the real
data applied to it. Applying the scope test — replace OpenMover with any ROS 2 /
Isaac project — the behaviour is unchanged.

---

## 6. What F1 establishes, and what it does not

**Establishes:**

- requirement-driven, inspectable, advisory target compatibility (G1, R6);
- target-aware fact sourcing reusing the Check Contract (G2);
- the minimal `Workload` model with `requires` (first half of G5, R5);
- three-way honesty: satisfied / measured-absent / unmeasured.

**Does not establish (and does not claim):**

- **Any target selection.** It reports; it never chooses. There is no ranking,
  no scoring, no automatic pick (R6, and the standing prohibition).
- **Composition.** Nothing deploys, builds, runs or collects. That is F2 (G3).
- **Steps and outputs.** They parse but are not acted on (F2).
- **GPU memory semantics beyond a simple threshold** — compared against the
  largest GPU's total memory, which is a reasonable approximation, not a claim
  about allocation.
- **`nav2`-style ROS package probing.** Discovery does not probe ROS packages, and
  F1 does not add that; such requirements are reported unmeasured, which is the
  honest outcome rather than a fabricated one.
- **G4** (legacy `remotes:` shim) — untouched and still tracked as outstanding
  cleanup (see traceability).

---

## 7. Tests

**39 new tests** in `tests/test_selection.py`: fact mapping (including that absent
facts are never invented); every verdict path — satisfied, range-satisfied,
out-of-range warning, probed-but-absent `missing`, unprobed `untested`,
no-version `untested`; the GPU paths — met, measured absence, not-inspected,
memory shortfall as warning, insufficient count as `missing`; target-level
reporting — unreachable as its own verdict, unreachable not evaluated, missing
inspection, ready, incompatible, `select_all` covering unreachable targets, and
JSON serialising unmeasured as first-class; and the workload model — parsing,
wrapped spelling, mixed-wrapper rejection, **unknown-key rejection**, type
validation, name fallback, missing file, directory listing, prefix lookup,
ambiguous prefix, requirement merge, collision precedence, and that F1 records
`steps`/`outputs` without acting on them.

**Full suite: 1093 passed, 1 failed.** The failure is the pre-existing
`test_perception_cmd.py` terminal-width artifact, unrelated to this stage.

---

## 8. Files changed

| File | Change |
| :--- | :--- |
| `src/caasi/core/selection.py` | **new** — target-aware fact sourcing and selection reporting |
| `src/caasi/core/workload.py` | **new** — minimal Workload model (F1 scope) |
| `src/caasi/cli/target_cmd.py` | `caasi target select` |
| `src/caasi/i18n/en.py` | 12 new strings |
| `tests/test_selection.py` | **new** — 39 tests |
| `plan/phases/phase-07/traceability.md` | **new** — requirement → gap → stage → evidence |
| `plan/phases/phase-07/architecture-gap-assessment.md` | G1–G5 annotated as live, each mapped to its stage |

**No gap is closed by this stage.** G1 and G2 remain **open** until this evidence is
accepted; G5 remains **open** until F2 completes it; G3 and G4 are untouched.

Reference trees unchanged: `openmover_robot` `f17c242a…`, `openmover_ws`
`1e09f5de…`. All fixtures were local and are removed; no target was modified.

---

## 9. Next step

**Stage F2** — workload `steps`/`outputs` and lifecycle composition
(`deploy → build → run → collect`), which addresses **G3** and completes **G5**,
while preserving the individual commands.

**Do not auto-proceed.** F2 also requires care that composition records the *same*
provenance as the manual path rather than a parallel model, and that a failing step
stops the chain instead of reporting partial success.
