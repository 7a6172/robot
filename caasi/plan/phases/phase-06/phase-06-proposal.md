# Phase 6 Proposal: Full Project Adoption & Caasi-Native Isaac/ROS Architecture

**Date**: 2026-10-03  
**Status**: Stage B Complete (Investigation & Architectural Recommendations — Pending User Review)  
**Repository Baseline**: `1512c3f`  
**Target Working Tree**: `/home/zar/Documents/phd/robot/caasi-workspace/`  
**Immutable Reference Baselines**: `/openmover_robot` and `/openmover_ws` (100% untouched)

---

## 1. Executive Summary & Design Vision

Phases 1–5 proved that `caasi`'s existing CLI commands and execution engine can manage, track, and audit an external OpenMover workspace across headless Isaac Sim, ROS 2 Nav2 closed-loop navigation, Isaac Lab RL training/evaluations, and physical hardware preflight checks.

In Phase 6, we address the larger architectural challenge:
> **Make caasi for an Isaac/ROS robotics project analogous in spirit to what `uv` provides for Python projects: one coherent project-level management layer that understands the project and removes unnecessary manual glue between ecosystem-specific tools.**

Today, an OpenMover researcher must manually navigate and maintain glue across six disconnected layers:
1. Sourcing ROS 2 Jazzy under `/opt/ros/jazzy/setup.bash` and the local overlay `install/setup.bash`.
2. Running `colcon build --symlink-install` with memory-constrained flags (`-j2` or `-j4`).
3. Switching to `~/isaacsim/python.sh` with specific environment scrubbing (`unset PYTHONPATH`, `unset CONDA_PREFIX`).
4. Invoking `cd ~/isaaclab && ./isaaclab.sh -p` for Isaac Lab tasks.
5. Managing procedural map generation, checkpoints, expert demonstration datasets, and episode logs across disparate paths.
6. Hand-crafting inter-process wiring between Isaac Sim ray-traced sensors and ROS 2 topics.

This proposal lays out the blueprint for a **canonical, caasi-native OpenMover project** and outlines candidates for **caasi 0.4.0**.

---

## 2. Current Project Inventory & Ecosystem Artifacts

An audit of the full OpenMover project establishes the following catalog of artifacts:

### 2.1 Artifact Classification

| Layer / Category | Artifact Types | Specific Code & Asset Locations | Ownership |
| :--- | :--- | :--- | :--- |
| **ROS 2 Source & Packages** | C++ (17), Python (3.12), CMakeLists.txt, package.xml | `src/openmover` (core product nodes, HAL, A* & pursuit)<br>`src/openmover_msgs` (custom interfaces)<br>`src/warehouse_simulation` (Pioneer 3DX, Nav2, actors)<br>`src/bluesea2` (dual LiDAR driver)<br>`src/ira_laser_tools` (scan merger)<br>`src/auto_mapping_toolbox`, `src/relocalization_toolbox` | **ROS 2 / colcon** (built via `ament_cmake`) |
| **Robotics Config & Launch** | YAML, Python Launch | `src/openmover/launch/` (`bootloader.launch.py`, `bringup.launch.py`)<br>`src/warehouse_simulation/launch/` (`warehouse_simulation.launch.py`, `stack_b.launch.py`)<br>`src/warehouse_simulation/config/nav2_params.yaml`, `slam_toolbox.yaml` | **ROS 2 Launch / Nav2** |
| **Simulation Assets & Scenes** | URDF, Xacro, USDA, USDC, USD | `src/openmover/urdf/robot_description.urdf`<br>`src/warehouse_simulation/urdf/pioneer3dx.urdf.xacro`<br>`isaac/scenes/warehouse.usda`, `workcell_mesh.usdc`, `simple_room.usda`<br>`isaac/assets/openmover_lab/robot_description/` | **USD / Isaac Sim** |
| **Isaac Sim Bridge Scripts** | Python | `isaac/scripts/16_bridge_ros.py` (Stack B: Nav2 bridge)<br>`isaac/scripts/17_bridge_openmover.py` (Stack A: OpenMover bridge)<br>`isaac/scripts/common.py` (RAM guard, process check) | **Isaac Sim (`python.sh`)** |
| **Isaac Lab RL Environments** | Python Gym, PyTorch | `isaac/lab/openmover_lab/openmover_nav_env.py` (DirectRLEnv)<br>`isaac/lab/openmover_lab/openmover_cfg.py`, `openmover_terrains.py`<br>`isaac/lab/21_run_openmover_nav.py` .. `34_aggregate_campaign.py` | **Isaac Lab (`isaaclab.sh -p`)** |
| **Procedural Maps & Assets** | JSON, PNG, SVG | `isaac/lab/maps/gen/` (56 procedural mazes + `_manifest.json`) | **Project Asset Data** |
| **Model Checkpoints & Demos** | PyTorch (`.pt`) | `isaac/lab/logs/rsl_rl/openmover_nav/bc_init_v3/model_0.pt`<br>`isaac/lab/logs/bc_demos/demos_p100_v3.pt` | **Model Artifacts (Git LFS / Storage)** |
| **Dependencies & System Tools** | Bash scripts, C++ vendor | `tools/install_deps.sh`, `tools/setup.sh`<br>`tools/osqp_build` (vendored OSQP C solver) | **System / CMake / apt** |

