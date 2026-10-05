# Phase 7: 0.4.0 Release Assessment

**Status:** Assessment before implementation.
**Date:** October 2026
**Scope:** Bounded release-hardening across the remaining roadmap, then a clean 0.4.0.

---

## 1. The release principle

> **Establish the coherent control-plane baseline and release it cleanly; defer
> deeper infrastructure until real usage justifies it.**

**Not** implemented to tick a roadmap box. Depth (queues, reservation, artifact
servers) stays deferred; only foundations that are *small and self-contained* are
in scope.

---

## 2. Current state: already at 0.4.0

`pyproject.toml` and `__version__` already read **0.4.0**, and `CHANGELOG.md` has a
0.4.0 section — so this pass **finishes** a release rather than starting one.

The control-plane chain is intact and validated end to end against two real
machines:

```text
project → workload → target → select → deploy → build → run → observe → collect → provenance
```

---

## 3. Item-by-item assessment

### R8 — selection and occupancy: **no work**

Explicitly out of scope: queues, reservations, waiting, retries, scheduling,
ranking, allocation, fleet. Already recorded as deferred **pending observed
contention**, not as an implementation gap. **Nothing to do; confirm and leave.**

### R9 — artifact destination model: **documentation + a small extension point, no infrastructure**

**What exists:** two destinations (`workstation`, `target_local`) with a real
distinction, per-kind defaults, per-artifact override, configurable via
`artifact_routing`, and an `ArtifactRoute.reason` explaining each decision. That is
already a coherent model.

**What is genuinely missing:** the model is **underspecified as an extension
point** — a reader cannot tell how a third destination *would* be added, or why it
was deliberately not added. `DESTINATIONS` is a closed tuple with no stated path
for extension.

**Proposed 0.4.0 scope:** document the model and its extension point **precisely**
in the module and the docs — what a destination is, the two that exist and why,
what a third would require, and why none is built now. **No artifact server, no CAS,
no object store.** If a genuinely minimal foundation appears (e.g. validating a
configured destination name against a documented rule), it may be added **only if it
is a few lines and introduces no infrastructure**. Otherwise documentation alone.

### R10 — monitoring web UI: **small FastAPI + Jinja2 + HTMX foundation**

**Stack (decision confirmed, supersedes an earlier stdlib-only proposal):** the
stack consistent with the author's other projects and the established caasi web
direction:

| Layer | Choice | Explicitly not |
| :--- | :--- | :--- |
| Server | **FastAPI** | — |
| Rendering | **Jinja2** (server-rendered) | — |
| Interactivity | **HTMX** | no SPA, no React/Vue |
| Styling | plain / flat CSS | no Tailwind, no build step |

**Consequence for dependencies:** caasi currently has exactly three runtime
dependencies (typer, rich, pyyaml). This adds a web stack, so it belongs in an
**optional extra** (e.g. `caasi[web]`) rather than the base install — the core CLI
must keep working without it, and `caasi web` should fail with a clear message
naming the extra when it is absent.

**Still deliberately absent:** no frontend build system, no SPA architecture, no
CSS framework.

**Proposed 0.4.0 scope:** a read-only server, launched explicitly by `caasi web`
(or equivalent), serving:

- targets and their occupancy (the M3 query);
- recent runs and their status;
- deployments and builds;
- artifacts of a run.

**Hard constraints, enforced not just documented:**

- **observation-only** — no deploy/build/run/stop/restart/enable/rollback, and no
  endpoint that mutates anything;
- **no second control plane** — it renders the same core queries the CLI renders;
- **local-only by default** (bind `127.0.0.1`) and **explicitly opt-in**.

The "no control actions" rule needs a **test that fails if a mutating route is
added**, not merely prose — that is where the one-control-plane boundary is easiest
to violate. Under FastAPI this is checkable structurally: enumerate the app's routes
and assert every one is `GET` and none is a control action.

**Initial content scope** (agreed): targets; target occupancy; runs and run state;
deployments; artifacts; ROS 2-focused observation where practical.

**Extensibility:** local-only binding (`127.0.0.1`) for 0.4.0, but the server should
be easy to expose to remote/other access later without restructuring — i.e. the
binding is a setting, not a hard-coded assumption woven through the code.

