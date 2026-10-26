# Phase 8: Three-Way Feature & Reuse Assessment

**Status:** Assessment complete — **no porting started, no code changed**
**Date:** 2026-10-26
**Trigger:** the user's observation that *"the lab ROS 1 code appears to have more features
than the physical robot's ROS 1 implementation"* — and that the robot's code must **not** be
assumed to be the complete specification.

> **Core correction to my earlier position.** In the Gate 1 report I framed the robot's ROS 1
> code as the behavioural spec and treated the lab stack as a different robot's code. **That was
> right about hardware and wrong about features.** The lab stack is substantially richer, and
> the CAASI ROS 2 port is a port of **the lab stack**, not of the robot's. This report measures
> all three properly.

---

## 0. Headline

| Claim | Verdict | Evidence |
|---|---|---|
| Lab ROS 1 has more features than robot ROS 1 | **TRUE — by a wide margin** | 17 executables vs 3; 8 msg + 10 srv vs 1 msg + 0 srv; 49 vs 2 topic strings |
| CAASI ROS 2 is missing lab functionality | **FALSE — it is a near-complete port** | **0** lab topics missing from CAASI; 68 vs 49 topics present |
| CAASI algorithms differ from lab | **FALSE at algorithm level** | planner/relocalization/mapping source is ROS-API translation only |
| Lab stack builds on this robot | **NO — blocked by 3 missing packages + 1 real source defect** | measured below |

**The decisive finding: CAASI ROS 2 is not a reduced version of the lab stack. It is the lab
stack, already ported, plus more.** The real gap is not *features* — it is **hardware**: CAASI is
built for the lab's sensors (bluesea2 ×2), while the robot has a Vanjee.

---

## 1. The three implementations

| | **Robot ROS 1** (`openmover_robot_spec`) | **Lab ROS 1** (`openmover_robot`) | **CAASI ROS 2** (`caasi-workspace/openmover`) |
|---|---|---|---|
| Purpose | what actually flies on the robot | research/feature-rich reference | the existing ROS 2 port |
| C++ executables | **3** (`motor_node`, `screen_node`, `vanjee_lidar_sdk_node`) | **17** | **12** |
| Python nodes | 11 helper scripts | ~9 (hal, server, teleop, workload) | ~20 (incl. all server handlers) |
| Messages | **1** msg, 0 srv | **8** msg, **10** srv | **8** msg, **10** srv |
| Topic strings | 2 (`cmd_vel` … ) | **49** | **68** |
| LiDAR | Vanjee 718H (1 unit) | bluesea2 (2 units) | bluesea2 (2 units) |
| SLAM/Nav | gmapping / amcl / move_base | **Cartographer + custom planner** | **Cartographer + custom planner** |
| Hardware verified | ✅ L4 (this phase) | ❌ never on hardware | ❌ never on robot hardware |

---

## 2. Feature matrix — what exists where

Legend: ✅ present · ➖ absent · 🔁 functionally absorbed elsewhere

### 2.1 C++ nodes

| Node | Robot | Lab | CAASI | Notes |
|---|---|---|---|---|
| `motor_node` / `motor_handler` | ✅ `motor_node` | ✅ `motor_handler` | ✅ `motor_handler` | same wire protocol |
| `screen_node` | ✅ | ➖ | ➖ | **robot-only**; lab/CAASI use `io_board_handler` |
| `vanjee_lidar_sdk_node` | ✅ | ➖ | ➖ | **robot-only**; vendor SDK |
| `bluesea2_node` (×2) | ➖ | ✅ | ✅ | **lab/CAASI only** — robot has no bluesea |
| `io_board_handler` | ➖ | ✅ | ✅ | lab BMS/lift; robot uses `screen_node` |
| `localization_handler` | ➖ | ✅ | ✅ | Cartographer-based |
| `localization_confidence_handler` | ➖ | ✅ | ✅ | |
| `navigation_handler` | ➖ | ✅ | ✅ | CAASI **absorbs** `global_planner_handler` |
| `global_planner_handler` | ➖ | ✅ | 🔁 | absorbed into `navigation_handler` (`make_plan()`, `GetPlan` timing) |
| `obstacle_handler` | ➖ | ✅ | ✅ | |
| `teleop_handler` | ✅ `teleop_node.py` | ✅ | ✅ | |
| `simulation_handler` | ➖ | ✅ | ✅ | Gazebo/Isaac bridge |
| `auto_mapping_handler` | ➖ | ✅ | ✅ | 1153 lines, `auto_mapping/state` + `auto_mapping/request` |
| `relocalization_2d_handler` | ➖ | ✅ | ✅ | GICP + likelihood field |
| `laserscan_multi_merger` | ➖ | ✅ | ✅ | |
| `laser_merger_node` / `laserscan_virtualizer` | ➖ | ✅ | ➖ | **lab-only**, both are `ira_laser_tools` variants |
| `key_control` | ➖ | ✅ | ✅ | |
| `speaker_handler.py` | ➖ | ✅ | ✅ | |
| **`ok.py`/`ok2.py`/`final.py`/… (11)** | ✅ | ➖ | ➖ | **robot-only experiment scripts** |

