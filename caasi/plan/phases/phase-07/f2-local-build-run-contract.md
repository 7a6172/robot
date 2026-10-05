# Phase 7: F2 Local Build/Run Destination Contract — Decision

**Status:** Decision recorded; smallest consistent correction implemented.
**Date:** October 2026
**Origin:** pre-existing defect reported (not fixed) in [`stage-f2-report.md`](stage-f2-report.md) §2.5.

---

## 1. The observed defect

For `target: local`:

- **`build`** took an `is_local_workspace` path, ran in the **project root**, and
  recorded `.caasi-build.json` there (`build.execute_target_build` sets
  `destination_path=str(project_root)`).
- **`run`** looked for the build record at the **deployment destination**
  (`build.get_last_build_status(target, dest, …)` from `runs.start_target_run`).

So `caasi build --target local` followed by `caasi run --target local` **already
failed today**, independent of F2. Confirmed identical at HEAD before any of this
work started.

---

## 2. The decision: what does `target: local` mean?

The contract was genuinely ambiguous — project-root build, destination build, or an
explicit project-vs-deployed distinction. **The existing code already answers it**,
and the answer was not a choice so much as an inconsistency to resolve:

**`local` is a deployed target, exactly like a remote one.**

Evidence, from caasi's own behaviour:

| Behaviour | Where it points |
| :--- | :--- |
| `deploy.resolve_deployment_destination(local)` | `~/.caasi/deployments/local/<project>` — a **deployed copy**, not the project root |
| `runs.start_target_run` **requires** an active deployment | *"No active deployment found on target 'local'… run 'caasi deploy local' first"* |
| `start_target_run` executes at | the **deployment destination** (`{dest}/.caasi/runs/<run_id>`) |

So two of the three sides already agree that `local` means **the deployed copy**.
The build's `is_local_workspace` path was the outlier.

**Canonical contract:**

```text
caasi deploy --target local     → ~/.caasi/deployments/local/<project>
caasi build  --target local     → builds AT that deployment, records .caasi-build.json THERE
caasi run    --target local     → runs AT that deployment, finds the record there
```

This makes `local` semantics **identical to every other target**, which is what the
R8 review requires: `local` must be a valid target for the same lifecycle semantics
as remote ones, because a future `--where` policy could select it.

### 2.1 What is deliberately NOT changed

The `is_local_workspace` path is **not deleted**. It remains correct for its actual
purpose: a **local workspace build** with no deployment — e.g. `colcon build` in
one's own checkout, where `caasi build` is used standalone. Removing it would break
that workflow.

The correction is narrower: when the target is `local` **and a deployment exists**,
the build belongs to that deployment. That is the case `run` depends on.

---

## 3. The smallest consistent correction

`build.execute_target_build` should treat the **existence of a deployment** as what
selects the deployed path, rather than the target being named `local`.

Rule:

```text
if the target has an active deployment at its destination:
        build at that destination (any transport, including local)
else if the target is a local workspace with no deployment:
        build in the project root (existing standalone behaviour, unchanged)
else:
        remote build (existing behaviour, unchanged)
```

**Why this is the smallest correct fix:**

- It does **not** add a lookup fallback (explicitly discouraged): it fixes *where
  the record is written*, so both sides agree on one location.
- It **removes** the special case rather than adding one: "is this a deployment?"
  is a better question than "is this target called `local`?".
- It leaves the standalone local-workspace build untouched, so no existing
  workflow regresses.
- `destination_path` is already a field on the build record; only the value
  changes for the deployed-local case.

---

## 4. Regression tests

1. `build --target local` with an active deployment records `.caasi-build.json`
   **at the deployment destination**.
2. `run --target local` then finds it (the previously failing path).
3. A local **workspace** build with no deployment still records in the project root
   — the standalone behaviour is preserved.
4. A remote build is unaffected.

---

## 5. Validation

End to end on the real `local` target: `deploy → build → run`, expecting the
previously-broken chain to complete, and the composed workload path to work on
`local` **with a build step** (which it could not before).
