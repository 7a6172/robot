# Phase 7: 0.4.0 Examples — Catalog Proposal (revised)

**Status:** Proposal. **Nothing implemented.** Awaiting review.
**Supersedes:** an earlier narrow proposal that covered only the 0.4.0 control-plane
workflow. **Corrected scope:** the catalog covers the **complete basic CLI**, so a new
user can find a real example for essentially **every basic caasi command** — including
commands that predate 0.4.0.

---

## 1. The goal, restated

> A new user should be able to think *"I want to know how to use `caasi X` — where is
> the smallest real example?"* and find it quickly.

**Command coverage, not example-count inflation.** A small number of coherent
projects, each demonstrating many commands.

---

## 2. Complete CLI inventory

Extracted **programmatically from the live command tree** (not hand-listed), so it is
exhaustive rather than approximate:

**57 root commands · 253 command paths.**

| Root | Subs | Root | Subs | Root | Subs |
| :--- | ---: | :--- | ---: | :--- | ---: |
| `project` | 32 | `physics` | 5 | `mapping` | 4 |
| `run` | 13 | `native` | 5 | `cosmos` | 4 |
| `ros` | 12 | `lab` | 5 | `tools` | 3 |
| `runtime` | 8 | `isaac-ros` | 5 | `nitros` | 3 |
| `target` (alias `node`) | 7 | `control` | 5 | `benchmark` | 3 |
| `perception` | 7 | `warp` | 4 | `pipeline` | 2 |
| `gpu` | 7 | `vision` | 4 | `version`, `train`, `test`, `start`, `shell`, `setup`, `rviz2`, `rqt`, `rosbag`, `replay`, `monitor`, `logs`, `init`, `info`, `help`, `doctor`, `deploy`, `check`, `build`, `audit` | 1 each |
| `dataset` | 7 | `sensor` | 4 | | |
| `config` | 7 | `workload` | 4 | | |
| `view` | 6 | `remote` | 4 | | |
| `nav` | 6 | `motion` | 6 | | |
| `moveit` | 6 | `groot` | 6 | | |
| `env` | 6 | `container` | 6 | | |
| `teleop` | 5 | `system` | 5 | | |
| `slam` | 5 | `sim` | 5 | | |

**Aliases:** `caasi node` ≡ `caasi target`; `caasi start` ≡ `caasi run start`;
`caasi logs` ≡ `caasi run logs`; `caasi init` ≡ `caasi project init`.

---

## 3. Classification of every command

### Class 1 — Standalone step (shown as its own small stage)

Not a separate example each, but each deserves its own visible step rather than
being buried: `project init`, `project validate`, `env fingerprint`, `target check`,
`target select`, `target occupancy`, `workload run`, `deploy`, `build`,
`run artifacts`, `tools run`.

### Class 2 — Grouped (demonstrated together — the bulk of the CLI)

| Group | Commands |
| :--- | :--- |
| Project lifecycle | `project add/remove/list/inspect/add-file/config/info` |
| Project definitions | `project robot …`, `project scene …`, `project task …` |
| Run lifecycle | `run start/list/status/logs/attach/pause/resume/restart/stop/inspect` |
| Workload | `workload list/inspect/run` |
| Targets | `target list/inspect/check/runtime/select/occupancy` |
| Runtime lifecycle | `runtime install/enable/start/status/verify/update/rollback` |
| ROS 2 | `ros status/list/node/topic/service/graph` |
| Environment | `env inspect/fingerprint/compare`, `check`, `doctor`, `info`, `version` |
| Config | `config show/get/set/path/catalog/tools` |
| Artifacts/provenance | `run artifacts`, `audit`, `run inspect` |

### Class 3 — Cookbook / reference (read-only; no project needed)

`version`, `info`, `help`, `doctor`, `gpu`, `system`, `sensor`, `vision`, `physics`,
`native`, `shell`, `config path`, `test`.

### Class 4 — Technology example (canonical upstream example)

| Ecosystem | Canonical example | Commands demonstrated |
| :--- | :--- | :--- |
| **ROS 2** | `demo_nodes_py` (talker/listener, `add_two_ints`) | `ros *`, `control`, `pipeline`, `target runtime` |
| **ROS 2 (visual)** | `turtlesim` | `ros *`, `rviz2`, `rqt`, `teleop replay`, `dataset`, `replay` |
| **Isaac Lab** | `cartpole` | `train`, `lab`, `benchmark`, `check` |
| **Isaac Sim** | upstream samples | `sim *`, `view *`, `physics`, `warp` |
| **Isaac ROS** | `isaac_ros_*` packages | `isaac-ros`, `perception`, `nitros`, `slam`, `mapping`, `motion` |
| **Docker** | a public image | `container *`, `target runtime` |
| **ROS 2 nav stack** | Nav2 / MoveIt bringup | `nav`, `moveit` (read-only verbs only) |

