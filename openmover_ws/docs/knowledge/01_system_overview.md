# 01 — System Overview

## Identity

OpenMover is an indoor mobile robot platform built at Southwest Jiaotong University. It is a
differential-drive robot (Pioneer 3DX-style chassis) originally developed on **ROS 1 Noetic** and
fully ported to **ROS 2 Jazzy** (the current, canonical codebase).

| Attribute | Value |
|---|---|
| Robot type | Differential drive, indoor service/research robot |
| Chassis lineage | Pioneer 3DX-style (two drive wheels + caster/swivel wheels) |
| Perception | Two 2D LiDARs (Bluesea/Lanhai, front + rear, merged to one 360° scan) |
| Other hardware | Speaker (pygame), chassis IO board (buttons, e-stop, BMS), motor controller |
| OS | Ubuntu 24.04 LTS |
| ROS | ROS 2 Jazzy (Python 3.12, C++17) |
| Simulator | Gazebo Harmonic (gz-sim 8.x) via `ros_gz` bridge |
| SLAM | Cartographer (core stack) / slam_toolbox (warehouse demo) |
| Navigation | Custom controller + global planner (core stack) / Nav2 with MPPI (warehouse demo) |
| Build system | colcon + ament_cmake, `-j2` parallelism (16 GB RAM machine constraint) |

## The two stacks (this is the most important structural fact)

The workspace ships **two independent, complete robot stacks** that share no runtime nodes:

### Stack A — Robot core (`openmover` + toolboxes)

The actual product. Orchestrated by a Python HAL/SDK layer. Features:

- Manual teleop (keyboard/joystick), mapping mode (Cartographer + frontier-based auto-mapping),
  navigation mode (map server + localization + custom controller), and recovery flows.
- Custom algorithm toolboxes, both GPL-3.0, originally by ZHANG Muhua:
  - `auto_mapping_toolbox` — autonomous exploration/mapping state machine (RRT frontiers,
    TSP back-to-origin).
  - `relocalization_toolbox` — global 2D relocalization (RRT reachability sampling → likelihood
    field scoring → GICP refinement), i.e., kidnapped-robot recovery.
- Real hardware drivers: `bluesea2` (2D LiDAR, manually ported, no vendor ROS 2 driver exists),
  `motor_handler` (TCP to motor controller), `io_board_handler` (TCP to chassis IO board).
- One entry point for everything: `ros2 launch openmover workload.launch.py system_mode:=<0|1>`
  where `0 = simulation`, `1 = real robot`.

### Stack B — Warehouse demo (`warehouse_simulation`)

A standalone simulation-only demo and research sandbox: Pioneer 3DX model in a warehouse world
with two walking pedestrian actors, using the *modern community stack* (slam_toolbox + Nav2 with
MPPI controller). It has its own teleop (`key_control`), its own RViz, its own tests. It is the
place where Nav2-era patterns are validated and where perception/learning experiments start.

## Directory map

```
/home/zar/Documents/phd/robot/
├── openmover_ws/                     ← ROS 2 workspace (THE canonical codebase)
│   ├── src/
│   │   ├── openmover/                ← Stack A core
│   │   ├── openmover_msgs/           ← Stack A custom interfaces
│   │   ├── auto_mapping_toolbox/     ← auto_mapping_toolbox + auto_mapping_toolbox_msgs
│   │   ├── relocalization_toolbox/   ← relocalization_toolbox + relocalization_toolbox_msgs
│   │   ├── warehouse_simulation/     ← Stack B (demo/research sandbox)
│   │   ├── bluesea2/                 ← 2D LiDAR vendor driver (manual port)
│   │   └── ira_laser_tools/          ← laserscan_multi_merger (multi-LiDAR merge)
│   ├── tools/                        ← check_system.sh, install_deps.sh, setup.sh, vendored OSQP
│   ├── docs/                         ← HTML docs for humans; docs/knowledge/ = this folder
│   ├── build/  install/  log/        ← colcon artifacts (symlink-install)
│   └── .trae/documents/              ← migration plan, chat history (project management)
└── openmover_robot/                  ← ROS 1 Noetic original (read-only ground truth)
    ├── openmover_ws/src/             ← original ROS 1 packages
    └── config/                       ← original runtime config (config.txt snapshot)
```

Runtime data (created/used at run time, outside the repo):

```
~/openmover_robot/maps/      ← saved maps (pgm + yaml + pbstream), subdirs simulation/ real-world/
~/openmover_robot/sounds/    ← speaker assets
~/openmover_robot/logs/      ← HAL logger output
```

## Conventions (follow these in any code you write for this project)

1. **Services, not actions.** Nothing in the system uses `rclcpp_action`. Goal semantics
   (nav-to, relocalize, auto-map, mode switching) are synchronous service calls.
2. **Topic namespace:** `openmover/<domain>/<name>` for the core stack
   (domains: `hardware`, `control`, `localization`, `navigation`, `mapping`, `server`, `flow`).
   Stack B uses bare topics (`/scan`, `/cmd_vel`, `/odom`, `/tf`, `/map`).
3. **Custom messages** are only created in the `*_msgs` packages, never inline.
4. **Sim/real branching** is done once, in launch, via the `system_mode` argument
   (`0` = sim, `1` = real); `use_sim_time` is threaded through as a launch argument
   (there is no global param server).
5. **C++ nodes** are named `*_handler` and live in `openmover/src/<domain>/`; **Python scripts**
   are named `*_handler.py` or live under `scripts/hal|server|teleop|workload`.
6. **Parity principle:** when porting/touching anything, ROS 1 behavior is the ground truth
   unless a deviation is explicitly documented (see [08_migration_notes.md](08_migration_notes.md)).
   Deliberate deviations are marked in code comments and in `docs/changelog.html`.
7. **Attribution:** package.xml maintainers = current maintainer (`zar`); original authors are
   listed as `<author>` with a "(ROS 2 Jazzy port)" note. Toolbox C++ headers carry
   `@author ZHANG Muhua` + `ROS 2 Jazzy port by zar`.
8. Code comments may be Chinese (repo convention); documentation and Doxygen blocks are English.

## Key external dependencies

- `cartographer_ros` (Jazzy apt packages) — SLAM and localization in Stack A.
- `nav2_*` packages — Nav2 full stack in Stack B; only `nav2_map_server`,
  `nav2_lifecycle_manager`, `nav2_costmap_2d`, `nav2_util` inside Stack A.
- `slam_toolbox` — Stack B mapping.
- `ros_gz_sim` / `ros_gz_bridge` — Gazebo Harmonic integration.
- **OSQP** — built/vendored under `tools/osqp_build`, installed to `/usr/local`
  (used by the auto-mapping global planner's path smoother). Not declared in package.xml
  (accepted known minor; installed by `tools/install_deps.sh`).
- PCL, Eigen, OpenCV, yaml-cpp, Boost; Python: pynput (keyboard teleop), pygame (speaker).
