# Phase 8 Gate 1: Four-Way Source Discrepancy Report

**Status:** Completed (read-only investigation — no builds, no deployments, no hardware activation, no motion)
**Date:** 2026-10-25
**Scope:** Robot ROS 1 snapshot vs Lab ROS 1 vs Lab ROS 2 reference vs CAASI ROS 2
**Method:** Static source inspection + read-only remote filesystem inspection over Wi-Fi. **No runtime behaviour was observed.** Everything below is source-derived unless explicitly marked OBSERVED.

---

## 0. Headline

**The robot is a physically different vehicle running a different codebase from the lab OpenMover.**
The existing CAASI ROS 2 port is a faithful port of the *lab* robot and is **not** a port of the
robot now in front of us. However, the two codebases share a **direct lineage**: the robot's
`motor_node.cpp` is a **~78 % fork** of the lab's `motor_handler.cpp` with a **byte-identical wire
protocol**. This makes a port far more tractable than "two unrelated robots" would imply.

---

## 1. Provenance record

| # | Implementation | Path | Revision / identity | Files | Snapshot |
|---|---|---|---|---|---|
| 1 | **Robot ROS 1** | `caasi-workspace/openmover_robot_spec/src/` ← `swjtumover@10.212.19.95:/mnt/ubuntu20/home/swjtumover/swjtumover/swjtumover_ws/src` (`/dev/sda2`) | **no VCS** (plain files) | 696 | 2026-10-25T23:27+08, tree `9d46a6c515dc74ae1d136baadfdb503a3e06fe8cd61ad915d189601c0b29b78d` |
| 2 | **Lab ROS 1** | `openmover_robot/` | parent repo `79dc52f80f156b36c1383a5cb19315dc87eb858e` (2026-10-03) | 2577 | read-only, untouched |
| 3 | **Lab ROS 2 reference** | `openmover_ws/` | parent repo `79dc52f80f156b36c1383a5cb19315dc87eb858e` | 6769 | read-only, untouched |
| 4 | **CAASI ROS 2** | `caasi-workspace/openmover/` | parent repo `8c86c0aa4cf7411a0d9490a79629d1d9f0a5744c` (2026-10-04) | 4512 | writable working tree |

Snapshot integrity: `SNAPSHOT-MANIFEST.txt` beside the snapshot records per-file SHA-256 and the
aggregate tree hash. The source on `/dev/sda2` was **never written to** — the copy was one-way
`rsync -a` to the workstation.

**No git history exists in the robot source.** "Which implementation is running" cannot be
answered from revision metadata; it is answered below from launch configuration and file presence.

---

## 2. Package topology — zero overlap

| Robot (`swjtumover_ws`) | Lab ROS 1 (`openmover_ws`) |
|---|---|
| `swjtumover_bringup` | `openmover` |
| `swjtumover_msgs` | `openmover_msgs` |
| `vanjee_lidar_sdk` (+ `vanjee_lidar_msg`) | `bluesea2` |
| — | `ira_laser_tools` |
| — | `auto_mapping_toolbox` (+ `_msgs`) |
| — | `relocalization_toolbox` (+ `_msgs`) |
| — | `warehouse_simulation` |

**Confirmed:** the package name sets are disjoint. `grep -ri "vanjee|swjtumover"` across
`openmover_robot/` and `openmover_ws/` returns **zero** matches, and vice versa.

---

## 3. Hardware — confirmed physical divergence

### 3.1 Chassis geometry (CONFIRMED — derived from URDF joint origins)

| | Robot `swjtumover05` | Lab OpenMover |
|---|---|---|
| links | **8** | 9 |
| wheel separation | **0.2060 m** (2 × 0.103) | **0.3240 m** (2 × 0.162) |
| wheel radius (URDF z) | 0.050346 m | 0.050353 m |
| LiDAR links | **1** — `lidar_link` | **2** — `lidar_forward_link`, `lidar_rear_link` |
| caster | 4 × ball, axis `1 1 1`, offset 0.10843/0.1 | 4 × ball, axis `1 1 1`, offset 0.14277/0.154 |
| `base_link` mass | 3.747 kg | (differs) |