### Class 5 — Unsafe / destructive / physical — explained, never performed

| Command | Why | Handling |
| :--- | :--- | :--- |
| `run stop`, `run restart` | terminates a live process | demonstrated against **the example's own run** |
| `run delete` | **destructive** | **no `--dry-run` exists** — documented only; **never executed** |
| `project remove --purge` | **destructive** | **no `--dry-run` exists** — documented only; **never executed** |
| `runtime rollback`, `runtime update` | changes a live installation | **ephemeral example unit only** |
| `teleop start`, `teleop record` | **physical robot motion** | **never commanded**; documented with the safety note |
| `nav launch`, `moveit launch`, `motion execute` | **physical motion / bringup** | documented; only `status`/`plan`/`inspect` demonstrated |
| `control *` (controller changes) | changes hardware state | only `list`/`status`/`check`/`doctor` |
| `setup` | mutates the user's environment | documented, not run |
| `deploy`/`build` to a **production robot** | affects real hardware | examples target the user's own **test** machine |

**No example or CI run executes a Class 5 destructive command.**

---

## 4. Proposed organization — few projects, broad coverage

```text
examples/
├── README.md                    # command index: "caasi X" -> example (discoverability)
├── COVERAGE.md                  # the full command -> example matrix (auditable)
├── 01-python-project/           # backbone; the largest command count
├── 02-targets-and-selection/
├── 03-ros2-demo-nodes/          # canonical ROS 2
├── 04-container/                # canonical Docker image
├── 05-ros2-turtlesim/           # canonical turtlesim (manual: display)
├── 06-isaac-lab-cartpole/       # canonical Isaac Lab task (opt-in: GPU)
├── 07-control-plane-end-to-end/ # select -> deploy -> build -> run -> collect -> provenance
└── cookbook/                    # Class-3 read-only reference
```

**How the reuse works.** Example **01** is *one* small Python project that
demonstrates the project, workload, run, logs, status, inspect, artifacts,
provenance and environment families — because they are all facets of one real
workflow. Someone asking *"how do I use `caasi run logs`?"* finds it in 01, **not**
in a dedicated logs example.

