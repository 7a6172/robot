# Phase 7 Report: R9 — Artifact Destination Model

**Status:** Completed & Verified
**Date:** October 2026
**Checkpoint:** 1 of the 0.4.0 release-hardening pass
**Assessment:** [`release-0.4.0-assessment.md`](release-0.4.0-assessment.md)

---

## 1. What this checkpoint was

Per the accepted assessment, R9 is **documentation and model work only**:

> Document the existing two-destination model accurately — per-kind defaults,
> per-artifact overrides, configuration, decision/reason information, and what a
> future third destination would need to implement.

**No artifact infrastructure, no CAS, no object store, no artifact server.**

**Verified: `+213 lines, 0 deletions`.** The only source change is the module
docstring — no runtime behaviour was touched.

---

## 2. What was documented

`caasi/core/artifacts.py`'s module docstring is now the **authoritative reference**
for the routing model, covering exactly what was asked:

### The resolution order, with reasons

Every artifact gets one `ArtifactRoute`, decided by the first matching rule, and the
route records **which** rule it was:

| Rule | Destination | `route.reason` |
| :--- | :--- | :--- |
| declaration matches **and** names a destination | that destination | `declared` |
| declaration matches, no destination | policy for the declared kind | `declared-kind-policy` |
| no declaration; inferred kind has a rule | `by_kind[kind]` | `kind-policy` |
| nothing applies | `policy.unclassified` | `unclassified` |

`route.declared` distinguishes a deliberate instruction from a default.

### Per-kind defaults

Deliberately conservative — **nothing copies by accident**: `metrics`/`report`/`log`
→ `workstation`; everything unclassified → `target_local`, so a run emitting
gigabytes cannot silently saturate a slow link.

### Declarations and configuration

The `outputs:` block (`path` glob, `kind`, `destination` override, `required`) and
the project-level `artifact_routing` block (per kind, with `default`/`unclassified`/`*`
fallback). **Unknown destination names are ignored, not guessed** — a typo cannot
route data somewhere unintended.

### What a third destination would require

Recorded as **five concrete prerequisites**: an entry in `DESTINATIONS`; a transport
that performs the copy (only `workstation` is fetched today; `target_local` is
recorded and never moved); a resolution rule plus its `reason`; configuration
handling; and inspection plus tests including an unreachable-destination path.

And the explicit **non-requirement**, which matters as much: **no server, no
content-addressed store, no object store, no database.** A future destination should
remain a *transfer target*, not become infrastructure — which is why none is built
speculatively.

---

## 3. Tests — keeping the documentation honest

**9 new tests** in `tests/test_artifacts.py`. Prose that drifts from code is worse
than no prose, so the documented model is asserted:

- the two destinations are exactly those documented;
- **the full resolution order holds**, rule by rule, including each `reason` string;
- `declared` distinguishes an instruction from a default;
- the per-kind defaults are as documented;
- the documented configuration shape works, including all three fallback aliases;
- **an unknown destination is ignored, not guessed**;
- **no third destination is implemented** (asserting the deliberate absence);
- **the extension point is documented** — the docstring must state the prerequisites
  *and* the non-requirements.

### 3.1 A test that was wrong, not the code

`test_unknown_destination_in_config_is_ignored_not_guessed` initially failed,
because I asserted `"metrics" not in policy.by_kind`. But `metrics` is a **built-in
default**, so it is always present — the invalid value was correctly ignored (it
stayed `workstation`, not `archive`). **The code was right and my assertion was
wrong**; it now checks the value is unchanged rather than the key absent, and also
that a genuinely new kind is rejected outright.

Worth recording because the first instinct on a red test is to suspect the code.

---

## 4. A release-hardening gap found — reported, not silently absorbed

While checking where to place user-facing R9 documentation, I found that the
**`docs/` site is stale and does not cover the 0.4.0 surface at all**:

| Finding | Detail |
| :--- | :--- |
| Version badge | most pages still read **`v0.3.0`**; three (`data`, `observability`, `remote`) already mention `v0.4.0` — a **partial, unfinished** update |
| Missing pages | **no page for `target`, `workload`, `runtime` or `tools`** — i.e. the entire control-plane surface this release is *about* |
| `platform.html` | covers `physics`, `warp`, `groot`, `cosmos` — not targets |

**This is genuinely important for a release**, but it is **larger than R9's
checkpoint** (an R9 page would still leave targets, workloads, runtime and tools
undocumented). Per the agreed boundary — *"if something appears to require a larger
architectural change, stop and report it rather than silently expanding 0.4.0"* — I
am **reporting it rather than absorbing it**.

**Recommendation:** treat the documentation set as its own checkpoint in the
hardening pass (it was listed as *"documentation/examples for the complete
workflow"*), covering the version badge, the missing 0.4.0 pages, and a complete
workflow walkthrough. Not done here.

---

## 5. Files changed

| File | Change |
| :--- | :--- |
| `src/caasi/core/artifacts.py` | module docstring is now the authoritative model reference (**+103 lines, 0 deletions**) |
| `tests/test_artifacts.py` | **9 new tests** asserting the documented model |

Reference trees unchanged: `openmover_robot` `f17c242a…`, `openmover_ws`
`1e09f5de…`, `caasi-workspace/openmover` 0 dirty.

**Full suite: 1233 passed, 1 failed** — the pre-existing `test_perception_cmd.py`
terminal-width artifact.

---

## 6. Next step

**Stopping for review**, before **R10** (FastAPI + Jinja2 + HTMX, observation-only,
in an optional extra with a mutating-route guard).

Awaiting direction on the **documentation-set gap** in §4 — whether to make it an
explicit checkpoint in this hardening pass.