---

## 3. Current caasi Coverage vs. Project Requirements

| Requirement | Existing caasi Capability | Coverage Status | Evidence & Limitations |
| :--- | :--- | :---: | :--- |
| **Project Manifest & Metadata** | `caasi project init / validate` | **Partially Sufficient** | `caasi.yaml` declares components (`robot`, `ros2`, `isaac_sim`, `isaac_lab`, `nav2`) and version requirements. Missing: declarative package listings, build settings, and workspace overlay specifications. |
| **Environment Preflight & Locking** | `caasi env inspect`, `caasi check`, `caasi.lock` | **Sufficient** | Accurately validates ROS 2 Jazzy, Isaac Sim 6.0, Isaac Lab 3.0, CPU, RAM, and hardware GPU driver. |
| **ROS 2 Build Orchestration** | N/A (Manual `colcon build`) | **Missing** | No `caasi build` command. User must manually source ROS 2, configure compiler flags (`-j2`), and execute `colcon build`. |
| **Simulation Execution** | `caasi sim run <exp.yaml>` | **Sufficient** | Successfully executes headless Isaac Sim with `python.sh`, isolates logs, and captures Layer 6 provenance bundles. |
| **Isaac Lab Task Execution** | `caasi lab run / play / evaluate` | **Partially Sufficient** | Supports `isaaclab.sh -p <script>`, but launcher lacks flexibility for Python scripts requiring clean env separation without `-p` dispatcher. |
| **ROS 2 Launch Execution** | `caasi ros launch <file>` | **Sufficient** | Launches tracked ROS 2 graphs, connects over DDS, monitors active topics/services, and provides clean stop. |
| **Run Lineage & Recovery** | `caasi run start / stop / restart / inspect` | **Sufficient** | Robust process-group termination (`os.killpg`), restart lineage tracking (`restarted_from`), and artifact inventory. |
| **Sensor & Hardware Inspection** | `caasi sensor list / inspect` | **Sufficient** | Discovers V4L2 cameras, serial ports, and SDK availability without importing heavy vendor modules. |

---

## 4. Problems Discovered in the Current OpenMover Project

Our investigation identified four major friction areas in the existing codebase:

### Problem 1: Hard-Coded Absolute Paths
Many scripts embed user-specific absolute paths.
- **Example in `isaac/lab/openmover_lab/openmover_cfg.py`**:
  ```python
  OPENMOVER_USD = "/home/zar/Documents/phd/robot/openmover_ws/isaac/assets/openmover_lab/robot_description/robot_description.usda"
  ```
- **Example in `isaac/lab/21_run_openmover_nav.py`**:
  ```python
  cd ~/isaaclab && ./isaaclab.sh -p /home/zar/Documents/phd/robot/openmover_ws/isaac/lab/21_run_openmover_nav.py
  ```
