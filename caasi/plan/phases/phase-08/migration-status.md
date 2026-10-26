# Phase 8 — Migration Status: ROS 1 → ROS 2

**Date:** 2026-10-26
**Scope of this iteration:** Batch A (finalise M1 + commits), Batch B (hardware
integrations), Batch C (stationary integration, as far as the environment allows),
Batch D (watchdog).

> Evidence levels: **L1** source inspection · **L2** build/automated tests · **L3**
> runtime ROS 2 · **L4** physical hardware. Nothing here claims equivalence from source
> similarity or a successful compile.

---

## 1. Feature-by-feature status

| Feature | ROS 1 (robot) | ROS 2 (caasi/openmover) | Evidence | Status |
|---|---|---|---|---|
| Motor telemetry (`motor_state`, `odom`) | `motor_node` | `motor_handler` | **L4** on robot (25 Hz, 0 faults); **L3** on workstation via UDP sink | **Ported & verified** |
| Motor actuation gate | none (direct `cmd_vel`) | two-factor default-deny | **L3**, 19 tests | **Ported, improved** (safety addition) |
| Command watchdog | **absent** (defect) | `motor.cmd_vel_timeout` | **L3** (87 nonzero → 0 after stop) | **New** — fixes a defect present in ROS 1 |
| Fail-closed motor config | **absent** (`param(default)` fail-open) | required + range-checked | **L3** | **New** — fixes an ROS 1 defect |
| Screen/QR display | `screen_node` | `screen_handler.py` | **L4** frame captured on robot; **L3** byte-identical port + 3 tests | **Ported & verified** |
| Vanjee 718H LiDAR | `vanjee_lidar_sdk` (ROS 1 build) | not built | **L4** in ROS 1 only | **Not integrated** — see §4 |
| RealSense D415 | `realsense2_camera` (ROS 1) | no launch entry; upstream ROS 2 package absent here | **L4** in ROS 1 only | **Not integrated** — see §4 |
| Hardware profile selection | n/a (single robot) | `hardware:=`, `lidar_driver:=`, `io_driver:=` | **L3** validation by execution | **Delivered** |
| Gazebo-free bringup | n/a | lazy `ros_gz_sim` | **L3** launch now introspectable/configurable | **Delivered** |
| Navigation / planning | gmapping + amcl + move_base | Cartographer + custom A*/OSQP + Nav2 config | L1/L2 (caasi builds; upstream audit) | **Retained from caasi** — ROS 1 stack deliberately not ported |
| Relocalization (GICP 2D) | `relocalization_toolbox` | same algorithms, ROS 2 API | L1/L2 | **Already ported** (pre-existing) |
| Auto-mapping / exploration | `auto_mapping_toolbox` | same, ROS 2 API | L1/L2 | **Already ported** (pre-existing) |
| Obstacle / collision checking | `obstacle_handler` | `obstacle_handler` | L1/L2 | **Already ported** |
| Lab LiDAR (bluesea2 ×2) | n/a | `bluesea2_node` ×2 + merger | L2 build | **Retained** (lab profile) |
| Lab IO board | `io_board_handler` | `io_board_handler` | L1/L2 | **Retained** (lab profile) |
| Helper/experiment scripts (11) | present | not ported | L1 classification | **Deliberately not ported** (6 unreferenced, 1 duplicate) |
| `swjtumover_msgs` | 1 msg | `openmover_msgs/MotorState` (field-identical) | L1 | **Reused** — no duplicate package |

---

## 2. Commits

| Commit | Content |
|---|---|
| `0bac153` | robot ROS 1 snapshot (335 files) + provenance + four-way discrepancy report |
| `71ed826` | Gate 2 feasibility + real-hardware sensor verification |
| `ca15847` | feature/reuse assessment + hardware-extension plan |
| `0a8093c` | M1: default-deny actuation gate + fail-closed motor configuration |
| `671ba89` | ROS 2 screen handler + protocol tests |
| `20433a3` | hardware profile selection + lazy Gazebo resolution |
| `6b95d5d` | cmd_vel watchdog |

Working tree additionally holds `caasi/plan/phases/phase-08/m1-actuation-gate-report.md`
and `caasi/plan/current.md`, committed separately as documentation.

---

## 3. Build and test results

| Check | Result |
|---|---|
| `colcon build --packages-select openmover` | **clean**, no warnings from changed files |
| `pytest tests/test_motor_actuation_gate.py` | **19 passed** |
| `pytest tests/test_screen_handler.py` | **3 passed** |
| `pytest tests/` (full, ROS unsourced) | **1249 passed, 2 failed, 22 skipped** |
| Baseline comparison | the **same two** failures as the preserved baseline (`test_dataset_cmd::test_dataset_generate_dry_run`, `test_perception_cmd::test_perception_segment_dry_run_passes_extra_args`), independently reproduced against a pristine `git archive HEAD`. **No new failures.** |