**Conclusion:** different chassis, different track width (36 % narrower), single LiDAR instead of
dual. No geometric parameter of the lab robot applies to the robot.

### 3.2 LiDAR — vendor and protocol are entirely different

| | Robot | Lab |
|---|---|---|
| driver | **`vanjee_lidar_sdk`** (Vanjee 718H) | `bluesea2` |
| instances | 1 | 2 (forward + rear) |
| transport | **UDP**, `lidar_address 192.168.110.100`, `host_address 192.168.110.10`, ports 7000/5000 | UDP unicast/multicast `192.168.100.101`/`.102:502` |
| output | `scan` (LaserScan), `pointcloud` optional | 2 × scan, merged by `laserscan_multi_merger` into one 360° scan |
| merge step | **none — no merger needed** | `ira_laser_tools` required |
| frame | `lidar_link` | `lidar_forward_link` / `lidar_rear_link` |

> **GOOD NEWS (CONFIRMED):** `vanjee_lidar_sdk` is **vendor dual-target**. It ships
> `package_ros1.xml` *and* `package_ros2.xml`, and `CMakeLists.txt` performs runtime detection:
> `find_package(roscpp QUIET)` → `-DROS_FOUND`; `find_package(rclcpp QUIET)` **AND**
> `COMPILE_METHOD STREQUAL "COLCON"` → `-DROS2_FOUND`. The node source is conditionally compiled
> (`#ifdef ROS_FOUND` / `#ifdef ROS2_FOUND`). **A ROS 2 build path already exists upstream** —
> this subsystem may not need to be ported at all, only built with colcon.

### 3.3 Motor controller — **protocol identical, node forked** (see §5)

### 3.4 Camera — different device, different driver

| | Robot | Lab |
|---|---|---|
| hardware | **Intel RealSense D415** (`8086:0ad3`, on USB — verified via `lsusb`) | V4L2 USB HIK 2K (`2bdf:028a`) |
| driver | `realsense2_camera` → `rs_camera.launch` (640×480 @30 fps, align_depth, pointcloud filter, clip 3.0 m) | custom V4L2 capture |
| topics | `/d415/color/image_raw`, `/d415/depth/image_rect_raw` | (lab equivalent differs) |

RealSense is **USB-attached and physically present**. It does **not** require Ethernet.

### 3.5 Chassis IO — only the robot has this

`screen_node.cpp`: UDP socket to the **same** `192.168.100.100`, **port 26**, 5 Hz, subscribing
`qrcode_text` (`std_msgs/String`). The lab uses `io_board_handler` (port 26, BMS/e-stop/lift)
instead — **different device, same IP**.

### 3.6 Network requirements — CONFIRMED, and currently unmet

| Device | Address | Transport | Status now |
|---|---|---|---|
| motor board | `192.168.100.100:23` | UDP | **UNREACHABLE** |
| screen/IO board | `192.168.100.100:26` | UDP | **UNREACHABLE** |
| Vanjee LiDAR | `192.168.110.100` → host must hold `192.168.110.10` | UDP | **UNREACHABLE** |
| RealSense D415 | USB | — | present |

`enp1s0` and `enp3s0` are both **DOWN**; **no `192.168.x` address exists on any interface**.
These are **two different subnets** (`.100` and `.110`). *Source-derived, not physically tested.*

---

## 4. ROS interface surface

### 4.1 Robot nodes and their interfaces (from source)

