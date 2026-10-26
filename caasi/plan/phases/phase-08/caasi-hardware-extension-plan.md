# Phase 8: CAASI Hardware Extension — Revised Plan (post-decision, pre-implementation)

**Status:** Planning only. **No source, launch, config, dependency or system change. Nothing
installed, deployed or launched. Robot not contacted for actuation.**
**Date:** 2026-10-26 — supersedes both earlier versions of this document.
**Governing principle:** *caasi discovers, configures, connects, validates and orchestrates
existing robotics software — it does not reimplement it.*

---

## 0. What changed since the last revision

| Item | Previous claim | **Corrected finding** |
|---|---|---|
| **Vanjee ROS 2 build = "one-line change"** | one `set(COMPILE_METHOD COLCON)` | **WRONG — it is 3 blockers, not 1.** See §6. My earlier claim was based on reading only the `CMakeLists.txt` guard, not the message package or `main()`. |
| **Vanjee ROS 2 "unreachable / stub"** | I briefly read `main()` as a bare stub | **Partly wrong, corrected:** the ROS 2 **publisher layer is genuinely implemented** (`source_scandata_ros.hpp:101+`, `source_pointcloud_ros.hpp:193+`, `source_imu_packet_ros.hpp`). Only `main()`'s ROS 2 branch is minimal — `rclcpp::init()` + wait, and **`config_path` is inside `#ifdef ROS_FOUND`, so it does not work under ROS 2**. |
| `actuation_enabled` placement | "at the send site" | **Confirmed feasible and precisely located** — one `sendto` at `motor_handler.cpp:384`; the other four (`:560-572`) are the shutdown zero-flush and are already safe. |
| Parameter loading | "load YAML explicitly" | **Insufficient.** All params use `declare_parameter(name, default)` — a missing key silently substitutes a default. This is the **fail-open** pattern you flagged. A range/guard is required. |

---

## 1. Decisions recorded (your preliminary decisions + what they require)

| # | Your decision | Consequence for this plan |
|---|---|---|
| **D1** | Do not port ROS 1 navigation, **subject to validating the physical robot's actual requirements against CAASI's ROS 2 stack** | **Gate added**: a requirements-validation step (§7, V4) before D1 is treated as closed. If CAASI's stack cannot meet a specific robot requirement, that gap is reported, not silently accepted. |
| **D2** | External Vanjee underlay, **conditional on verifying it works with the actual target distribution and dependencies** | **Gate added** (§6). Verification is *not* satisfied by source inspection — it requires an actual build attempt on a ROS 2 Jazzy host. |
| **D3** | Revisit actuation configuration before approval | §2 below is the revised design, awaiting your approval. |
| **D4** | Keep CAASI's odometry interface initially, **subject to verifying compatibility with its consumers** | **Gate added** (§7, V5): enumerate actual subscribers of `openmover/hardware/odom` and confirm they do not require `nav_msgs/Odometry`. |
| **D5** | Reuse `openmover_msgs/MotorState` **after checking semantic compatibility, not just field equality** | **Gate added** (§5.2): field equality was already proven; **semantic** compatibility (units, sign conventions, frame, fault-meaning) is now an explicit acceptance item. |
| **D6** | Do not port unreferenced helper scripts without evidence of need | Adopted; no script is in scope. |
| **D7** | Document the watchdog issue; keep it separate; **treat it as a blocker for future physical movement** | Recorded (§4) as a **hard gate on M7**, independent of this integration. |

---

## 2. Revised actuation safety design (D3)

### 2.1 The threat model your constraints name

1. A missing config must not enable actuation.
2. An invalid/unrecognised value must not enable actuation.
3. Permission must be enforced at the **final transmission boundary**.
4. A command received while disabled must **not** be released as a stale nonzero command after
   enabling.
5. Telemetry must remain available while disabled.
6. Hardware selection must not itself grant permission.

### 2.2 Where the boundary actually is (verified)

```
cmd_vel_callback  ──> motor_speed_cmd_data.speed_rpm_{left,right}   (a mutable field)
                          │
                          ▼
   send loop (while rclcpp::ok) ── composes packet ──> sendto()  at :384   <-- THE BOUNDARY
```

The other four `sendto()` calls (`:560-572`) are the **shutdown zero-velocity flush** — they write
`0x00` to the speed bytes unconditionally. They are already safe and **must not be gated** (gating
them would prevent the safe stop).

### 2.3 Proposed enforcement — fail-closed by construction

**Design rule: permission is a *derived* predicate, never a stored truth.**

