# Phase 6 Report: Full Project Adoption & Caasi-Native Isaac/ROS Workspace

**Date**: 2026-10-03  
**Status**: Completed & Dogfood-Validated  
**Repository Baseline**: `1512c3f`  
**Phase 6 Checkpoint**: `8711aa3`  
**Phase 6 Canonical Workspace**: `/home/zar/Documents/phd/robot/caasi-workspace/openmover/`  
**Read-Only Trees Preserved**: `/openmover_robot` and `/openmover_ws` (100% untouched)  
**Test Suite**: 870 passed (177.05s)

---

## 1. Executive Summary

Phase 6 transitioned `caasi` from an external orchestrator into a **unified project-level management and control layer**. Analogous in spirit to what `uv` provides for Python projects, `caasi` now provides a single cohesive interface that understands the structure, lifecycle, and toolchains of an integrated Isaac Sim + Isaac Lab + ROS 2 robotics project without replacing or duplicating underlying ecosystem tools (colcon, CMake, ROS 2, Isaac Sim, Isaac Lab, Nav2, PyTorch, CUDA, USD).

### Key Outcomes
1. **Canonical Caasi-Native OpenMover Project Established**: Created `/home/zar/Documents/phd/robot/caasi-workspace/openmover` hosting the complete robotics project (ROS 2 packages, assets, simulation bridges, Isaac Lab Gym tasks, configurations, declarative experiments, and lockfiles).
2. **Resource-Aware Workspace Build (`caasi build`)**: Implemented a continuous RAM-budgeted build orchestrator wrapping `colcon build --symlink-install`. Rather than arbitrary fixed caps, it derives parallelism dynamically from physical RAM ($\text{RAM\_PER\_WORKER} = 6.0\text{ GiB}$, $\text{SYSTEM\_RESERVED} = 2.0\text{ GiB}$), yielding 7 parallel workers on 46.8 GiB RAM and 20 cores.
3. **Automatic Project ROS Overlay Chaining**: Extended `caasi.core.rosenv` to detect `<project_root>/install/setup.bash` and chain-source it after the base ROS 2 underlay (`/opt/ros/jazzy/setup.bash`). Commands executed through caasi immediately recognize project-built packages without manual shell sourcing.
4. **Project Root Injection**: Injected `CAASI_PROJECT_ROOT` into process environments and refactored path resolution in simulation and lab scripts to eliminate hardcoded machine paths.
5. **Rigorous Dogfooding from Fresh Environment**: Validated the complete workflow from a clean, stripped subshell (`env -i` without pre-sourced ROS paths), demonstrating that project inspection, full clean builds, package discovery, live Isaac Sim simulation, and Isaac Lab execution work cleanly without manual environment glue.

---

## 2. Canonical Project Architecture & Layout

The canonical OpenMover project is materialized at `/home/zar/Documents/phd/robot/caasi-workspace/openmover/`:

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
│   ├── tasks/               # Evaluation runners (21_run_openmover_nav.py, 33_run_campaign.py)
│   ├── campaign/            # Campaign artifacts
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
    version: jazzy
  isaac_sim:
    version: ">=5.0"
  isaac_lab:
    version: ">=2.0"
  nav2: {}
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
- **Resource Policy Model**:
  In complex C++ robotics packages (e.g. Nav2 costmaps, PCL filters, Cartographer, custom message generators), compiler memory consumption frequently spikes to 4–6 GiB per compilation unit under heavy template metaprogramming. Unconstrained compilation (`colcon build` without flags) launches as many workers as CPU cores (e.g. 20), quickly triggering kernel swap thrashing or OOM freezes on workstations with $\le 64\text{ GiB}$ RAM.
- **Continuous RAM-Budget Formula**:
  $$\text{usable\_ram} = \max(0.0, \text{ram\_gb} - \text{SYSTEM\_RESERVED\_RAM\_GB})$$
  $$\text{ram\_workers} = \max\left(1, \left\lfloor \frac{\text{usable\_ram}}{\text{RAM\_PER\_WORKER\_GB}} \right\rfloor\right)$$
  $$\text{workers} = \max(1, \min(\text{cpus}, \text{ram\_workers}))$$
  With parameters:
  - $\text{SYSTEM\_RESERVED\_RAM\_GB} = 2.0\text{ GiB}$ (host OS and background services)
  - $\text{RAM\_PER\_WORKER\_GB} = 6.0\text{ GiB}$ (peak compiler process memory budget)
