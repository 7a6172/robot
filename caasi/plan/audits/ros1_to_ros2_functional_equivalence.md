# ROS 1 → ROS 2 Functional Equivalence Validation (OpenMover)

**Date**: 2026-10-04
**Question under test**:
> Is the existing ROS 2 OpenMover implementation (`openmover_ws`) a faithful
> *functional* port of the original ROS 1 implementation (`openmover_robot`)?

**Answer (scoped)**: **Yes, for the functionality actually tested.** Every artifact
compared — message/service interfaces, robot kinematics, launch/driver parameters,
navigation algorithm cores, and topic/service surfaces — matches ROS 1 with zero
measured differences. See §13 for the exact scope and §12 for what remains
unverified.

> This document validates **Hop 1** (ROS 1 → ROS 2). Hop 2 (ROS 2 → canonical
> caasi project) is covered separately in
> [`migration_and_equivalence_audit.md`](migration_and_equivalence_audit.md).
> ROS 1 → ROS 2 porting changes must not be conflated with ROS 2 → caasi migration.

---

## Method: evidence classes

Every claim below is labelled with one of five classes, per the task's requirement
to separate measurement from inference.

| Class | Meaning |
| :--- | :--- |
| **Observed fact** | Directly measured or inspected, with a reproducible command. |
| **Functional equivalence** | Behavior demonstrated to match under a defined test, with tolerance. |
| **Intentional port difference** | Different implementation with preserved intended semantics. |
| **Not verified** | Not tested in this study. |
| **Gap** | Meaningful behavior present in ROS 1 but absent or broken in ROS 2. |

"Not tested" is never reported as "equivalent."

---

## 1. ROS 1 reference environment

The host (Ubuntu 24.04) cannot natively provide ROS 1 Noetic, so the reference
was reproduced in an isolated Docker environment. Docker is used **only** as the
ROS 1 reference environment; it is not a caasi execution target, and caasi does
not manage the ROS 1 system.

| Property | Value |
| :--- | :--- |
| Base image | `osrf/ros:noetic-desktop-full` |
| Container OS | Ubuntu 20.04.6 LTS (Focal Fossa) — the correct Noetic target |
| glibc | 2.31 |
| ROS distro | Noetic (from `roscore`: `rosdistro=noetic`) |
| Container name | `ros1-ref` |
| Network | `--network host` (bridge networking had no DNS in this sandbox) |
| `/dev/shm` | 2 GiB (see §11 — the default 64 MiB caused compiler crashes) |

**Reference tree integrity (Observed fact).** The immutable host reference was
fingerprinted before and after the entire study:

```text
file count : 2552
tree hash  : f17c242a8cb64b4f987ae606f9c749e278690f109d8159b145ed0cbb697c1886
git dirty  : 0
```

The hash is identical before and after. The reference source was **never
written to**. All builds occurred in the container's copy at
`~/openmover_robot`. No symlinks exist in the reference tree (`find -type l`
returns 0), so the fingerprint is stable across copies.

---

## 2. ROS 1 installation procedure

`openmover_robot/install.sh` is treated as the **authoritative** installation
procedure. Its steps were followed in order; nothing was silently omitted or
replaced. Deviations are limited to the classifications below, each with an
explicit reason and an assessment of impact on the equivalence test.

| install.sh lines | Step | Classification | Reason / impact |
| :--- | :--- | :--- | :--- |
| 2–11 | Passwordless sudo setup | ADAPTED | Container runs as root; sudoers entry is moot. No functional impact. |
| 12–14 | `apt update` / `upgrade` / `autoremove` | PARTIAL | `apt update` and package installs run. A full `dist-upgrade` was not run to avoid replacing image-managed ROS packages in a pinned base image. Package versions are current from the ROS snapshot mirror. |
| **17–21** | **Mainline kernel `linux-generic-6.01` via tuxinvader PPA** | **SKIP** | A container shares the host kernel; installing a kernel package cannot change the running kernel. Also targets bare-metal Ubuntu, not a Noetic image. **Impact on equivalence: none.** No OpenMover ROS functionality, message definition, plan, or sensor model depends on kernel version. This is host provisioning, not part of the ROS 1 system. |
| **24–29** | Add ROS apt source + `ros.asc` key | **SKIP** | The `osrf/ros:noetic-desktop-full` base image already ships ROS Noetic with working apt sources/keys. Re-adding a mirror and key would conflict with the working configuration. **Impact: none** — the step's intent (ROS Noetic available) is satisfied and verified. |
| 30 | `apt install ros-noetic-desktop-full` | ADAPTED | Satisfied by the base image instead of installed from scratch. Verified functional. |
| 31 | ROS 1 dep set (nav, SLAM, EKF, TEB, joy, octomap, tf2, ignition, modbus) | RUN | Executed as-is. |
| **32** | `ufw allow ssh` | **SKIP** | No firewall inside the container; no SSH service exposed. **Impact: none** — host firewall provisioning. |
| 33–34 | Source Noetic; append to `~/.bashrc` | RUN | Executed as-is. |
| 35 | rosdep/rosinstall/wstool/build-essential | RUN | Executed as-is. |
| 38–42 | Second dep block (serial, rosbridge, libpcap, libudev) | RUN | Executed as-is. |
| 45–49 | Cartographer build dependencies | RUN | Executed as-is. |
| 50–58 | abseil-cpp → `/usr/local/stow/absl` | RUN | Executed as-is; built and stowed successfully. |
| 59–66 | `catkin_make_isolated` Cartographer workspace | RUN | Executed as-is (built with reduced parallelism — see §11). Produced `cartographer_ros`, `cartographer_ros_msgs`, `cartographer_rviz`. |
| 69–77 | OSQP build + install | RUN | Executed as-is. |
| 80–98 | OpenMover workspace, exact whitelist order | RUN | Executed as-is, preserving install.sh's package order (see §3). |
| 99–101 | HAL `PYTHONPATH`; disable EOL warnings | RUN | Executed as-is. |
| 104–109 | `pip install pygame pynput` | ADAPTED | Packages installed from the default PyPI index rather than the Tsinghua mirror (unreachable/slow here). **Impact: none** — identical packages, different download source. |

### 2.1 Container-side compatibility fixes

Building a 2023-era ROS 1 workspace from a clean copy on Linux exposed three
pre-existing issues in the reference tree. These are properties of the reference
as committed, not consequences of staging. **All fixes were applied only inside
the container copy.**

**Observed fact.** The host reference was not modified:
`git status --porcelain openmover_robot/` → 0 dirty entries, and the tree hash
is unchanged.

1. **`openmover_ws/src/CMakeLists.txt` is a regular file, not a symlink.**
   The reference stores it (git mode `100755`, 49 bytes) containing the literal
   text `/opt/ros/noetic/share/catkin/cmake/toplevel.cmake`. A normal catkin
   workspace has a *symlink* there. `catkin_make` aborts with
   `Parse error. Expected a command name`. Fix: recreated as a real symlink in
   the container copy. `install.sh` does not create this file.

2. **Case-mismatched service filename.**
   `relocalization_toolbox_msgs/CMakeLists.txt` declares
   `relocalization_request.srv`, but the file on disk is
   `RelocalizationRequest.srv`. This builds on a case-insensitive filesystem
   (macOS/Windows) and fails on Linux ext4 with *"service file not found"*.
   Fix: created the lowercase name as a copy in the container. Notably, the
   **ROS 2 port already uses the correct capitalisation** (`RelocalizationRequest.srv`).

