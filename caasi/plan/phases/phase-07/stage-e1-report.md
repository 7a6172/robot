# Phase 7 Stage E1 Report: Result / Output Collection

**Status:** Completed & Empirically Verified
**Date:** October 2026
**Parents:** [`stage-e-discovery.md`](stage-e-discovery.md), [`stage-e-observability-addendum.md`](stage-e-observability-addendum.md)
**Predecessor:** E2 (remote ROS 2 observability) — see [`stage-e2-report.md`](stage-e2-report.md)

---

## 1. Objective

Close the compute-side lifecycle:

```text
project → deployment → target → build → run → artifacts/results → destination
```

So that for a run on a remote target, caasi knows **what was produced, which run
produced it, where it now resides, whether it should come back, how it is
identified, and how it relates to provenance** — without becoming an artifact
store, and without ever deleting anything.

---

## 2. Design decisions

The investigation left three genuine forks. All three were decided before
implementation:

| Decision | Choice | Rationale |
| :--- | :--- | :--- |
| Default for unclassified outputs | **Leave on target, record location** | Nothing is silently moved; a run emitting gigabytes cannot saturate a slow relay unasked |
| Hashing | **Hash small artifacts by default; large ones only with `--verify`** | Hashing is O(bytes); a large checkpoint set must not stream over the link just to be listed |
| Failed/stopped runs | **Collect for succeeded, failed and stopped** | Debugging a failure is a primary use for outputs; the terminal status is recorded alongside |

Two further design points, recorded because they shape the code:

- **A declaration is a filter.** When a project declares `outputs:`, that
  declaration *defines* what the run produces — which is its stated purpose,
  and what separates requested results from source files and scratch. With no
  declaration, everything non-bookkeeping is inventoried, so a project that
  declares nothing still loses nothing.
- **`releasable` is a separate field, not a `status` value.** `status` describes
  the deployment *act*; `releasable` describes its intended *longevity*. Setting
  `releasable` never changes `status`.

---

## 3. What was implemented

### 3.1 `caasi.core.artifacts` (new module)

| Concept | Purpose |
| :--- | :--- |
| `Artifact` | one produced file: id, kind, size, path, location, sha256, route |
| `ArtifactRoute` | destination + reason + whether it came from a declaration |
| `ArtifactRecord` | a run's artifacts plus the provenance chain that identifies the run |
| `OutputDeclaration` | one declared `outputs:` pattern with routing intent |
| `RoutingPolicy` | default destination per kind, overridable via `artifact_routing` |
| `inventory_directory` / `inventory_remote` | enumerate produced files (local / over SSH) |
| `plan_collection` | pure split of fetch-vs-leave, no I/O |
| `collect_artifacts` | copy only the routed files, per-file `rsync` |
| `save_artifact_record` / `load_artifact_record` | the sibling `artifacts.yaml` |
| `resolve_lifecycle` / `is_releasable` / `mark_deployment_releasable` | E1.5 recording |

**Deliberate limits.** caasi routes; it does not interpret. It never parses a
checkpoint, reads a metric, or understands a domain format. `kind` is advisory
metadata that never gates collection — an unknown extension is simply `other`.

### 3.2 `outputs:` on the experiment schema (E1.2)

```yaml
outputs:
  - results/*.json                    # simplest form
  - path: checkpoints/*.pt            # explicit
    kind: model
    destination: target_local
```

A malformed declaration is a **configuration error**, not a silently empty
collection.

### 3.3 `caasi run artifacts` (E1.3/E1.4)

```bash
caasi run artifacts <run>                      # list, with kind/size/route
caasi run artifacts <run> --collect --dry-run  # show the plan only
caasi run artifacts <run> --collect            # copy routed files back
caasi run artifacts <run> --verify             # hash everything, including large
caasi run artifacts <run> --json
```

### 3.4 Lifecycle intent (E1.5)

```yaml
lifecycle: ephemeral    # compute: results then releasable
lifecycle: persistent   # robot: durable (the default)
```

