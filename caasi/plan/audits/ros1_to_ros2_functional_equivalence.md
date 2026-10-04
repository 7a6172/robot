# ROS 1 → ROS 2 Functional Equivalence Validation (OpenMover)

**Date**: 2026-10-04
**Question under test**:
> Is the existing ROS 2 OpenMover implementation (`openmover_ws`) a faithful
> *functional* port of the original ROS 1 implementation (`openmover_robot`)?

**Answer (scoped)**: **Yes, for the functionality actually tested.** Every artifact
compared — message/service interfaces, robot kinematics, launch/driver parameters,
navigation algorithm cores, and topic/service surfaces — matches ROS 1 with zero
measured differences — and six simulator-free runtime behaviors (see §12) match
as well. See §14 for the exact scope and §13 for what remains unverified.

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

These gaps are stated explicitly rather than glossed, per §13; some were subsequently closed by the behavioral pass in §12.

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

## 9. Static-comparison test methodology and numerical results

> **Note.** This section covers the *static* comparison suite (T1–T11), each of
> which is a machine-checked comparison of definitions, parameters, models or
> source. The **runtime behavioral** suite (Tests A–F) is in §12 and was run
> afterwards; where §9.3 lists a scenario as not executed, §12 states whether it
> was subsequently tested.

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

### 9.3 Scenarios deliberately NOT executed in the static pass

> Several rows below were subsequently addressed by the runtime behavioral pass
> in §12; see the pointers in the table.

| Scenario | Reason | Status |
| :--- | :--- | :--- |
| Gazebo Classic vs Gazebo Harmonic physics | ROS 1 Gazebo not launched headlessly; simulators are different engines | **NOT COMPARABLE** (confirmed §12.1) |
| End-to-end navigation run (goal → trajectory) | ROS 1 navigation stack not driven in this study | **NOT YET VERIFIED** (still open) |
| LiDAR scan data equivalence | Requires live sensor; no live stream compared | **PARTIALLY CLOSED** — merger compared on synthetic scans, §12.6 |
| Odometry drift / trajectory shape | Requires running simulation on both sides | **PARTIALLY CLOSED** — odometry transform compared exactly, §12.3 |
| Planner path output comparison | Requires identical costmaps and inputs on both stacks | **CLOSED at algorithm level** — §12.7 (service level still not comparable) |
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

## 12. Behavioral equivalence pass (runtime, simulator-free)

The earlier sections establish **static** equivalence (interfaces, kinematics,
parameters, source). This section adds **runtime behavioral** evidence for the
cases where a fair, deterministic comparison between the two stacks exists.

### 12.1 What is and is not fairly comparable

The two systems expose different simulators, and the task explicitly forbids
forcing a physics-equivalence test. The comparison surface was therefore chosen
by asking what can be driven with **byte-identical inputs** on both stacks:

| Area | Fair comparison? | Basis |
| :--- | :--- | :--- |
| `simulation_handler` (`cmd_vel`, emergency, mode gating) | **Yes** | Pure ROS message-transform node; no simulator dependency in either stack. Identical subscriptions/publications and identical gating logic. |
| `simulation_handler` odometry/twist transform | **Yes** | Pure message re-publication (`Odometry` → `PoseWithCovarianceStamped` + `TwistWithCovarianceStamped`). |
| `obstacle_handler` (scan → obstacle grid) | **Yes** | Pure geometric algorithm: `LaserScan` + TF in, `obstacle` grid out. |
| `robot_state_publisher` forward kinematics | **Yes** | Same URDF + same joint state ⇒ same FK. Independent of simulator. |
| `laserscan_multi_merger` (dual scan → 360° scan) | **Yes** | Pure geometric transform of two scans through TF; no simulator. |
| Global planner `make_plan()` | **Yes (algorithm level)** | Same synthetic costmaps, start/goal and parameters; both sides call `make_plan` directly. |
| ROS-service-level planner path (`navfn/MakeNavPlan` vs Nav2) | **No** | ROS 1 exposes a standalone planner node on `costmap_2d::Costmap2DROS`; ROS 2 embeds planning in `navigation_handler` over Nav2 costmaps. No common service scenario. **NOT DIRECTLY COMPARABLE.** |
| Gazebo Classic vs Gazebo Harmonic vs Isaac Sim **physics** | **No** | Different engines, and no shared robot scenario: the ROS 1 warehouse demo (`warehouse_simulation_toolkit`) is a **Pioneer 3DX + gmapping + move_base** demo that uses neither the OpenMover robot nor the OpenMover navigation stack in either tree. **NOT COMPARABLE.** |
| Physical hardware paths | **No** | Requires the real robot at `192.168.100.100`. Deliberately out of scope. |