| Node | Topics published | Topics subscribed | Params |
|---|---|---|---|
| `motor_node` | `odom` (`nav_msgs/Odometry`), `motor_state/left`, `motor_state/right` (`swjtumover_msgs/motor_state`) | `cmd_vel` (`geometry_msgs/Twist`) | `~/motor/*` (10 params) |
| `screen_node` | — (UDP out) | `qrcode_text` (`std_msgs/String`) | `~/screen/*` (3) |
| `teleop_node.py` | `cmd_vel` | keyboard via `pynput` | `~/teleop/*` (7) |
| `vanjee_lidar_sdk_node` | `scan` (`sensor_msgs/LaserScan`), `pointcloud` | — | `config_path` → `lidar.yaml` |
| `robot_state_publisher` | `/tf`, `/tf_static` | `/joint_states` | `robot_description` |
| `joint_state_publisher` | `/joint_states` | — | — |
| `realsense2_camera` | `/d415/*` | — | launch args |

**Total robot topic surface: `cmd_vel`, `odom`, `motor_state/left`, `motor_state/right`,
`qrcode_text`, `scan`, `/tf`, `/tf_static`, `/joint_states`, `/d415/color/image_raw`,
`/d415/depth/image_rect_raw`.**

### 4.2 TF tree

- **Robot:** `odom` → `base_link` (broadcast by `motor_node` when `publish_tf: true`) →
  `lidar_link` (URDF fixed), wheels + 4 balls (URDF).
- **Lab:** `odom` → `base_link` → `lidar_forward_link` / `lidar_rear_link`.
- Frame constants: robot `robot_frames.h` defines `odom`, `map`, `base_link`, **`lidar_link`** —
  the lab has no `lidar_link`.

### 4.3 Messages

| Robot | Lab ROS 1 | Lab ROS 2 (`openmover_msgs`) |
|---|---|---|
| `swjtumover_msgs/motor_state` (1 msg, 9 fields) | 8 msg + 10 srv | 8 `.msg` + 11 `.srv` |
| `vanjee_lidar_msg` (from SDK) | — | — |
| `swjtumover_bringup/msg`, `/srv`, `/action` — **all empty dirs** | — | — |

> **KEY FINDING (CONFIRMED):** `swjtumover_msgs/msg/motor_state.msg` is **field-for-field
> identical** to CAASI ROS 2 `openmover_msgs/msg/MotorState.msg` (header, phase_current, rpm,
> position_deg, and the five fault booleans). This is strong evidence of a **common ancestor**,
> not coincidence.

---

## 5. Motor control — the linchpin finding

### 5.1 Wire protocol — **IDENTICAL** (CONFIRMED, constant by constant)

| Constant | Robot `motor_node` | Lab `motor_handler` | |
|---|---|---|---|
| `STATE_CONTROL_LEFT_MOTOR` | 0 | 0 | SAME |
| `STATE_CONTROL_RIGHT_MOTOR` | 1 | 1 | SAME |
| `MOTOR_LEFT_ID` | 1 | 1 | SAME |
| `MOTOR_RIGHT_ID` | 2 | 2 | SAME |
| `MOTOR_CMD_BUFFER_SIZE` | 10 | 10 | SAME |
| `MOTOR_RECV_BUFFER_SIZE` | 10 | 10 | SAME |
| command byte[1] | `0x64` | `0x64` | SAME |
| checksum | `crc8_maxim`, last byte | `crc8_maxim`, last byte | SAME |
| packet layout | `[id][0x64][rpm_hi][rpm_lo][0][0][acc][0][0][crc]` | identical | SAME |

The lab's **ROS 2** `motor_handler.cpp` retains the same constants and packet layout
(`MOTOR_LEFT_ID 1`, `0x64`, `MOTOR_CMD_BUFFER_SIZE 10`, `crc8_maxim`), so the wire protocol
survived the lab ROS 1 → ROS 2 port **unchanged**.

### 5.2 Source lineage — **~78 % fork** (CONFIRMED by line overlap)

| | lines | unique stripped lines |
|---|---|---|
| `motor_node.cpp` (robot) | 530 | 348 |
| `motor_handler.cpp` (lab) | 567 | 343 |
| shared | — | **270** (77.6 % of robot, 78.7 % of lab) |

`motor_node.cpp` differs from `motor_handler.cpp` in exactly the expected ways: node name
(`motor_node` vs `motor_handler`), a reduced/renamed topic set, and the added
`swjtumover_msgs/motor_state` publish. **The odometry dead-reckoning maths is shared.**

