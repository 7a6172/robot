# Phase 6 Report: Full Project Adoption & Caasi-Native Isaac/ROS Workspace

**Date**: 2026-10-03  
**Status**: Completed  
**Repository Baseline**: `1512c3f`  
**Phase 6 Target Workspace**: `/home/zar/Documents/phd/robot/caasi-workspace/openmover/`  
**Read-Only Trees Preserved**: `/openmover_robot` and `/openmover_ws` (100% untouched)  
**Test Suite**: 870 passed (184.81s)

---

## 1. Executive Summary

Phase 6 transitioned `caasi` from an external orchestrator of foreign workspaces into a **unified project-level management and control layer**. Analogous in spirit to what `uv` provides for Python projects, `caasi` now provides a single cohesive interface that understands the structure, lifecycle, and toolchains of an integrated Isaac Sim + Isaac Lab + ROS 2 robotics project without replacing or duplicating underlying ecosystem tools (colcon, CMake, ROS 2, Isaac Sim, Isaac Lab, Nav2, PyTorch, CUDA, USD).

### Key Achievements
1. **Canonical Caasi-Native OpenMover Project Established**: Created `/home/zar/Documents/phd/robot/caasi-workspace/openmover` hosting the complete robotics project (ROS 2 packages, assets, simulation bridges, Isaac Lab Gym tasks, configurations, declarative experiments, and lockfiles).
2. **`caasi build` Implemented**: Introduced a resource-aware workspace build orchestrator that wraps `colcon build --symlink-install` with RAM-safe parallel worker calculation (e.g. 6 workers on 46 GiB host RAM), package filtering (`-p`, `-u`), clean builds, and output streaming.
3. **Automatic Project Overlay Chaining**: Extended `caasi.core.rosenv` to detect `<project_root>/install/setup.bash` and chain-source it after the base ROS 2 underlay (`/opt/ros/jazzy/setup.bash`). Commands executed through caasi immediately recognize project-built packages without manual shell sourcing.
4. **Project Root Injection**: Injected `CAASI_PROJECT_ROOT` into process environments and refactored path resolution in simulation and lab scripts to eliminate hardcoded host paths.
5. **End-to-End Validation**:
   - `caasi build -p openmover_msgs`: Built in 11.47s.
   - `caasi build`: Compiled 9 ROS 2 packages with 6 parallel workers in 69.39s.
   - `caasi native ros pkg prefix openmover_msgs`: Resolved project install prefix directly without manual sourcing.
   - `caasi sim run experiments/sim_warehouse_bridge.yaml`: Headless Isaac Sim simulation with pioneer3dx, warehouse scene, and ROS 2 RTX LiDAR bridge (run `20261003-202114-sim-warehouse-bridge`, status `succeeded`).
   - `caasi lab run experiments/lab_smoke.yaml`: Bounded Isaac Lab RL task rollout (run `20261003-202234-lab-smoke`, 20 environment steps in 0.55s, 37 env-steps/s on `cuda:0`, status `succeeded`).
   - Complete Level 6 execution provenance captured for all runs.
6. **Safety & Repository Integrity**: Read-only source trees (`/openmover_robot` and `/openmover_ws`) remained 100% untouched. All 870 unit and smoke tests passed cleanly.

---

## 2. Canonical Project Architecture & Layout

The canonical OpenMover project was materialized under `/home/zar/Documents/phd/robot/caasi-workspace/openmover/`:

```text
caasi-workspace/openmover/
├── caasi.yaml               # Project manifest, components, layout, and tool versions
├── caasi.lock               # Resolved toolchain and dependency lockfile
├── src/                     # ROS 2 packages built by colcon via caasi build
│   ├── openmover/
│   ├── openmover_msgs/
│   ├── warehouse_simulation/
│   ├── bluesea2/
│   ├── ira_laser_tools/
│   ├── auto_mapping_toolbox/
│   └── relocalization_toolbox/
├── assets/                  # Centralized visual, collision, and simulation assets
│   ├── robots/              # URDF, meshes, and USD representations (pioneer3dx, robot_description)
│   └── scenes/              # warehouse.usda, workcell_mesh.usdc, simple_room.usda
├── lab/                     # Isaac Lab reinforcement learning workspace
│   ├── openmover_lab/       # Gym environment package (openmover_nav_env, terrains, configs)
│   ├── tasks/               # Evaluation runners (21_run_openmover_nav.py, etc.)
│   ├── campaign/            # Multi-map campaign runners (33_run_campaign.py)
│   ├── maps/                # Occupancy grids and costmaps
│   └── models/              # Policy checkpoints and models
├── sim/                     # Native Isaac Sim scripts and bridges
│   └── bridges/             # 16_bridge_ros.py, common.py, lidar_mirror.py, bridge_core.py
├── config/                  # Configuration files
│   ├── nav2/                # navigation.yaml
│   └── slam/                # mapping.yaml
├── experiments/             # Declarative experiment manifests
│   ├── sim_warehouse_bridge.yaml
│   ├── lab_smoke.yaml
│   └── lab_campaign.yaml
└── .caasi/                  # Project-local run state, caches, and provenance
```

### Manifest Configuration (`caasi.yaml`)

```yaml
schema: 1
name: openmover
version: 0.4.0
components:
  isaac_sim: true
  isaac_lab: true
  ros2: true
  nav2: true
requires:
  ros2:
    distro: jazzy
  isaac_sim:
    version: "4.5.0"
  isaac_lab:
    version: ">=2.0"
project_layout:
  src: src
  assets: assets
  lab: lab
  sim: sim
  config: config
  experiments: experiments
tested:
  - os: linux
    arch: x86_64
    ros_distro: jazzy
    isaac_sim: 4.5.0
tools:
  isaacsim:
    default: "6.0"
    versions:
      "6.0":
        path: /home/zar/isaacsim
        python: /home/zar/isaacsim/python.sh
  isaaclab:
    default: "3.0.0"
    versions:
      "3.0.0":
        path: /home/zar/isaaclab
```

---

## 3. Core caasi 0.4.0 Capabilities Implemented

### 3.1 Resource-Aware Workspace Build (`caasi build`)
- Implemented in `caasi/src/caasi/core/build.py` and `caasi/src/caasi/cli/build_cmd.py`.
- **Parallel Worker Sizing**: Evaluates system physical RAM and CPU cores to avoid out-of-memory kernel locks during parallel C++ compilation:
  - RAM < 16 GiB: min(2, CPUs)
  - 16–32 GiB: min(4, CPUs)
  - 32–48 GiB: min(6, CPUs)
  - $\ge 48$ GiB: min(8, CPUs)
  - On the host machine (46.8 GiB RAM, 20 logical cores), defaults safely to 6 parallel workers.
- **CLI Options**:
  - `-p, --packages-select`: selectively build specific packages.
  - `-u, --packages-up-to`: build dependencies up to selected packages.
  - `-j, --jobs`: explicit worker count override.
  - `--symlink-install / --no-symlink-install`: enables symlink install by default.
  - `--clean`: removes `build/`, `install/`, and `log/` prior to compiling.
  - `--cmake-args`: passes custom CMake flags.
  - `--json`: outputs machine-readable build summary.

### 3.2 Project Overlay Chaining (`caasi.core.rosenv`)
- Extended `caasi/src/caasi/core/rosenv.py` with `project_setup_file(project_root)`.
- If `<project_root>/install/setup.bash` is present, `rosenv.sourced_env()`, `rosenv.wrap()`, and `rosenv.is_sourced()` automatically chain both `/opt/ros/jazzy/setup.bash` AND `<project_root>/install/setup.bash`.
- When build completes, `rosenv.clear_cache()` invalidates memoized environment variables, making new artifacts instantly visible.

### 3.3 Dynamic Project Root Injection & Path De-Hardcoding
- Injected `CAASI_PROJECT_ROOT` in `experiment.build_command` and `runs.start_run`.
- Updated `common.py` in `sim/bridges` and `openmover_cfg.py` in `lab/openmover_lab` to dynamically resolve asset locations relative to `CAASI_PROJECT_ROOT` and the current package hierarchy rather than fixed `/home/zar/...` paths.

---

## 4. Empirical Validation & Results