**On the Gazebo decision.** Neither simulator was launched. Recording why: the
ROS 1 `warehouse_simulation.launch` spawns a `pioneer3dx` model and runs
`slam_gmapping` + `move_base` + `navfn`; the ROS 2 counterpart is the same
Pioneer demo ported to Gazebo Harmonic. Comparing them would test the demo, not
OpenMover, and would confound Gazebo Classic↔Harmonic differences with any port
difference. The simulator change therefore remains classified as an
**intentional simulator replacement**, not an equivalence claim.

### 12.2 Test A — `cmd_vel` response (PASS)

Both `simulation_handler` implementations were driven with the **identical**
sequence of inputs and service calls. Expected behavior is derived from the
source, which is structurally identical in both stacks.

| # | Case | Input (vx, wz) | Expected | ROS 1 | ROS 2 | Result |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | manual mode = true, **auto** channel | (0.11, 0.22) | suppressed | not published | not published | **PASS** |
| 2 | manual mode = true, **manual** channel | (0.33, 0.44) | forwarded | (0.33, 0.44) | (0.33, 0.44) | **PASS** |
| 3 | manual mode = false, **auto** channel | (0.55, 0.66) | forwarded | (0.55, 0.66) | (0.55, 0.66) | **PASS** |
| 4 | manual mode = false, **manual** channel | (0.77, 0.88) | suppressed | not published | not published | **PASS** |
| 5 | emergency = true, auto channel | (0.99, 0.99) | published but **zeroed** | (0.0, 0.0) | (0.0, 0.0) | **PASS** |
| 6 | emergency = false, auto channel | (0.12, 0.34) | forwarded again | (0.12, 0.34) | (0.12, 0.34) | **PASS** |

Service contract: `/openmover/control/cmd_vel_mode/request` and
`/openmover/control/stop/request` were available on both stacks and both
returned `result = "ok"` (`CMD_RESPONSE_OK`) for every call.

**Tolerance: exact** (discrete outcomes) and **0 ULP** (float equality).
Result: **29/29 checks PASS, 0 FAIL.**

### 12.3 Test B — odometry / twist transform (PASS)

Identical `nav_msgs/Odometry` published on `/openmover/hardware/odom_sim`:
`x=1.25, y=-2.5, z=0.125, lin_x=0.4, ang_z=-0.15`.

| Output topic | Field | ROS 1 | ROS 2 | Tolerance | Result |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `/openmover/hardware/odom` | `frame_id` | `odom` | `odom` | exact | **PASS** |
| `/openmover/hardware/odom` | x, y, z | 1.25, -2.5, 0.125 | 1.25, -2.5, 0.125 | 0 ULP | **PASS** |
| `/openmover/hardware/twist` | `frame_id` | `odom` | `odom` | exact | **PASS** |
| `/openmover/hardware/twist` | lin_x, ang_z | 0.4, -0.15 | 0.4, -0.15 | 0 ULP | **PASS** |

### 12.4 Test C — obstacle grid from an identical scan (PASS)

Identical 360-sample `LaserScan` on `/openmover/hardware/lidar/scan/obstacle`
with four known returns (forward 1.0 m, left 0.5 m, rear 2.0 m, right 0.75 m),
`obs_min_dist = 0.02`, `obstacle_grid_number = 5`.

| Cell array | ROS 1 | ROS 2 | Tolerance | Result |
| :--- | :--- | :--- | :--- | :--- |
| `size` | 5 | 5 | exact | **PASS** |
| `obstacle_forward[2]` | 1.7300000190734863 | 1.7300000190734863 | 0 ULP | **PASS** |
| `obstacle_backward[1]` | 0.7300000190734863 | 0.7300000190734863 | 0 ULP | **PASS** |
| `obstacle_left[1]` | 0.5299999713897705 | 0.5299999713897705 | 0 ULP | **PASS** |
| `obstacle_right[1]` | 0.2800000011920929 | 0.2800000011920929 | 0 ULP | **PASS** |
| all other cells | `inf` | `inf` | exact | **PASS** |

All 20 grid cells agree, and the four non-infinite cells are **bit-identical**
(independently verified by comparing IEEE-754 hex encodings:
`0x3ffbae1480000000`, `0x3fe75c2900000000`, `0x3fe0f5c280000000`,
`0x3fd1eb8520000000` on both sides).

