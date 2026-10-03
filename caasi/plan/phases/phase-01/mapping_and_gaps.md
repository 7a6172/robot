# OpenMover ↔ Caasi Capability Mapping and Gap Analysis

## 1. Principle & Methodology

As dictated by the Caasi development charter:
> **"The question for every OpenMover requirement should be: Can the existing Caasi already do this? If yes, use/document the existing capability rather than creating another abstraction."**

This document establishes the two-way relationship:
1. **Direct Mappings**: OpenMover requirements that existing Caasi v0.3.0 capabilities directly solve.
2. **Genuine Gaps**: Real requirements from the OpenMover research project that cannot be represented or executed with existing Caasi abstractions, structured strictly according to the 6-point evaluation criteria.

---

## 2. Requirement → Existing Caasi Capability Mapping

| # | OpenMover Research / Engineering Requirement | Existing Caasi v0.3.0 Capability | How It Would Be Used |
|---|---|---|---|
| 1 | **Robot Asset & Kinematic Modeling**<br>Dual differential-drive models (OpenMover & Pioneer 3DX), URDF, STL/DAE meshes, USD assets | `caasi project add robot`<br>`robots/<name>.yaml`<br>`core/project.py` | Register `robots/openmover.yaml` and `robots/pioneer3dx.yaml`. Asset files organized in `robot/urdf`, `robot/meshes`, `robot/usd`. Inspectable offline via `caasi project list`. |
| 2 | **Simulation Scene Management**<br>Warehouse USD, simple room USD, collision meshes | `caasi project add isaac_sim`<br>`scenes/<name>.yaml`<br>`isaac/sim/scenes/` | Register `scenes/warehouse.yaml` and `scenes/simple_room.yaml`. USD references declared in scene definitions. |
| 3 | **Stack B (Nav2 Sandbox) Navigation**<br>Nav2 bringup, costmap params, map server | `caasi nav status`<br>`caasi nav launch`<br>`caasi nav inspect` | `caasi nav launch --params <nav2_params.yaml> --map <map.yaml>` delegates directly to `nav2_bringup/bringup_launch.py`, tracking the navigation stack as a Caasi background run. |
| 4 | **Stack A (Product Stack) Bringup**<br>ROS 2 launch files for HAL, Cartographer, product mover | `caasi ros launch` | `caasi ros launch openmover bringup.launch.py system_mode:=simulation launch_gazebo:=0` starts the core stack as a managed Caasi run with automatic PID tracking and log capture. |
| 5 | **Headless Isaac Sim Bridge Execution**<br>`16_bridge_ros.py` and `17_bridge_openmover.py` driving physics and dual LiDARs | `caasi sim run`<br>`caasi sim headless`<br>`core/experiment.py` | Experiment YAML specifies `backend: sim`, pointing to the bridge script. Caasi resolves `/home/zar/isaacsim/python.sh` automatically and executes headlessly. |
| 6 | **Isaac Lab Policy Training & Evaluation**<br>PPO training (`22_train_openmover_nav.py`), evaluation (`21_run_openmover_nav.py`) | `caasi lab run`<br>`caasi lab play`<br>`caasi lab evaluate` | Experiment YAML specifies `backend: lab`. `caasi lab evaluate --checkpoint <model.pt>` seamlessly passes checkpoints and captures evaluation logs into `.caasi/runs/`. |
| 7 | **Behavioral Demonstration Collection**<br>Expert trajectories recorded with A* DWA / geodesic | `caasi dataset generate`<br>`caasi dataset list` | Experiment YAML specifies demo collector; `caasi dataset generate <config.yaml> --episodes 100` tracks generated `.pt` datasets under `datasets/` with file counts and sizes. |
| 8 | **Preflight Machine & Stack Verification**<br>Verify ROS 2 Jazzy, Isaac Sim 6.0, RTX 3080, CUDA 13.0, display server | `caasi check sim`<br>`caasi check ros`<br>`caasi doctor` | `caasi check sim` verifies NVIDIA driver, VRAM, and Isaac Sim installation with uniform exit codes before executing any experiment. |
| 9 | **Live Resource Monitoring & RAM Guard**<br>Monitor CPU, RAM, GPU %, VRAM, steps/s | `caasi monitor <run-id>`<br>`caasi gpu monitor` | Real-time Rich dashboard displaying RAM (out of 48 GB), VRAM (out of 10 GB), process RSS, and simulation throughput. |
| 10 | **Experiment Provenance & Audit**<br>Tracking git commit, hardware snapshot, package versions for every experiment | Layer 6 Provenance Bundle<br>`caasi audit` | Written to every run automatically: `manifest.yaml`, `environment.yaml`, `hardware.yaml`, `dependencies.yaml`, `git.json`. `caasi audit` audits reproducibility across 6 scopes. |
| 11 | **Remote Cluster / Workstation Execution**<br>Offload heavy training or evaluation to a remote GPU server | `caasi remote run <host>` | Configured in `caasi.yaml` under `remotes:`. Dispatches experiments over SSH as tracked runs with exit-code capture. |