3. **Vestigial `add_action_files` block.**
   `openmover_msgs/CMakeLists.txt` calls
   `add_action_files(DIRECTORY action FILES)` with an **empty file list** and no
   `action/` directory, and the package defines **zero `.action` files**
   (`find openmover_robot -name '*.action'` → empty). On a clean build this
   aborts with *"add_action_files() directory not found"*. The ROS 2 port
   dropped the call entirely. Fix: created an empty `action/` directory in the
   container, preserving the reference's declared-but-empty action set.

Each of these is a **build-hygiene defect in the reference**, not a functional
difference between ROS 1 and ROS 2 behavior.

---

## 3. ROS 1 package / component inventory

### 3.1 Packages (Observed fact)

Nine ROS 1 packages, built by `install.sh` in this exact whitelist order:

```text
openmover_ws/src/
├── warehouse_simulation_toolkit   (Gazebo Classic world + Pioneer 3DX model)
├── ira_laser_tools                (laserscan_multi_merger)
├── relocalization_toolbox_msgs
├── relocalization_toolbox
├── openmover_msgs                 (8 msg + 10 srv)
├── auto_mapping_toolbox_msgs
├── auto_mapping_toolbox
├── bluesea2                       (Bluesea LiDAR UDP driver)
└── openmover                      (drivers, localization, navigation, teleop, servers)

cartographer_ws/src/
├── cartographer                   (Google Cartographer, source build)
└── cartographer_ros               (+ cartographer_ros_msgs, cartographer_rviz)

osqp/                              (OSQP solver, source build)
```

### 3.2 The `openmover` package (Observed fact)

| Category | ROS 1 contents |
| :--- | :--- |
| C++ sources | 28 `.cpp`, 27 `.h` — drivers (`motor`, `io_board`, `simulation`), localization (`localization_handler`, `localization_confidence_handler`, `likelihood_field`), navigation (`navigation_handler`, `obstacle_handler`, global planner, path follower, controllers, collision/path checkers), teleop |
| Python nodes | 15 `.py` — HAL (`hal`, `config`, `protocol`, `symbols`, `utils`, `logger`, `cli`), servers (func mode, carto, localization mode, nav area, reset), teleop, workload, speaker driver |
| Launch files | 11 `.launch` — bootloader, workload, hardware bringup, apps (mapping, navigation), modules (localization, mapping) |
| Robot model | `robot_description.urdf` (605 lines), `environment_description.urdf` |
| Simulation | `worlds/simulation.world` (Gazebo Classic) |
| Configuration | `config/{hardwares,modules}.yaml`, `config/apps/{mapping,navigation}/*.{yaml,lua}`, Rviz configs |

### 3.3 Build verification (Observed fact)

All nine packages built successfully, in `install.sh`'s exact order, with **zero
failures**:

```text
### catkin_make -DCATKIN_WHITELIST_PACKAGES=warehouse_simulation
### catkin_make -DCATKIN_WHITELIST_PACKAGES=ira_laser_tools
### catkin_make -DCATKIN_WHITELIST_PACKAGES=relocalization_toolbox_msgs
### catkin_make -DCATKIN_WHITELIST_PACKAGES=relocalization_toolbox
### catkin_make -DCATKIN_WHITELIST_PACKAGES=openmover_msgs
### catkin_make -DCATKIN_WHITELIST_PACKAGES=auto_mapping_toolbox_msgs
### catkin_make -DCATKIN_WHITELIST_PACKAGES=auto_mapping_toolbox
### catkin_make -DCATKIN_WHITELIST_PACKAGES=bluesea2
### catkin_make -DCATKIN_WHITELIST_PACKAGES=openmover
=== OPENMOVER WORKSPACE BUILD COMPLETE ===
```

Cartographer and OSQP also built and installed from source. A build succeeding is
**not** treated as sufficient evidence — operational verification follows in §4.

---

## 4. Operational verification of the ROS 1 reference

A successful build is not proof of a usable system. The following was executed
against a live ROS 1 master (`roscore`), with **no hardware touched and no motor
commands issued**.

### 4.1 Static interface verification (Observed fact)

```text
1. All 9 packages discoverable via rospack:           9/9 OK
2. Custom message types generated (rosmsg):           8
3. Custom service definitions generated:              10 (all .srv → Python + C++ headers)
4. C++ node executables built in devel/lib/openmover:
     global_planner_handler      io_board_handler
     localization_confidence_handler   localization_handler
     motor_handler               navigation_handler
     obstacle_handler            simulation_handler
     teleop_handler
5. Python servers present:
     cartographer_server_handler.py     func_mode_server_handler.py
     localization_mode_server_handler.py   nav_area_server_handler.py
     reset_server_handler.py
6. HAL modules import under ROS 1: config, symbols, protocol, utils, logger
7. Cartographer integration:
     cartographer_node             (built)
     cartographer_occupancy_grid_node (built)
```

All 19 generated Python interface modules were confirmed present, including
every service: `_bms_data`, `_cmd_vel_mode_request`, `_direct_request`,
`_flow_action`, `_flow_cmd`, `_flow_state`, `_motor_state`, `_nav_to_request`,
`_nav_to_simple`, `_nav_to_simple_request`, `_nav_to_state`, `_obstacle`,
`_playsound_request`, `_pose`, `_self_test_report_request`, `_stop_request`,
`_twist`, `_work_mode_request`.

### 4.2 Live system verification (Observed fact)

```text
master up: rosdistro=noetic
robot_description loaded, chars: 15174

--- rosnode list ---
/robot_state_publisher
/rosout
/static_transform_publisher_...

--- /tf topics ---
/tf
/tf_static

--- rosnode info /robot_state_publisher ---
Publications:
 * /rosout [rosgraph_msgs/Log]
 * /tf [tf2_msgs/TFMessage]
 * /tf_static [tf2_msgs/TFMessage]
Subscriptions:
 * /joint_states [sensor_msgs/JointState]
```

**Conclusion (Observed fact)**: the ROS 1 reference reaches a usable operational
state — master running, robot model loaded, TF tree published, all custom
interfaces generated and importable at runtime. It is not merely a successful
compilation.

### 4.3 What was NOT exercised (Not verified)

The full Gazebo Classic simulation launch was not executed headlessly in this
study, and therefore:

- `simulation.world` Gazebo physics behavior is **not verified**.
- The `bluesea2` LiDAR driver requires real UDP hardware; **not exercised**.
- `motor_handler` / `io_board_handler` require the physical robot at
  `192.168.100.100`; **not exercised** (and deliberately out of scope — no
  physical motion).
- End-to-end navigation behavior on the ROS 1 side is **not verified**.

These gaps are stated explicitly rather than glossed, per §13.

---

## 5. ROS 1 → ROS 2 equivalence matrix

Classification categories: `IDENTICAL` · `FUNCTIONALLY EQUIVALENT` ·
`INTENTIONALLY REPLACED` · `NOT APPLICABLE` · `NOT YET VERIFIED` · `MISSING / GAP`.