- **Consequence**: The codebase cannot be relocated, run on another workstation, or run in a branched workspace without breaking USD stage loading.

### Problem 2: Fragile Relative CWD Assumptions
Scripts assume specific execution directories:
- `33_run_campaign.py` assumes subprocess cwd is `~/isaaclab`, requiring arguments like `--out` to be forced to absolute paths to prevent outputs from being scattered into the Isaac Lab home directory.
- `func_mode_server_handler.py` assumes flat installed layout and hard-codes paths to `~/openmover_robot/maps/`.

### Problem 3: Disconnected Build and Overlay Management
- To build the C++ nodes (`motor_handler`, `navigation_handler`, `mover`), developers must know to run `bash tools/setup.sh` or remember `colcon build --symlink-install --parallel-workers 2`.
- When running `caasi ros launch`, if the user has not manually sourced `install/setup.bash` in the launching shell, the launch fails because `caasi` only auto-sources `/opt/ros/jazzy/setup.bash`, unaware of local workspace overlays.

### Problem 4: Fragmented Component Taxonomy
In `openmover_ws`, files are split somewhat arbitrarily between `src/` (ROS 2), `isaac/` (simulation scripts & assets), `isaac/lab/` (RL tasks), and `tools/` (dependencies). A unified project model should clarify the relationships between robots, scenes, navigation tasks, and experiments.

---

## 5. Proposed Caasi-Native Architecture

We propose organizing the canonical OpenMover project under `/home/zar/Documents/phd/robot/caasi-workspace/openmover/` with the following clean, modular structure:

```text
caasi-workspace/openmover/
├── caasi.yaml                      # Canonical project manifest & tool configuration
├── caasi.lock                      # Resolved environment & component lockfile
│
├── packages/                       # [ROS 2 / C++ / Python packages]
│   ├── openmover/                  # Core product package (HAL, controllers, nodes)
│   ├── openmover_msgs/             # Custom message & service definitions
│   ├── warehouse_simulation/       # Reference simulation & Nav2 bringup
│   ├── bluesea2/                   # Dual LiDAR hardware drivers
│   ├── ira_laser_tools/            # Multi-scan merger
│   ├── auto_mapping_toolbox/       # Frontier exploration
│   └── relocalization_toolbox/     # 2D global relocalization
│
├── robots/                         # [Robot definitions & asset models]
│   ├── openmover/
│   │   ├── robot.yaml              # Caasi robot definition (kind: robot, sensors, drives)
│   │   ├── urdf/robot_description.urdf
│   │   ├── meshes/                 # Visual and collision STL/DAE
│   │   └── usd/robot_description.usda  # Converted Isaac USD articulation
│   └── pioneer3dx/
│       ├── robot.yaml
│       ├── urdf/pioneer3dx.urdf.xacro
│       └── usd/pioneer3dx.usda
│
├── scenes/                         # [Simulation environments & USD worlds]
│   ├── warehouse/
│   │   ├── scene.yaml              # Caasi scene definition
│   │   ├── warehouse.usda          # Isaac Sim USD scene
│   │   └── meshes/workcell_mesh.usdc
│   └── simple_room/
│       ├── scene.yaml
│       └── simple_room.usda
│
├── lab/                            # [Isaac Lab learning & evaluation]
│   ├── environments/               # Gym DirectRLEnv definitions (openmover_nav_env.py)
│   ├── tasks/                      # Rollout & runner scripts (21_run_openmover_nav.py)
│   ├── campaign/                   # Campaign runners (33_run_campaign.py, 34_aggregate.py)
│   ├── maps/                       # Procedural maze JSONs & generator scripts
│   └── policies/                   # Checkpoints & expert demo datasets (model_0.pt)
│
├── experiments/                    # [Declarative experiment manifests]
│   ├── sim_warehouse_bridge.yaml   # Isaac Sim + ROS bridge run
│   ├── nav2_closed_loop.yaml       # Nav2 navigation stack run
│   ├── lab_smoke.yaml              # Gym environment rollout run
│   └── campaign_bounded.yaml       # Multi-arm evaluation campaign run
│
├── config/                         # [Shared navigation & system parameters]
│   ├── nav2_params.yaml
│   ├── slam_toolbox.yaml
│   └── hardwares.yaml
│
└── .caasi/                         # [Caasi internal state, local cache, run index]
```