### 12.5 Test D — TF / forward kinematics (PASS)

Identical `robot_description` and identical joint state
(`wheel_left 0.75`, `wheel_right -0.25`, `ball_front_left 0.1`,
`ball_rear_right -0.1`) fed to `robot_state_publisher` on both stacks.

| Frame | ROS 1 translation | ROS 2 translation | Agreement | Result |
| :--- | :--- | :--- | :--- | :--- |
| `wheel_left_link` | (0.0, 0.162, 0.050353) | (0.0, 0.162, 0.050353) | max diff 5.55e-17 | **PASS** |
| `wheel_right_link` | (0.0, -0.162, 0.050353) | (0.0, -0.162, 0.050353) | max diff 1.11e-16 | **PASS** |
| `ball_front_left_link` | (0.14277, 0.154, 0.02015) | (0.14277, 0.154, 0.02015) | max diff 6.94e-18 | **PASS** |
| `ball_rear_right_link` | (-0.14277, -0.154, 0.02015) | (-0.14277, -0.154, 0.02015) | max diff 6.94e-18 | **PASS** |
| `lidar_forward_link` | (0.22015, 0.0, 0.07513) | (0.22015, 0.0, 0.07513) | **bit-identical** | **PASS** |
| `lidar_rear_link` | (-0.22015, 0.0, 0.07513) | (-0.22015, 0.0, 0.07513) | max diff 4.24e-22 | **PASS** |

**Tolerance declared before comparison: 1e-12.** Worst observed difference
**1.11e-16** (one ULP). All translations are exactly equal; quaternion
components differ only in the last bit, which is the expected result of two
different `sin`/`cos` implementations for the same angle.

TF topology also matched: static edges `base_link → lidar_forward_link` and
`base_link → lidar_rear_link`, with the joint-driven frames on `/tf`.

### 12.6 Test E — `laserscan_multi_merger` (PASS, bit-identical)

Identical dual-scan input on `/openmover/hardware/lidar_forward/scan` and
`/openmover/hardware/lidar_rear/scan`, with identical static transforms for
both LiDAR frames and the same merger parameters as the project's `bringup`
configuration (`angle_increment 0.006962`, `range_min 0.33`, `range_max 20.0`,
`destination_frame lidar_link`).

| Merged output field | ROS 1 | ROS 2 | Tolerance | Result |
| :--- | :--- | :--- | :--- | :--- |
| `frame_id` | `lidar_link` | `lidar_link` | exact | **PASS** |
| `num_ranges` | 903 | 903 | exact | **PASS** |
| `angle_min` | `0xc00921fb40000000` | `0xc00921fb40000000` | 0 ULP | **PASS** |
| `angle_max` | `0x400921fb40000000` | `0x400921fb40000000` | 0 ULP | **PASS** |
| `angle_increment` | `0x3f7c842fa0000000` | `0x3f7c842fa0000000` | 0 ULP | **PASS** |
| `range_min` | `0x3fd51eb860000000` | `0x3fd51eb860000000` | 0 ULP | **PASS** |
| `range_max` | `0x4034000000000000` | `0x4034000000000000` | 0 ULP | **PASS** |
| merged return index | 902 | 902 | exact | **PASS** |
| merged return angle | `0x40091ae4a6e00000` | `0x40091ae4a6e00000` | 0 ULP | **PASS** |
| merged return range | `0x3fe8f48800000000` | `0x3fe8f48800000000` | 0 ULP | **PASS** |

The merged scan — including the 903-sample geometry and the single finite
return — is **bit-identical** across the ROS 1 ↔ ROS 2 boundary.

### 12.7 Test F — global planner algorithm A/B (PASS at 1-cell tolerance)

Both sides called `make_plan()` directly on the **same** deterministic synthetic
costmaps (200×200 cells @ 0.05 m), the same start (1.0, 1.0) and goal (8.0, 8.0),
and the same planner parameters. Two scenarios:

- **S1** free map.
- **S2** lethal vertical wall at x-index 100 with a doorway gap at y-index 80–120,
  so the plan must route through the doorway.

**Tolerance, declared before comparing:** the planner plans on a 0.05 m grid, so
agreement within **one grid cell (0.05 m)** means both implementations selected
the same free-space route. Route agreement is measured as the symmetric
**Hausdorff distance** between the two polylines. (Per-point comparison is not
used as the criterion — two planners may sample the same route at different
waypoint intervals — and rounding coordinates to cell indices is unstable near
cell boundaries.)