```cpp
// Declared WITHOUT a default: absence is an error, not a silent false/true.
// (declare_parameter with a default is what makes the current params fail-open.)
bool actuation_enabled = <declare, no usable default>;

// A single derived predicate, recomputed every iteration:
const bool may_actuate =
        actuation_enabled                    // explicit opt-in
     && !emergency_flag                      // existing gate, preserved
     && <existing manual/auto gate>;         // existing gate, preserved

// At the boundary (:384), immediately before sendto:
int16_t speed_rpm = ...;
if (!may_actuate) speed_rpm = 0;             // <- force zero at the LAST moment
```

**Why this satisfies each constraint:**

| Constraint | How |
|---|---|
| Missing config ≠ enabled | Permission declared **without a default**; absence fails the node's startup (see 2.4) or evaluates false. It can never default to `true`. |
| Invalid value ≠ enabled | Non-bool / unparseable ⇒ treated as **false**. Type is checked by rclcpp; the semantic guard defaults to deny. |
| Checked at the boundary | The `if (!may_actuate) speed_rpm = 0;` sits **after** packet composition and immediately before `sendto()`, so no path reaches the wire with a nonzero speed unless permitted. |
| **No stale release** | This is the key property. Because the speed is **re-forced to zero at every send**, a nonzero command that arrived while disabled is *overwritten at transmission*, not merely suppressed. It cannot later "escape". **Additionally**: enabling must clear `motor_speed_cmd_data` to zero, so post-enable output starts from a known state rather than the last stored command. |
| Telemetry preserved | The gate touches **only** the speed bytes of the outgoing command. `odom`, `twist`, `motor_state/*` publishing is entirely outside it and continues. |
| Hardware selection ≠ permission | See 2.5. |

### 2.4 Fail-closed on a missing/invalid parameter

Two acceptable mechanisms; both are native `rclcpp`, no new abstraction:

- **(a) Declare with a range descriptor and no usable default** — the node refuses to start if the
  parameter is absent or out of range.
- **(b) `has_parameter()` check at startup** — if absent, log `FATAL` and `rclcpp::shutdown()`.

**Recommendation: (b) for the permission flag** (explicit, obvious in logs, no dependence on
descriptor semantics), plus **(a) for the geometry/limits params** (non-negative radii, positive
`control_freq`, etc.) so a bad motor config is rejected rather than silently driving.

> **This closes the exact hole measured earlier on the robot**: outside `bringup.launch`, the
> robot's node silently ran on code defaults (`wheel_acc 10000` vs 1800, `wheel_radius 0.0535` vs
> 0.05035, `odom_compensation_ratio 1.0` vs 1.047). Those defaults exist because every parameter is
> declared *with* a value. The permission flag must not follow that pattern.

### 2.5 Hardware selection must not grant permission (your constraint 2)

**Three independent facts, never collapsed:**

| Fact | Where it lives | Can it grant actuation? |
|---|---|---|
| *Which hardware am I on?* | launch arg `hardware:=` selecting a param file | **No** |
| *What are this robot's parameters?* | the YAML param file | **No** |
| *May this process drive motors?* | a **separate, explicitly-passed** launch arg `actuation_enabled:=true` | **only this** |

**Rule: the YAML profile never contains `actuation_enabled`.** It is passed as a **launch
argument defaulting to `false`**, so:

- selecting `hardware:=robot` starts the robot's drivers with actuation **off**;
- an inherited/copied/wrong YAML cannot enable it, because the key is not read from YAML;
- enabling requires an explicit `actuation_enabled:=true` **on the command line**, which is
  visible in provenance and in `run` records.

**Lab preservation:** the lab profile's *launch entry* may pass `actuation_enabled:=true`, so the
lab behaves exactly as today. This is a launch-file default per entry point, not a YAML key — so it
is still explicit and auditable, and it cannot leak into the robot profile by copy-paste of a YAML.

> This is a change from my previous plan, which put the flag in the YAML. **Your constraint is
> correct: a YAML default is not an explicit opt-in.**

### 2.6 Testable consequence

Any accidental activation now requires **two** independent mistakes: a wrong launch arg *and* a
code path that bypasses the boundary check. The second is excluded by the checkpoint at `:384`.

---

## 3. Launch compatibility (your constraints 3)

**No custom framework. No manifest schema change.** Three native additions to
`bringup.launch.py`, all using idioms already present in that file:

| Arg | Default | Effect |
|---|---|---|
| `hardware` | `openmover_lab` | selects `config_defaults/hardware/<name>.yaml` |
| `lidar_driver` | `bluesea2` | `IfCondition` gating `bluesea2_node`×2 **vs** `vanjee_lidar_sdk_node` |
| `io_driver` | `io_board` | `IfCondition` gating `io_board_handler` **vs** `screen_node` |
| `actuation_enabled` | **`false`** | passed to `motor_handler`; **not** read from YAML |

**Rejecting incompatible combinations.** Two native options, in order of preference:

1. **Structural (preferred):** make the driver choice a **single** arg
   (`lidar_driver:=bluesea2|vanjee`) feeding mutually exclusive `IfCondition`s. Two drivers can
   never be launched because they are two branches of one condition — not because a validator
   polices them. Same for `io_driver`.
2. **Fail-fast guard:** an `OpaqueFunction` that raises if `hardware` and `lidar_driver` disagree
   (e.g. `hardware:=swjtumover` with `lidar_driver:=bluesea2`). This is ~5 lines and uses
   `OpaqueFunction`, which the file already uses.

**Recommendation: both.** (1) makes the bad state unrepresentable; (2) catches a *stale* explicit
override that contradicts the profile.

**Explicitly rejected:** a `hardware:` key in `caasi.yaml`, a profile registry, a plugin
mechanism. The profile is a launch-time fact; the target's **tags** (already implemented) are the
natural place to record *which* machine it belongs to.

---

## 4. Watchdog boundary (D7) — recorded, out of scope, blocking M7

**Finding (measured, pre-existing in both implementations):** `speed_rpm_*` is written only inside
the `cmd_vel` callbacks (`motor_handler.cpp:180,194,198,214,228,232`). The send loop transmits the
**last stored value every iteration**. **No timeout zeroes it.** A publisher that stops mid-command
leaves the last nonzero RPM commanded indefinitely.

**Scope decision:** *not* changed here. Changing it would alter existing lab behaviour, which your
constraints protect.

**Standing rule (recorded as a project constraint):**

> **No physical movement test (M7) may proceed until a stale-command mitigation is separately
> reviewed, implemented and tested.** The `actuation_enabled` gate does **not** mitigate this — it
> prevents *unauthorised* actuation, not *stale* actuation by an authorised publisher.

These are two different properties and must not be conflated:
- `actuation_enabled` answers *"may this process actuate at all?"*
- a watchdog answers *"should this command still be in effect?"*

---

## 5. Compatibility gates (D4, D5)

### 5.1 D4 — odometry interface

CAASI publishes `PoseWithCovarianceStamped` on `openmover/hardware/odom`. The robot's ROS 1
publishes `nav_msgs/Odometry` on `odom`. **Gate: enumerate the real subscribers before deciding.**
Specifically confirm that `navigation_handler`, `localization_handler`,
`localization_confidence_handler` and `obstacle_handler` consume the CAASI type and do not require
`nav_msgs/Odometry`. If any consumer needs the ROS 1 shape, add a small relay **then** — not
speculatively.

### 5.2 D5 — message semantics, not just fields

Field equality is already proven (`header, phase_current, rpm, position_deg` + 5 fault bools).
**Still to verify (semantic):**

| Aspect | Question |
|---|---|
| `rpm` sign | Is negative "reverse" in both? (Robot measured `rpm: -1` at rest.) |
| `position_deg` | Cumulative or wrapped? (Robot measured `349.9` and `21.4` — suggests wrapped 0–360.) |
| `phase_current` units | Amperes in both? (Robot measured ~0.0002 A at rest.) |
| Fault flags | Same meaning per bit, or merely same names? |
| `header.frame_id` | Robot leaves it empty; does CAASI's expect a frame? |

**Gate: resolve these before reusing the message.** If a semantic mismatch exists, a separate
package *is* justified — which is exactly why D5 was conditioned.

---

## 6. Vanjee underlay verification (D2) — corrected assessment

### 6.1 ROS 2 support is real, but the build is **not** one line from usable