### 2.2 Topic surface — the decisive measurement

Extracted every quoted `openmover/*` string from all three trees:

| | count |
|---|---|
| Lab ROS 1 | **49** |
| CAASI ROS 2 | **68** |
| **Lab topics MISSING from CAASI** | **0** |

`openmover/flow/state` initially looked lab-only — **it is present in CAASI**
(`protocol.py:339`), written with single quotes and line-wrapped, which my first regex missed.
**Recording that as a measurement error I corrected, not a finding.**

CAASI-only additions: `openmover/navigation/global_planner/make_plan` (the absorbed planner).

### 2.3 Messages and services

| | Robot | Lab | CAASI |
|---|---|---|---|
| `.msg` | 1 (`motor_state`) | 8 | **8** |
| `.srv` | 0 | 10 | **10** |
| Naming | `snake_case` | `snake_case` + subdirs (`srv/driver/…`) | `PascalCase` flat |

CAASI's 8 msg and 10 srv **match the lab exactly in count**, restructured per ROS 2 conventions.

---

## 3. Algorithm reuse — measured, not assumed

I diffed every C++ file present in **both** lab ROS 1 and CAASI ROS 2 (117 files).

| Category | Count |
|---|---|
| Files present in both | **117** |
| Differences are **only** ROS logging / `ros::`→`rclcpp` / `#include` / comments | **48** |
| Files with larger diffs — inspected below | 69 |

### 3.1 Spot-check of the largest diffs

| File | Diff size | Verdict |
|---|---|---|
| `dijkstra.cpp` | 1 line | **comment only** — `ROS_INFO` → `// RCLCPP_INFO` |
| `math_utils.cpp` | 364 lines | **pure API translation** — `geometry_msgs::` → `geometry_msgs::msg::`, `tf::getYaw` → `tf2::getYaw`, `openmover_msgs::nav_to_request` → `::srv::NavToRequest` |
| `navigation_handler.cpp` | 501 lines | **API + structural** — CAASI absorbs `global_planner_handler`, adds `COSTMAP_NAME`/`PLANNER_NAME` defines, keeps all three topics |
| `laserscan_multi_merger.cpp` | 403 lines | API translation (ROS 1 → 2 message/param API) |

**No algorithmic rewrite was found in any inspected file.** The nav planner, relocalization
(GICP/likelihood-field/submap/sampling/sector-query), and auto-mapping
(global/local exploration, TSP optimisation, collision prediction) all carry over as
**translation, not reimplementation**.

> **Important caveat, per your instruction:** this establishes **source-level reusability**, not
> behavioural equivalence. Successful ROS 1 compilation does **not** imply ROS 2 compatibility,
> and byte-similar source does not imply identical runtime behaviour. The earlier Phase 7 audit
> measured behaviour for **six** specific behaviours only; nothing here extends that.

---

## 4. Build-only assessment (item 3 of your request)

Attempted on the robot in a **separate workspace** (`/tmp/lab_build_ws`) built from copies.
**The lab tree, the robot spec snapshot and the robot's own workspace were never modified.**

### 4.1 Result: build FAILS, for two distinct reasons

| # | Blocker | Type | Exact evidence |
|---|---|---|---|
| **B1** | `cartographer_ros_msgs` not found | **missing dependency** | `openmover_msgs/CMakeLists.txt:12` `find_package(catkin REQUIRED COMPONENTS … cartographer_ros_msgs)`. Not installed on the robot. |
| **B2** | `relocalization_request.srv` does not exist | **genuine source/build-system defect** | `relocalization_toolbox_msgs/CMakeLists.txt:16-19` declares `relocalization_request.srv`; disk has **`RelocalizationRequest.srv`** — a **case mismatch**. |

Additional missing packages (would block later stages): **`ira_laser_tools`**,
**`rosbridge_server`**, **`osqp`** (the lab ships `osqp/` in source but `auto_mapping_toolbox`
does `find_package(osqp REQUIRED)` — it expects an *installed* osqp).

