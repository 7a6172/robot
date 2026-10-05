# 07 — The whole chain, end to end

**Prerequisites:** ROS 2 (`/opt/ros/<distro>`) · a target you may deploy to.
The **built-in `local` target works**, so a second machine is optional but is the
more instructive case. **CPU-only is fine — no GPU required.**

This is the control-plane workflow in one place:

```text
select → deploy → build → run → collect → provenance
```

Every step is demonstrated **both** composed and individually, because when
something breaks you debug the individual steps.

---

## Before you start

Use a machine you may deploy to — **not a production robot**. Deployment copies the
project to the target's deployment root; it does not modify your source tree.

```bash
cd examples/07-control-plane-end-to-end
```

## 1. Where could this run?

```bash
caasi target select
```

Each target gets a verdict with the measured fact behind it. The project requires
`ros2: jazzy`, so a target without ROS 2 is eliminated *with that reason shown*.

## 2. Run the whole chain

```bash
caasi workload run report --target local
```

You will see each step reported as it completes, and at the end the ids it
produced:

```text
✔ deploy   — deployed deploy-cp-demo-... (verified)
✔ build    — built on local
✔ run      — <run-id> succeeded on local
✔ collect  — collected 1 artifact(s)

  produced: build_id=... deployment_id=... run_id=... git_revision=... run_status=succeeded
```

## 3. Or choose the target by policy

```bash
caasi workload run report --where any           # any suitable target
caasi workload run report --where idle          # prefer one that is not busy
caasi workload run report --where prefer:ros2   # prefer a tag
```

`--target` and `--where` are mutually exclusive; one is required. If nothing
satisfies the workload, caasi **fails and explains** — it never queues or waits.

## 4. The same thing, step by step

```bash
caasi deploy local
caasi build --target local
caasi run start experiments/report.yaml --target local
caasi run artifacts <run-id> --collect
```

## 5. Read the provenance

This is the point of the whole exercise — any result can be traced back:

```bash
caasi run list                                  # the run, its target and state
caasi run artifacts <run-id>                    # what it produced, and where each file went
caasi audit                                     # the chain: project → run → deployment → build
```

A run record carries `target`, `deployment_id`, `build_id`, `git_revision`,
`project` and — when a workload produced it — **which workload** and whether a
policy chose the target. Manual and composed runs record the *same* fields, so the
two are indistinguishable afterwards.

---

## What this demonstrates about failure

A chain stops at the first failing step and **names it**, leaving the earlier ids
visible so you can continue by hand. That is deliberate: partial success must be
visible, not reported as success.

If you want to see it, point the run step at a script that fails — the chain stops
at `run`, `collect` never executes, and the **script's own exit code** is reported
unchanged.

---

## What caasi provides vs the ecosystem

| Ecosystem provides | caasi provides |
| :--- | :--- |
| ROS 2 itself; `colcon` performs the build | Choosing a target, checking it fits, sequencing the steps |
| The `ament_cmake` build system | Recording deployment, build and run identity |
| Your script and what it computes | Artifact routing, collection, and the provenance chain |

The package under `src/demo_pkg/` is deliberately tiny. **caasi does not own the
build system** — `caasi build` invokes `colcon`, and the package is an ordinary ROS 2
package.