| Layer | Status |
|---|---|
| Publisher layer (`source_scandata_ros.hpp:101+`, `source_pointcloud_ros.hpp:193+`, `source_imu_packet_ros.hpp`) | ✅ **ROS 2 implemented** (`rclcpp::Publisher`, `sensor_msgs::msg::LaserScan`, frame/topic from YAML) |
| `main()` ROS 2 branch | ⚠️ minimal: `rclcpp::init()` + wait. **`config_path` is inside `#ifdef ROS_FOUND`**, so under ROS 2 the config path cannot be overridden — it always falls back to the compiled-in `PROJECT_PATH` |
| `CMakeLists.txt:18` | ❌ `set(COMPILE_METHOD CATKIN)` — a **plain `set()`, not `CACHE`**, so `-DCOMPILE_METHOD=COLCON` **does not override it**. A source edit is required. |
| `vanjee_lidar_msg` | ❌ **catkin-only**: `buildtool_depend catkin`, `find_package(catkin … message_generation)`, `generate_messages()`. **No ament/`rosidl_generate_interfaces` path exists.** |
| `vanjee_driver` (nested) | ⚠️ plain CMake, `add_subdirectory`'d — needs `yaml-cpp`, `Eigen3`, `PCL`; `TBB`/`PCAP` optional (`DISABLE_PCAP_PARSE=ON`, `ENABLE_TBB=OFF` by default) |

**Therefore: three changes, not one** — (i) make `COMPILE_METHOD` overridable, (ii) port or bypass
`vanjee_lidar_msg` for ament, (iii) expose `config_path` under ROS 2.

### 6.2 Because of (ii), reconsider the options honestly

| Option | Effort | Maintenance | Note |
|---|---|---|---|
| (a) External underlay, patched | 3 small patches; a fork to track | **fork drift** | still the lightest that reuses the vendor driver |
| (b) Upstream PR to Vanjee | unknown latency | none if accepted | correct long-term; not a plan dependency |
| (c) Write a thin ROS 2 node over **`vanjee_driver`** (plain CMake, no ROS dependency) | ~1 node, no message-package port | **we own the node** | **Viable** — the ROS 2 publisher layer is thin; `vanjee_driver` does the decoding. Avoids the catkin-only msg package entirely and needs no `COMPILE_METHOD` patch. |
| (d) Use a different existing ROS 2 lidar bridge | unknown | none | **must be investigated before (c)** — the integration-first rule |

**Recommendation: investigate (d) first, then (c), then (a).** I previously recommended (a)
outright; on the evidence of §6.1 that was premature — the catkin-only message package makes (a)
more invasive than presented.

**Verification requirements before D2 is settled** (none performed; the robot is unreachable):
1. Does a ROS 2 **Jazzy** build of the SDK succeed, with its actual dependency set?
2. Do `yaml-cpp`, `Eigen3`, `PCL` exist in the **Jazzy** target environment?
3. ~~Is `vanjee_lidar_msg` actually consumed by the scan path?~~ **RESOLVED — NO.** Verified:
   `grep -rn vanjee_lidar_msg src/source/source_scandata_ros.hpp source_pointcloud_ros.hpp` →
   **no match**. The catkin-only package is referenced **only** by the *packet* message paths
   (`src/msg/ros_msg/vanjeelidar_packet.hpp`, `src/vanjee_lidar_msg/…`). **A scan-only ROS 2 node
   needs no message-package port at all**, which materially reduces the cost of every option below.
4. Licence: **BSD-3-Clause — confirmed compatible**; no copyleft obligation. Attribution required.

### 6.3 Consequence of U3 on the options

Because the catkin-only `vanjee_lidar_msg` is needed **only** by packet/IMU publishing — not by
`/scan` — a **scan-only** integration avoids the hardest blocker entirely:

| Option | Now costs |
|---|---|
| (a) patched underlay | `COMPILE_METHOD` override + `config_path` exposure; **message port no longer needed** for scan |
| (c) thin node over `vanjee_driver` | unchanged (still viable, still avoids all ROS packaging) |

This raises (a) back toward viability and leaves (c) as the low-risk fallback. **Option (d) — an
existing maintained ROS 2 bridge — is still to be investigated before either**, per the
integration-first rule.

---

## 7. Validation plan — workstation only, no hardware