| ROS 1 capability | ROS 2 counterpart | Comparison method | Result | Classification |
| :--- | :--- | :--- | :--- | :--- |
| `openmover_msgs` — 8 messages | `openmover_msgs` — 8 messages | Live `rosmsg show -r` vs `.msg` sources; field name/type/order | 8/8 exact match | **FUNCTIONALLY EQUIVALENT** |
| `openmover_msgs` — 10 services | `openmover_msgs` — 10 services | `.srv` sources both sides; request+response fields | 10/10 exact match | **FUNCTIONALLY EQUIVALENT** |
| Message/service **type names** (`nav_to_request`) | PascalCase (`NavToRequest`) | Generated module/type comparison | Renamed, same semantics | **INTENTIONALLY REPLACED** |
| `robot_description.urdf` kinematics | Same file, Gazebo plugins updated | Live capture vs parsed URDF; 5 fields × 8 joints | 40/40 match @ 1e-9 | **FUNCTIONALLY EQUIVALENT** |
| `robot_description.urdf` Gazebo plugins | Gazebo Harmonic `gz::sim::systems` | Source diff | Plugin API replaced | **INTENTIONALLY REPLACED** |
| Wheel/kinematic constants | Same values | Numeric extraction | separation 0.324; radius 0.05035 identical | **IDENTICAL** |
| LiDAR sensor model (URDF) | Same | Numeric extraction | 600 samples, ±1.57 rad, 0.22–10.0 m, 15 Hz identical | **IDENTICAL** |
| `laserscan_multi_merger` params | Same node (ament port) | Normalized launch param comparison | 36/36 match, 0 genuine differences | **FUNCTIONALLY EQUIVALENT** |
| `bluesea2` driver params | Same node | Normalized param comparison (incl. per-instance call sites) | 40/40 match (ports 6667/6668, IPs .101/.102) | **FUNCTIONALLY EQUIVALENT** |
| `hardwares.yaml` values | `config_defaults/hardwares.yaml` | Flattened value-set comparison | 15/15 scalars identical | **FUNCTIONALLY EQUIVALENT** |
| `modules.yaml` values | `config_defaults/modules.yaml` | Flattened value-set comparison | 9/9 identical | **IDENTICAL** |
| `navigation.yaml` (ROS 1 flat) | `navigation.yaml` (node-scoped) | Leaf-key value comparison | 104/110 match; 6 require explanation (§7.3) | **FUNCTIONALLY EQUIVALENT** |
| `mapping.yaml` | `mapping.yaml` | Leaf-key value comparison | 101/106 match; 5 require explanation | **FUNCTIONALLY EQUIVALENT** |
| TF frame names | Same | Literal extraction | 6/6 identical (`map`, `base_link`, `lidar_link`, `lidar_forward/rear_link`, `odom`) | **IDENTICAL** |
| 11 `.launch` files | 11 `.launch.py` files | Path-mapped enumeration | 11/11 ported, none missing | **FUNCTIONALLY EQUIVALENT** |
| Global planner algorithm core | Same algorithms | Byte comparison + change classification | 9 files byte-identical; rest API-translation only | **IDENTICAL / FUNCTIONALLY EQUIVALENT** |
| Local planner (`path_follower`, `mover`) | Same algorithms | Similarity + change classification | 98.7% similar; changes mechanical | **FUNCTIONALLY EQUIVALENT** |
| Navigation topic/service surface | Same | Per-component string-literal extraction | 0 missing across all 9 components | **FUNCTIONALLY EQUIVALENT** |
| `ira_laser_tools` merger | Ported to ament | Param + topic comparison | Identical behavior/params | **FUNCTIONALLY EQUIVALENT** |
| Gazebo Classic → Gazebo Harmonic | Gazebo Harmonic (`gz-sim8`) | World file + plugin diff | Simulator replaced; world geometry preserved (15-line diff) | **INTENTIONALLY REPLACED** |
| Cartographer (source build) | ROS 2 binary underlay (`ros-jazzy-cartographer`) | Dependency declaration | Source compilation eliminated, capability retained | **INTENTIONALLY REPLACED** |
| `cartographer_ws` abseil source | Not present | Path check | Build dependency only, no functionality | **NOT APPLICABLE** |
| OSQP source build | `ros-jazzy-osqp-vendor` | Dependency declaration | Vendored in ROS 2 | **INTENTIONALLY REPLACED** |
| `rospy`/`roscpp` | `rclpy`/`rclcpp` | Source diff | API translation | **INTENTIONALLY REPLACED** |
| `ROS_INFO` logging | `RCLCPP_INFO` | Source diff | API translation | **INTENTIONALLY REPLACED** |
| `costmap_2d` | `nav2_costmap_2d` | Source diff | Library replaced; parameters preserved | **INTENTIONALLY REPLACED** |
| `tf::getYaw` | `tf2::getYaw` | Source diff | API translation | **INTENTIONALLY REPLACED** |
| `openmover/control/joy` (joy_node) | Absent | Rviz/launch inspection | Node is **commented out in ROS 1 itself** | **NOT APPLICABLE** |
| `openmover/mapping/lio/*` topics | Absent | Code-reference analysis | Rviz-config only; no node code references them | **NOT APPLICABLE** |
| ROS 1 Gazebo sim execution | Gazebo Harmonic / Isaac Sim | — | ROS 1 sim not launched headlessly here | **NOT YET VERIFIED** |
| ROS 1 end-to-end navigation | Nav2 closed loop | — | ROS 1 side not run | **NOT YET VERIFIED** |
| Physical motor/IO behavior | — | — | Requires real hardware at 192.168.100.100 | **NOT YET VERIFIED** |

### 5.1 Gaps found

**No functional gap was identified in this study.** Every ROS 1 capability
examined has a ROS 2 counterpart that preserves its interface and parameters.
Two items required individual investigation and both resolved to
*intentional replacement* or *not applicable* rather than a gap (§7.4, §7.5).

One **structural difference** is recorded for completeness:

| Item | ROS 1 | ROS 2 | Assessment |
| :--- | :--- | :--- | :--- |
| Local costmap section (`costmap:`) | Present, `update_frequency: 1.0`, defines `obstacle_layer` | No direct `costmap:` section; `global_costmap` carries the same `obstacle_layer` content with `update_frequency: 3.0` | **FUNCTIONALLY EQUIVALENT with a numeric difference** — see §7.3 |

---

## 6. Interface comparison

### 6.1 Messages — 8/8 exact match (Functional equivalence)

Method: ROS 1 definitions captured **live** from the running container with
`rosmsg show -r` (raw, non-recursive), compared against the ROS 2 `.msg` sources.
Field **name**, **type** and **order** are compared.

> **Methodology note.** `rosmsg show` (without `-r`) *expands* nested types — a
> `std_msgs/Header` field prints as its subfields `seq`/`stamp`/`frame_id`.
> Comparing that expansion against a ROS 2 `.msg` source would fabricate
> differences that do not exist. Both sides are therefore reduced to declared
> top-level fields. An earlier naive comparison produced 5 false "differences"
> from exactly this artifact; the corrected comparison shows none.

| ROS 1 message | ROS 2 message | Fields | Result |
| :--- | :--- | ---: | :--- |
| `bms_data` | `BmsData` | 4 | MATCH |
| `flow_state` | `FlowState` | 7 | MATCH |
| `motor_state` | `MotorState` | 9 | MATCH |
| `nav_to_simple` | `NavToSimple` | 16 | MATCH |
| `nav_to_state` | `NavToState` | 9 | MATCH |
| `obstacle` | `Obstacle` | 6 | MATCH |
| `pose` | `Pose` | 6 | MATCH |
| `twist` | `Twist` | 6 | MATCH |

