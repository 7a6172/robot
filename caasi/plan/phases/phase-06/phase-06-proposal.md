# Phase 6 Proposal (Revised): Full Project Adoption & Caasi-Native Isaac/ROS Architecture

**Date**: 2026-10-03  
**Status**: Stage B Complete (Comprehensive Architectural Blueprint — Awaiting User Review)  
**Repository Baseline**: `efd2a1b`  
**Target Working Tree**: `/home/zar/Documents/phd/robot/caasi-workspace/`  
**Immutable Reference Baselines**: `/openmover_robot` and `/openmover_ws` (100% untouched)

---

## 1. Executive Summary & Design Vision

Phases 1–5 proved that `caasi`'s existing execution engine, Layer 6 provenance tracking, process management, and diagnostic tools can orchestrate, track, and audit an external robotics codebase.

In Phase 6, we address the foundational objective:
> **Make caasi for an Isaac/ROS robotics project analogous in spirit to what `uv` provides for Python projects: one coherent project-level management layer that understands the project and removes unnecessary manual glue between ecosystem-specific tools.**

We do **not** want `caasi` to replace established tools like ROS 2, `colcon`, CMake, Nav2, Isaac Sim, Isaac Lab, PyTorch, USD, or Git. Those tools own domain execution and algorithms.

Instead, `caasi` must become the **declarative contract and orchestrator** that knows how those pieces fit together. As a developer, you interact with `caasi`, and `caasi` coordinates the underlying tools deterministically.

---

## 2. Answers to the Core Architectural Questions

### Question 1: What should the ideal caasi-managed Isaac/ROS project actually look like?

An ideal caasi project is a self-contained, relocatable directory with an explicit contract defined in `caasi.yaml`. It replaces implicit developer memory (which scripts to source, what paths to set, what flags to pass) with declarative, deterministic project metadata.

```text
caasi-workspace/openmover/
├── caasi.yaml                      # The Unified Project Manifest
├── caasi.lock                      # Resolved environment & toolchain lockfile
│
├── src/                            # ROS 2 Colcon Workspace
│   ├── openmover/                  # Core robot stack (HAL, controllers, motion nodes)
│   ├── openmover_msgs/             # ROS 2 interface definitions
│   ├── warehouse_simulation/       # Simulation stack, actors, Nav2 bringup
│   ├── bluesea2/                   # Dual LiDAR drivers
│   ├── ira_laser_tools/            # Scan merger
│   ├── auto_mapping_toolbox/       # Frontier exploration
│   └── relocalization_toolbox/     # 2D global relocalization
│
├── assets/                         # Canonical Multi-Ecosystem Asset Tree
│   ├── robots/                     # Robot kinematic descriptions & geometries
│   │   ├── openmover/
│   │   │   ├── robot.yaml          # Robot definition (dof, sensors, joints, frames)
│   │   │   ├── urdf/               # Canonical URDF/Xacro
│   │   │   ├── meshes/             # Visual and collision STL/DAE
│   │   │   └── usd/                # Converted Isaac USD articulation
│   │   └── pioneer3dx/
│   │       ├── robot.yaml
│   │       ├── urdf/
│   │       └── usd/
│   └── scenes/                     # Simulation USD Stages and Worlds
│       ├── warehouse/
│       │   ├── scene.yaml          # Scene metadata (spawn points, bounds, lighting)
│       │   ├── warehouse.usda      # Isaac Sim USD stage
│       │   └── meshes/             # High-poly workcell collision meshes
│       └── simple_room/
│           ├── scene.yaml
│           └── simple_room.usda
│
├── lab/                            # Isaac Lab Learning & Evaluation Subsystem
│   ├── openmover_lab/              # Python Gym package (DirectRLEnv, observation configs)
│   ├── tasks/                      # Rollout & evaluation runners (21_run_openmover_nav.py)
│   ├── campaign/                   # Multi-arm campaign runner & aggregator (33, 34)
│   ├── maps/                       # Procedural maze JSONs & generators
│   └── models/                     # Checkpoints & expert demo datasets (model_0.pt)
│
├── sim/                            # Isaac Sim Native Simulation Subsystem
│   ├── bridges/                    # Headless bridges (16_bridge_ros.py, 17_bridge_openmover.py)
│   ├── extensions/                 # Custom Omniverse Kit extensions
│   └── configs/                    # Simulation rendering/physics configs
│
├── config/                         # Unified Project Configuration
│   ├── nav2/                       # Nav2 MPPI/DWB parameters & costmaps
│   ├── slam/                       # SLAM Toolbox online async parameters
│   └── hardware/                   # Physical robot motor/IO YAML configs
│
├── experiments/                    # Declarative Experiment Manifests
│   ├── warehouse_nav2_sim.yaml     # Isaac Sim + Nav2 closed-loop run
│   ├── lab_smoke.yaml              # Isaac Lab Gym smoke rollout
│   └── campaign_bounded.yaml       # Multi-arm evaluation campaign run
│
└── .caasi/                         # Caasi local state, overlay cache, and run index
```

