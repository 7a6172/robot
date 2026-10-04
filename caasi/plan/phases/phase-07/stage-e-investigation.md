# Phase 7 Stage E Investigation: Artifact Management & Result Routing

**Status:** Investigation / Evidence + Proposed Scope (no implementation yet)
**Date:** October 2026
**Predecessor:** Stage D (real remote target validation, completed — see [`stage-d-report.md`](stage-d-report.md))
**Design mandate:** remain project-agnostic; extend the existing lifecycle rather than redesign it

---

## 0. Method and evidence classes

Per the evidence discipline used throughout Phase 7, every statement below is
tagged:

| Class | Meaning |
| :--- | :--- |
| **Existing capability** | Inspected in the code and, where possible, exercised |
| **Observed gap** | Demonstrated by direct measurement against the real target |
| **Measured behaviour** | A number obtained by running something |
| **Future design** | Proposed only; not implemented |

Nothing here is implemented. This document exists so Stage E scope can be
agreed before code is written.

---

## 1. What the lifecycle looks like today

The chain the user described already exists **except for the last hop**:

```text
project → deployment → target → build → run → logs/provenance
                                                    ▲
                                              (artifacts end here today)
```

**Existing capability.** A `RunRecord` already carries a complete, linked
provenance chain. Verified from a real Stage D remote run
(`caasi run inspect <id> --json`):

```json
{
  "id": "20261004-182108-target-smoke",
  "target": "u24-307",
  "target_transport": "ssh",
  "destination": "/home/zar/caasi-deployments/openmover",
  "deployment_id": "deploy-openmover-20261004-100729-8c304a34",
  "build_id": "build-u24-307-1791108950-c26895",
  "git_revision": "8c304a349784bfb03f24e1a9af329a4b7805ce7b-dirty",
  "project": "openmover",
  "remote_run_dir": "/home/zar/caasi-deployments/openmover/.caasi/runs/20261004-182108-target-smoke",
  "files": [ ... ]
}
```

So asking **"which run produced it"** and **"what is it related to"** is already
answerable — the identity backbone exists. What is missing is the artifact
*itself* as a first-class concept.

---

## 2. Existing capability inventory

### 2.1 Provenance (host side) — substantial

**Existing capability.** `caasi.core.provenance` writes a 7-file bundle into the
host run directory:

```text
manifest.yaml  environment.yaml  hardware.yaml  dependencies.yaml
configuration.yaml  git.json  processes.json
```

**Measured behaviour.** Confirmed present for the Stage D remote run:

```text
$ ls ~/.caasi/runs/20261004-182108-target-smoke/
configuration.yaml  dependencies.yaml  environment.yaml  git.json
hardware.yaml       manifest.yaml      processes.json
```

It also redacts secrets (`SECRET_MARKERS`, `is_secret_key`, `redact_secrets`) —
a good precedent for treating provenance data carefully.

### 2.2 Provenance (target side) — partial, and asymmetric

**Observed gap.** For the same remote run, the target holds only a **minimal**
manifest, not the bundle:

```text
TARGET  : manifest.yaml, run.sh, pid, pgid, stdout.log, stderr.log, exit_code
HOST    : the full 7-file bundle
```

The target manifest does carry the full identity chain
(`deployment_id`, `build_id`, `run_id`, `target`, `project`), so attribution is
possible on both sides — but environment/hardware/dependency provenance is
host-only. This asymmetry is stated here as an observation, not a defect: the
Stage A/B design intentionally captures the workstation-side view.

### 2.3 Remote run-file enumeration — exists, shallow

**Existing capability.** `caasi.core.runs.inspect_run_files` lists run-directory
files over SSH:

```python
f"find '{run_dir}' -maxdepth 2 -type f -exec stat -c '%n %s' {{}} +"
```

**Measured behaviour.** Directly exercised on the real target. A probe creating
`outputs/metrics.json` and `outputs/checkpoint.bin` inside the remote run
directory was enumerated correctly:

```text
┌────────────────────────┬──────────┐
│ File                   │     Size │
│ outputs/checkpoint.bin │ 64.0 KiB │
│ outputs/metrics.json   │     17 B │
└────────────────────────┴──────────┘
```

**So `caasi` can already *see* remote outputs** — at one directory level, by
size only, with no identity, content hash, type, or lifecycle.

### 2.4 Viewer artifact discovery — file-type knowledge exists

**Existing capability.** `caasi.core.viewers` already classifies output files by
extension for replay/view purposes:

```python
MESH_EXTS  = {".obj", ".stl", ".gltf", ".glb", ".fbx", ".off"}
POINT_EXTS = {".ply", ".pcd", ".pts", ".xyz", ".xyzn"}
_RUN_FILES = {"manifest.yaml", "run.sh", "stdout.log", "stderr.log", "exit_code"}
```

`recorded_artifacts(run_dir)` returns everything in the run directory **except**
that small bookkeeping set. This is a narrow, working precedent for "what counts
as an artifact", currently limited to 3D-data viewers.

### 2.5 Dataset management — adjacent, not the same concern

**Existing capability.** `caasi.core.dataset` + `caasi dataset` CLI provide
`list`, `generate`, `inspect`, `convert`, `validate`, `download` with metadata
JSON and jsonl/csv indexing.

**Observed boundary.** This manages *datasets* under `~/.caasi/datasets`,
including downloading from Hugging Face / NGC / URL. It is **input-oriented** and
does not model outputs produced *by* a run, nor their routing.

### 2.6 Deploy exclusion taxonomy — the inverse

**Existing capability.** `caasi.core.deploy.DEFAULT_EXCLUDE_PATTERNS` already
encodes "what is not project content": `build`, `install`, `log`, `.git`,
`__pycache__`, `.caasi/runs`, `.caasi/deployments`, `.caasi/builds`, …

This is the mirror image of an artifact taxonomy. Any Stage E design should
reuse the same vocabulary rather than invent a second one.

### 2.7 Artifact routing — proposed, not implemented

**Future design (pre-existing).** The Phase 7 proposal §5 already sketches an
`artifact_routing` block:

```yaml
artifact_routing:
  telemetry:        { destination: workstation }
  logs:             { destination: target_local, stream_summary: true }
  model_checkpoints:{ destination: target_local }
  provenance:       { destination: workstation }
```

Stage E should **implement this intent**, not replace it. Confirming it is
unimplemented: `grep` finds no `artifact_routing` handling in `src/`, and
`caasi.yaml` for the canonical project has no such block.

---

## 3. Observed gaps

Ordered by how directly they block the user's stated goal.

### G-E1 — Outputs are visible but not *known* (no artifact identity)

**Observed gap.** `inspect_run_files` returns `{path, size}` only. There is no
content hash, no type, no producer attribution, no creation time, no
"this is a model checkpoint vs a metric vs a log" distinction.

Consequence: two runs writing `metrics.json` are indistinguishable without
manual inspection; artifact versioning is impossible; duplicated artifacts cannot
be detected.

### G-E2 — No routing: artifacts cannot leave the target

**Observed gap.** Verified in Stage D: after a remote run produced outputs on
`u24-307`, the host had **no record of them at all**:

```text
created on target:  outputs/checkpoint.bin (64 KiB), outputs/metrics.json
what does the HOST know? -> (host has NO record of these outputs)
```

There is no fetch/pull/route mechanism anywhere in `src/` (the only download path
is `dataset.download`, which fetches from Hugging Face / NGC / URL — not from a
target). This is the central Stage E gap.

### G-E3 — No declaration of expected outputs

**Observed gap.** An experiment cannot declare what it produces
(`target_smoke.yaml` has `name`/`backend`/`script`/`cwd`/`description` only).
Without a declaration, caasi cannot distinguish intended results from incidental
scratch files, cannot pre-allocate destinations, and cannot verify completeness.

### G-E4 — No retention/placement policy

**Observed gap.** Nothing decides whether an artifact should stay on the target
(large checkpoints on a GPU box), return to the workstation (small metrics), or
go to shared storage. The proposal's `artifact_routing` block expresses this; no
code implements it.

### G-E5 — Size-stratified reality is unaddressed

**Measured behaviour.** Output scale varies by orders of magnitude, so a single
copy-everything policy is wrong. The figures below were measured on the
**local workstation (`zar@u24-z690p`)** at the exact path:

```text
/home/zar/Documents/phd/robot/openmover_ws/isaac/lab
```

| Output class | Example | Measured |
| :--- | :--- | :--- |
| Result JSON | campaign aggregates | **462 files** |
| Model checkpoints | `.pt` weights | **330 files** |
| Video | `.mp4` episodes | **67 files** |
| **Total (that one directory)** | | **5.0 GB** (1531 files) |
| ROS build/log tree (local project) | `build`, `install`, `log` | 193M / 13M / 4.1M |

**Provenance of this measurement — important for correct interpretation:**