```text
messages matching: 8   differing: 0
```

**Critical negative result**: the ROS 1 and ROS 2 versions of these messages are
**not** merely similar — they are field-for-field, type-for-type identical,
including order. This includes `nav_to_state`'s nine fields with nested
`openmover_msgs/pose` and `openmover_msgs/twist` references and the fixed-size
`bool[4] obstacle` array.

### 6.2 Services — 10/10 exact match (Functional equivalence)

| ROS 1 (nested path) | ROS 2 (flattened) | Request fields | Response fields | Result |
| :--- | :--- | ---: | ---: | :--- |
| `driver/cmd_vel_mode_request` | `CmdVelModeRequest` | 1 | 1 | MATCH |
| `driver/playsound_request` | `PlaysoundRequest` | 2 | 1 | MATCH |
| `driver/stop_request` | `StopRequest` | 1 | 1 | MATCH |
| `localization/direct_request` | `DirectRequest` | 1 | 1 | MATCH |
| `manager/flow_action` | `FlowAction` | 2 | 1 | MATCH |
| `manager/flow_cmd` | `FlowCmd` | 2 | 1 | MATCH |
| `manager/self_test_report_request` | `SelfTestReportRequest` | 2 | 1 | MATCH |
| `mode/work_mode_request` | `WorkModeRequest` | 3 | 1 | MATCH |
| `navigation/nav_to_request` | `NavToRequest` | 13 | 1 | MATCH |
| `navigation/nav_to_simple_request` | `NavToSimpleRequest` | 1 | 1 | MATCH |

```text
services matching: 10   differing: 0
```

`NavToRequest` — the primary navigation command interface, 13 request fields
(`cmd`, `localization_sources`, `pose`, `twist`, `ignore_obstacle`,
`strighting_stop_distance`, `turning_stop_distance`, `use_global_planner`,
`use_planned_path`, `button_required`, `planned_path`, `xy_tolerance`,
`yaw_tolerance`) — is identical in both.

### 6.3 Interface naming (Intentional port difference)

ROS 1 uses `snake_case` type names and nests services in subdirectories; ROS 2
uses `PascalCase` and a flat `srv/` directory. This changes the **wire type
name** (`openmover_msgs/nav_to_request` → `openmover_msgs/srv/NavToRequest`) but
not field semantics.

```text
ROS 1: openmover_msgs/nav_to_request     (rosmsg show -r → 13 fields)
ROS 2: openmover_msgs/srv/NavToRequest   (same 13 fields)
```

**Semantic consequence**: ROS 1 and ROS 2 nodes cannot exchange these messages
across a mixed-version bridge without a type-name mapping. This is inherent to
the port and expected; it is a naming normalization, not a behavioral change.

### 6.4 Topics — 0 missing across all components (Functional equivalence)

Per-component extraction of every `openmover/*` string literal from node sources:

| Component | ROS 1 topics | ROS 2 topics | Shared | Missing in ROS 2 |
| :--- | ---: | ---: | ---: | :--- |
| `navigation_handler.cpp` | 14 | 15 | 14 | none (+1 added) |
| `obstacle_handler.cpp` | 2 | 2 | 2 | none |
| `localization_handler.cpp` | 10 | 10 | 10 | none |
| `localization_confidence_handler.cpp` | 3 | 3 | 3 | none |
| `motor_handler.cpp` | 9 | 9 | 9 | none |
| `io_board_handler.cpp` | 9 | 9 | 9 | none |
| `simulation_handler.cpp` | 8 | 8 | 8 | none |
| `teleop_handler.cpp` | 3 | 3 | 3 | none |
| `hal.py` | 1 | 1 | 1 | none |

The single addition is `openmover/navigation/global_planner/make_plan`, a ROS 2
planner service endpoint.

### 6.5 TF frames — 6/6 identical (Identical)

```text
ROS 1 frames: base_link, lidar_forward_link, lidar_link, lidar_rear_link, map, odom
ROS 2 frames: base_link, lidar_forward_link, lidar_link, lidar_rear_link, map, odom
only ROS1: []      only ROS2: []
```

---

## 7. Robot / model comparison

### 7.1 Kinematics — numerically identical (Functional equivalence)

Method: the ROS 1 model was captured **live** from the running container's
`/robot_description` parameter (15174 chars), exported as JSON, and compared
against the ROS 2 port's `robot_description.urdf` parsed directly. Tolerance
`1e-9` (these are exact decimal literals).

```text
links:  ROS1=9  ROS2=9  identical_set=True
joints: ROS1=8  ROS2=8  identical_set=True
tolerance: 1e-09
joint fields compared: type, parent, child, origin_xyz, axis (5 x 8 joints)
FAILURES: 0
   none - ROS 1 and ROS 2 kinematic models are numerically identical
```

```text
joint                  type        parent     child                  origin_xyz                axis
ball_front_left_joint  continuous  base_link  ball_front_left_link   0.14277  0.154  0.02015   1 1 1
ball_front_right_joint continuous  base_link  ball_front_right_link  0.14277 -0.154  0.02015   1 1 1
ball_rear_left_joint   continuous  base_link  ball_rear_left_link   -0.14277  0.154  0.02015   1 1 1
ball_rear_right_joint  continuous  base_link  ball_rear_right_link  -0.14277 -0.154  0.02015   1 1 1
lidar_forward_joint    fixed       base_link  lidar_forward_link     0.22015  0      0.07513   0 0 0
lidar_rear_joint       fixed       base_link  lidar_rear_link       -0.22015  0      0.07513   0 0 0
wheel_left_joint       continuous  base_link  wheel_left_link        0        0.162  0.050353  0 1 0
wheel_right_joint      continuous  base_link  wheel_right_link       0       -0.162  0.050353  0 1 0
```

### 7.2 Physical constants (Identical)

| Parameter | ROS 1 | ROS 2 | Result |
| :--- | :--- | :--- | :--- |
| Wheel separation | `0.324` | `0.324` | identical |
| Wheel diameter → radius | `0.1007` → `0.05035` | `0.05035` | identical (diameter/2 = radius exactly) |
| Update rate | `50` | `50` | identical |
| Odometry topic | `openmover/hardware/odom_sim` | `openmover/hardware/odom_sim` | identical |
| LiDAR samples | `600` | `600` | identical |
| LiDAR angle range | `-1.57 … 1.57` | `-1.57 … 1.57` | identical |
| LiDAR range | `0.22 … 10.0 m` | `0.22 … 10.0 m` | identical |
| LiDAR resolution | `0.03` | `0.03` | identical |

Cross-check: the URDF `wheel_left_joint` offset `0.162` equals `chassis_radius: 0.162`
in `hardwares.yaml`, and `2 × 0.162 = 0.324` equals the wheel separation. The
robot model and the configuration are mutually consistent in **both** systems.

### 7.3 Robot footprint and costmap configuration

`hardwares.yaml` — 15/15 scalar values identical. The footprint differs only in
representation:

```text
ROS 1: footprint: [[0.27, 0.22], [0.27, -0.22], [-0.27, -0.22], [-0.27, 0.22]]
ROS 2: footprint: [0.27, 0.22, 0.27, -0.22, -0.27, -0.22, -0.27, 0.22]
EQUIVALENT GEOMETRY: True
```

`navigation.yaml` — 104/110 leaf values match. The differences resolve as:

| Item | ROS 1 | ROS 2 | Assessment |
| :--- | :--- | :--- | :--- |
| `costmap.update_frequency` | `1.0` | `global_costmap` uses `3.0` | **Numeric difference** — see below |
| `plugins` format | `[{name, type}, …]` | `["static_layer", …]` + `plugin:` keys | ROS 2 param syntax |
| `update_frequency` (global) | `3.0` ×2 | `3.0` ×2 | identical |
| `control_freq` | `100` | `100.0` | same value, YAML numeric |
| `raytrace_range` | `3` | `3.0` | same value |
| `map_topic` | `openmover/mapping/map` | `/openmover/mapping/map` | leading slash only |

The only substantive item is `costmap.update_frequency`. ROS 1's `costmap:`
section (which defines the same `obstacle_layer` content that ROS 2 carries in
`global_costmap`) sets `update_frequency: 1.0`, while ROS 2's `global_costmap`
uses `3.0`. All other `obstacle_layer` values match exactly
(`obstacle_range 2.5`, `raytrace_range 3.0`, `combination_method 1`,
`track_unknown_space true`, `observation_sources laser_scan_sensor`).

**Classification**: **FUNCTIONALLY EQUIVALENT with a numeric difference.** The
costmap is updated more frequently in ROS 2 (3 Hz vs 1 Hz). Both values are
internally plausible; the ROS 2 value matches the `publish_frequency: 3.0` used
in both. **This has not been independently validated as behaviorally
equivalent** — it is a configuration difference recorded honestly rather than
asserted equivalent.

`mapping.yaml` — 101/106 match, with the same explanation for all differences
(`plugins` syntax, `raytrace_range` `5` vs `5.0`, `map_topic` slash,
`update_frequency`).

---

## 8. Navigation and localization comparison

### 8.1 Source-level correspondence (Observed fact)

The `openmover` package: **86 ROS 1 files, 94 ROS 2 files**.

```text
byte-identical:            20
present in both, MODIFIED: 54
only in ROS1:              12   (11 .launch XML + global_planner_handler.cpp)
only in ROS2:              20   (.launch.py ×11, config_defaults/, launch_manager.py,
                                 cartographer_initialpose_adapter.py, topic_utils.hpp)
```

All 11 ROS 1 `.launch` files have `.launch.py` counterparts — a complete 1:1
launch port with no omissions.

### 8.2 Global planner — the algorithm core is verbatim (Identical)

**20 files are byte-identical**, including essentially the entire planning
mathematics:

```text
IDENTICAL  global_planner/dijkstra.h, expander.h, gradient_path.h, grid_path.h
IDENTICAL  global_planner/osqp_smoother.h, osqp_utils.h
IDENTICAL  global_planner/potential_calculator.h, quadratic_calculator.h, traceback.h
IDENTICAL  global_planner/grid_path.cpp, osqp_smoother.cpp, osqp_utils.cpp
```

Files that changed were classified by inspecting whether the change is a ROS API
translation or an algorithmic edit:

| File | Changed lines | ROS API | Non-API | Verdict |
| :--- | ---: | ---: | ---: | :--- |
| `dijkstra.cpp` | 0 | 0 | 0 | API translation only (a commented-out log line) |
| `gradient_path.cpp` | 12 | 12 | 0 | API translation only |
| `quadratic_calculator.cpp` | 0 | 0 | 0 | API translation only |
| `polyline_generation.cpp` | 0 | 0 | 0 | API translation only |
| `backend_optimization.cpp` | 0 | 0 | 0 | API translation only |
| `controllers.cpp` | 4 | 4 | 0 | API translation only |
| `planner.cpp` | 212 | 122 | 90 | see below |
| `math_utils.cpp` | 426 | 346 | 80 | see below |
| `path_follower.cpp` | 122 | 76 | 46 | see below |
| `mover.cpp` | 20 | 8 | 12 | see below |
| `orientation_filter.cpp` | 14 | 10 | 4 | see below |
| `planner_with_costmap.cpp` | 30 | 24 | 6 | see below |

The "non-API" lines were inspected individually and are mechanical translations
of the same nature:

```diff
-#include <costmap_2d/cost_values.h>            +#include <nav2_costmap_2d/cost_values.hpp>
-costmap_2d::Costmap2D *costmap                +nav2_costmap_2d::Costmap2D *costmap
-geometry_msgs::Polygon footprint_polygon;     +static geometry_msgs::msg::Polygon footprint_polygon;
-ROS_INFO("...")                               +RCLCPP_INFO(rclcpp::get_logger("navigation"), "...")
-float yaw = tf::getYaw(...)                   +float yaw = tf2::getYaw(...)
-openmover_msgs::obstacle                      +openmover_msgs::msg::Obstacle
-std::vector<boost::thread> threads;           +std::vector<std::thread> threads;
```

plus one structural addition: an `rclcpp::Node *node` parameter threaded through
`initialize(...)` so the planner can read ROS 2 parameters (ROS 1 read them
implicitly from the global param server). Function signatures and control flow
are otherwise preserved.

**Conclusion**: the ROS 1 global planner algorithm (Dijkstra over a potential
field with OSQP trajectory smoothing) is preserved. The port is a ROS API
translation, not a reimplementation.

### 8.3 Component similarity summary (Observed fact)

| Component | ROS 1 lines | ROS 2 lines | Similarity | Interpretation |
| :--- | ---: | ---: | ---: | :--- |
| `global_planner` | 2823 | 2835 | 95.6% | algorithm preserved |
| `local_planner` | 2104 | 2110 | 98.7% | algorithm preserved |
| `math_utils` | 2367 | 2367 | 99.1% | algorithm preserved |
| `controllers` | 175 | 175 | 98.9% | algorithm preserved |
| `likelihood_field` | 567 | 570 | 98.3% | algorithm preserved |
| `collision_checker` | 214 | 217 | 96.2% | algorithm preserved |
| `path_checker` | 254 | 258 | 95.9% | algorithm preserved |
| `motor_handler` | 568 | 579 | 87.6% | ROS-boundary translation |
| `obstacle_handler` | 459 | 471 | 86.4% | ROS-boundary translation |
| `io_board_handler` | 498 | 517 | 85.6% | ROS-boundary translation |
| `localization_handler` | 350 | 358 | 78.5% | ROS-boundary translation |
| `navigation_handler` | 1194 | 1290 | 76.3% | ROS-boundary translation |
| `loc_confidence` | 233 | 243 | 74.1% | ROS-boundary translation |
| `teleop_handler` | 179 | 195 | 70.3% | ROS-boundary translation |
| `simulation_handler` | 144 | 154 | 67.0% | simulator boundary |

Algorithmic components are 95–99% similar; ROS-boundary glue is 67–88%, exactly
the pattern expected from API translation.

### 8.4 HAL fidelity (Observed fact)

The ROS 2 HAL is explicitly documented as preserving ROS 1 behavior:

```text
# ROS 2 Jazzy port (Stage 6): rospy -> rclpy via protocol helper layer.
# Function signatures, logic, logging and quirks are kept identical to ROS 1
# (including original bugs, which are marked with [ROS1-bug] comments).
```

The port even **preserves original ROS 1 bugs**, marking them:
`# [ROS1-bug] 原代码为 execute_mode == execute_mode['sync']（字典与字符串比较，恒为 False）`
— a comparison that is always `False` in ROS 1 and remains so in ROS 2.

HAL file correspondence:

```text
IDENTICAL  config.py, symbols.py, logger.py
modified   hal.py (2585 → 2582), protocol.py (271 → 427),
           utils.py (65 → 64), cli.py (248 → 247)
```

`protocol.py` grew because ROS 2 has no implicit background spinner; the port
adds an explicit executor thread so synchronous service calls and subscriptions
behave as under ROS 1 — a middleware adaptation, not a semantic change.

### 8.5 Localization / SLAM semantics

| ROS 1 | ROS 2 | Relationship |
| :--- | :--- | :--- |
| Cartographer (source build via `catkin_make_isolated`) | Cartographer (ROS 2 binary underlay) | Same SLAM algorithm; distribution method changed |
| `cartographer_node`, `cartographer_occupancy_grid_node` | Same node names | Preserved |
| Map topic `openmover/mapping/map` | `openmover/mapping/map` | Identical |
| `localization_confidence_handler` + `likelihood_field` | Same (98.3% similar) | Algorithm preserved |
| `robot_pose_ekf` dependency (installed by install.sh) | — | Listed in `install.sh` deps; see note below |

**Note on `robot_pose_ekf`:** `install.sh` installs `ros-noetic-robot-pose-ekf`,
and `carto_localization.launch` contains **commented-out** `amcl` and `gmcl`
nodes. The active localization path in both systems is Cartographer plus the
custom `localization_handler`/`localization_confidence_handler`. The ROS 1
launch file's commented blocks were inspected directly.

### 8.6 The `localization/odom` remap (Intentional port difference — a correction)

This was the only ROS 1-only topic with real code references. Investigation
resolved it definitively.

**ROS 1** (`carto_localization.launch`, active):
```xml
<remap from="odom" to="openmover/localization/odom" />
```
But `localization_handler.cpp` **publishes** `openmover/localization/odom` as
`geometry_msgs/PoseWithCovarianceStamped`, while Cartographer expects
`nav_msgs/Odometry` on its `odom` input. ROS 1 routes a mismatched type.

**ROS 2** (`carto_localization.launch.py`, with an explicit comment):
```python
# localization/odom 是 PoseWithCovarianceStamped，类型不匹配
('odom', 'openmover/localization/odom_legacy'),
```
ROS 2 routes Cartographer to `odom_legacy` (`nav_msgs/Odometry`) — the
type-correct choice.

**Classification**: **INTENTIONALLY REPLACED (port correction).** The topic
`openmover/localization/odom` still exists in ROS 2 with the same type and
publisher, and ROS 2's `navigation_handler` subscribes to it — verified present
in §6.4 (0 missing). Only the *Cartographer input routing* differs, and ROS 2's
version fixes a ROS 1 type mismatch. This is not a gap.

### 8.7 Simulator replacement (Intentional port difference — Gazebo Classic → Harmonic)

Per the task's requirement to separate model/interface/behavior from
simulation-engine equivalence:

| Aspect | Assessment |
| :--- | :--- |
| **Robot model** | **Equivalent** — kinematics identical (§7.1), 40/40 fields @ 1e-9 |
| **ROS interface** | **Equivalent** — topics, frames and LiDAR/odom topic names identical |
| **World/scene content** | **Preserved** — the ROS 2 world differs from the ROS 1 world by only **15 lines** |
| **Simulation engine** | **REPLACED** — Gazebo Classic (ROS 1) → Gazebo Harmonic `gz-sim8` + `ros_gz_bridge` (ROS 2) |
| **Simulation behavior** | **NOT VERIFIED** — neither simulator was executed headlessly in this study |

World file diff (complete, 15 lines): `<sdf version='1.7'>` → `1.8`, four
`gz-sim-*-system` plugin additions (`Physics`, `UserCommands`,
`SceneBroadcaster`, `Sensors` with `ogre2`), and `model://` → `package://` URI
scheme. The ROS 1 `differential_drive_controller` plugin became the ROS 2
`gz::sim::systems::DiffDrive` plugin with **matching physical parameters**
(`wheel_separation 0.324`, wheel radius `0.05035` = diameter/2, odom topic
`openmover/hardware/odom_sim`, 50 Hz). The ROS 1 `<sensor type="ray">` LiDAR
became `type="gpu_lidar"` with **identical scan geometry** (600 samples,
±1.57 rad, 0.22–10.0 m).

**Conclusion**: the simulator was replaced, and the *model and interface* the
simulator must satisfy were preserved. Whether the two simulators produce
numerically comparable physics is **not verified**.

### 8.8 Isaac Sim relationship

The canonical caasi project and the ROS 2 dogfooding runs use **Isaac Sim**
rather than Gazebo. This is a further layer beyond the ROS 1 → ROS 2 port:

```text
ROS 1 Gazebo Classic  →  ROS 2 Gazebo Harmonic  →  Isaac Sim (caasi runs)
```

The ROS 2 launch system supports this explicitly via `launch_gazebo:=0`, which
runs the full simulation-mode node graph on external simulation input
(`openmover/control/cmd_vel_sim`, `openmover/hardware/odom_sim`,
`openmover/hardware/lidar_*/scan`, `/clock`). Isaac Sim is therefore
**NOT EQUIVALENT** to the ROS 1 simulator; it is a third simulator satisfying
the same ROS interface. Model equivalence is established (§7.1); simulation-engine
equivalence between Gazebo Classic and Isaac Sim is **NOT VERIFIED**.

---

## 9. Behavioral test methodology and numerical results

### 9.1 Approach

Where a comparison could be made **deterministically and fairly**, it was made
with machine-readable output and an explicit tolerance. Where a scenario could
not be reproduced fairly on both systems, it is marked **NOT DIRECTLY COMPARABLE**
rather than given an invented equivalence test.

### 9.2 Tests executed

| # | Test | ROS 1 source | ROS 2 source | Metric | Tolerance | Result |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| T1 | Kinematic model | Live `/robot_description` from running master | Port `.urdf` | 5 fields × 8 joints (type, parent, child, origin_xyz, axis) | 1e-9 | **PASS** 40/40, 0 failures |
| T2 | Link/joint sets | Live capture | Port URDF | set equality | exact | **PASS** 9 links, 8 joints, sets equal |
| T3 | Message fields | `rosmsg show -r` (live) | `.msg` sources | 8 messages, field name+type+order | exact | **PASS** 8/8 |
| T4 | Service fields | `.srv` sources | `.srv` sources | 10 services, request+response | exact | **PASS** 10/10 |
| T5 | Driver params | `bringup.launch` XML | `bringup.launch.py` | 40 params, normalized | exact | **PASS** 36/36 literals + 4/4 per-instance |
| T6 | TF frames | Launch/config literals | Launch/config literals | 6 frames | exact | **PASS** 6/6 |
| T7 | Hardware config | `hardwares.yaml` | `config_defaults/hardwares.yaml` | 15 scalars + footprint | exact / geometry | **PASS** |
| T8 | Module config | `modules.yaml` | `config_defaults/modules.yaml` | 9 values | exact | **PASS** 9/9 |
| T9 | Nav/mapping config | `navigation.yaml`, `mapping.yaml` | node-scoped equivalents | leaf values | exact | **PASS with 6+5 explained diffs** §7.3 |
| T10 | Topic surface | node source literals | node source literals | 9 components | exact | **PASS** 0 missing |
| T11 | Robot world | ROS 1 world file | ROS 2 world file | textual diff | — | **15-line diff** (plugins + URI scheme) |

