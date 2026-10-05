# Phase 7: 0.4.0 Examples — Proposed Set

**Status:** Proposal. **Nothing implemented.** Awaiting review.
**Parent:** [`release-0.4.0-assessment.md`](release-0.4.0-assessment.md) §3a

---

## 1. Principle

> **The ecosystem owns the technology example. caasi demonstrates managing it.**

Each example is a **small caasi project** that references or adapts a *canonical*
ecosystem example — it does not re-implement one. The README of each states plainly
**what caasi provides** versus **what the ecosystem provides**.

---

## 2. A constraint that shapes the whole set

**Verified, not assumed:** `turtlesim` — the most famous ROS 2 teaching example —
is a **Qt GUI application**. It requires `DISPLAY`, so it **cannot be validated
headlessly in CI**.

That matters because the release requires examples to be "tested in CI where
practical". So the set is built on two tracks:

| Track | Anchor | CI-validatable |
| :--- | :--- | :--- |
| **Agnostic** | plain Python, ROS 2 CLI | **yes** — no display, no Isaac |
| **ROS 2** | `demo_nodes_py` (talker/listener, `add_two_ints`) | **yes** — display-free canonical examples |
| **Visual (optional)** | `turtlesim` | **no** — needs `DISPLAY`; documented as manual |

`turtlesim` is still worth including **because it is the example users recognise** —
but it is honestly labelled as requiring a display and **not** claimed as
CI-validated.

**Isaac Lab (`cartpole`) is excluded from the CI set** for a different reason: it
needs Isaac Sim and a GPU. It appears as an **opt-in example with documented
prerequisites**, skipped automatically when the environment is absent.

---

## 3. Structure — deliberately minimal

```text
examples/
├── README.md                      # index: what each teaches, prerequisites, caasi vs ecosystem
├── 01-project-and-environment/    # caasi project + environment inspection
├── 02-first-workload/             # define and run a workload locally
├── 03-targets-and-selection/      # targets, check, select, occupancy, --where
├── 04-remote-lifecycle/           # deploy → build → run → collect on a target
├── 05-ros2-observation/           # observe a real ROS 2 graph
├── 06-artifacts-and-provenance/   # declare outputs, collect, trace provenance
├── 07-end-to-end/                 # the whole chain in one workload
├── 08-ros2-turtlesim/             # canonical ROS 2 example (manual; needs display)
└── 09-isaac-lab-cartpole/         # canonical Isaac Lab task (opt-in; GPU + Isaac Sim)
```

**No example framework.** Each directory is a **normal caasi project** that
`caasi project init` could have produced, plus a `README.md` and a
`workloads/`/`experiments/` file. Examples are discovered by the index README and
linked from the docs site.

**Validation** lives in `tests/test_examples.py`, which walks the example
directories and runs the **safe subset** — so CI (`pytest -q` on release tags)
covers them automatically with **no new infrastructure**.

---

## 4. The proposed set

### 01 — project and environment *(concepts 1, 2)*

**Teaches:** `project init`, `project validate`, `project info`; `env fingerprint`,
`check`, `doctor`.

**Ecosystem:** none — pure caasi, since this stage is about the project itself.

### 02 — first workload *(concepts 4, 5, 6)*

**Teaches:** defining a `workloads/*.yaml`, running it **locally**, then `run list`,
`run logs`, `caasi logs -f`.

**Ecosystem:** a ~15-line Python script the user owns. Deliberately trivial — the
*point* is the caasi workflow around it, and a canonical technology example would
add noise without teaching anything new here.

**Also the teaching moment for the run model:** detached execution, exit codes, and
that a launched run is not the same as a succeeded one.

### 03 — targets and selection *(concepts 3, 7, 14)*

**Teaches:** `target list`, `target check`, `target inspect`, `target select`,
`target occupancy`, and `--where any|idle|prefer:<tag>`.

**Ecosystem:** none — this is pure control-plane. Uses whatever targets the user has
configured, and **works with only `local`**, so it needs no second machine.

### 04 — remote lifecycle *(concepts 8, 9, 10)*

**Teaches:** `deploy`, target-native `build`, remote `run`, `collect` — the composed
`workload run --target` chain, and the same steps run individually.

**Ecosystem:** a **minimal ROS 2 package** (`ament_cmake`, one package) so `build`
has something real to do. Not a copy of any upstream project — a few lines, and
clearly labelled as such.

**Requires a second target** (an SSH host) — documented as a prerequisite, and
**skipped in CI** when none is configured.

### 05 — ROS 2 observation *(concept 11)*

**Teaches:** `ros status|list|node|topic|service|graph`, `--domain`, and
`ros … --target`.