### 5.3 Topic/type divergence that will bite (CONFIRMED)

| Concept | Robot ROS 1 | CAASI ROS 2 (lab) | Compatible? |
|---|---|---|---|
| odometry | `odom` — `nav_msgs/Odometry` | `openmover/hardware/odom` — **`geometry_msgs/PoseWithCovarianceStamped`** | **NO** — different type and name |
| twist | (inside `Odometry`) | `openmover/hardware/twist` — `TwistWithCovarianceStamped` | **NO** |
| motor state | `motor_state/left` — `swjtumover_msgs/motor_state` | `openmover/hardware/motor_state/left` — `openmover_msgs/MotorState` | type-equivalent, **name differs** |
| velocity in | `cmd_vel` | `control/cmd_vel_sim` (sim) / mode-gated | **NO** |
| scan | `scan` | `openmover/hardware/lidar/scan` (post-merge) | **name differs** |

The lab ROS 2 stack renamed and re-typed **every** hardware topic and wrapped `cmd_vel` in a
mode/emergency-stop gate that the robot's `motor_node` does not have.

### 5.4 Parameter defaults disagree with the YAML (CONFIRMED — latent hazard)

The YAML **is** correctly loaded (`<rosparam>` inside `<node>` → `/motor_node/motor/*`, and the
code reads `NodeHandle("~/motor")` → `/motor_node/motor/*` — these match), so the defaults below
are dormant. They are nonetheless a hazard if the YAML is ever missing:

| Param | `motor.yaml` | code default |
|---|---|---|
| `wheel_acc` | **1800** | **10000** |
| `wheel_radius` | **0.05035** | **0.0535** |
| `odom_compensation_ratio` | **1.047** | **1.0** |
| `control_freq` | 50 | 50 |

> A silent fallback would change acceleration by 5.6×, wheel radius by 6 %, and remove a 4.7 %
> odometry correction. **A port must preserve the YAML values, not the code defaults.**

### 5.5 Phantom dependency (CONFIRMED)

`swjtumover_bringup/package.xml` declares `<depend>relocalization_toolbox_msgs</depend>` — a
package that exists **only in the lab tree**, and which appears **nowhere** in the robot's C++,
Python, launch or config. It is a stale declaration, not a real dependency. It would nonetheless
break a clean `catkin_make` of the robot source in isolation.

---

## 6. Launch configuration

| Robot launch | Nodes |
|---|---|
| `bringup.launch` | rsp, jsp, **vanjee_lidar_sdk_node**, **motor_node**, **screen_node**, **teleop_node.py**, rviz, + `rs_camera.launch` |
| `bringup_gmapping.launch` | as above + **`slam_gmapping`** |
| `amcl.launch` / `move_base.launch` / `map_server.launch` / `map_save.launch` | single-purpose |
| `exam_project.launch` | (composition) |

Robot SLAM/nav = **gmapping + amcl + move_base**.
Lab SLAM/nav = **Cartographer + custom A*/DWA + Nav2** (ROS 2).

### Helper scripts present on the robot (`swjtumover_bringup/scripts/`)
`exam_line_following.py`, `exam_nav_goals.py`, `final.py`, `nav_goal.py`, `obstacle_rplidar.py`,
`ok.py`, `ok2.py`, `omove_following.py`, `omove_following（复件）.py`, `scan_filter_120deg.py`,
`teleop_node.py`.

These publish/consume `move_base_simple/goal`, `/scan`, `/lane_image`, `/d415/color/image_raw`.
**They are robot-only functionality with no lab or ROS 2 counterpart**, and several look like
experiment scratch files (`ok.py`/`ok2.py`/`（复件）` = "copy"). Whether they are *in scope* for
"every single bit of functionality" is an open question for you — see §9 Q1.

---

## 7. Dependency reality check