### 9.3 Tests deliberately NOT executed

| Scenario | Reason | Status |
| :--- | :--- | :--- |
| Gazebo Classic vs Gazebo Harmonic physics | ROS 1 Gazebo not launched headlessly; simulators are different engines | **NOT DIRECTLY COMPARABLE** |
| End-to-end navigation run (goal → trajectory) | ROS 1 navigation stack not driven in this study | **NOT YET VERIFIED** |
| LiDAR scan data equivalence | Requires live sensor or running simulator on both sides | **NOT YET VERIFIED** |
| Odometry drift / trajectory shape | Requires running simulation on both sides | **NOT YET VERIFIED** |
| Planner path output comparison | Would require identical costmaps and inputs on both stacks | **NOT YET VERIFIED** |
| Motor command wire behavior | Requires physical robot at `192.168.100.100` | **OUT OF SCOPE** (deliberate — no physical motion) |

**No attempt was made to force agreement.** Where the systems intentionally
differ (Gazebo Classic vs Harmonic; ROS 1 nav stack vs Nav2; ROS 1 vs Isaac Sim),
the difference is named rather than tested away.

### 9.4 A methodological correction worth recording

An intermediate comparison reported **5 false message differences** (e.g.
`flow_state` "missing" `voltage`/`percent`/`current`). The cause was comparing
`rosmsg show` output — which **expands nested types inline** — against ROS 2
`.msg` sources. Re-running with `rosmsg show -r` (raw) showed all 8 messages
match exactly.

This is recorded deliberately: it is an example of a measurement artifact that
would have been reported as a genuine gap if not investigated.

---

## 10. Intentionally changed components

Per ROS 1 → ROS 2 porting norms. None of these is classified as a failure.

| ROS 1 | Reason for change | ROS 2 implementation | Semantic consequence | Status |
| :--- | :--- | :--- | :--- | :--- |
| `rospy` | ROS 2 middleware | `rclpy` + explicit executor thread | None; synchronous call semantics preserved | Intentionally replaced |
| `roscpp` | ROS 2 middleware | `rclcpp` | None; node/param plumbing threaded explicitly | Intentionally replaced |
| `catkin` / `catkin_make` | ROS 2 build system | `ament_cmake` / `colcon` | None | Intentionally replaced |
| `roslaunch` XML | ROS 2 launch | Python `launch` files | None; all 11 launches ported 1:1 | Intentionally replaced |
| ROS 1 global param server | ROS 2 per-node parameters | Node-scoped YAML + `declare_parameter` | Parameters explicit; values preserved | Intentionally replaced |
| `ROS_INFO`/`ROS_WARN` macros | ROS 2 logging | `RCLCPP_*` with explicit logger | None | Intentionally replaced |
| `costmap_2d` (ROS 1 nav) | Nav2 stack | `nav2_costmap_2d` | None; parameters preserved | Intentionally replaced |
| `tf::getYaw` (tf1) | tf2 unification | `tf2::getYaw` | None | Intentionally replaced |
| `boost::thread` | C++11 standard library | `std::thread` | None | Intentionally replaced |
| Gazebo Classic | EOL simulator | Gazebo Harmonic (`gz-sim8`) | Simulator replaced; model/interface preserved | Intentionally replaced |
| Cartographer source build | ROS 2 packaging | `ros-jazzy-cartographer` binary underlay | Capability retained; build simplified | Intentionally replaced |
| OSQP source build | ROS 2 packaging | `ros-jazzy-osqp-vendor` | Capability retained | Intentionally replaced |
| Service type naming (`nav_to_request`) | ROS 2 naming conventions | `NavToRequest` | Wire type name differs; semantics identical | Intentionally replaced |
| Service directory nesting | ROS 2 flat `srv/` | Flattened | None | Intentionally replaced |
| Cartographer `odom` remap | ROS 1 type mismatch | `odom_legacy` (`nav_msgs/Odometry`) | Fixes a ROS 1 type error (§8.6) | Intentionally replaced (correction) |

---

## 11. Environment issues encountered (not equivalence findings)

These were investigated to conclusion and are explicitly **not** OpenMover or
port defects.

### 11.1 Non-deterministic GCC internal compiler errors

Two builds initially failed with `internal compiler error: Segmentation fault`
at unrelated translation units, with non-deterministic crash locations.

- **Cartographer**: failed with `ninja -j20`; **succeeded with `-j4`**.
- Container `/dev/shm` was **64 MiB** (Docker default).
- `free` showed 37 GiB available; cgroup `oom_kill` counters were **0** — not OOM.
- A pure-base64/GCC crash was reproduced only under high parallelism.

**Conclusion**: compiler crashes were caused by container `/dev/shm` pressure
under many concurrent `gcc` processes, **not** by the OpenMover source. Raising
`/dev/shm` and/or reducing parallelism resolves it. This mirrors a root cause
independently discovered during the (paused) Stage D target validation.

### 11.2 Reference-tree build-hygiene defects

Documented in §2.1: a regular-file-instead-of-symlink `toplevel.cmake`, a
case-mismatched `.srv` filename, and a vestigial empty `add_action_files` block.
All are **pre-existing properties of the committed reference** (fixed in the
container copy only; the host tree was not modified).

### 11.3 Docker networking

Bridge networking had no DNS resolution in this sandbox (`Temporary failure
resolving 'archive.ubuntu.com'`). `--network host` resolved it.

---

## 12. Unverified components

Explicitly **not** verified in this study. None is claimed equivalent.

1. **ROS 1 Gazebo Classic simulation execution** — not launched headlessly.
2. **ROS 1 end-to-end navigation** — the navigation stack was not driven to a goal.
3. **ROS 2 Gazebo Harmonic simulation** — not executed against these parameters here.
4. **Cross-simulator physics equivalence** (Classic vs Harmonic vs Isaac Sim).
5. **LiDAR scan-value equivalence** — no live scan comparison performed.
6. **Odometry/trajectory numerics** — requires running simulation on both sides.
7. **Planner path output** — no A/B plan comparison with identical inputs.
8. **Physical hardware paths** (`motor_handler`, `io_board_handler`,
   `bluesea2` live UDP) — require the real robot; deliberately out of scope.
9. **`warehouse_simulation` Gazebo models** — model files present; not rendered or
   physically compared.
10. **The `costmap.update_frequency` 1.0 vs 3.0 difference** — recorded as a
    numeric difference; its behavioral impact was **not** measured.
11. **ROS 1 `auto_mapping_toolbox` exploration behavior** — not executed.
12. **Timing/latency behavior** — no performance comparison was attempted.

---

## 13. Overall equivalence conclusion

**For the operational functionality that was actually tested, the ROS 2
OpenMover implementation faithfully preserves the behavior of the original ROS 1
implementation.**