### 4.1 Build Verification
- **Targeted Build**:
  - Command: `caasi build -p openmover_msgs`
  - Workers: 6
  - Output: 1 package finished in 11.2s (total 11.47s)
  - Exit code: 0
- **Full Workspace Build**:
  - Command: `caasi build`
  - Workers: 6
  - Output: 9 packages finished in 1min 9s (total 69.39s)
  - Packages compiled: `auto_mapping_toolbox`, `auto_mapping_toolbox_msgs`, `bluesea2`, `ira_laser_tools`, `openmover`, `openmover_msgs`, `relocalization_toolbox`, `relocalization_toolbox_msgs`, `warehouse_simulation`.
  - Exit code: 0

### 4.2 Overlay Discovery Verification
- Command: `caasi native ros pkg prefix openmover_msgs`
- Result: `/home/zar/Documents/phd/robot/caasi-workspace/openmover/install/openmover_msgs`
- Exit code: 0
- Confirms that commands delegated through caasi automatically locate project packages without prior `source install/setup.bash`.

### 4.3 Isaac Sim Simulation & ROS 2 Bridge Execution
- Command: `caasi sim run experiments/sim_warehouse_bridge.yaml`
- Run ID: `20261003-202114-sim-warehouse-bridge`
- Duration: 10s bounded
- App Startup: 11.0s (warm shader cache)
- Telemetry:
  - Robot settled at `x=0.000 y=-0.000 z=-0.001`
  - Advertised ROS 2 topics: `/cmd_vel` (sub), `/clock`, `/odom`, `/tf`, `/openmover/hardware/lidar_forward/scan`, `/openmover/hardware/lidar_rear/scan` (pub)
- Exit code: 0 (Status: `succeeded`)

### 4.4 Isaac Lab RL Task Execution
- Command: `caasi lab run experiments/lab_smoke.yaml`
- Run ID: `20261003-202234-lab-smoke`
- Parameters: 1 env, 20 steps, random policy, device `cuda:0`
- Telemetry:
  - Obstacle table: 1024 tiles
  - Geodesic grid: 1024 tiles $\times$ 32 $\times$ 32 cells (res 0.25m)
  - Observation space: `Box(-inf, inf, (1, 1208), float32)`
  - Action space: `Box(-inf, inf, (1, 2), float32)`
  - Performance: 20 steps in 0.55s (37 env-steps/s)
  - Dual LiDAR readings recorded (front mean 0.347m, rear mean 0.420m)
- Exit code: 0 (Status: `succeeded`)

### 4.5 Regression Testing
- Command: `pytest caasi/tests -q`
- Result: 870 passed in 184.81s (0 regressions, 11 new tests added covering `caasi build` and overlay chaining).

---

## 5. Architectural Boundary Summary

| Domain | Underlying System Tool | Caasi Role |
| :--- | :--- | :--- |
| **Workspace Build** | `colcon build`, `CMake`, `ament_cmake` | RAM-safe worker sizing, project root discovery, execution tracking, error reporting. |
| **ROS Environment** | `/opt/ros/jazzy/setup.bash`, `local_setup.bash` | Deterministic chain-sourcing of underlay and project overlay into child processes. |
| **Simulation** | NVIDIA Isaac Sim (`python.sh`), Omniverse Kit | Headless launch configuration, asset resolution, runtime monitoring, Level 6 provenance. |
| **Reinforcement Learning** | NVIDIA Isaac Lab (`isaaclab.sh`), PyTorch, Gym | Environment launch, task argument dispatch, execution auditing. |
| **Navigation & Autonomy** | Nav2, Cartographer, custom planners | Launch coordination, parameter mapping, process lifecycle management. |

---

## 6. Next Steps & Recommendations

With the canonical caasi-native OpenMover project operational, the following avenues are recommended:
1. **Interactive Multi-Process Workspaces**: Implement a declarative multi-process launcher (e.g. `caasi launch openmover.yaml`) that coordinates Isaac Sim, the ROS bridge, Nav2, and monitoring in a single command session.
2. **Containerized Build Isolation**: Option to run `caasi build` or `caasi sim` inside containerized OCI images with GPU pass-through while sharing the project directory.
3. **Workspace Packaging**: Support exporting the complete canonical project bundle with locked provenance for deployment on remote clusters or physical robots.