### Why this structure is appropriate:
1. **Separation of Concerns**: ROS packages remain standard ROS packages inside `packages/` (fully buildable with `colcon`).
2. **Explicit Robot/Scene Assets**: Moves robot descriptions and USD meshes into dedicated `robots/` and `scenes/` directories, matching `caasi`'s Layer 2 taxonomy.
3. **Relocatable Path Anchors**: Replaces all hardcoded `/home/zar/...` paths with workspace-relative resolutions anchored to project root.
4. **Clean Experiment Separation**: Experiments in `experiments/` define what to run; execution artifacts are isolated in `~/.caasi/runs/`.

---

## 6. Proposed Code Changes in OpenMover

To achieve a clean, relocatable, and caasi-native project, the following specific adaptations are proposed:

1. **Replace Hard-Coded Path Strings with Environment/Manifest Anchors**:
   - `openmover_cfg.py`: Change `OPENMOVER_USD = "/home/zar/..."` to resolve relative to `PROJECT_ROOT / "robots/openmover/usd/robot_description.usda"`, or via an environment variable `CAASI_PROJECT_ROOT`.
   - `16_bridge_ros.py` / `17_bridge_openmover.py`: Change asset and scene loading to use `PROJECT_ROOT / "scenes/warehouse/warehouse.usda"`.
2. **Clean CWD Independence in Task Scripts**:
   - Update `33_run_campaign.py` and `21_run_openmover_nav.py` so paths to maps (`lab/maps/gen/`), checkpoints (`lab/policies/`), and results are derived from the script's project anchor rather than `os.getcwd()`.
3. **Consolidate Simulation Bridges**:
   - Align bridge arguments with declarative `experiments/*.yaml` configs, eliminating redundant shell wrappers.

---

## 7. What Should NOT Be Changed (Ecosystem Ownership Boundaries)

In strict accordance with our architectural principles, `caasi` will **NOT** replace or duplicate:
1. **ROS 2 & colcon**: `caasi` will not replace `colcon` or `ament_cmake`. `packages/` will remain standard ROS 2 packages with standard `CMakeLists.txt` and `package.xml`.
2. **Nav2 & Behavior Trees**: Nav2 algorithms, costmaps, and XML behavior trees remain 100% owned by Nav2.
3. **Isaac Sim / Isaac Lab Core**: USD physics simulation, PhysX schemas, and Gym interfaces remain standard Isaac Sim/Lab components.
4. **PyTorch & CUDA**: Tensor computation, GPU memory management, and neural network inference remain owned by PyTorch.
5. **Git / OS Networking**: Version control and network interface configuration (IP addresses, subnets) remain OS/Git responsibilities.

---

## 8. Caasi 0.4.0 Capability Candidates

Based on actual migration friction, we have identified several high-value candidates for `caasi 0.4.0`. We categorize them strictly by necessity:

### Category 1: Essential for Project Adoption

#### Candidate A: `caasi build` (Workspace Build Orchestrator)
- **Problem**: Building ROS 2 packages currently requires dropping out of `caasi`, remembering to source `/opt/ros/jazzy/setup.bash`, manually passing memory flags (`colcon build --symlink-install --parallel-workers 2`), and managing OSQP vendor includes.
- **Proposed caasi solution**: `caasi build [package]`
  - Detects `packages/` in project root.
  - Automatically derives safe concurrency (`-j`) from available system RAM (e.g. 2 workers if RAM < 32 GB, preventing system freezes).
  - Invokes `colcon build --symlink-install` with sourced ROS 2 environment.
  - Registers the build overlay path (`install/setup.bash`) in `.caasi/overlay.json`.
- **Value**: Provides the "one command build" analogous to `cargo build` or `uv build` without replacing `colcon`.