Recorded on the deployment. After an ephemeral deployment's declared results are
collected, the deployment is marked `releasable` — **a recording only**. caasi has
no delete or release operation at all; the CLI says so explicitly:
*"marked releasable (recorded only; nothing was removed)"*.

---

## 4. Validation

Two workloads, per the instruction to use the smallest that gives valid evidence:

1. **A minimal generated-file workload** (3 output files: two small results, one
   2 MiB stand-in checkpoint) — used for both local and remote validation.
2. **Real OpenMover project data** as *additional* evidence, not as a
   prerequisite.

**Remote target: `u24-307`** (the real machine from Stage D, not a container).

### 4.1 Remote inventory — PASS

```console
$ caasi run artifacts 20261005-160913-e1-gen
Run artifacts (20261005-160913-e1-gen)
  Location: u24-307 (ssh)
┃ Artifact                     ┃ Kind    ┃    Size ┃ Route        ┃
│ outputs/checkpoints/model.pt │ model   │ 2.0 MiB │ target_local │
│ outputs/results/metrics.json │ metrics │    29 B │ workstation  │
│ outputs/results/summary.csv  │ metrics │    24 B │ workstation  │
  3 artifact(s), 2.0 MiB total
```

Files were enumerated **on the target over SSH**, classified, and routed per the
declaration.

### 4.2 Collection plan and collection — PASS

```console
$ caasi run artifacts 20261005-160913-e1-gen --collect --dry-run
Collection plan
  to copy to workstation: 2
    outputs/results/metrics.json
    outputs/results/summary.csv
  to leave on target: 1
    outputs/checkpoints/model.pt
  dry run - nothing was transferred

$ caasi run artifacts 20261005-160913-e1-gen --collect
Run 20261005-160913-e1-gen: 2 artifact(s) collected.
  record: …/artifacts.yaml
```

Exactly the two routed results came back; the checkpoint did **not**.

**Content integrity (measured):**

```text
host   sha256  6e48c64b502132d3f28b6603334a195d314c464a94803d82ee46311496cb7211
target sha256  6e48c64b502132d3f28b6603334a195d314c464a94803d82ee46311496cb7211
→ identical
```

### 4.3 The ephemeral-vs-persistent distinction — PASS

This is the distinction the stage exists to make real.

| | Ephemeral (compute) | Persistent (robot) |
| :--- | :--- | :--- |
| Small results | copied to workstation | copied to workstation |
| Large checkpoint | **left on target** | **left on target** |
| Deployment after collection | `releasable: True` recorded | **not marked** |
| Anything deleted | **no** | **no** |

Measured evidence for the persistent case: the deployment record stayed
`lifecycle=persistent, releasable=False` after collection, and no
"marked releasable" line was printed. Collecting a log from a robot must not
make the robot look disposable.

Measured evidence that nothing was destroyed in either case:

```text
deployment present: yes
output files: 3
checkpoint still there: yes
```

### 4.4 Additional evidence from real OpenMover data

Run without mocks against the canonical project's real `lab/` tree (241 map
JSONs, 37 PNGs, 28 source files, 6.2 MB):

- **Undeclared**: 306 artifacts (6.2 MB) found — but note it includes 28 `.py`
  **source files**, which is precisely why declarations matter.
- **Declared** (`maps/*.json`): correctly narrowed to **241 real map files
  (3.1 MB)**, excluding source.

This produced a **genuine bug fix**: OpenMover's SLAM/mapping results are `.json`,
which extension inference calls `metrics`. A declaration naming them `map` was
being ignored. Fixed so a **declared kind now wins over extension inference** —
a project's declaration is better evidence than a file extension. Regression test
added (`test_declared_kind_overrides_extension_inference`).

### 4.5 Bugs found by validation

Recorded because they are the point of validating with real workloads:

| Bug | Symptom | Fix |
| :--- | :--- | :--- |
| Provenance bundle treated as artifacts | `configuration.yaml`, `hardware.yaml`, … listed as run results | Extended `BOOKKEEPING_NAMES` to cover the whole bundle |
| Wrong inventory root | Actual outputs were missed entirely | Inventory the run's **working directory**, not the run directory (which holds bookkeeping) |
| Declaration ignored for kind | Declared `kind: map` still reported `metrics` | `resolve_kind()` lets a declaration win |