| | Robot | Lab |
|---|---|---|
| build | catkin (`3.install.sh` → `catkin_make`) | catkin |
| ROS | Noetic (`/opt/ros/noetic`) | Noetic |
| notable apt deps | `ros-noetic-serial*`, `pygame`, `pynput` | `desktop-full`, navigation, gmapping, robot-pose-ekf, teb, joy, octomap, modbus, rosbridge, **Cartographer (source build)**, OSQP, PCL/VTK |
| nav stack | gmapping / amcl / move_base (binary apt) | Cartographer (source) + custom planners |
| ROS 2 side | **`vanjee_lidar_sdk` already dual-target** | ported package-by-package in CAASI ROS 2 |

### 7.1 Lab ROS 1 standalone buildability (Gate 1 item 3) — assessed, NOT attempted

Feasible, with caveats:
- Requires `ros-noetic-desktop-full` plus navigation/gmapping/teb/joy/octomap/modbus/rosbridge.
- **Cartographer must be built from source** (`cartographer_ws/abseil-cpp` + `stow`, per
  `install.sh`) — the heaviest single dependency.
- `ira_laser_tools` needs `libpcl-all-dev`, `pcl_ros`, `libvtk-qt` — the **reference tree has
  known build-hygiene defects** already documented (a regular file where catkin expects a
  `toplevel.cmake` symlink, case-mismatched `relocalization_request.srv`, vestigial
  `add_action_files` block). Prior work fixed these only inside a container copy.
- **Recommended option:** the existing Docker approach (`osrf/ros:noetic-desktop-full`,
  `--network host --shm-size=2g`) as an isolated ROS 1 oracle. It worked before and requires no
  host system changes. *Not run in this stage — no packages installed, nothing launched.*
- **Carried-forward gap:** there is still **no committed Dockerfile** for this environment.

---

## 8. Classification

### 8.1 Identical or demonstrably equivalent
- **Motor wire protocol** — byte-identical packet layout, IDs, crc8-Maxim, `0x64` opcode, across
  robot ROS 1 → lab ROS 1 → lab ROS 2.
- **`motor_state` message content** — field-for-field identical (`swjtumover_msgs/motor_state` ≡
  `openmover_msgs/MotorState`).
- **Odometry dead-reckoning core** — shared source lineage (~78 % line overlap).
- **`crc8_maxim` implementation** — shared.

### 8.2 Different implementation, equivalent role
- `motor_node` vs `motor_handler` — same UDP device protocol, different node identity and topic set.
- `screen_node` (robot, UDP :26, `qrcode_text`) vs `io_board_handler` (lab, UDP :26, BMS/e-stop/lift) —
  **same address, different device and different message surface. Not interchangeable.**
- `vanjee_lidar_sdk` (robot) vs `bluesea2` + `laserscan_multi_merger` (lab) — both yield one
  `scan` on `lidar_*link`, but via totally different drivers and frames.
- `realsense2_camera` (robot) vs V4L2 HIK (lab).

### 8.3 Behavioural differences / incompatibilities
- **Chassis geometry**: 0.206 m vs 0.324 m track — any port that reuses lab odometry/nav
  constants is **wrong for the robot**.
- **Topic names and types** (§5.3): odometry type differs (`Odometry` vs
  `PoseWithCovarianceStamped`); every hardware topic renamed under `openmover/hardware/*`.
- **`cmd_vel` gating**: CAASI ROS 2 gates velocity behind a mode service + emergency stop; the
  robot's `motor_node` drives directly from `cmd_vel`.
- **Single vs dual LiDAR** and therefore **no merger node** on the robot.
- **SLAM/nav stack**: gmapping/amcl/move_base vs Cartographer/Nav2.
- **Keyboard teleop** via `pynput` (robot) vs the lab's teleop handler.

### 8.4 Hardware-specific assumptions & configuration
- Subnets `192.168.100.0/24` (motor+IO) **and** `192.168.110.0/24` (LiDAR host `.10`).
- Vanjee 718H specifics: UDP, `wait_for_difop`, `min_distance 0.25`, `max_distance 25`.
- Param defaults diverge from YAML (§5.4).
- `odom_compensation_ratio = 1.047` — a **robot-measured calibration constant** that must be
  carried forward verbatim.