### 4.2 B2 is a pre-existing defect, not something I introduced

This is **the same class of defect** already recorded in the Phase 7 ROS 1 reference audit
("a case-mismatched `relocalization_request.srv`"). It is a defect **in the lab tree itself** and
would break a clean `catkin_make` for anyone. I worked around it **only in the /tmp copy**
(symlink) to continue the assessment, and **left the original untouched**.

### 4.3 What this means

The lab stack **cannot be built on this robot without installing ≥3 packages** — which you
correctly ruled out. So:

- **B1-type blockers are dependency gaps**, not source problems. On a machine with
  `ros-noetic-cartographer-ros` etc., they would disappear.
- **B2 is a real defect** in the lab tree and would need a one-line fix in any ROS 2 port too.
- **Nothing here is evidence about ROS 2 compatibility.**

### 4.4 The robot's own stack, by contrast, **did** build and run

Already established this phase: `motor_node`, `screen_node`, `vanjee_lidar_sdk_node` are prebuilt
and **verified at L4 on real hardware**. Distinguishing: *the robot stack is buildable+runnable
here; the lab stack is neither, without new packages.*

---

## 5. Which lab features are actually used?

| Feature | In lab source | Evidence of use | Judgement |
|---|---|---|---|
| Cartographer SLAM/localization | ✅ | launch files + `cartographer_server_handler.py` | **core** |
| Custom global planner (A*, OSQP smoothing) | ✅ | `navigation_handler`, launch | **core** |
| Relocalization (GICP 2D) | ✅ | `relocalization_2d_handler`, `initialpose` | **core** |
| Auto-mapping / exploration | ✅ | `auto_mapping/request` service, 1153 lines | **core, advanced** |
| Obstacle handling / collision checker | ✅ | `obstacle_handler` | **core** |
| `laserscan_virtualizer` / `laser_merger_node` | ✅ | no launch reference found | **unused duplicate** of `laserscan_multi_merger` |
| `warehouse_simulation` | ✅ | Isaac/Gazebo launches | **simulation-only** |
| `speaker_handler.py` | ✅ | `sound_filepath` param | used (needs `$(env HOME)/openmover_robot/sounds/`) |
| Lab `bluesea2` | ✅ | hardwares bringup | **hardware we do not have** |
| Workload / Isaac Lab | ✅ | `workload.py`, `lab/` | **simulation/research** |

**Robot-only features the lab does not have**: `screen_node` (IO display text),
`vanjee_lidar_sdk` integration, and the 11 experiment scripts.

---

## 6. Reuse classification