---

### Question 2: What should caasi know about the project, and what should remain the responsibility of ROS/colcon/CMake/Isaac/etc.?

| Responsibility Domain | What `caasi` Knows & Manages | What Underlying Tools Own & Execute |
| :--- | :--- | :--- |
| **Workspace Build** | `caasi` knows where packages reside (`src/`), derives RAM-safe parallel workers (`-j2` on $\le 16$ GB; `-j4` on 32 GB; `-j8` on 48 GB+), sources base ROS 2, and records the resulting local overlay path in `.caasi/overlay.json`. | **`colcon` / CMake / `ament_cmake`** parse `CMakeLists.txt` and `package.xml`, compile C++ binaries, generate ROS message headers, and install libraries to `install/`. |
| **ROS 2 Middleware** | `caasi` knows which ROS distro is required (`jazzy`), chains `/opt/ros/jazzy/setup.bash` with the project's `install/setup.bash`, tracks background launch processes, and monitors graph health. | **ROS 2 / DDS** handles node discovery, pub/sub communication, intra-process zero-copy transport, and service execution. |
| **Simulation** | `caasi` knows the resolved Isaac Sim installation path (`~/isaacsim`), injects `CAASI_PROJECT_ROOT`, manages headless/windowed flags, isolates stdout/stderr logs, and terminates the Kit process group cleanly without orphaned processes. | **Isaac Sim / Omniverse Kit** handles PhysX physics simulation, RTX ray-traced LiDAR rendering, and USD stage composition. |
| **Isaac Lab Learning** | `caasi` knows which scripts are Gym tasks, launches them with the appropriate Python interpreter or `isaaclab.sh -p` wrapper, and tracks training runs as first-class experiments. | **Isaac Lab / PyTorch / Gymnasium** handles tensor stepping, policy optimization, CUDA memory allocation, and observation buffers. |
| **Navigation & Autonomy**| `caasi` manages the launch parameters and lifecycle of the navigation stack. | **Nav2** executes path planning (NavFn/Smac), trajectory control (MPPI/DWB), costmap inflation, and recovery behaviors. |
| **Assets & Paths** | `caasi` provides the root anchor (`CAASI_PROJECT_ROOT`) and resolves relative asset paths across robots, scenes, and meshes. | **USD / URDF** handles kinematic tree hierarchies, collision bounding boxes, and material shading. |
| **Provenance & Runs** | `caasi` records exact Git commits, hardware snapshots, launch commands, environment variables, exit codes, and restart lineage in immutable run bundles. | **Operating System / File System** stores run artifacts. |

---

### Question 3: What is the best project layout and why?

The layout shown in Question 1 is chosen for five concrete reasons:
1. **Colcon Compatibility**: Keeping ROS packages under `src/` preserves standard `colcon build` conventions. Any standard ROS tool or CI system can build the workspace without custom flags.
2. **Explicit Layer 2 Asset Structure**: Splitting assets into `assets/robots/` and `assets/scenes/` directly mirrors `caasi`'s Layer 2 taxonomy (`kind: robot`, `kind: scene`), providing metadata-inspectable assets without launching a simulator.
3. **Dedicated Subsystem Directories (`sim/` and `lab/`)**: Isolating Isaac Sim bridge scripts from Isaac Lab RL Gym environments avoids mixing Omniverse Kit scripts with RSL-RL training code.
4. **Relocatable Root Anchoring**: Eliminates all hardcoded user paths (`/home/zar/...`) by establishing a predictable relative structure.
5. **No Clutter in Root**: Cleanly separates source code (`src/`), learning code (`lab/`), declarative configs (`config/`, `experiments/`), and generated outputs (`.caasi/`, `~/.caasi/runs/`).

---

### Question 4: How should caasi discover/adopt an existing raw project in the future?