---

## 5. Scope boundaries

**Established:**

1. Remote and local produced files can be inventoried with identity (kind, size,
   hash) without transferring them.
2. Declared outputs can be routed between `workstation` and `target_local`.
3. Collection transfers **only** routed files, verifiably byte-identical, and
   never transfers, modifies or deletes anything else.
4. The artifact record joins every artifact to the run's provenance chain
   (`run_id`, `deployment_id`, `build_id`, `git_revision`, `remote_run_dir`).
5. Ephemeral and persistent deployments are distinguished, and only ephemeral
   ones are ever marked releasable.

**Not established (explicitly untested):**

- **No deletion / release / teardown.** By design: nothing in E1 removes
  anything, and `releasable` is a recording. A future stage would need to decide
  whether an actual release operation is ever wanted.
- **No artifact store.** No content-addressed storage, no dedup across runs, no
  retention policy, no pruning.
- **No shared/remote destination** (S3, NAS, another host). Only
  `workstation` and `target_local` exist.
- **No artifact ↔ `caasi dataset` integration.** Outputs are not hydrated into
  the dataset system.
- **No resumable/interruptible transfer** beyond per-file `rsync --partial`; no
  transfer progress reporting on a slow link.
- **No verification that declared outputs were all produced.** A `required:`
  field parses but is not yet enforced — a run that silently produces nothing
  is reported as zero artifacts, not a failure.
- **No persistent-runtime work** (install/configure, enable, durability,
  update/rollback). Not started, per instruction.

---

## 6. Tests

**42 new tests** (39 in `tests/test_artifacts.py`, 3 in `tests/test_experiment.py`),
covering classification, bookkeeping exclusion,
declaration parsing and validation, glob/directory matching, routing precedence
(declaration → kind policy → unclassified), config-driven policy, declared-kind
override, inventory with and without declarations, hash policy by size, content-based
artifact identity, collection planning, the local-already-here case, record
round-tripping, lifecycle resolution precedence, and the releasable rules
including idempotence and the persistent-never-releasable guard.

**Full suite: 976 passed, 1 failed.** The single failure
(`test_perception_cmd.py::test_perception_segment_dry_run_passes_extra_args`) is
**pre-existing and unrelated** — proven so in Stage D by stashing changes and
reproducing it on the unmodified commit; it concerns Isaac ROS perception
(untouched by E1) and its cause is terminal-width line wrapping.

---

## 7. Files changed

| File | Change |
| :--- | :--- |
| `src/caasi/core/artifacts.py` | **new** — inventory, routing, collection, record, lifecycle |
| `src/caasi/core/experiment.py` | `outputs:` parsing, validated |
| `src/caasi/core/deploy.py` | `lifecycle` / `releasable` on `DeploymentRecord`; lifecycle recorded at deploy |
| `src/caasi/cli/run_cmd.py` | `caasi run artifacts`; inventory helpers |
| `src/caasi/i18n/en.py` | 18 new user-facing strings |
| `tests/test_artifacts.py` | **new** — 39 tests |
| `tests/test_experiment.py` | 3 tests for declared outputs |

No reference tree modified: `openmover_robot` `f17c242a…` and `openmover_ws`
`1e09f5de…` unchanged. The test deployment on `u24-307` was removed after
validation.

---

## 8. Next step

E1 is complete. **Do not auto-proceed.** Remaining work, in the agreed framing:

- **Persistent runtime lifecycle** (Stage F): install/configure, enable,
  durability verification, update/redeploy, rollback — still requiring real
  robot evidence, and deliberately untouched here.
- **Non-ROS observability adapters** (container, systemd, bare process) behind
  E2's capability-keyed pattern.
- **Optional E1 extensions**, none required: shared/remote artifact destinations,
  `required:` enforcement, artifact→dataset hydration.

Recommended next: decide between the persistent-runtime lifecycle and the
non-ROS adapters based on which gap matters more for the next real workflow.