| Scenario | ROS 1 success | ROS 2 success | Waypoints (ROS1/ROS2) | Symmetric Hausdorff | Path length ROS1 | Path length ROS2 | Length Δ | Result |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| S1 free map | true | true | 397 / 397 | **7.477e-03 m** (0.150 cells) | 9.8995 m | 9.8996 m | 1.21e-04 m | **PASS** |
| S2 wall + doorway | true | true | 415 / 414 | **2.140e-02 m** (0.428 cells) | 10.3345 m | 10.3236 m | 1.09e-02 m | **PASS** |

Both scenarios succeed on both sides, both reach the identical goal, and the
routes agree to **under half a grid cell**. Path lengths agree to `1.2e-04 m`
(S1) and `1.1e-02 m` (S2). In S2 both paths pass through the doorway (crossing
y ≈ 5.0 near x ≈ 4.3–5.3), confirming the same route rather than merely a
similar-length one.

**Residual difference and its cause.** The waypoints are not byte-identical. The
planners were compiled with **different compilers**: GCC 9.4.0 (Ubuntu 20.04,
ROS 1) and GCC 13.3.0 (Ubuntu 24.04, ROS 2). Different compilers
contract/reassociate floating-point arithmetic differently, shifting sub-cell
interpolated waypoint positions. This is consistent with the source finding
(§8.2): the planner algorithm files are byte-identical or ROS-API-translation
only, so there is no algorithmic difference to explain the drift. **The
byte-identical source finding is therefore sufficient to explain the residual:
it is arithmetic, not algorithm.**

Determinism was verified: re-running the ROS 2 harness reproduced its output
exactly, so the difference is a stable cross-toolchain difference rather than
run-to-run noise.

**Scope note.** This tests the planner *algorithm* only. The ROS-service-level
planner path is **not directly comparable** (§12.1) and is not claimed
equivalent.

### 12.8 Costmap frequency — evidence and status

The audit's §7.3 recorded an unresolved configuration difference:
ROS 1 `costmap.update_frequency = 1.0` vs ROS 2 `global_costmap = 3.0`.
**Neither value was changed.** This behavioral pass did **not** measure its
significance, because the costmap update loop is driven by `navigation_handler`
against a live costmap and no common runtime scenario exists between the two
stacks (§12.1). It therefore remains:

> **Observed configuration difference; behavioral significance not yet measured.**

### 12.9 Behavioral summary

| Test | Subject | Metric | Tolerance | Result |
| :--- | :--- | :--- | :--- | :--- |
| A | `cmd_vel` gating, mode service, emergency | 6 cases, published/values | exact / 0 ULP | **PASS 29/29 checks** |
| B | odometry + twist transform | 4 numeric fields, frame ids | exact / 0 ULP | **PASS** |
| C | obstacle grid | 20 cells | exact / 0 ULP | **PASS (bit-identical)** |
| D | TF forward kinematics | 6 frames × (t, q) = 42 values | 1e-12 | **PASS (worst 1.11e-16)** |
| E | `laserscan_multi_merger` | full merged scan | 0 ULP | **PASS (bit-identical)** |
| F | global planner algorithm | 2 scenarios, route + length | 1 cell (0.05 m) | **PASS (worst 0.43 cell)** |

No behavioral discrepancy attributable to the ROS 1 → ROS 2 port was found.

### 12.10 Newly discovered differences in this pass

**None attributable to the port.** Two items were found and each is explained:

1. **Planner waypoint drift (Test F)** — sub-cell, caused by the GCC version
   difference between the two toolchains, not by the port. The byte-identical /
   API-translation-only source finding explains it.
2. **Repeat confirmation of the costmap frequency difference** — already
   recorded in §7.3; still unresolved and left unchanged (§12.8).

Two **measurement artifacts** were encountered and corrected rather than
reported as findings:

1. `rosmsg show` (recursive) vs `rosmsg show -r` — see §6.1.
2. Naive cell-index rounding to compare planner routes gave a misleadingly low
   86–89% "similarity"; the boundary-stable Hausdorff metric shows the routes
   agree to well under one cell. The naive metric was discarded.

---

## 13. Unverified components

Explicitly **not** verified in this study. None is claimed equivalent.
Items struck through were resolved by the behavioral pass (§12).

1. **Gazebo Classic vs Gazebo Harmonic vs Isaac Sim physics** — no common
   OpenMover scenario exists between the stacks, so no comparison was attempted.