#### Candidate B: Automatic Project Overlay Sourcing
- **Problem**: When `caasi ros launch` or `caasi ros list` runs, `caasi.core.rosenv` only auto-sources `/opt/ros/<distro>/setup.bash`. It does not know about the project's local `install/setup.bash`, so local packages cannot be found unless sourced manually in the parent terminal.
- **Proposed caasi solution**: Teach `rosenv.py` to inspect the project root for `install/setup.bash` and chain-source it after the base ROS distro.
- **Value**: Eliminates the most common user friction in ROS development: forgetting to source the local workspace overlay.

#### Candidate C: `CAASI_PROJECT_ROOT` Environment Injection
- **Problem**: Python scripts and USD stage loaders need to locate project assets without hardcoding absolute paths.
- **Proposed caasi solution**: When `caasi run start`, `caasi sim run`, or `caasi lab run` launches any experiment, automatically inject `CAASI_PROJECT_ROOT=<path>` into the process environment.
- **Value**: Standardizes relocatable asset loading across all project scripts.

---

### Category 2: Strongly Useful Improvements

#### Candidate D: Declarative Workspace Overlays in `caasi.yaml`
- **Proposal**: Allow `caasi.yaml` to declare project workspace subdirectories:
  ```yaml
  workspace:
    packages: packages/
    install_dir: install/
    build_dir: build/
  ```
- **Value**: Explicitly informs `caasi check`, `caasi doctor`, and `caasi build` where project packages reside.

#### Candidate E: `caasi run diff <run1> <run2>`
- **Proposal**: A CLI diff tool that compares two run directories, highlighting differences in Git commit, launch arguments, hardware RAM at launch, and dependency versions.
- **Value**: Substantially aids empirical reproducibility and regression tracking.

---

### Category 3: Future / Not Yet Justified (Defer)
- **Custom USD Asset Packaging**: Defer; standard relative USD file references are sufficient.
- **Custom ROS Package Generator (`caasi pkg new`)**: Defer; `ros2 pkg create` already handles this well.
- **Remote Cloud Sync in Phase 6**: Defer to Phase 7.

---

## 9. Migration Roadmap (Post-Approval Stages)

Once this proposal is discussed and approved, the implementation will proceed through these staged steps:

1. **Stage 1 (Scaffold)**: Create canonical structure `/home/zar/Documents/phd/robot/caasi-workspace/openmover/` with updated `caasi.yaml`.
2. **Stage 2 (Packages & Build)**: Copy ROS packages into `packages/`, verify build via `caasi build` (or colcon integration), test local overlay auto-sourcing.
3. **Stage 3 (Assets & Robots)**: Migrate robot URDFs, meshes, and USD files into `robots/openmover/` and `robots/pioneer3dx/`; verify relative paths.
4. **Stage 4 (Scenes & Sim)**: Migrate warehouse scene and meshes into `scenes/warehouse/`; test `caasi sim run` headless simulation.
5. **Stage 5 (Lab & Tasks)**: Migrate Isaac Lab Gym environments and campaign runners into `lab/`; verify point-goal navigation rollout.
6. **Stage 6 (Full Verification)**: Run full end-to-end verification (build $\rightarrow$ sim bridge $\rightarrow$ Nav2 closed loop $\rightarrow$ RL eval $\rightarrow$ provenance audit).
7. **Stage 7 (Documentation & 0.4.0 Finalization)**: Author Phase 6 report, case studies, and finalize the `0.4.0` design specification.

---

## 10. Discussion Points for User Review

Before proceeding with implementation, please review the following key decisions:
1. **Project Directory Location**: Do you approve establishing `/home/zar/Documents/phd/robot/caasi-workspace/openmover/` as the canonical caasi-native project?
2. **Component Directory Structure**: Does the layout (`packages/`, `robots/`, `scenes/`, `lab/`, `experiments/`, `config/`) meet your expectations for a clean, uv-inspired robotics project?
3. **Scope for caasi Modifications**: Do you approve implementing **Candidate A (`caasi build`)**, **Candidate B (Auto-sourcing local overlay)**, and **Candidate C (`CAASI_PROJECT_ROOT` injection)** as part of Phase 6 / caasi 0.4.0?