---

## 3. Genuine Caasi Gaps Analysis

The following items are **genuine architectural gaps** discovered from the real OpenMover research workflow that cannot be cleanly achieved using existing Caasi v0.3.0 capabilities.

---

### Gap 1: Multi-Process Interdependent Run Orchestration (Composite Runs)

#### 1. What OpenMover needs:
In both Stack A (`openmover`) and Stack B (`warehouse_simulation`), running an experiment in simulation requires orchestrating **two interdependent processes**:
1. The **Simulation Bridge** (`isaac/scripts/17_bridge_openmover.py` or `16_bridge_ros.py`), which boots Isaac Sim, spawns the robot, and brings up the ROS 2 `/clock`, `/odom`, and `/scan` publishers.
2. The **ROS 2 Navigation Stack** (`openmover` bringup/bootloader or `nav2_bringup`), which must only start *after* the simulator is actively publishing clock/sensor data, and must terminate cleanly whenever the simulator shuts down.

#### 2. Why existing Caasi cannot provide it:
Caasi's `run_cmd.py` and `experiment.py` currently manage **exactly one process per run**. There is no declarative way to express:
- A run composed of multiple services (`services: [sim, ros_stack]`);
- Dependency order and readiness gates (e.g., `wait_for: { topic: "/clock", timeout: 30 }`);
- Coordinated lifecycle management (stopping the composite run terminates both sub-processes).
Currently, the user must manually open multiple terminals or write custom bash scripts, bypassing Caasi's run tracking for one or both processes.

#### 3. Smallest generalized Caasi capability:
A **Composite Run** (or **Pipeline/Service**) specification in `experiment.yaml`:
```yaml
name: stack_b_navigation
backend: composite
services:
  simulator:
    backend: sim
    script: isaac/scripts/16_bridge_ros.py
    readiness:
      topic: /clock
      timeout: 45
  stack:
    backend: ros
    launch: warehouse_simulation/launch/warehouse_simulation.launch.py
    depends_on: [simulator]
```
Caasi launches `simulator`, waits for the readiness probe, launches `stack`, and tracks both under a unified parent run ID (`manifest.yaml` records `services: {simulator: <run_id_1>, stack: <run_id_2>}`).

#### 4. How it fits existing architecture:
- Reuses `core/runs.py` without changing the fundamental run wrapper (`run.sh`, `exit_code`, PID liveness).
- Extends `core/experiment.py` to recognize `backend: composite` or a `services` mapping.
- `caasi run stop <parent_id>` cascades SIGTERM to child run IDs.
- Fully general: applies to any robotics system pairing a simulator with a middleware stack.

#### 5. What files/code would need changing:
- `src/caasi/core/experiment.py`: Add `CompositeExperiment` data model and parser.
- `src/caasi/core/runs.py`: Add parent/child relationship in `RunRecord` and cascade stop logic.
- `src/caasi/cli/run_cmd.py`: Support orchestrating readiness checks and child run dispatch.

#### 6. How it would be tested:
Create `experiments/test_composite.yaml` launching a mock publisher and subscriber, verify readiness delay, verify both PIDs are tracked, and confirm `caasi run stop` cleanly reaps both.

---

### Gap 2: Dynamic Hardware Safety Thresholds (RAM / VRAM Preflight Guard)

#### 1. What OpenMover needs:
OpenMover experiments have hard hardware cliffs:
- Launching Isaac Sim when available system RAM is below 8.0 GiB causes Linux out-of-memory lockups and hard system freezes.
- Launching dual RTX LiDAR rendering when free VRAM is below 3.5 GiB causes Vulkan driver crashes.
OpenMover currently guards against this via custom boilerplate in `isaac/scripts/common.py` (`common.preflight()`).

