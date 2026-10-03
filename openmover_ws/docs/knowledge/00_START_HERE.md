# OpenMover Knowledge Base — Start Here

This folder is a machine-readable description of the OpenMover robot system, written so an AI
model (or a new engineer) can understand the whole project **without reading the codebase first**.
If you are an AI assistant reading this: consume the files in the order below, then answer
questions or make changes based on this knowledge. Verify details against the source only when
you need exact line-level accuracy.

## What this system is (30 seconds)

OpenMover is a small differential-drive indoor robot (Pioneer 3DX-style chassis, two 2D LiDARs,
speaker, battery management) developed as a ROS 1 Noetic stack and **ported to ROS 2 Jazzy +
Gazebo Harmonic** (Ubuntu 24.04). The workspace contains two complete stacks:

1. **Robot core stack (`openmover`)** — the real product: hardware drivers, Cartographer-based
   localization/mapping, a custom navigation controller, autonomous mapping and global
   relocalization toolboxes, plus a Python HAL/SDK orchestration layer. Runs in **simulation**
   (Gazebo) or on the **real robot** from one launch entry point (`system_mode` argument).
2. **Warehouse demo stack (`warehouse_simulation`)** — a standalone, Nav2 + slam_toolbox based
   demo in a warehouse world with pedestrian actors; used as a modern-stack reference and
   research sandbox.

## Reading order

| # | File | Contents |
|---|---|---|
| 1 | [01_system_overview.md](01_system_overview.md) | Big picture: platform, hardware, repo layout, key conventions |
| 2 | [02_architecture.md](02_architecture.md) | Runtime architecture: nodes, topics, services, TF, HAL layer, launch hierarchy |
| 3 | [03_packages.md](03_packages.md) | All 9 packages in detail (executables, interfaces, parameters) |
| 4 | [04_workflows_simulation.md](04_workflows_simulation.md) | Everything you can do in simulation, with exact commands |
| 5 | [05_workflows_real_robot.md](05_workflows_real_robot.md) | Real-robot hardware, network, bringup, safety |
| 6 | [06_configuration.md](06_configuration.md) | Every config file, map format, runtime directories, parameters that matter |
| 7 | [07_build_tools.md](07_build_tools.md) | Build rules (16 GB constraint), helper scripts, tests, troubleshooting |
| 8 | [08_migration_notes.md](08_migration_notes.md) | ROS 1 → ROS 2 history, deliberate changes, parity rules, known issues |
| 9 | [09_research_directions.md](09_research_directions.md) | What this system is being used for next (Isaac Sim, sim-to-real research) |

## Quick orientation facts

- Workspace root: `/home/zar/Documents/phd/robot/openmover_ws` (colcon workspace, `src/` has the packages).
- ROS 1 reference tree (ground truth for parity): `/home/zar/Documents/phd/robot/openmover_robot/openmover_ws/src/`.
- Platform: Ubuntu 24.04, ROS 2 Jazzy, Gazebo Harmonic (gz-sim 8.x), Python 3.12, C++17.
- All custom ROS interfaces live in `openmover_msgs` (and two `*_msgs` packages for the toolboxes).
- **The system uses services, never actions.** All goal/control semantics are service calls.
- Topic namespace convention: everything in the core stack is under `openmover/...`
  (`openmover/hardware/*`, `openmover/control/*`, `openmover/localization/*`,
  `openmover/navigation/*`, `openmover/mapping/*`, `openmover/server/*`, `openmover/flow/*`).
- Human-facing HTML docs live in `openmover_ws/docs/*.html` (getting started, build, usage,
  hardware, architecture, packages, audit, changelog). This knowledge base is the AI-facing twin.
- **Machine constraint (important for any advice you give):** the primary dev machine has 16 GB
  RAM. Full-parallel builds and full-load simulations have hard-frozen it. All builds use
  `MAKEFLAGS="-j2" CMAKE_BUILD_PARALLEL_LEVEL=2 colcon build --symlink-install --parallel-workers 2`.