- **Host Evaluation**:
  On the host workstation ($46.8\text{ GiB}$ RAM, $20\text{ logical cores}$):
  $$\text{usable\_ram} = 46.8 - 2.0 = 44.8\text{ GiB}$$
  $$\text{workers} = \min(20, \lfloor 44.8 / 6.0 \rfloor) = 7\text{ parallel workers}$$
- **CLI Options**:
  - `-p, --packages-select`: selectively build specific packages.
  - `-u, --packages-up-to`: build dependencies up to selected packages.
  - `-j, --jobs`: explicit worker count override.
  - `--symlink-install`: enabled by default.
  - `--clean`: removes `build/`, `install/`, and `log/` prior to compiling.
  - `--cmake-args`: passes custom CMake flags.
  - `--json`: outputs machine-readable build summary.

### 3.2 Project Overlay Chaining (`caasi.core.rosenv`)
- Extended `caasi/src/caasi/core/rosenv.py` with `project_setup_file(project_root)`.
- If `<project_root>/install/setup.bash` is present, `rosenv.sourced_env()`, `rosenv.wrap()`, and `rosenv.is_sourced()` automatically chain both `/opt/ros/jazzy/setup.bash` AND `<project_root>/install/setup.bash`.
- When build completes, `rosenv.clear_cache()` invalidates memoized environment variables, making new artifacts instantly visible.

### 3.3 Dynamic Project Root Injection & Path Resolution
- Injected `CAASI_PROJECT_ROOT` in `experiment.build_command` and `runs.start_run`.
- Updated `common.py` in `sim/bridges` and `openmover_cfg.py` in `lab/openmover_lab` to dynamically resolve asset locations relative to `CAASI_PROJECT_ROOT` and the package directory hierarchy rather than fixed `/home/zar/...` paths.

---

## 4. Empirical Dogfooding Validation

We executed a comprehensive validation pass strictly from fresh, unsourced subshells (`env -i HOME="$HOME" USER="$USER" PATH="/usr/local/bin:/usr/bin:/bin"`):

### 4.1 Project Preflight (`caasi check project`)
- Executed from unsourced subshell.
- Detected: `fingerprint: COMPATIBLE`, `isaac_lab: 3.0.0 (COMPATIBLE)`, `isaac_sim: 6.0 (COMPATIBLE)`, `ros2: jazzy (COMPATIBLE)`.
- Verified lockfile `caasi.lock` contains 7 resolved versions.

### 4.2 Clean Build from Fresh Shell (`caasi build --clean`)
- Command: `env -i ... caasi build --clean`
- Dynamic worker sizing: 7 parallel workers ($46.8\text{ GiB RAM}$).
- Result: Cleaned `build/`, `install/`, `log/`, and compiled all 9 packages from scratch in 73.56s.
- Exit code: 0.

### 4.3 Overlay Resolution in Fresh Shell
- Command: `env -i ... caasi native ros interface show openmover_msgs/msg/Obstacle`
- Result: Cleanly resolved message definition directly from `<project>/install/openmover_msgs` without manual sourcing.
- Command: `env -i ... caasi ros status`
- Result: Detected ROS 2 Jazzy and active topics.

### 4.4 Isaac Sim Simulation & ROS 2 Bridge Execution
- Command: `caasi sim run experiments/sim_warehouse_bridge.yaml --name dogfood-sim-bridge`
- Run ID: `20261003-230005-dogfood-sim-bridge`
- Duration: 90.0s bounded run.
- Telemetry:
  - App startup: 6.5s (warm shader cache).
  - Isaac Sim loaded pioneer3dx articulation and warehouse workcell mesh.
  - Stepped 5,401 physics iterations ($dt = 0.0167\text{ s}$).
  - Published 2,700 scan frames at 30 Hz ($TICK = 0.067\text{ s}$) from dual RTX LiDARs.
  - ROS 2 topics active: `/clock`, `/cmd_vel`, `/odom`, `/openmover/hardware/lidar_forward/scan`, `/openmover/hardware/lidar_rear/scan`, `/tf`, `/tf_static`.