### 8.5 Missing / unverified / unsupported
- **No ROS 2 implementation of `swjtumover_bringup` exists** (motor_node, screen_node, teleop).
- **No ROS 2 equivalent of gmapping / amcl / move_base.**
- **Vanjee ROS 2 build path exists in source but was never built or run here** — UNVERIFIED.
- **Nothing runtime has been observed.** ROS 1 was not running; no hardware was reached.
- **Which source is running on the robot**: launch config is consistent with the snapshot, but
  there is no VCS and no runtime confirmation. **UNVERIFIED.**

### 8.6 Reusable ROS 2 components
- **`vanjee_lidar_sdk`** — highest-value reuse; upstream dual-target, likely colcon-buildable as-is.
- **Motor UDP protocol layer + crc8 + odometry maths** — portable nearly verbatim from either
  `motor_node.cpp` or CAASI `motor_handler.cpp`.
- **`swjtumover_msgs` → ROS 2** — trivial (`rosidl`), and already proven by `openmover_msgs`.
- **`robot_state_publisher` / `joint_state_publisher`** — native ROS 2 equivalents.
- **`realsense2_camera`** — mature ROS 2 package exists.

### 8.7 Components requiring redesign
- **Chassis parameters** — must be re-derived from the robot's URDF, not inherited.
- **`screen_node`** — UDP payload format is bespoke; needs its own ROS 2 node.
- **`cmd_vel` path** — decide whether to keep the robot's direct subscribe or adopt CAASI's gate.
- **Nav/SLAM** — Nav2 replacement for gmapping/amcl/move_base is a **porting project**, not a task.
- **Helper experiment scripts** — need a scope decision (§9 Q1).

---

## 9. Open questions requiring your decision

**Q1 — Scope of "every single bit of functionality."** Does that include the 11 helper scripts
(`exam_*.py`, `nav_goal.py`, `omove_following.py`, `ok.py`/`ok2.py`, `scan_filter_120deg.py`, …)?
Some appear to be scratch/duplicate files (`ok.py`/`ok2.py`, `（复件）`). Porting all of them is
substantial extra work; porting none risks dropping real capability.

**Q2 — Behaviour contract: which topic names must be preserved?** The robot's existing consumers
use `cmd_vel` / `odom` / `scan`. The lab's ROS 2 port renamed everything under
`openmover/hardware/*`. **Should the robot's ROS 2 port preserve the original ROS 1 names**
(so existing scripts/RViz configs keep working), or adopt the lab ROS 2 naming?

**Q3 — `cmd_vel` gating.** Should the robot's ROS 2 port keep the robot's direct
`cmd_vel → motors` behaviour, or adopt the lab ROS 2 mode/emergency-stop gate (safer, but a
behavioural change from the working ROS 1 system)?

**Q4 — Nav/SLAM in or out of the first port?** Per your earlier instruction the first stage is
hardware bringup only. Confirm Nav2 (replacing gmapping/amcl/move_base) is a **separate later
stage**, so Gate 2/3 stay bounded.

**Q5 — Is the ROS 1 system on `/dev/sda2` actually the one flown on the robot?** There is no VCS.
A live baseline (Gate 2) would settle this definitively.

---

## 10. What was inspected vs what was tested

| | Status |
|---|---|
| Robot source read (696 files, hashed) | **Inspected** |
| Robot filesystem metadata via SSH | **Inspected** |
| `lsusb` on robot (RealSense confirmed) | **Observed** |
| Network reachability of `192.168.100.100`, `192.168.110.100/.10` | **Observed — all UNREACHABLE** |
| ROS 1 process check on robot | **Observed — nothing running** |
| Any ROS 1 node executed | **NO** |
| Any ROS 2 build performed | **NO** |
| Any hardware device accessed | **NO** |
| Any network interface configured | **NO** |
| Robot moved | **NO** |