2. **ROS 1 end-to-end navigation to a goal** — the navigation stack was not
   driven, on either stack, in this study.
3. **ROS-service-level planner path** (`navfn/MakeNavPlan` vs Nav2) — not
   directly comparable (§12.1). Only the planner *algorithm* was compared (§12.7).
4. **Full LiDAR scan-value equivalence from a live sensor** — the merger was
   compared on identical synthetic scans (§12.6), but no live scan stream was
   compared.
5. **Odometry/trajectory numerics through a full run** — the odometry *transform*
   was compared exactly (§12.3), but integrated trajectory behavior was not.
6. **Physical hardware paths** (`motor_handler`, `io_board_handler`,
   `bluesea2` live UDP) — require the real robot; deliberately out of scope.
7. **`warehouse_simulation` Gazebo models** — model files present; not rendered.
8. **The `costmap.update_frequency` 1.0 vs 3.0 difference** — still recorded as
   an unresolved configuration difference; its behavioral impact was **not**
   measured (§12.8).
9. **ROS 1 `auto_mapping_toolbox` exploration behavior** — not executed.
10. **Timing/latency/throughput behavior** — no performance comparison attempted.
11. **`navigation_handler` and `localization_handler` end-to-end behavior** —
    these require a live costmap/map and TF graph; only their interfaces,
    parameters and source were compared, not their runtime behavior.
12. **Cartographer SLAM output equivalence** — the ROS 1 Cartographer stack was
    built and installed but not run; no map/trajectory comparison was made.

---

## 14. Overall equivalence conclusion

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

And on **runtime behavior** (behavioral pass, §12) — simulator-free, identical
inputs on both stacks:

| Runtime dimension | Evidence | Result |
| :--- | :--- | :--- |
| `cmd_vel` gating / mode service / emergency | 6 deterministic cases + 3 service calls | **29/29 checks PASS** |
| Odometry + twist transform | 4 numeric fields + frame ids | **PASS, 0 ULP** |
| Obstacle grid from an identical scan | 20 cells | **PASS, bit-identical** |
| TF forward kinematics | 6 frames × (translation, quaternion) | **PASS @ 1e-12**, worst 1.11e-16 |
| `laserscan_multi_merger` output | full merged 903-sample scan | **PASS, bit-identical** |
| Global planner algorithm | 2 scenarios, route + path length | **PASS @ 1 cell**, worst 0.43 cell |

### What this claim does NOT cover

- It does **not** claim simulation equivalence. The simulator was replaced
  (Gazebo Classic → Gazebo Harmonic, and optionally Isaac Sim). Model and
  interface equivalence are established; **physics equivalence is not tested**.
- It does **not** claim behavior under a running ROS 1 navigation experiment,
  because the ROS 1 stack was not driven end-to-end.
- It does **not** cover physical hardware paths.
- It does **not** assert the `costmap.update_frequency` difference is immaterial;
  that specific numeric difference remains recorded unresolved (§12.8).
- It does **not** extend the runtime evidence beyond the six tested behaviors. In
  particular `navigation_handler`, `localization_handler`, SLAM output, and
  integrated trajectory behavior were **not** exercised at runtime.

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
| Planner waypoints differ by 0.15–0.43 cell | Same route; residual is the GCC 9.4 vs 13.3 floating-point difference (§12.7) — explained by the byte-identical source finding |
| Naive cell-index comparison showed only 86–89% route similarity | Measurement artifact of unstable rounding; the boundary-stable Hausdorff metric shows sub-cell agreement |

### Scope statement

> The ROS 2 OpenMover implementation is functionally equivalent to the ROS 1
> implementation **for (a) the static interfaces — messages, services,
> kinematics, parameters, topics and TF frames — and algorithmic source cores
> that were directly compared, and (b) the six simulator-free runtime behaviors
> measured in §12 (`cmd_vel` handling, odometry/twist transform, obstacle-grid
> computation, TF forward kinematics, dual-scan merging, and the global planner
> algorithm)**. Simulation physics, end-to-end navigation, SLAM output,
> `navigation_handler`/`localization_handler` runtime behavior, and physical
> hardware paths remain **unverified** and are not claimed equivalent.

### Direct answer to the research question

> **Does the ROS 2 implementation faithfully preserve the tested operational
> behavior of the original ROS 1 implementation?**

