# caasi examples

**A new user should be able to ask *"how do I use `caasi X`?"* and find the smallest
real example here.**

Seven examples, each a coherent project rather than a command-by-command demo —
because related caasi commands belong to one workflow, and a pile of artificial
single-command projects would teach you less.

> **Every current caasi command is accounted for.** See
> [`COVERAGE.md`](COVERAGE.md) for the auditable command → example mapping
> (57 root commands, 253 command paths, generated from the live CLI).

---

## Start here

| Example | Teaches | Prerequisites | Validation |
| :--- | :--- | :--- | :--- |
| **[01 — Your first project](01-python-project/README.md)** | the core workflow: project, workload, run, logs, artifacts, provenance | Python 3.10+ | **CI** |
| **[02 — Targets and selection](02-targets-and-selection/README.md)** | `target *`, `select`, `occupancy`, `--where` | none (works with `local`) | **CI** |
| **[03 — ROS 2 observation](03-ros2-demo-nodes/README.md)** | `ros *`, `tools`, `pipeline` | ROS 2, **no display needed** | **CI** |
| **[04 — Containers and runtimes](04-container/README.md)** | `container *`, `target runtime` | Docker or Podman | **CI** |
| **[05 — `turtlesim`](05-ros2-turtlesim/README.md)** | the ROS 2 example everyone knows, plus `rviz2`/`rqt`, bags | ROS 2 + **a display** | **manual** |
| **[06 — Isaac / Isaac Lab](06-isaac-lab-cartpole/README.md)** | `train`, `lab`, `sim`, GPU-aware selection | **GPU + Isaac Sim + Isaac Lab** | **opt-in** |
| **[07 — Control plane end to end](07-control-plane-end-to-end/README.md)** | `select → deploy → build → run → collect → provenance` | ROS 2; a target to deploy to | **CI** (local) / opt-in |
| **[Cookbook](cookbook/README.md)** | the read-only inspection commands | none | **CI** |

**Suggested order for a new user:** 01 → 02 → then 03 or 04 → then 07. Examples 05
and 06 need hardware or a display and are best left until the basics are clear.

---

## Find the example for a command

| I want to know about… | Go to |
| :--- | :--- |
| `caasi project *` | **01** |
| `caasi workload *`, `caasi run *` | **01** (and **07** for the remote chain) |
| `caasi env *`, `caasi check` | **01** |
| `caasi target *`, `--where`, `caasi target occupancy` | **02** (and **07** for remote) |
| `caasi ros *`, `caasi tools *`, `caasi pipeline` | **03** (and **05** for a GUI) |
| `caasi container *`, `caasi target runtime` | **04** |
| `caasi deploy`, `caasi build`, `caasi runtime *`, `caasi remote *` | **07** |
| `caasi rviz2`, `caasi rqt`, `caasi replay`, `caasi dataset` | **05** |
| `caasi sim *`, `caasi train`, `caasi lab`, `caasi benchmark`, `caasi isaac-ros`, `caasi perception`, `caasi nav`, `caasi moveit` | **06** |
| `caasi version`, `info`, `gpu`, `system`, `sensor`, `vision`, `physics`, `config`, `monitor` | **[Cookbook](cookbook/README.md)** |

For the complete listing, use [`COVERAGE.md`](COVERAGE.md).

---

## How these examples relate to caasi

Each example README states **what caasi provides versus what the underlying
ecosystem provides**, because the distinction is the point:

- the **ROS 2** example uses ROS 2's own `demo_nodes_py` — caasi observes it;
- the **container** example uses a normal Docker image — caasi observes it;
- the **Isaac Lab** example uses Isaac Lab's own `cartpole` task and entry point —
  caasi configures, launches and tracks it;
- the **Python** example is a deliberately trivial script, because what is being
  taught is the caasi workflow *around* your code.

**No example reimplements an upstream tool, and none invents safety features the CLI
does not have.**

---

## Safety

- **No example moves hardware.** `teleop start`/`record`, `nav launch`,
  `moveit launch` and `motion execute` are documented but **never executed**.
- **No example deletes anything.** `run delete` and `project remove` are documented,
  never run — and neither has a `--dry-run`, so there is no safe demonstration.
- Examples that deploy target **your own** machine or a test target. Point them at a
  machine you may deploy to, not a production robot.

---

## Validating the examples

```bash
pytest tests/test_examples.py -q
```

This runs the CI-tier examples end to end. Opt-in and manual examples are **skipped
automatically** when their prerequisites are absent, and are never claimed as
validated when they were not run.