| Component | Reuse class | What reuse actually requires in ROS 2 |
|---|---|---|
| Navigation planner algorithms (`dijkstra`, `osqp_smoother`, `gradient_path`, `orientation_filter`, `polyline_generation`, `planner_with_costmap`) | **Already reused** | nothing — already in CAASI, translation only |
| Relocalization 2D (GICP, likelihood field, submap, sampling, sector query) | **Already reused** | nothing — already in CAASI |
| Auto-mapping (global/local exploration, TSP, collision prediction) | **Already reused** | nothing — already in CAASI |
| `navigation_handler` (+ absorbed planner) | **Already reused** | nothing |
| All 5 Python server handlers, HAL, teleop | **Already reused** | nothing |
| `robot_state_publisher` / `joint_state_publisher` | upstream | native ROS 2 packages exist |
| **Vanjee LiDAR** | **config/build only** | vendor SDK is dual-target — needs a colcon build, not a port |
| **`motor_node`** | **adapter** | port from the **robot's** source (its topics/config), borrowing rclcpp idiom from CAASI `motor_handler` |
| **`screen_node`** | **genuine port** | small bespoke UDP node, no ROS 2 equivalent exists |
| **`teleop_node.py`** | **adapter** | `pynput` keyboard node → ROS 2 `rclpy` |
| **`swjtumover_msgs`** | **build-system change** | `rosidl` conversion (proven trivial by `openmover_msgs`) |
| **gmapping / amcl / move_base** | **genuine port** (robot's nav) | No ROS 2 equivalent; would be Nav2 — **out of milestone 1, and possibly unnecessary if Cartographer is adopted** |
| `laserscan_virtualizer`, `laser_merger_node` | **do not port** | unreferenced duplicates |
| Robot's 11 experiment scripts | **decide later** | 6 are unreferenced; 1 is a byte-identical duplicate |

---

## 7. Answering your actual question

> *"If the previous code already covers our use cases then we might save effort"*

**Yes — and more than you expected.** The significant realisation is that the **effort is
already spent**: CAASI ROS 2 is a complete port of the lab stack's *software* features, with
zero missing topics and no algorithmic divergence found.

What CAASI **cannot** do today is drive **this robot**, because:

| Gap | Nature |
|---|---|
| CAASI targets `bluesea2` ×2; robot has one Vanjee | hardware |
| CAASI targets `io_board_handler`; robot has `screen_node` | hardware |
| CAASI's `motor_handler` uses lab topics/geometry (`chassis_radius 0.162`); robot is `0.103` | configuration |
| CAASI has no `swjtumover_msgs` equivalent | build-system |
| CAASI has no gmapping/amcl/move_base equivalents | nav stack choice |

**So the work is not "port the lab features" — it is "make the already-ported features run on
this hardware".** That is a much smaller and much better-defined job.

---

## 8. Recommended target feature set for CAASI ROS 2

### Preserve from the lab (already in CAASI — do not rewrite)
Cartographer SLAM + localization, custom global planner + OSQP smoothing, relocalization 2D
(GICP), auto-mapping/exploration, obstacle + collision checking, all 5 server handlers, HAL,
teleop modes, flow/action state machine.

### Take from the physical robot (verified on hardware)
- **Vanjee 718H LiDAR** — `/scan`, `lidar_link`, 1440 samples, 14.03 Hz *(L4 verified)*
- **`motor_node`** semantics: topics `odom`/`motor_state/left|right`/`cmd_vel`,
  params `chassis_radius 0.103`, `odom_compensation_ratio 1.047`, `wheel_acc 1800`, 50 Hz
  *(L4 verified)*
- **`screen_node`** IO display protocol (port 26, `qrcode.txt="…"`) *(L4 verified)*
- **RealSense D415** via `realsense2_camera` *(L4 verified)*
- **`swjtumover_msgs/motor_state`**

### Already in CAASI (keep)
Everything listed in §8.1, plus the Isaac Sim / Isaac Lab layers, of which the robot has none.

### Remains to be implemented
1. Vanjee ROS 2 build integration (colcon) + config path **must** be explicit
2. `motor_node` ROS 2 port with the **default-disabled actuation gate** (Group 3)
3. `screen_node` ROS 2 port
4. `swjtumover_msgs` → `rosidl`
5. Reconcile topic naming — preserve robot names per Group 2
6. Decide whether the robot needs Cartographer (from CAASI) or Nav2

### Explicitly **not** worth doing
- Porting the lab stack to this robot (blocked, needs packages, gains nothing CAASI lacks)
- Porting `laserscan_virtualizer` / `laser_merger_node` (unreferenced)
- Porting the 6 unreferenced experiment scripts without evidence they are used

---

## 9. Open questions for your decision

1. **Navigation stack for the robot** — the robot's ROS 1 uses gmapping/amcl/move_base, but
   CAASI already has **Cartographer + a custom planner**. Adopting CAASI's stack would reuse a
   large, proven codebase and avoid a Nav2 port entirely. **Which do you want?**
   (This materially changes the port's size.)
2. **`screen_node` vs `io_board_handler`** — the robot has the former, CAASI the latter. Does the
   robot's IO board support the lab protocol at all? Only a hardware test could tell.
3. **Helper scripts** (still open from Gate 1) — 6 unreferenced, 1 duplicate.
4. **Do you want me to fix the B2 case-mismatch** in the lab tree? It is a real defect, but the
   lab tree is read-only to me.

---

## 10. What was inspected vs tested

| | Level | Status |
|---|---|---|
| Robot ROS 1 on real hardware | **L4** | ✅ verified this phase (LiDAR, RealSense, motor telemetry, screen IO) |
| Robot ROS 1 motor actuation | — | ❌ **never tested** |
| Lab ROS 1 build | **L2** | ❌ **build failed** — B1 missing dep, B2 source defect |
| Lab ROS 1 runtime | **L3** | ❌ **never launched** (constraint honoured) |
| CAASI ROS 2 build | **L2** | ✅ builds (Phase 6/7), 1250 tests passing |
| CAASI ROS 2 on **robot** hardware | **L4** | ❌ **never** — CAASI has only run on lab/sim hardware |
| Algorithm equivalence | **L1** | source-level only; **behavioural equivalence NOT claimed** |

**No behavioural equivalence is claimed anywhere in this report.** Source similarity (L1) and
successful compilation (L2) are **not** evidence of equivalent behaviour.