- Exit code: 0 (Status: `succeeded`).
- Provenance: 11 artifacts captured in `~/.caasi/runs/20261003-230005-dogfood-sim-bridge/`.

### 4.5 Isaac Lab Campaign Workflow
- Command: `caasi run start experiments/lab_campaign.yaml`
- Run ID: `20261003-231610-lab-campaign`
- Result: Resolved and planned the full 56-map evaluation campaign across 3 arms (`shield`, `astar_dwa`, `astar_dwa_shield`) with an estimated wall clock of 4.38h.
- Exit code: 0 (Status: `succeeded`).

### 4.6 Regression Testing
- Command: `pytest caasi/tests -q`
- Result: **870 passed** in 177.05s (0 regressions).

---

## 5. Structured Assessment

### 5.1 Observed Facts
1. The entire OpenMover project now lives inside `caasi-workspace/openmover` with no dependencies on external workspace modifications.
2. In a stripped subshell with zero ROS environment variables, `caasi build`, `caasi native ros`, and `caasi sim run` locate, build, and link both the ROS underlay and project overlay automatically.
3. The build parallelism calculation dynamically scales with available RAM: on our machine, $(46.8 - 2.0) / 6.0 = 7$ workers, completing a 9-package clean build in 73.56s without memory thrashing.
4. Isaac Sim and Isaac Lab execute headlessly, load project-relative assets, interact over ROS 2 topics, and exit cleanly with status `succeeded` and Level 6 provenance.

### 5.2 Observed Friction
1. **Interactive Publisher Blocking**: Running `ros2 topic pub --once` from within subshells or background tasks can hang indefinitely if subscriber QoS durability/reliability doesn't acknowledge within a standard CLI timeout.
2. **Script Argument Propagation**: In Isaac Sim Python launcher scripts, `SimulationApp` parses command-line flags on import, requiring domain scripts to use `parse_known_args()` prior to Omniverse initialization to safely capture custom arguments like `--duration`.

### 5.3 Direct Benefits
1. **Zero Manual Sourcing**: Developers no longer need to remember to run `source /opt/ros/jazzy/setup.bash` or `source install/setup.bash` before interacting with the project.
2. **Single Build Orchestrator**: `caasi build` eliminates manual colcon argument assembly, provides RAM safety, and invalidates internal caches automatically.
3. **Reproducible Toolchain Locking**: `caasi.lock` captures exact versions of ROS, Isaac Sim, Isaac Lab, GCC, CMake, and Python for auditability.
4. **Decoupled Architecture**: Established ecosystem tools remain the execution engines; `caasi` strictly manages orchestration, environment chaining, and provenance.

### 5.4 Limitations
1. **Single-Node Execution per Command**: Running simultaneous multi-subsystem workflows (e.g. Isaac Sim + Nav2 + RViz) currently requires launching separate `caasi` commands or using external ROS 2 launch files.
2. **Local Workstation Scope**: The canonical project currently targets local host environments; cross-platform deployment across heterogenous machines relies on identical system packages or container isolation.

### 5.5 Remaining Gaps
1. **Coordinated Multi-Process Lifecycle**: While individual processes are tracked as runs, shutting down an entire multi-process stack (e.g. simulator + navigation + controllers) requires stopping multiple run IDs or relying on SIGINT propagation from launch files.
2. **Declarative Stack Orchestration**: Experiment YAMLs currently declare single-process runs (`backend: sim`, `backend: lab`, `backend: ros`), rather than composite stacks.

### 5.6 Future Feature Ideas (For Later Phases)
1. **Multi-Process Stack Orchestrator (`caasi launch`)**: A unified manifest format to declare and supervise composite stacks (e.g. simulation bridge + Nav2 + SLAM).
2. **Container Pass-Through**: Running `caasi build` or `caasi sim` inside official NVIDIA / ROS Docker containers while binding the local canonical workspace.
3. **Workspace Deployment Bundling**: Exporting self-contained bundles with frozen environments for deployment to robot compute hardware.