**No behavioural equivalence is claimed anywhere in this report.** All behavioural statements are
source-derived and pending Gate 2 confirmation.

---

## 11. Recommended porting strategy (for your approval — no code written)

**Do not create an independent port from scratch, and do not reuse the lab port wholesale.**

Three-tier approach:

1. **Reuse upstream where it already exists** — `vanjee_lidar_sdk` (dual-target), `realsense2_camera`,
   `robot_state_publisher`, `joint_state_publisher`. Verify the Vanjee ROS 2 build first; it is the
   largest single win.
2. **Port mechanically from the robot's own ROS 1 source** — `motor_node`, `screen_node`,
   `teleop_node`, `swjtumover_msgs`. The motor layer is a near-verbatim translation because the
   wire protocol is byte-identical; borrow the *rclcpp idiom* from CAASI `motor_handler.cpp` but
   keep the **robot's** topic contract, **robot's** parameters, and **robot's** direct `cmd_vel`
   semantics. Preserve `odom_compensation_ratio = 1.047` exactly.
3. **Re-derive, do not inherit, anything geometric or navigational** — URDF parameters, track
   width, Nav2 config. The lab values are provably wrong for this robot.

Rationale: the CAASI port is the right **reference for ROS 2 idioms and infrastructure**, and the
wrong **source of behaviour truth** for this robot. The robot's ROS 1 source plus the Gate 2
runtime baseline are the behavioural truth.

---

## 12. Proposed next step

**Gate 2 — live ROS 1 behavioural baseline**, strictly read-only and stationary, per your
instructions. Before it can run, its prerequisites must be settled, and they are **not** met today:

1. ROS 1 must be running — it currently is not.
2. `192.168.100.0/24` and `192.168.110.0/24` must be reachable — neither is, and both Ethernet
   ports are down. **I will not configure them; you must approve and perform any change.**

Per your instruction I will **first** investigate whether Noetic + hardware access can work from
the running Ubuntu 24.04 (chroot feasibility, `/dev` passthrough, UDP reachability, `ROS_MASTER`
config) and report the exact requirements **before** you consider any reboot. No reboot, no boot
entry change, no interface configuration will be performed by me.

---

## 13. Helper Script Inventory (Group 1 requirement, added 2026-10-25)

All 11 scripts preserved in the snapshot. **None deleted. None ported.** Classification below is
based on actual imports, behaviour, launch references and hash comparison.

| # | Script | Lines | SHA-256 (first 8) | Dependencies | Launch-referenced? | Category |
|---|---|---|---|---|---|---|
| 1 | `teleop_node.py` | 165 | `ec2bb93e` | rospy, `pynput`, threading, Twist | **YES** — `bringup.launch`, `bringup_gmapping.launch` | **Required functionality** |
| 2 | `exam_line_following.py` | 311 | `fd08f2fb` | rospy, cv2, numpy, cv_bridge, Twist, Image, Bool | `exam_project.launch` | **Useful utility** (exam demo phase 1) |
| 3 | `exam_nav_goals.py` | 273 | `57f1364c` | rospy, actionlib, move_base_msgs, PoseWithCovarianceStamped, Bool, Empty | `exam_project.launch` | **Useful utility** (exam demo phase 2) |
| 4 | `nav_goal.py` | 44 | `70b9c5c4` | rospy, PoseStamped | `exam_project.launch` | **Useful utility** — minimal goal sender |
| 5 | `final.py` | 259 | `69c860e6` | rospy, cv2, numpy, actionlib, cv_bridge, move_base_msgs, tf | **no** | **Unclear** — likely superseded by the split exam scripts |
| 6 | `omove_following.py` | 285 | `55bf610a` | rospy, cv2, numpy, cv_bridge, Twist, Image | **no** | **Unclear** — vision following, bypasses nav stack |
| 7 | `omove_following（复件）.py` | 285 | `55bf610a` | identical | **no** | **Experimental/duplicate** — **byte-identical** to #6 |
| 8 | `ok.py` | 124 | `da21adb7` | rospy, actionlib, os, signal, move_base_msgs, tf | **no** | **Experimental/duplicate** — scratch |
| 9 | `ok2.py` | 49 | `a01393c7` | rospy, PoseStamped | **no** | **Experimental/duplicate** — scratch; subset of `nav_goal.py` |
| 10 | `obstacle_rplidar.py` | 169 | `4cd87541` | rospy, math, LaserScan, Twist | **no** | **Unclear** — name references **rplidar**, not the Vanjee actually fitted |
| 11 | `scan_filter_120deg.py` | 48 | `e36a02a9` | rospy, math, LaserScan | **no** | **Useful utility** — 120° forward filter, self-contained |