**Ecosystem:** **`demo_nodes_py`** — the canonical ROS 2 talker/listener. It is
standard, display-free, and deterministic enough to assert on. The example runs the
*upstream* nodes and uses caasi only to observe them.

**This is the clearest illustration of the philosophy:** the nodes are ROS 2's
example; caasi contributes observation and, where relevant, the target context.

### 06 — artifacts and provenance *(concepts 13, 15)*

**Teaches:** declaring `outputs:`, the routing model (from the R9 documentation),
`run artifacts`, `--collect`, and tracing a result back through
`run → deployment → build`.

**Ecosystem:** none beyond the plain script — the point is the **destination model
and provenance chain**.

### 07 — end-to-end *(concept 16)*

**Teaches:** one `workload run` composing `select → deploy → build → run → collect`
with `--where`, followed by reading the provenance it produced.

**Ecosystem:** combines the minimal ROS 2 package from 04 with the declared outputs
from 06 — no new technology.

### 08 — ROS 2 `turtlesim` *(the recognised example)*

**Teaches:** the same observation skills against the example users **already know**,
plus `--where` when a robot target is available.

**Ecosystem:** **`turtlesim`** — used as-is via `ros2 run turtlesim turtlesim_node`.
caasi contributes nothing to the node; it demonstrates observing it.

**Honestly labelled:** requires a **display**; **not** CI-validated; the README says
so and points at example 05 for the headless equivalent.

### 09 — Isaac Lab `cartpole` *(opt-in)*

**Teaches:** `caasi train` around a **canonical Isaac Lab task**, plus GPU-aware
target selection (`--where prefer:gpu`) and `target inspect`.

**Ecosystem:** **`isaaclab`'s own `cartpole` task**, launched through the upstream
`scripts/reinforcement_learning` entry point that the example's experiment config
**names as its `script`**. caasi does not hardcode that path — `caasi train`
delegates to whatever script the experiment declares — so the example supplies the
project, the requirements, the experiment config and the target choice, while the
training entry point stays Isaac Lab's.

**Prerequisites documented:** Isaac Sim + a CUDA GPU. **Skipped automatically** when
absent, so it never breaks the suite on a machine without a GPU.

---

## 5. Safety

Every example is **safe by construction**:

- no physical robot motion — `turtlesim` is a GUI simulation, `demo_nodes` is
  pub/sub, `cartpole` is a simulated task;
- no hazardous operations; nothing deploys to hardware;
- example 04 targets **the user's own configured target**, and the README says to
  use a test machine rather than a production robot.

`turtle_teleop_key` is **not** used — it invites interactive key control and teaches
nothing caasi-specific.

---

## 6. Coverage against the requested concept list

| # | Concept | Where |
| :--- | :--- | :--- |
| 1 | project creation/inspection | 01 |
| 2 | environment inspection/fingerprint | 01 |
| 3 | target discovery/checking | 03 |
| 4 | workload definition | 02 |
| 5 | local execution | 02 |
| 6 | logs/status/inspection | 02 |
| 7 | target selection and `--where` | 03, 07 |
| 8 | deployment | 04 |
| 9 | target-native build | 04 |
| 10 | remote execution | 04 |
| 11 | ROS 2 observation | 05, 08 |
| 12 | runtime/tool observation | 03, 05 |
| 13 | artifact declaration/collection | 06 |
| 14 | occupancy | 03 |
| 15 | provenance | 06, 07 |
| 16 | end-to-end workflow | 07 |

All sixteen are covered. **Concept 12** (`target runtime`, `tools`) is folded into
03/05 rather than given its own example, because it teaches the same
observe-the-target skill as 03 — the instruction was explicitly **not** to force
every command into an artificial example.

---

## 7. Explicitly not done

- **No** `hello caasi` filler demos.
- **No** example framework or runner.
- **No** duplication of upstream projects — canonical examples are referenced.
- **No** physical-robot or hazardous examples.
- **No** example for every subcommand — the list teaches the *workflow*.
- **No** CI requirement added: examples validate through the **existing**
  `pytest -q` release workflow.

---

## 8. Recommended implementation order

1. `examples/README.md` index + the minimal structure and the test harness skeleton.
2. **01–03** (agnostic, no prerequisites) — the foundation a new user meets first.
3. **05–07** (ROS 2 `demo_nodes`, artifacts, end-to-end) — the CI-validatable core.
4. **04** (requires a second target).
5. **08–09** (turtlesim, Isaac Lab) — opt-in, prerequisite-heavy.
6. Wire the index into the **documentation checkpoint** (the docs-site gap already
   identified).

**Awaiting review before implementing.**