- Machine: `u24-z690p` (the workstation). **Not** the remote target.
- It is a **pre-existing historical Isaac Lab campaign output directory**, not
  caasi-generated remote artifacts. File mtimes span 2026-09-02 → 2026-09-07;
  **0 files** were touched on 2026-10-04 when Stage D ran; the tree was last
  committed in the baseline `79dc52f` (2026-10-03), with 749 of its files
  git-tracked under `openmover_ws/`.
- Nothing was copied between `u24-z690p` and `u24-307` during this work. The only
  transfer was the Stage D deployment: **835 files / 40.4 MiB** of project
  *source*. Verified on the target: **0 `.pt` files** in `~`, and the deployed
  `lab/models/` is 4.0 KB and contains no artifacts.

So this figure is cited **only as a realistic magnitude for the design question**
(what if a run produces gigabytes of checkpoints and video?), using a real
example from this project. It is *not* evidence that caasi produced or moved
those artifacts — caasi has no such capability, which is precisely gap G-E2.

Returning gigabytes to the workstation by default would be actively harmful;
keeping 4 KB of metrics on the target would defeat the purpose. That contrast —
not the specific directory — is the justification for a *routing* policy rather
than a *sync* policy.

---

## 4. What Stage E should NOT do

Recorded explicitly, because scope creep here would be easy:

- **No distributed artifact store / content-addressed storage service.** This is
  not an S3 replacement.
- **No provenance re-architecture.** The existing 7-file bundle and the
  `deployment → build → run` chain already work; Stage E extends the chain.
- **No fleet/scheduling coupling.** Multi-target selection is a
  *later* stage; Stage E must work for a single target (and for `local`).
- **No dataset-management merge.** `caasi dataset` stays as it is; if outputs
  should become datasets, that is a *later* integration, not a Stage E
  requirement.
- **No new transport.** Reuse the existing `rsync` (deploy, Stage B) and SSH
  (Stage A/C2) mechanisms.

---

## 5. Proposed smallest coherent Stage E scope

A three-part slice that closes the lifecycle without inventing a subsystem. Each
part maps to an existing mechanism.

### Part 1 — Declare outputs (manifest/experiment)

**Reuses:** experiment YAML parsing, `DEFAULT_EXCLUDE_PATTERNS` vocabulary.

Add an optional `outputs:` declaration to experiment configs, with a sane default
(`outputs/` under the run directory, matching the convention already observed in
Stage D):

```yaml
name: lab-campaign
script: ../lab/tasks/33_run_campaign.py
outputs:
  - path: results/*.json      # -> small, return to workstation
    kind: metrics
  - path: checkpoints/*.pt    # -> large, keep on target
    kind: model
  - path: videos/*.mp4
    kind: media
```

`kind` is advisory metadata; routing is driven by the policy in Part 2.

### Part 2 — Route by policy (`artifact_routing`)

**Reuses:** the proposal's existing YAML shape; the Stage B `rsync` transport.

Implement the already-proposed `artifact_routing` block, resolved per
artifact kind, with an explicit default that is safe:

```yaml
artifact_routing:
  metrics:    { destination: workstation }
  provenance: { destination: workstation }
  model:      { destination: target_local }
  media:      { destination: target_local }
```

Destinations to support in Stage E (minimum viable set):

| Destination | Meaning |
| :--- | :--- |
| `workstation` | copy back into the host run directory |
| `target_local` | leave in place on the target; record location only |

Explicitly deferred: shared storage / S3 / remote dataset sinks.

### Part 3 — Record artifact identity and location

**Reuses:** the existing run-directory provenance, `inspect_run_files`, the
`RunRecord` chain.

Introduce an artifacts record written alongside the run manifest, capturing for
each artifact:

```text
artifact_id        stable id (run_id + relative path + content hash prefix)
run_id             which run produced it          (exists today)
producer           project / experiment / script
kind               metrics | model | media | log | other
path_local         where it is now (host or target)
path_target        target-side path, if it stays remote
target             target it resides on            (exists today)
size_bytes         measured
sha256             content hash (streamed, no full read into memory)
created_at         mtime
routing            the policy decision that was applied
provenance_links   deployment_id / build_id / git_revision  (exist today)
```

Surface it through the existing read surfaces rather than new ones:

- `caasi run inspect <id>` — extend the existing table/JSON with artifact rows.
- `caasi run artifacts <id> [--json]` — thin new command if `inspect` becomes
  crowded; returns the same structure.