### 13.1 Key observations

- **Only 2 of 11 are in the production bringup path**: `teleop_node.py` (both bringups) and the
  three `exam_*`/`nav_goal` scripts which belong to `exam_project.launch` — a *separate optional
  demo*, not the default bringup.
- **6 of 11 are referenced by no launch file at all**: `final.py`, `omove_following.py`,
  `omove_following（复件）.py`, `ok.py`, `ok2.py`, `obstacle_rplidar.py`, `scan_filter_120deg.py`.
- **Confirmed duplicate**: `omove_following（复件）.py` ≡ `omove_following.py` (identical SHA-256).
  `（复件）` literally means "copy". It should not be ported, but must be **retained in the snapshot**.
- **No `catkin_install_python` in `swjtumover_bringup/CMakeLists.txt`** — the scripts are run from
  the source tree via `devel/`, not installed. A ROS 2 port must add an explicit install rule.
- **`obstacle_rplidar.py` names a different sensor** (RPLIDAR) than the fitted Vanjee 718H. Either
  dead code from an earlier configuration or intended for the LiDAR's scan topic regardless of
  vendor — **cannot be determined from source; needs runtime observation.**
- **Python 2/3 mix**: `nav_goal.py` and `ok2.py` carry `#!/usr/bin/env python` with `print` usage
  that needs checking; the rest are `python3`. A port must not assume uniform Python 3 semantics.

### 13.2 Porting recommendation (proposed, not approved)

| Disposition | Scripts |
|---|---|
| **Port in milestone 1** (hardware bringup) | `teleop_node.py` — *only if* the actuation gate design retains a teleop path |
| **Port later, with navigation** | `exam_line_following.py`, `exam_nav_goals.py`, `nav_goal.py`, `final.py` (they depend on `move_base`/AMCL) |
| **Assess at runtime before deciding** | `obstacle_rplidar.py`, `scan_filter_120deg.py`, `omove_following.py` |
| **Do not port; retain in snapshot** | `omove_following（复件）.py` (byte-identical duplicate), `ok.py`, `ok2.py` (scratch) |

**None of this is decided.** Per Group 1, exclusions require evidence of actual dependencies and
behaviour — which requires Gate 2 runtime observation. Until then the classification above is
source-derived only (L1).

---

## 14. Group 2–4 decisions recorded (2026-10-25)

- **Group 2 — Interfaces:** the robot's **ROS 1 names, types, units and semantics are preserved
  wherever practical**, including `cmd_vel`, `odom`, `scan`. The lab port's
  `openmover/hardware/*` renaming and its `PoseWithCovarianceStamped` odometry are **not**
  inherited by default. Any deliberate deviation must be documented with its compatibility impact.
- **Group 3 — Motor safety:** the ROS 2 design **must not permit unrestricted physical actuation by
  default**. An **explicit, default-disabled actuation gate** is required, while preserving the
  original command interface where practical. This is an **intentional safety improvement** over
  the robot's direct ROS 1 `cmd_vel` path. **No nonzero velocity, no motor activation** in
  milestone 1.
- **Group 4 — Navigation:** gmapping, AMCL, move_base and their Nav2 migration are **out of** the
  first hardware-bringup milestone. Their dependencies and requirements are to be recorded for a
  separate later stage.
