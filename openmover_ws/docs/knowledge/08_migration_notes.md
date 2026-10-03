# 08 — Migration History: ROS 1 Noetic → ROS 2 Jazzy

## Why

ROS 1 is EOL (Noetic support ends May 2025), and the project's next phase (NVIDIA Isaac Sim,
GPU-accelerated robot learning) requires a modern ROS 2 stack. The migration was executed as a
staged plan (stages 0–11, complete) followed by an 8-fix parity audit. The ROS 1 tree at
`/home/zar/Documents/phd/robot/openmover_robot/` remains the ground-truth reference.

## Platform shift

| Aspect | ROS 1 (was) | ROS 2 (now) |
|---|---|---|
| Distro | Noetic (Python 3.8) | Jazzy (Python 3.12) |
| Simulator | Gazebo Classic 11 | Gazebo Harmonic (gz-sim 8.10) |
| Middleware | roscpp/rospy + master | rclcpp/rclpy + DDS (no master) |
| OS | Ubuntu 20.04 | Ubuntu 24.04 |
| Launch | roslaunch (XML + Python API) | `ros2 launch` Python; subprocess management re-implemented in `launch_manager.py` |

## Major substitutions (decision log)

| Was | Now | Why |
|---|---|---|
| gmapping | **slam_toolbox** (Stack B) | maintained on Jazzy, better maps |
| move_base + DWB | **Nav2 + MPPI** (Stack B) | maintained controller; cost: `controller_frequency 20.0` + retuned velocity limits |
| move_base-era custom nav (Stack A) | **same custom controller**, ported; nav2_costmap_2d embedded | parity with ROS 1 behavior |
| virtualizer node | **dropped** | its output was unused in the graph |
| vendor bluesea2 driver | **manual port** | no vendor Jazzy driver exists |
| ira_laser_tools (upstream) | **manual port** (PCL dep removed) | upstream not released for Jazzy |
| Gazebo Classic world | **world rebuilt** in SDF/Harmonic | Classic models incompatible; layout, spawn pose, actor paths preserved |
| proxy collision boxes for pedestrians | **perception-based stop** | proxy hack deleted — actors' feet are genuinely seen by LiDAR; costmap stops the robot; matches real-robot behavior |
| cartographer initialpose topic | **adapter node** (`cartographer_initialpose_adapter.py`) | ROS 2 cartographer removed the topic; adapter uses trajectory services |

## Deliberate behavioral deviations (documented, intentional)

1. **`warehouse_simulation` key_control DOWN = reverse** (−0.7·scale). ROS 1 mapped DOWN to
   `-0.0` (stop, no reverse existed). Nav2 `vx_min: -0.35` and the DiffDrive plugin permit it.
2. **key_control is hold-to-drive**: commands repeat at 20 Hz while a key is held (OS key-repeat),
   auto-stop on release — instead of ROS 1's single one-shot pulse.
3. **Pedestrian actor waypoints z lifted 0 → 1.0** (gz Harmonic actor skin anchor; prevents
   floor-sinking). Waypoint x/y/timing identical to ROS 1.

## Parity rules (binding for future work)

- ROS 1 behavior is the default ground truth. Any new deviation must be commented in code and
  recorded in `docs/changelog.html`.
- Config parity is exact — even **dead keys** are preserved if they exist in ROS 1
  (e.g., `dist_gain_far`/`dist_gain_near`; `rrt_sampling_duration` vs
  `reachability_sampling_duration`), because removing them creates a diff rather than fixing one.
- Topic/service contracts and frame names must not change without updating HAL clients and docs.
- The warehouse simulation world preserves layout, spawn poses, and actor paths.

## Audit outcome (8 fixes, all verified)

A post-migration audit compared every subsystem against ROS 1 and fixed 8 defects
(details in `docs/audit.html`): among them the slam_toolbox lifecycle activation guard,
key_control safety behavior, actor z-lift, restored build flags for the 16 GB machine, and
license/authorship metadata restoration. End-to-end validation: drive → map → save → localize →
navigate → pedestrian stop/resume all working; 6/6 tests pass.

**Known minors (accepted):** rviz1-format configs in `config_defaults/rviz` (inert);
OSQP undeclared in package.xml (system dep, documented); dead config keys (parity);
license TODOs **resolved** (licenses restored to ROS 1 declarations — see attribution below).
**Remaining risk:** the real-robot branch is not yet exercised on hardware.

## Attribution & licenses (REP-149 semantics applied)

`<maintainer>` = current maintainer (zar) on all 9 packages; `<author>` entries preserve original
authorship with explicit port notes. Per package:

| Package | Original author | License |
|---|---|---|
| openmover, openmover_msgs | ZHANG Muhua | `private` (restored from TODO) |
| auto_mapping_toolbox (+msgs) | ZHANG Muhua | `GPL-3.0 License` (msgs restored) |
| relocalization_toolbox (+msgs) | ZHANG Muhua | `GPL-3.0 License` (msgs restored) |
| warehouse_simulation | Wang Han | BSD |
| bluesea2 | Bluesea Technology (vendor) | as declared by vendor (none) |
| ira_laser_tools | upstream unimib authors | BSD |

The 20 toolbox C++ files with Doxygen headers carry `@author ZHANG Muhua` +
`ROS 2 Jazzy port by zar`. Note: parts of the ROS 1 tree predate ZHANG Muhua's
maintainership (predecessor work); the ROS 2 metadata credits declared ROS 1 maintainers.

## Where to read more

- `docs/changelog.html` — subsystem-by-subsystem change table + decision log.
- `docs/audit.html` — parity audit detail, known minors, validation summary.
- `.trae/documents/openmover_ros2_jazzy_migration_plan.md` — the original staged plan.