**ROS 2 focus:** the CLI's `ros` queries are the natural first content, but they are
**target-dependent and can be slow**. The design should render what is *recorded*
(targets, runs, deployments, artifacts) first, with ROS graph data opt-in per
target, so the UI never blocks on a slow target.

### G4 — `remotes:` shim: **deprecate, do NOT delete — not safe yet**

**Findings that make a pure deletion wrong:**

| Finding | Consequence |
| :--- | :--- |
| `targets.list_targets` **imports** `remotes:` entries | deleting the module would silently drop configured machines |
| `caasi remote connect` has **no target equivalent** | it is a live, unique capability |
| `remote.run` uses a **`path`** field targets do not have | not a pure duplicate |

So `remotes:` is **not** superseded: it is a *partially* overlapping legacy surface.
Removing it now would remove capability and risk dropping user configuration —
which the agreed constraint ("only if the current target architecture makes that
safe") explicitly forbids.

**Proposed 0.4.0 scope:** mark it **deprecated in help text and documentation**,
pointing at `targets:` as the canonical model, and record the migration path and
what blocks removal. **No removal in 0.4.0.** Full retirement is 0.5.0 work, gated
on either giving `target` a `path`/connect equivalent or deciding those features are
not needed.

**This is a scope reduction from the brief, reported rather than silently taken** —
the brief said "if safe", and the evidence says it is not yet safe.

### DDS-over-Tailscale — **no work**

Environmental, not a caasi defect. Stays documented.

### Idle race — **no work**

Intentional in the non-reservation model. Stays documented.

---

## 4. Release hardening

| Area | Planned action |
| :--- | :--- |
| CLI consistency / help text | audit help strings for staleness (two were already found stale this session) |
| Documentation / examples | a complete workflow walkthrough from `project init` to collected artifacts |
| Installation / upgrade path | verify `pip install` from a clean venv; document the 0.3.0 → 0.4.0 transition (command-surface changes) |
| Fresh-environment usability | confirm the tool behaves sensibly with no config and no targets |
| End-to-end regression | run the full suite; confirm only the known pre-existing failure |
| Provenance / report consistency | confirm composed and manual paths record the same fields |
| Stale entries | sweep `current.md` and roadmap docs for resolved-but-still-listed items |
| Working tree / references | verify clean trees and reference hashes |
| Release report + changelog | finalise the 0.4.0 changelog and write a release report |

---

## 5. Proposed checkpoint order

1. **R9** — document the artifact destination model and its extension point.
2. **R10** — small stdlib-only observation-only web foundation, with a guard test.
3. **G4** — deprecation in help and docs (no removal), with the blocker recorded.
4. **Release hardening** — CLI/help audit, workflow docs, install/upgrade, stale-entry sweep.
5. **Release report + changelog finalisation.**

Each checkpoint is independently reviewable and stops for review.

---

## 6. Risks and stop conditions

| Risk | Response |
| :--- | :--- |
| R10 grows beyond observation-only | **stop and report** — no write endpoints, no SPA, no build step; enforced by the route guard |
| R10's stack breaks the base install | web stack goes in an **optional extra**; the core CLI must work without it |
| G4 removal drops configuration or capability | **deprecate only**; removal needs a migration path (reported above) |
| The web UI drifts into a control plane | mutating-route guard test; no write endpoints |
| R9 grows into artifact infrastructure | documentation only unless a few-line foundation is clearly justified |
| Any item requires a larger architectural change | **stop and report** rather than expanding 0.4.0 |

---

## 7. Summary of proposed 0.4.0 scope

| Item | Scope | Size |
| :--- | :--- | :--- |
| R8 | confirm deferred, no work | none |
| R9 | document the model + extension point | **small** |
| R10 | FastAPI+Jinja2+HTMX observation-only foundation + guard | **small–medium** |
| G4 | deprecate in help/docs; **no removal** | **small** |
| DDS / idle race | no work | none |
| Hardening | CLI audit, workflow docs, install path, sweep | **medium** |

**Bounded.** Nothing here introduces a daemon, a queue, a database, an artifact
store, or a second control plane. R10 adds a web stack, but as an **optional extra**
with no frontend build step and no mutating routes.