**Discoverability.** `examples/README.md` is a **command index** (*"`caasi target
select` → example 02"*), and `COVERAGE.md` is the auditable matrix. Both are linked
from the docs site.

---

## 5. Coverage matrix (abridged — `COVERAGE.md` will be exhaustive)

| Command | Covered | Example | Execution | CI / manual | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `project init` | yes | 01 | runnable | **CI** | scaffolds a real project |
| `project add/list/inspect/add-file/info` | yes | 01 | runnable | **CI** | |
| `project remove` | **documented only** | 01 | **not executed** | manual | **destructive, no `--dry-run`** |
| `project validate`, `project config *` | yes | 01 | runnable | **CI** | |
| `project robot/scene/task *` | yes | 01 | runnable | **CI** | definitions, no hardware |
| `env inspect/fingerprint/compare` | yes | 01 | runnable | **CI** | |
| `check`, `doctor` | yes | 01 | runnable | **CI** | |
| `workload list/inspect/run` | yes | 01 | runnable | **CI** | local target |
| `run start/list/status/logs/inspect` | yes | 01 | runnable | **CI** | |
| `run pause/resume/stop/restart` | yes | 01 | runnable | **CI** | the example's own run |
| `run attach` | yes | 01 | documented | manual | needs a TTY |
| `run delete` | **documented only** | 01 | **not executed** | manual | **destructive, no `--dry-run`** |
| `run artifacts`, `audit` | yes | 01 | runnable | **CI** | provenance |
| `logs`, `start` (aliases) | yes | 01 | runnable | **CI** | |
| `target list/check/inspect` | yes | 02 | runnable | **CI** | works with `local` alone |
| `target select`, `target occupancy` | yes | 02 | runnable | **CI** | |
| `workload run --where` | yes | 02 | runnable | **CI** | |
| `target runtime` | yes | 02, 04 | runnable | **CI** | process/systemd/container |
| `ros status/list/node/topic/service/graph` | yes | 03 | ROS 2 demo | **CI** | canonical `demo_nodes_py` |
| `tools list/run`, `rosbag` | yes | 03 | runnable | **CI** | |
| `rviz2`, `rqt` | yes | 05 | GUI | manual | needs a display |
| `container *` | yes | 04 | Docker | **CI** | canonical public image |
| `deploy`, `build` | yes | 07 | runnable | **CI** | local deployed target |
| `runtime *` (incl. `rollback`/`update`) | yes | 07 | runnable | **CI** | ephemeral example unit |
| `ros * --target` | yes | 07 | ROS 2 + SSH | CI if configured | opt-in |
| `remote *` | yes | 07 | runnable | CI / opt-in | legacy shim, documented deprecated |
| `sim *`, `view *` | yes | 06 | Isaac Sim | **manual / opt-in** | needs Isaac Sim + GPU |
| `train`, `lab`, `benchmark` | yes | 06 | Isaac Lab | **manual / opt-in** | needs GPU |
| `isaac-ros`, `perception`, `nitros`, `slam`, `mapping`, `motion` | yes | 06 | Isaac ROS | **manual / opt-in** | needs Isaac ROS + GPU |
| `nav`, `moveit` | **partly** | 06 | Isaac/ROS | **manual** | read-only verbs; **launch never run** |
| `control` | **partly** | 03 | ROS 2 | manual | read-only verbs |
| `teleop start/record` | **documented only** | cookbook | — | manual | **physical motion — never executed** |
| `teleop replay`, `replay`, `dataset *` | yes | 05 | runnable | manual | bags from turtlesim |
| `gpu`, `system`, `sensor`, `vision`, `physics`, `warp`, `native`, `shell` | yes | cookbook | read-only | **CI** | informational |
| `config show/get/set/path/catalog/tools` | yes | 01 | runnable | **CI** | `set` on a scratch config |
| `version`, `info`, `help`, `test` | yes | cookbook | read-only | **CI** | |
| `setup` | **documented only** | cookbook | — | manual | **mutates the environment** |
| `node`, `pipeline` | yes | 02, 03 | alias / ROS 2 | **CI** | |

---

## 6. Commands without a runnable example, and why

| Command(s) | Reason |
| :--- | :--- |
| `run delete`, `project remove` | **destructive**, and **neither has a `--dry-run` guard** — so there is no safe demonstration at all. Documented, never executed. |
| `teleop start` / `teleop record` | **physical robot motion**. An example must never move hardware. |
| `nav launch`, `moveit launch`, `motion execute` | **physical motion / hardware bringup**. Only read-only siblings demonstrated. |
| `setup` | **mutates the user's environment**; documented rather than run. |
| `run attach` | needs an interactive TTY; not automatable. |
| `rviz2`, `rqt`, `turtlesim` | need a **display**; genuinely manual. |
| `sim *`, `train`, `lab`, `isaac-ros`, `perception`, `nitros`, `slam`, `mapping`, `motion` | need **Isaac Sim / Isaac ROS + GPU**; opt-in, auto-skipped when absent. |
| `slam`/`mapping` live modes | need a running robot/sim graph; read-only inspection shown where one exists. |

**Every command is accounted for — none silently omitted.**

---

## 7. Validation tiers

| Tier | Examples | Mechanism |
| :--- | :--- | :--- |
| **CI** | 01, 02, 03, 04, 07 (local), cookbook | `tests/test_examples.py`, run by the **existing** release `pytest -q` |
| **Opt-in** | 06 (Isaac), 07 (SSH target) | run when the prerequisite exists, **auto-skipped** otherwise |
| **Manual** | 05 (turtlesim), `rviz2`/`rqt`, nav/moveit launch | documented with prerequisites; **never claimed as CI-covered** |

**No new infrastructure** — the release workflow already runs the suite.

---

## 8. caasi vs the ecosystem (stated in every example README)

> **ROS 2 provides** the `demo_nodes_py` talker/listener. **caasi provides** the
> project, the target context, the observation commands, and the provenance around
> running them.

---

## 9. Explicit non-goals

No artificial project per command · no example framework · no duplication of
upstream projects · **no physical-robot or hazardous operations** · no example that
executes a destructive command · no new CI infrastructure.

---

## 10. Implementation order (after review)

1. `examples/README.md` index + `COVERAGE.md` + the `tests/test_examples.py` harness.
2. **01** — carries the largest command count.
3. **02** and **cookbook**.
4. **03** and **04**.
5. **07** (local).
6. **05** and **06** (opt-in/manual).
7. Wire the index into the documentation checkpoint.

---

## 11. Open question for review

The earlier proposal flagged the **docs-site gap** (no `target`/`workload`/`runtime`/
`tools` pages; stale version badges). With a full catalog, the natural home is
**`examples/README.md` as the command index** linked from a docs landing page — which
means the **documentation checkpoint should follow the examples**, not precede them.
Flagging the ordering rather than assuming it.