### Why this is the smallest coherent slice

It closes the stated lifecycle —

```text
project → deployment → target → build → run → artifacts/results → destination
```

— by adding exactly three things (declare, route, record), each attaching to
infrastructure that already exists (experiment parsing, `rsync`, run-record
provenance). It makes every question in the user's list answerable:

| User's question | Answered by |
| :--- | :--- |
| what was produced | Part 1 + Part 3 inventory |
| which run produced it | Part 3 `run_id` (chain exists today) |
| where it currently resides | Part 3 `path_local` / `path_target` / `target` |
| should it remain remote or be copied | Part 2 `artifact_routing` |
| how is it identified/versioned | Part 3 `artifact_id` + `sha256` |
| how does it relate to provenance | Part 3 `provenance_links` (chain exists today) |

---

## 6. Proposed implementation order within Stage E

Staged so each step is independently verifiable and the design can still change:

1. **E1 — Inventory only.** Compute the artifact inventory for a *finished* run
   (local and remote) with hash, size, kind, and location. No copying. Verify
   against the real `u24-307` target, and against a local run directory that
   produces a large output set (the 5 GB tree named in §3 G-E5 is a convenient
   magnitude reference, but a run producing outputs under a run directory is the
   better fixture).
2. **E2 — Declaration.** Add optional `outputs:` to experiment config; classify
   produced files by declaration, falling back to observed inventory.
3. **E3 — Routing.** Implement `workstation` and `target_local` destinations via
   the existing `rsync` path, with a `--dry-run` that reports the plan before
   transferring anything.
4. **E4 — Provenance integration.** Join artifact records into the existing
   provenance chain and expose through `run inspect`.

**E1 alone is already useful and low-risk**, so it is the natural first commit.

---

## 7. Open questions for review (before implementation)

These are genuine design forks, not rhetorical:

1. **Default for unclassified outputs.** Return to workstation, or leave on
   target? Returning is friendlier for small results but dangerous at
   multi-gigabyte scale; leaving is safe but means results silently stay remote.
   *(Recommendation: leave on target and record the location, so nothing is
   silently moved or lost.)*
2. **Hash everything, or hash on demand?** Hashing hundreds of multi-megabyte
   checkpoint files costs real I/O, especially over a relay. *(Recommendation:
   hash small artifacts by default, hash large ones only when `--verify` is
   requested.)*
3. **Where does the artifact record live** — inside `manifest.yaml`, or a sibling
   `artifacts.yaml`? *(Recommendation: sibling file, matching the existing
   one-concern-per-file bundle layout.)*
4. **Partially-complete runs.** Should artifacts be collected for a `stopped` or
   `failed` run? *(Recommendation: yes, and record the run's terminal status
   alongside, since debugging a failure is a primary use for outputs.)*
5. **Does Stage E need any `local`-target work**, or is it remote-only? *(The
   lifecycle is `local` too — `workstation` routing is then a no-op with the same
   identity recording.)*

---

## 8. Explicitly not yet decided

- Whether outputs should be hydratable back into `caasi dataset` (deferred).
- Whether artifact retention/pruning is ever automatic (deferred; likely never
  destructive without explicit instruction).
- Whether a shared-storage destination is needed (deferred until a real target
  requires it).

---

## 9. Evidence summary

| Claim | Class | How established |
| :--- | :--- | :--- |
| Full provenance chain exists on `RunRecord` | Existing capability | `run inspect --json` on a real Stage D run |
| Host provenance = 7-file bundle | Existing capability + measured | `ls ~/.caasi/runs/<id>/` |
| Target provenance = minimal manifest (asymmetric) | Observed gap | Compared both sides of one run |
| Remote run files are enumerable to depth 2, size only | Existing capability + measured | `inspect_run_files` exercised with probe outputs |
| Remote outputs are invisible to the host | Observed gap | Created outputs on `u24-307`; host had no record |
| No fetch/route mechanism exists | Observed gap | `grep` across `src/` |
| No output declaration in experiments | Observed gap | `target_smoke.yaml` inspected |
| `artifact_routing` designed but unimplemented | Existing design + observed gap | Proposal §5 vs `grep` in `src/` |
| Outputs span ~4 KB → ~5 GB in practice | Measured behaviour | `du`/`find` on **`u24-z690p`** at `openmover_ws/isaac/lab` (5.0 GB, pre-existing historical campaign outputs; **0** `.pt` and no such tree on `u24-307`) |

**No implementation has been performed. No reference tree was modified.**