| # | Test | Proves | Level |
|---|---|---|---|
| **V1** | **UDP sink**: run `motor_handler` with `actuation_enabled:=false` pointed at a local UDP socket. Publish **nonzero** `cmd_vel` repeatedly, then again after a delay. Assert **every** captured command frame has `speed_rpm == 0` (bytes 2–3). | Constraints 1, 3, 4 — including that a nonzero command received while disabled never reaches the wire. | L2 |
| **V2** | Same sink, **enable** after V1 sent nonzero commands. Assert the **first** transmitted frames after enabling are zero, proving no stale release. | Constraint 4 (the hard case). | L2 |
| **V3** | Run with the parameter **absent**; assert the node fails closed (does not start, or starts with actuation denied) and **emits no nonzero frame**. | Constraint 1. | L2 |
| **V4** | Run with an **invalid** value (wrong type / unrecognised); assert deny. | Constraint 2. | L2 |
| **V5** | Telemetry: with actuation disabled, assert `odom`, `twist`, `motor_state/left|right` still publish. | Constraint 5. | L2 |
| **V6** | Parameter load: assert the **loaded values** (`chassis_radius 0.103`, `wheel_acc 1800`, `odom_compensation_ratio 1.047`, `control_freq 50`) — not merely that the node started. | The measured default-substitution hazard. | L2 |
| **V7** | Launch introspection: `hardware:=openmover_lab` ⇒ no vanjee node, bluesea2 ×2; `hardware:=swjtumover` ⇒ inverse. Assert **BOTH** drivers never appear together. | Incompatible-combination impossibility. | L2 |
| **V8** | Launch guard: `hardware:=swjtumover lidar_driver:=bluesea2` ⇒ **fails fast**. | Fail-fast guard. | L2 |
| **V9** | D4 consumer check: enumerate subscribers of `openmover/hardware/odom`; assert none requires `nav_msgs/Odometry`. | D4 gate. | L1/L2 |
| **V10** | D5 semantic check: resolve the five semantic questions in §5.2. | D5 gate. | L1/L2 |
| **V11** | `screen_node` against a UDP sink: exact `qrcode.txt="…"` + 3×`0x00`, dedup honoured. | New node correctness. | L2 |
| **V12** | Regression: full suite (1,250) stays green; lab parameter snapshot unchanged. | No lab regression. | L2 |

**No V-test requires the robot.** V1–V4 need only a UDP socket on the workstation.

---

## 8. Acceptance criteria (exact)

**M1 (actuation safety) is complete when:**
- ✅ `actuation_enabled` is declared **without a usable default**; absent ⇒ denied.
- ✅ Any non-`true` value ⇒ denied.
- ✅ The deny is applied **at `motor_handler.cpp:384`**, after packet composition.
- ✅ Zeroing is re-applied **every iteration** (not once), so no stale value can survive.
- ✅ Enabling clears the stored command buffer.
- ✅ V1, V2, V3, V4, V5, V6 pass on a workstation with **no robot attached**.
- ✅ The **shutdown flush** (`:560-572`) is **not** gated and still emits zeros.
- ✅ Lab profile behaviour is byte-identical (lab launch entry passes `actuation_enabled:=true`).

**M2 (launch selection) is complete when:**
- ✅ V7 and V8 pass; no manifest/message/CLI change was made.

**M3 (screen_node) is complete when:**
- ✅ V11 passes; the node implements **only** the QR protocol.

**M4 (Vanjee) is complete when:**
- ✅ One of §6.2 (d)/(c)/(a) is chosen **with build evidence**, not source inspection.
- ✅ `/scan` publishes from a **recorded rosbag** with no hardware attached.

**D-gates close when:** D1 ← V4-grade requirements check; D2 ← §6.2 build evidence;
D4 ← V9; D5 ← V10.

---

## 9. Remaining uncertainties

| # | Uncertainty | Blocks |
|---|---|---|
| U1 | Does **any** consumer require `nav_msgs/Odometry`? | D4 |
| U2 | Are the five `motor_state` **semantics** identical (sign, wrap, units, fault meaning)? | D5 |
| U3 | Does the Vanjee scan path need `vanjee_lidar_msg` at all, or only packet/IMU paths do? | D2 cost |
| U4 | Does a Jazzy build succeed with the real dependency set? | D2 |
| U5 | Is there an existing maintained ROS 2 Vanjee bridge? (§6.2 (d), not yet investigated) | D2 choice |
| U6 | Can CAASI's ROS 2 stack satisfy the robot's **actual** nav requirements (D1 gate)? | D1 |

**Not uncertain:** the actuation design (§2) is fully specified and testable without hardware.

---

## 10. Should NOT be implemented

Hardware-profile system / manifest `hardware:` key · new CLI command · plugin framework · new
message package (pending D5) · ROS 1 nav port (pending D1) · second motor implementation ·
`laserscan_virtualizer` / `laser_merger_node` · helper scripts · camera streaming or LiDAR decoding
inside CAASI · **a watchdog change inside M1–M6**.

---

## 11. Recommended next action

**Implement M1 only** — the actuation gate and parameter validation — because it is the sole
safety-critical change, has **no dependency on any driver**, and every acceptance criterion (V1–V6)
is provable on a workstation against a UDP sink.

M2–M5 remain gated on D1/D2/D4/D5 as recorded. M7 remains blocked by D7 independently.
