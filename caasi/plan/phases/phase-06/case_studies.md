# Phase 6 Case Studies: Full Project Adoption & Caasi-Native Isaac/ROS Workspace

**Date**: 2026-10-03  
**Project**: OpenMover Canonical Workspace (`caasi-workspace/openmover`)  
**Baseline**: `1512c3f` $\rightarrow$ Phase 6

---

## Case Study 6.1: Resource-Aware Workspace Build (`caasi build`)

### Context & Problem
In standard ROS 2 robotics projects, developers manually invoke `colcon build --symlink-install`. On multi-core developer workstations with constrained RAM or memory-heavy C++ translation units (such as navigation planners, geometry parsers, and custom message code generators), default unconstrained worker counts (`nproc`) frequently exhaust physical RAM and trigger the Linux OOM killer or system lockups.

### Caasi Solution
We introduced `caasi build` as a first-class project orchestrator in `caasi.core.build`.
1. It automatically discovers the project root from the current working directory or any subdirectory.
2. It detects total system physical RAM (46.8 GiB) and CPU cores (20 cores) and selects a RAM-safe worker count:
   $$\text{Workers} = \min(6, 20) = 6$$
3. It executes `colcon build --parallel-workers 6 --symlink-install` within the project root under the properly wrapped ROS environment.

### Empirical Evidence
- **Single Package Build**:
  ```bash
  caasi build -p openmover_msgs
  ```
  - Result: 1 package completed in 11.2s (total 11.47s).
- **Full Workspace Build**:
  ```bash
  caasi build
  ```
  - Result: 9 packages compiled across 6 parallel workers in 69.39s.
  - Packages: `auto_mapping_toolbox`, `auto_mapping_toolbox_msgs`, `bluesea2`, `ira_laser_tools`, `openmover`, `openmover_msgs`, `relocalization_toolbox`, `relocalization_toolbox_msgs`, `warehouse_simulation`.
  - Exit code: 0.

---

## Case Study 6.2: Automatic Project ROS Overlay Chaining

### Context & Problem
After running `colcon build`, developers must remember to manually run `source install/setup.bash` in every shell session. If a command is launched from a new terminal, IDE, or script without sourcing, ROS 2 fails to find the newly built packages, launch files, or custom messages (`openmover_msgs`), leading to frustrating `Package not found` errors.

### Caasi Solution
`caasi.core.rosenv` was upgraded with automatic project overlay detection:
1. When any ROS-dependent command or wrapper runs, `rosenv.project_setup_file()` checks if the active caasi project has an `install/setup.bash`.
2. If present, `rosenv.is_sourced()`, `rosenv.sourced_env()`, and `rosenv.wrap()` automatically chain both the system underlay (`/opt/ros/jazzy/setup.bash`) and the project overlay (`<project_root>/install/setup.bash`).
3. Whenever `caasi build` completes, `rosenv.clear_cache()` invalidates memoized environment snapshots so newly built targets are instantly recognized.

### Empirical Evidence
In a completely fresh terminal where `install/setup.bash` was **never** manually sourced:
```bash
caasi native ros pkg prefix openmover_msgs
```
- Standard ROS without caasi: `Package not found` (exit code 1).
- Executed via caasi:
  ```text
  /home/zar/Documents/phd/robot/caasi-workspace/openmover/install/openmover_msgs
  ```
  (exit code 0).
- Project package query:
  ```bash
  caasi native ros pkg list | grep openmover
  ```
  Outputs `openmover`, `openmover_msgs` immediately.

---

## Case Study 6.3: Canonical Isaac Sim Warehouse Simulation & ROS 2 Bridge Execution

### Context & Problem
The OpenMover simulation stack requires coordinating NVIDIA Isaac Sim with project-specific USD assets (`pioneer3dx.usda`, `warehouse.usda`, `workcell_mesh.usdc`), RTX LiDAR sensors, and an active ROS 2 bridge publishing clock, odometry, TF, and laser scan topics. In external workspaces, path references were hardcoded to external directories.

### Caasi Solution
1. Consolidated all USD robots and scenes under `caasi-workspace/openmover/assets/`.
2. Placed bridge scripts under `caasi-workspace/openmover/sim/bridges/`.
3. Updated `common.py` to resolve assets dynamically via `CAASI_PROJECT_ROOT`.
4. Declared the experiment in `experiments/sim_warehouse_bridge.yaml`:
   ```yaml
   name: sim-warehouse-bridge
   backend: sim
   script: ../sim/bridges/16_bridge_ros.py
   cwd: .
   args:
     - --duration
     - "10"
   ```
5. Launched via `caasi sim run experiments/sim_warehouse_bridge.yaml`.

### Empirical Evidence
- **Run ID**: `20261003-202114-sim-warehouse-bridge`
- **Execution Telemetry**:
  - Application startup: 11.0s (warm Omniverse shader cache).
  - Isaac Sim loaded pioneer3dx articulation and warehouse workcell.
  - ROS 2 bridge initialized `rclpy` and registered publishers:
    - `/clock`
    - `/odom`
    - `/tf`
    - `/openmover/hardware/lidar_forward/scan`
    - `/openmover/hardware/lidar_rear/scan`
    - `/cmd_vel` (subscriber)
- **Status**: `succeeded` (exit code 0).
- **Provenance**: Generated complete Level 6 provenance bundle in `~/.caasi/runs/20261003-202114-sim-warehouse-bridge/`.

---

## Case Study 6.4: Isaac Lab Reinforcement Learning Rollout & Provenance Tracking

### Context & Problem
Evaluating reinforcement learning policies in Isaac Lab requires specific launcher wrappers (`isaaclab.sh -p <script>`), PyTorch CUDA device context, terrain meshes, and sensor ray-casting. Managing RL scripts alongside ROS 2 packages within the same repository typically causes Python environment conflicts.

### Caasi Solution
1. Structured `lab/` inside the canonical project with `openmover_lab` Gym package, `tasks/`, `maps/`, and `models/`.
2. Created declarative runner experiment `experiments/lab_smoke.yaml`:
   ```yaml
   name: lab-smoke
   backend: lab
   script: ../lab/tasks/21_run_openmover_nav.py
   cwd: .
   args:
     - --num_envs
     - "1"
     - --num_steps
     - "20"
     - --policy
     - random
   ```
3. Executed via `caasi lab run experiments/lab_smoke.yaml`.

### Empirical Evidence
- **Run ID**: `20261003-202234-lab-smoke`
- **Execution Telemetry**:
  - Loaded terrain mesh prim: 98,632 vertices, 431,436 faces.
  - Initialized obstacle table (1024 tiles) and geodesic grid.
  - Observation space: `Box(-inf, inf, (1, 1208), float32)`.
  - Action space: `Box(-inf, inf, (1, 2), float32)`.
  - Execution speed: 20 steps in 0.55s (37 env-steps/s on `cuda:0`).
  - Recorded dual LiDAR scan statistics (front mean 0.347m, rear mean 0.420m).
- **Status**: `succeeded` (exit code 0).
- **Provenance**: Generated full Level 6 provenance bundle in `~/.caasi/runs/20261003-202234-lab-smoke/`.