#### 2. Why existing Caasi cannot provide it:
Caasi's `core/check.py` checks *static* hardware presence (e.g., driver installed, GPU model recognized, total disk space), but does not evaluate *dynamic experiment-declared resource thresholds* (e.g. `min_available_ram_gb`, `min_free_vram_gb`) prior to launching a run.

#### 3. Smallest generalized Caasi capability:
Allow declarative resource requirements in `experiment.yaml` (and project `caasi.yaml`):
```yaml
name: isaac_warehouse
backend: sim
resources:
  min_available_ram_gb: 8.0
  min_free_vram_gb: 3.5
```
Before `caasi run start` spawns the process, it samples `sysinfo.virtual_memory().available` and `nvidia.query_gpus()`. If available resources are below the threshold, Caasi cleanly aborts with an informative error message and exit code 3 (`incompatible`), preventing system crashes.

#### 4. How it fits existing architecture:
- Perfectly matches the §16 Check Contract (`core/check.py`), where functional safety probes enforce `compatible` vs `incompatible`.
- Adds resource fields to `core/requirements.py` and `core/experiment.py`.
- Enriches the Layer 6 provenance `hardware.yaml` with the preflight check verdict.

#### 5. What files/code would need changing:
- `src/caasi/core/requirements.py`: Parse `resources` mapping.
- `src/caasi/core/check.py`: Add `DynamicResourceChecker` probe.
- `src/caasi/cli/run_cmd.py`: Run preflight check before launching background wrapper.

#### 6. How it would be tested:
Define an experiment requiring 100 GB RAM; verify `caasi run start` immediately aborts with exit code 3 and diagnostic guidance. Define an experiment requiring 2 GB RAM; verify it launches cleanly.

---

### Gap 3: Parameter Sweeps & Evaluation Campaign Matrix

#### 1. What OpenMover needs:
In research reinforcement learning and transfer evaluation (the NMTE paper), experiments are conducted across multi-dimensional parameter grids:
- 5 held-out test maps (`slalom`, `ring`, `rooms`, `serpentine`, `heldout`)
- 3 random seeds (`1, 7, 42`)
- 4 disturbance regimes (nominal, degraded friction, latency, payload bias)
- Checkpoints (`model_*.pt`)
Currently, OpenMover uses an unmanaged, custom script (`33_run_campaign.py` and `34_aggregate_campaign.py`) that runs outside Caasi, bypassing run tracking and provenance for the 60+ individual trials.

#### 2. Why existing Caasi cannot provide it:
Caasi only understands single, discrete runs (`caasi run start`, `caasi lab evaluate --checkpoint <pt>`). It has no concept of an *evaluation matrix*, parameter sweep generator, or campaign-level metric aggregation.

#### 3. Smallest generalized Caasi capability:
A **Campaign / Matrix** runner:
```yaml
name: nmte_generalization_campaign
backend: matrix
experiment: experiments/eval_nav.yaml
matrix:
  map: [slalom, ring, rooms]
  seed: [1, 7, 42]
  disturbance: [nominal, degraded]
output:
  summary_file: results/summary.json
```
Caasi sequences each combination as a tracked child run, records parameters into each run's provenance bundle, and aggregates trial results into a unified summary table.

#### 4. How it fits existing architecture:
- Sits above `core/runs.py` and `core/experiment.py`.
- Reuses `caasi lab evaluate` underneath for each individual trial.
- Integrates with `core/dataset.py` or `artifacts/` to store campaign results.

#### 5. What files/code would need changing:
- `src/caasi/core/experiment.py`: Add matrix schema support.
- `src/caasi/cli/lab.py` or new `src/caasi/cli/matrix_cmd.py`: Implement sequential matrix dispatch and summary aggregation.

#### 6. How it would be tested:
Run a 2×2 dummy matrix on a fast mock task, verify 4 distinct Caasi runs are created with proper provenance, and verify `summary.json` correctly aggregates the outcomes.

---

## 4. Conclusion & Recommended Action

Existing Caasi v0.3.0 is exceptionally well-suited to manage 80%+ of OpenMover's lifecycle immediately (project scaffold, ROS 2 launches, headless Isaac Sim execution, policy evaluation, dataset collection, live monitoring, provenance).

The three identified gaps (Composite Runs, Dynamic RAM Guard, Campaign Matrix) are **general robotics capabilities** that will substantially strengthen Caasi as a product while directly serving OpenMover research.