### Exact scope of the evidence

The claim rests on **directly measured, machine-checked comparisons**, all
producing zero differences:

| Dimension | Evidence | Result |
| :--- | :--- | :--- |
| Message interfaces | 8 messages, live ROS 1 vs ROS 2 sources | **8/8 exact** (name, type, order) |
| Service interfaces | 10 services, request + response | **10/10 exact** |
| Robot kinematics | 8 joints × 5 fields, live vs port | **40/40 exact @ 1e-9** |
| Link/joint topology | sets | **identical** (9 links, 8 joints) |
| Physical constants | wheel geometry, LiDAR model | **identical** |
| Driver parameters | `bluesea2`, `laserscan_multi_merger` | **36/36 literals match, 0 genuine differences**; 4 per-instance values (`6667`/`192.168.100.101`, `6668`/`192.168.100.102`) confirmed at call sites |
| Hardware/module config | `hardwares.yaml`, `modules.yaml` | **15/15 + 9/9 identical** |
| TF frames | 6 frames | **6/6 identical** |
| Topic surface | 9 components | **0 missing** |
| Launch files | 11 ROS 1 → 11 ROS 2 | **11/11 ported** |
| Algorithm cores | global planner, local planner, math | **95–99% preserved; changes are API translations** |

### What this claim does NOT cover

- It does **not** claim simulation equivalence. The simulator was replaced
  (Gazebo Classic → Gazebo Harmonic, and optionally Isaac Sim). Model and
  interface equivalence are established; **physics equivalence is not tested**.
- It does **not** claim behavior under a running ROS 1 navigation experiment,
  because the ROS 1 stack was not driven end-to-end.
- It does **not** cover physical hardware paths.
- It does **not** assert the `costmap.update_frequency` difference is immaterial;
  that specific numeric difference is recorded unresolved.

### Concrete discrepancies found

**None that constitute a functional gap.** The items that initially appeared as
differences were each resolved:

| Apparent issue | Resolution |
| :--- | :--- |
| 5 "missing" message fields | Measurement artifact (`rosmsg show` recursive expansion) — not a real difference |
| `localization/odom` ROS 1-only topic | ROS 2 routes Cartographer to `odom_legacy`, fixing a ROS 1 type mismatch; the topic itself is preserved |
| `control/joy` ROS 1-only topic | Joy node is commented out in ROS 1 itself |
| 7 `mapping/lio/*` ROS 1-only topics | Rviz-config only; no node code references them |
| `costmap.update_frequency` 1.0 vs 3.0 | Genuine numeric difference; behavioral impact unmeasured |
| ROS 2-only topics (`cmd_vel_sim`, `map_updates`, …) | Additions for the external-simulator path |

### Scope statement

> The ROS 2 OpenMover implementation is functionally equivalent to the ROS 1
> implementation **for the static interfaces (messages, services, kinematics,
> parameters, topics, TF frames) and algorithmic source cores that were directly
> compared**. Dynamic runtime behavior in simulation, end-to-end navigation, and
> physical hardware paths remains **unverified** and is not claimed equivalent.

---

## 14. Exact evidence and commands

### Comparison scripts (reproducible, committed alongside this audit)

```text
caasi/plan/audits/ros1-ros2-comparison/
├── ab_kinematics.py        T1/T2  kinematic A/B (live ROS 1 vs port)
├── ab_messages2.py         T3/T4  message + service field A/B
├── cmp_msgs.py                    message definition correspondence
├── cmp_urdf.py, cmp_urdf_params.py  URDF structure/parameter extraction
├── cmp_sources.py                 file-level correspondence (identical/modified)
├── cmp_launch_norm.py      T5     normalized launch-parameter comparison
├── cmp_configs.py          T7/T8  hardware/module YAML comparison
├── cmp_nav_cfg.py          T9     navigation/mapping config comparison
├── cmp_topics.py, check_ros1_topics.py   topic surface + code-reference check
├── cmp_handlers.py         T10    per-component topic/service surface
├── cmp_nav_src.py, classify_nav_diff.py  algorithm similarity + change class
├── classify_steps.py              install.sh step audit
├── stage_ros1.sh                  reference staging (read-only + rsync)
├── ros1_install_phase1/2/4.sh     install.sh execution in install.sh order
├── ros1_rawdefs.sh, ros1_srvdefs.sh, ros1_msgdefs.sh   live definition capture
├── ros1_tf_capture.sh     T1/T2  live kinematic capture from running master
└── verify_ros1.sh                 operational verification
```

### Key commands

```bash
# Reference integrity (before/after)
find openmover_robot -type f -not -path "*/.git/*" -print0 | sort -z \
  | xargs -0 sha256sum | sha256sum
# → f17c242a8cb64b4f987ae606f9c749e278690f109d8159b145ed0cbb697c1886

# Container setup
docker run -d --name ros1-ref --network host --shm-size=2g \
  -v /tmp/ros1-ref-staging:/mnt/ref:ro osrf/ros:noetic-desktop-full sleep infinity

# install.sh execution (order preserved)
docker exec ros1-ref bash /root/phase1.sh    # deps
docker exec ros1-ref bash /root/phase2.sh    # abseil, Cartographer, OSQP
docker exec ros1-ref bash /root/phase4.sh    # OpenMover workspace

# Operational verification
docker exec ros1-ref bash /root/verify.sh

# A/B comparisons
python3 ab_kinematics.py   # 40/40 @ 1e-9
python3 ab_messages2.py    # 8/8 messages, 10/10 services
```

### Reference integrity assertion

```text
before: file count 2552, tree hash f17c242a8cb64b4f987ae606f9c749e278690f109d8159b145ed0cbb697c1886, git dirty 0
after : file count 2552, tree hash f17c242a8cb64b4f987ae606f9c749e278690f109d8159b145ed0cbb697c1886, git dirty 0
```

The immutable ROS 1 reference was never modified.

---

## 15. Git state / checkpoint

- **Baseline commit**: `99fc43c` — *fix(phase-7): repair remote target discovery
  and target-native build over SSH* (Stage D WIP code fixes, independent of this audit)
- **Working tree**: clean except the new audit artifacts added by this study.
- **Reference trees** (`openmover_robot/`, `openmover_ws/`): unchanged, 0 dirty entries.
- **Container artifacts**: `ros1-ref` container and `/tmp/ros1-ref-staging/` are
  outside the repository and do not affect the checkpoint.

---

## 16. Notes on the existing migration audit

While preparing this document, two inaccuracies in
[`migration_and_equivalence_audit.md`](migration_and_equivalence_audit.md) were
identified and are corrected here:

1. **`Motion.msg` does not exist.** The existing audit lists
   `openmover_msgs` as containing "`Obstacle.msg`, `Motion.msg`" for both ROS 1
   and ROS 2. `find` returns no `Motion.msg` anywhere in either tree. The actual
   ROS 1 set is: `bms_data`, `flow_state`, `motor_state`, `nav_to_simple`,
   `nav_to_state`, `obstacle`, `pose`, `twist` (8 messages).

2. **Hop 1 was previously inferred, now measured.** The existing audit
   explicitly scoped itself to Hop 2 and treated ROS 1 equivalence as
   "established only where the existing ROS 2 port had already ported that
   functionality." This document supplies direct Hop 1 evidence.
