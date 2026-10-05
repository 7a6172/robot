# Phase 7 Report: Example Catalog and 0.4.0 Release Assessment

**Status:** Completed & Verified
**Date:** October 2026
**Checkpoint:** the runnable-example requirement, plus the release check it enabled
**Proposal:** [`examples-proposal.md`](examples-proposal.md)

---

## 1. What was built

A **general example catalog for the basic CLI** — not a showcase of the 0.4.0
additions. Seven coherent projects plus a cookbook, covering **every command in the
live CLI**.

| # | Example | Teaches | Tier |
| :--- | :--- | :--- | :--- |
| 01 | `01-python-project` | project, workload, run, logs, artifacts, provenance, env, config | **CI** |
| 02 | `02-targets-and-selection` | `target *`, `select`, `occupancy`, `--where` | **CI** |
| 03 | `03-ros2-demo-nodes` | `ros *`, `tools`, `pipeline` | **CI** |
| 04 | `04-container` | `container *`, `target runtime` | **CI** |
| 05 | `05-ros2-turtlesim` | the recognised ROS 2 example, `rviz2`/`rqt`, bags | **manual** |
| 06 | `06-isaac-lab-cartpole` | `train`, `lab`, `sim`, GPU-aware selection | **opt-in** |
| 07 | `07-control-plane-end-to-end` | `select → deploy → build → run → collect → provenance` | **CI** (local) / opt-in |
| — | `cookbook` | the read-only inspection commands | **CI** |

Plus `README.md` (the repository-local **command index**) and `COVERAGE.md` (the
**auditable matrix**).

---

## 2. Coverage: the audit, not a checkbox

**Generated from the live command tree**, not hand-maintained: **57 root commands,
253 command paths**, **all 253 listed**.

A command with no runnable example is still listed, **with the reason**. Nothing is
silently omitted — and that is *enforced by a test*, not merely intended:

- `test_coverage_matrix_accounts_for_every_live_command` — any command added later
  that is absent from the matrix **fails the suite**;
- it also fails if the matrix documents a **stale** command that no longer exists;
- `test_coverage_matrix_states_the_live_totals` — the stated counts must match the
  CLI, or the audit is not an audit.

**This caught 13 commands I had not classified** (cosmos, groot, monitor, teleop…)
on the first run. The automated audit found them; a hand-written list would not have.

---

## 3. Ecosystem examples: referenced, never duplicated

| Ecosystem | Canonical example used | caasi's contribution |
| :--- | :--- | :--- |
| **ROS 2** | `demo_nodes_py` talker/listener, `add_two_ints` | observation, `--domain` discipline, remote context |
| **ROS 2** | `turtlesim` | observation, bags, target-aware `rviz2`/`rqt` |
| **Isaac Lab** | `cartpole` + its own RL entry point | project, requirements, GPU-aware selection, run tracking |
| **Docker** | a normal public image | observation via the container CLI |

Every README states **what caasi provides vs what the ecosystem provides**.

**Verified not vendoring:** a test caps the catalog's source files, so copying an
upstream project in would fail the suite.

---

## 4. Honesty about what cannot be run

| Command(s) | Status | Why |
| :--- | :--- | :--- |
| `run delete`, `project remove` | **not executed** | destructive, and **no `--dry-run` exists** |
| `teleop start`/`record`, `nav launch`, `moveit launch`, `motion execute` | **not executed** | **physical motion / hardware bringup** |
| `setup` | **not executed** | mutates the user's environment |
| `rviz2`, `rqt`, `turtlesim` | **manual** | need a display |
| `sim`, `train`, `lab`, `isaac-ros`, `perception`, `nitros` | **opt-in** | need GPU + Isaac |

**No example invents a `--dry-run` the CLI does not provide** — a test asserts the
matrix says so explicitly for the destructive pair.

**A guard test** scans every shipped example file and fails if any of the eight
unsafe commands is *invoked* (as opposed to documented).

---

## 5. Validation performed

### 5.1 Examples run for real