Skipped = the 22 hardware-gated integration tests (19 + 3), which require a sourced ROS 2
environment and run in their own invocation.

---

## 4. Hardware integrations: proven vs inspected

| Integration | State |
|---|---|
| motor_handler (telemetry + gate + watchdog) | **Executed** end-to-end against a local UDP sink, 19 tests |
| screen_handler protocol | **Executed**, byte-identical to the L4 frame captured from the robot |
| hardware profile selection + validation | **Executed** (unknown profile and both contradiction cases rejected) |
| lazy Gazebo resolution | **Executed** — bringup is now introspectable on a Gazebo-less host |
| Vanjee 718H ROS 2 | **Not integrated.** No maintained upstream ROS 2 bridge found (vendor-SDK distribution only). The SDK's ROS 2 publisher layer is real but the build needs three changes: `COMPILE_METHOD` is hardcoded `CATKIN` (a plain `set()`, so `-D` cannot override), `config_path` is inside `#ifdef ROS_FOUND`, and `vanjee_lidar_msg` is catkin-only — though the scan path does **not** use that message package, which reduces the work. All build dependencies (PCL, Eigen, yaml-cpp, pcap, TBB) are present here. **Needs a decision:** patched underlay vs thin node over the plain-CMake `vanjee_driver`. |
| RealSense D415 ROS 2 | **Not integrated.** `realsense2_camera` is not installed, and packages may not be installed here. The robot's own ROS 1 driver worked at L4 (16.6 Hz, 94.2 % valid depth). |
| Full bringup on the robot | **Not attempted.** The robot currently boots Ubuntu 20 / Noetic; the ROS 2 target OS needs booting. |

---

## 5. Environment gaps found (not code defects)

| Gap | Effect |
|---|---|
| `joint_state_publisher` not installed | real-mode bringup aborts at launch: *"package 'joint_state_publisher' not found"* |
| `ros_gz_sim`, `ros_gz_bridge` not installed | simulation path unavailable (now lazily resolved, so it no longer blocks the whole file) |
| `realsense2_camera` not installed | camera integration cannot be executed here |
| **Workstation routes to `192.168.100.0/24`** | `ip route get 192.168.100.100` resolves via the default gateway, so real-mode bringup from this workstation **could** send traffic toward the robot's motor board. Therefore **no real-mode bringup was run here**; every test used `127.0.0.1` sinks. |

---

## 6. Confirmed defects

| Defect | Where | Status |
|---|---|---|
| Last command persists forever (no expiry) | **both** trees | **FIXED in ROS 2** (watchdog). ROS 1 left as-is (read-only). |
| Fail-open defaults for motion parameters | **ROS 1**, and ROS 2 until M1 | **FIXED in ROS 2**; ROS 1 documented, unfixed |
| Params file could grant actuation | ROS 2 (M1 first cut) | **FIXED** (two-factor) |
| Shutdown SIGSEGV after the zero flush | ROS 2 | **Open.** Reproduced 3/3; flush completes first; reliability only (exit 139 would make a good run look failed). Not fixed — root cause in rclcpp teardown not yet established. |
| `ros2 param set` reports success but has no effect on permission | ROS 2 | **Open**, fail-safe, documentation issue |
| Brake byte `[7]` reads the ungated stored speed | ROS 2 (same as ROS 1) | **Open**, no motion risk (transmitted speed is 0) |
| `io_board_handler` defaults to port 23 (motor board) | ROS 2 | **Open**, latent config hazard; lab YAML supplies 26 |

---

## 7. Verdict

- **Migration implementation:** *substantially complete for the motor and IO-display
  subsystems*, which are the parts that differ on this robot. Motor telemetry, the
  actuation gate, the watchdog, fail-closed configuration, the screen protocol and
  hardware profile selection are implemented and test-verified on a workstation.
- **Sensor integration: incomplete.** Vanjee and RealSense are **not** integrated in
  ROS 2. Vanjee needs a decision (§4); RealSense needs a package that cannot be installed
  here.
- **Stationary system integration: partial.** Per-node integration is executed and
  proven; **full bringup is not**, because standard ROS 2 packages are missing on this
  host and the robot is not booted into the ROS 2 OS.

**Not complete.** The remaining path is: decide the Vanjee approach, then boot the robot
into Ubuntu 24 / Jazzy where `joint_state_publisher`, `ros_gz_*` and
`realsense2_camera` can be installed properly, then run the stationary bringup there.