For an arbitrary, existing robotics repository, `caasi discover` (or `caasi project adopt`) should follow this deterministic four-stage pipeline:

```text
Existing Raw Repo
        ↓
[1. Filesystem & Metadata Scan]
  • Find package.xml / CMakeLists.txt → Detect ROS 1/2 packages & distros
  • Find .usda / .usdc / .urdf / .xacro → Detect robots, meshes, and scenes
  • Find DirectRLEnv / isaaclab.sh → Detect Isaac Lab tasks
  • Find nav2_params.yaml / moveit → Detect navigation / manipulation stacks
        ↓
[2. Capability & Topology Mapping]
  • Match discovered components against Caasi's capability catalog
  • Check system compatibility (CPU, RAM, GPU, drivers)
        ↓
[3. Proposal Generation (Interactive Dry-Run)]
  • Propose caasi.yaml manifest with detected components & requirements
  • Propose safe migration mappings (e.g. moving assets to assets/, packages to src/)
  • Highlight hard-coded absolute paths that need refactoring
        ↓
[4. Project Materialization]
  • Generate canonical caasi.yaml and initial caasi.lock
  • User confirms; project is adopted and ready for caasi build / caasi run
```

---

### Question 5: How should a native caasi project avoid the discovery problem by having a deterministic structure?

A native caasi project avoids discovery heuristics entirely through a **strict project contract**:
1. **Root Manifest Anchor**: The existence of `caasi.yaml` defines the project root.
2. **Declared Project Layout in `caasi.yaml`**:
   ```yaml
   schema: 1
   name: openmover
   version: 0.1.0
   
   layout:
     ros_workspace: src/
     robots: assets/robots/
     scenes: assets/scenes/
     lab: lab/
     sim: sim/
     experiments: experiments/
     config: config/
   
   components:
     robot: true
     ros2: true
     nav2: true
     isaac_sim: true
     isaac_lab: true
   
   requires:
     ros2: { distro: jazzy }
     isaac_sim: { version: '>=5.0' }
     isaac_lab: { version: '>=2.0' }
     nav2: {}
   ```
3. **Deterministic Tool Behavior**:
   - `caasi build` always knows to build `layout.ros_workspace` (`src/`).
   - `caasi ros launch` always knows to check `install/setup.bash` inside the project.
   - `caasi sim` always resolves scenes relative to `layout.scenes`.
   - `caasi lab` always executes tasks relative to `layout.lab`.

There is no guessing, regex parsing, or dynamic scanning during daily development.

---

### Question 6: How should build systems, environments, overlays, assets, configs, experiments, datasets, and execution fit together?

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           caasi.yaml / caasi.lock                           │
│                 (Manifest, Tool Requirements, Path Layout)                  │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                ┌──────────────────────┴──────────────────────┐
                ▼                                             ▼
     [Environment Layer]                             [Build Layer]
   • Verify OS, GPU, CUDA                          • caasi build src/
   • Sourced ROS 2 Jazzy                           • RAM-safe concurrency (-j2)
   • Chain install/setup.bash                      • Emits local overlay
                │                                             │
                └──────────────────────┬──────────────────────┘
                                       ▼
                              [Execution Layer]
           caasi run start experiments/warehouse_nav2_sim.yaml
                                       │
     ┌─────────────────────────────────┼─────────────────────────────────┐
     ▼                                 ▼                                 ▼
[Isaac Sim Engine]             [ROS 2 Node Graph]               [Isaac Lab RL]
 • sim/bridges/16_bridge_ros    • packages/openmover             • lab/tasks/21_run...
 • Loads assets/scenes/         • packages/warehouse_sim         • DirectRLEnv Gym
 • Ingests /cmd_vel             • Nav2 planner & costmaps        • CUDA:0 rollout
 • Publishes /clock, /scan      • Publishes /cmd_vel             • Checkpoints/demos
     └─────────────────────────────────┬─────────────────────────────────┘
                                       ▼
                       [Centralized Provenance & Logs]
                        ~/.caasi/runs/<run-id>/
                        • manifest.yaml, hardware.yaml, git.json
                        • stdout.log, stderr.log, exit_code