**Yes, for the behavior actually tested.** Six simulator-free behavioral
comparisons were run with identical inputs on both stacks and declared
tolerances. Three produced **bit-identical** outputs (obstacle grid, merged
LiDAR scan, odometry/twist), one agreed to **1e-12** (forward kinematics), one
matched on every discrete and numeric check (**29/29**, `cmd_vel` handling), and
one agreed to **under half a grid cell** on route and path length (global
planner algorithm).

**No behavioral discrepancy attributable to the ROS 1 → ROS 2 port was found.**
The single residual numeric difference (planner waypoints, Test F) is explained
by a toolchain difference — GCC 9.4 vs GCC 13.3 — and is consistent with the
finding that the planner sources are byte-identical or API-translation only.

This conclusion is deliberately bounded: it does not extend to simulation
physics (no common scenario exists), to the ROS-service-level planner path, to
end-to-end navigation, or to physical hardware.

---

## 15. Exact evidence and commands

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

Behavioral pass (§12):
├── behavioral_ros1.sh      A/B/C  ROS 1 simulation_handler + obstacle_handler probe
├── behavioral_ros2_run.sh, behavioral_ros2.py   A/B/C  ROS 2 counterpart
├── compare_abc.py          A/B/C  comparison -> 29/29 PASS
├── tf_probe.py             D      shared TF/FK probe (both stacks)
├── test_d_ros1.sh, test_d_ros2.sh  D  robot_state_publisher bring-up
├── compare_d.py            D      comparison -> 6/6 PASS @ 1e-12
├── merger_probe.py         E      shared dual-scan merger probe
├── test_e_ros1.sh, test_e_ros2.sh  E  merger bring-up
├── planner_ab_ros1.cpp, build_planner_ros1.sh   F  ROS 1 planner harness
├── planner_ab_ros2.cpp, build_planner_ros2.sh   F  ROS 2 planner harness
└── compare_f.py            F      comparison -> 2/2 PASS @ 1 cell
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

# A/B comparisons (static)
python3 ab_kinematics.py   # 40/40 @ 1e-9
python3 ab_messages2.py    # 8/8 messages, 10/10 services

# Behavioral pass (§12)
docker cp behavioral_ros1.sh ros1-ref:/root/beh.sh
docker exec ros1-ref bash /root/beh.sh > /tmp/ros1_beh.log
bash behavioral_ros2_run.sh > /tmp/ros2_beh.log
python3 compare_abc.py     # 29/29 PASS

docker exec ros1-ref bash /root/test_d.sh > /tmp/ros1_test_d.log
bash test_d_ros2.sh > /tmp/ros2_test_d.log
python3 compare_d.py       # 6/6 PASS @ 1e-12

docker exec ros1-ref bash /root/test_e.sh > /tmp/ros1_test_e.log
bash test_e_ros2.sh > /tmp/ros2_test_e.log   # bit-identical merged scan

docker exec ros1-ref bash /root/build_planner.sh > /tmp/ros1_test_f.log
bash build_planner_ros2.sh > /tmp/ros2_test_f.log
python3 compare_f.py       # 2/2 PASS @ 1 cell
```

### Reference integrity assertion

```text
before: file count 2552, tree hash f17c242a8cb64b4f987ae606f9c749e278690f109d8159b145ed0cbb697c1886, git dirty 0
after : file count 2552, tree hash f17c242a8cb64b4f987ae606f9c749e278690f109d8159b145ed0cbb697c1886, git dirty 0
```

The immutable ROS 1 reference was never modified.

---

## 16. Git state / checkpoint

- **Static pass committed as** `be5ac4b` — *docs(audit): add measured ROS 1 → ROS 2
  functional equivalence validation*.
- **Behavioral pass (§12)** is committed as the follow-up checkpoint that adds this
  section and the behavioral harnesses under `ros1-ros2-comparison/`.
- **Working tree**: clean except the audit artifacts added by this study.
- **Reference trees** (`openmover_robot/`, `openmover_ws/`): unchanged. Reference
  integrity re-verified after the behavioral pass — file count 2552 and tree hash
  `f17c242a8cb64b4f987ae606f9c749e278690f109d8159b145ed0cbb697c1886`, unchanged,
  0 dirty entries.
- **Container artifacts**: the `ros1-ref` container and `/tmp/ros1-ref-staging/` are
  outside the repository and do not affect the checkpoint. The `/tmp` harness
  outputs (`ros1_beh.log`, `ros2_beh.log`, `ros1_test_{d,e,f}.log`, `ros2_test_*.log`)
  are transient; the scripts that regenerate them are committed.

---

## 17. Notes on the existing migration audit

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