| Check | Result |
| :--- | :--- |
| `01`: full composed workload (`deploy → run → collect`) | **succeeded**; artifact collected; full provenance recorded |
| `01`: all 8 claimed commands (`project validate/info/list`, `config show/path`, `workload list/inspect`, `check`) | **all ok** |
| `01`: `project validate` | **valid** after adding the expected layout |
| `02`: `target list/inspect/occupancy`, `target select` | **all ok** |
| `04`: `container check/doctor` | **ok** |
| `07`: `project validate` | **valid**; the 4-step chain composes |

### 5.2 Coverage re-verified against the live CLI

Re-extracted after implementation: **253 paths, byte-identical** to the inventory the
matrix was generated from.

### 5.3 Tier claims verified truthful

- **CI** examples genuinely run (tested).
- **Opt-in/manual** examples *declare* they are not validated — asserted by a test,
  so the claim cannot silently drift into implying CI coverage.
- Tier values are constrained to a known set.

---

## 6. Defects found while building

All found by the tests or by running the examples — none papered over.

1. **`run` needs a deployment even on `local`.** Example 01's first workload had
   only `run → collect` and **failed** with *"No active deployment found"*. This is
   correct behaviour (the contract decided in the F2 fix) and was turned into
   **teaching material**: the workload now includes `deploy`, and the README explains
   why the refusal is deliberate.
2. **`project validate` rejects an incomplete layout.** The first draft of examples
   01/07 was missing `artifacts/`, `logs/`, `.caasi/`, and (for the `ros2` component)
   `ros/launch`, `ros/config`, `ros/params`. Fixed — a first example must not open
   with errors.
3. **13 commands were unclassified** in the first matrix — caught by the automated
   audit, then classified.
4. **The cookbook never stated the caasi-vs-ecosystem boundary** — caught by a test.
5. **My own test was wrong once**: it ran example 01's script in a flat directory,
   but the script resolves its project root from its own location. The **example was
   right**; the test now mirrors the real `scripts/` layout.

---

## 7. Release-hardening status

| Area | Status |
| :--- | :--- |
| Examples (this checkpoint) | **done** — 7 examples + cookbook, index, auditable coverage, CI validation |
| CLI consistency / help text | partially done — two stale help strings were fixed earlier (`--target`); a full pass remains |
| Documentation set | **gap confirmed, not closed** — the docs site still lacks `target`/`workload`/`runtime`/`tools` pages and has stale version badges |
| Installation / upgrade path | not yet verified in a clean environment |
| Fresh-environment usability | not yet verified |
| End-to-end regression | **done** — full suite run |
| Provenance/report consistency | verified during example 07 |
| Stale roadmap entries | partially swept earlier |
| Release report + changelog | changelog section exists; to be finalised |

**Remaining hardening work is documentation and install-path verification** — not
capability. The documentation set is the largest remaining item and was flagged
earlier rather than absorbed.

---

## 8. Files added

| Path | Content |
| :--- | :--- |
| `examples/README.md` | the repository-local **command index** |
| `examples/COVERAGE.md` | the **auditable matrix** (253 commands) |
| `examples/01-python-project/` | project + scripts + experiment + workload + README |
| `examples/02-targets-and-selection/` | README |
| `examples/03-ros2-demo-nodes/` | README |
| `examples/04-container/` | README |
| `examples/05-ros2-turtlesim/` | README |
| `examples/06-isaac-lab-cartpole/` | README |
| `examples/07-control-plane-end-to-end/` | project + ROS 2 package + experiment + workload + README |
| `examples/cookbook/README.md` | read-only command reference |
| `tests/test_examples.py` | **17 tests** |

Reference trees unchanged: `openmover_robot` `f17c242a…`, `openmover_ws`
`1e09f5de…`, `caasi-workspace/openmover` 0 dirty. Generated runtime state was
removed; the examples ship no build artefacts.

**Full suite: 1250 passed, 1 failed** — the pre-existing `test_perception_cmd.py`
terminal-width artifact.

---

## 9. Next step

**Stopping for review.**

Remaining for 0.4.0: the **documentation set** (the confirmed gap — now with the
example catalog as its natural content), **install/upgrade verification**, and
**finalising the changelog and release report**.