```

---

### Question 7: What caasi capabilities are genuinely required to make the developer experience coherent?

1. **`caasi build` (Workspace Build Orchestrator)**: Builds ROS 2 packages using `colcon` with automatic, RAM-safe thread scaling (`-j2` on 16 GB, `-j4` on 32 GB, `-j8` on 48 GB+) to prevent system freezes.
2. **Automatic Local Overlay Sourcing**: Sourced ROS 2 commands (`caasi ros launch`, `caasi ros list`, `caasi run start`) automatically chain the project's `install/setup.bash` after `/opt/ros/jazzy/setup.bash`.
3. **`CAASI_PROJECT_ROOT` Environment Injection**: Automatically injected into every process launched by `caasi`, enabling relocatable, deterministic asset loading.
4. **Project Layout Declaration in `caasi.yaml`**: Allows declarative path mappings (`layout.ros_workspace`, `layout.robots`, `layout.scenes`, `layout.lab`).
5. **Project Asset Validation (`caasi asset check`)**: Verifies that declared URDFs, meshes, and USD files exist on disk before simulation launch.
6. **Provenance Diff (`caasi run diff <run1> <run2>`)**: Compares git commits, arguments, dependencies, and environment between two runs.

---

### Question 8: Which capabilities should belong in `0.4.0`, and which should wait?

#### Required for caasi 0.4.0 (Phase 6 Core)
- **Feature 1: `caasi build`**: Basic `colcon` wrapper with RAM-derived parallelism (`--parallel-workers`) and overlay registration.
- **Feature 2: Auto-sourcing project overlay**: Update `caasi.core.rosenv` to detect and source `<project>/install/setup.bash`.
- **Feature 3: `CAASI_PROJECT_ROOT` Injection**: In `caasi.core.runs._popen` and `caasi.core.experiment.build_command`.
- **Feature 4: Project Layout Schema**: Extend `caasi.yaml` schema to recognize `layout` mappings.

#### Strongly Useful (Candidate for 0.4.1 / Fast Follow)
- **Feature 5: `caasi run diff`**: Provenance diff CLI.
- **Feature 6: `caasi asset validate`**: Preflight verification of URDF/USD asset references.

#### Future Work (Phase 7+ / Defer)
- **`caasi project adopt / discover`**: Automatic heuristic scanning of arbitrary external repos (Phase 8).
- **Remote Synchronization**: `caasi remote` workspace sync and cluster dispatch (Phase 7).
- **Custom USD Asset Bundling**: Archiving scenes into self-contained zip packages.

---

### Question 9: What would the normal developer workflow look like from a fresh project through build → simulation → ROS2 → Isaac Lab → experiments → results?

```bash
# 1. Inspect and validate the environment
caasi env inspect
caasi check project

# 2. Build the ROS 2 packages safely (auto-sizes -j to available RAM)
caasi build

# 3. Launch Isaac Sim warehouse simulation with ROS bridge as a tracked run
caasi sim run experiments/sim_warehouse_bridge.yaml

# 4. Concurrently launch Nav2 navigation stack (auto-sources local overlay)
caasi ros launch packages/warehouse_simulation/launch/stack_b.launch.py -- nav:=true

# 5. Monitor live graph and system resources
caasi run list
caasi monitor system

# 6. Execute Isaac Lab RL evaluation campaign
caasi run start experiments/campaign_bounded.yaml

# 7. Check logs, inspect artifacts, and review provenance
caasi logs latest -f
caasi run inspect latest
```

---

### Question 10: What should explicitly NOT be built because an established ecosystem already handles it?

1. **Do NOT build a custom compiler or build tool**: `caasi` must invoke `colcon build`. Do not reinvent CMake, gcc, or ament.
2. **Do NOT build a custom ROS middleware or DDS router**: ROS 2 Jazzy and Zenoh/FastDDS handle message routing.
3. **Do NOT build a custom navigation planner**: Nav2 owns path planning, costmaps, and recoveries.
4. **Do NOT build a custom physics or rendering engine**: Isaac Sim and PhysX own physics and raytracing.
5. **Do NOT build a custom neural network or RL framework**: PyTorch and Gymnasium own tensors, policies, and environment rollouts.
6. **Do NOT build a custom VCS or asset downloader**: Git, Git LFS, and Hugging Face CLI handle version control and large model checkpoints.

---

## 3. Stage C: Next Step & Discussion Gate

This revised proposal provides a complete architectural blueprint.

Before implementing Stage D (Canonical Project Materialization & caasi 0.4.0 Features), please review these 10 answers with ChatGPT. Once you give approval, we will proceed with the approved implementation plan.
