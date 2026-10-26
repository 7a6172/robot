# Phase 8 Gate 2: RealSense D415 + Motor Telemetry Verification

**Status:** Completed — bounded, driver-only, robot stationary
**Date:** 2026-10-25/26
**Host:** robot `swjtumover05`, native **Ubuntu 20.04.6 / ROS Noetic**, `swjtumover@10.212.19.94`
**Scope:** RealSense D415 (approved request) **and** motor telemetry (covered by the user's
broad subsequent authorization: *"you can do all the remaining tests you need under noetic"*).
**Reported separately from the LiDAR evidence** per instruction.

> Evidence levels are kept explicit. **Nothing here is a claim of ROS 1 → ROS 2 equivalence.**

---

# PART A — RealSense D415

## A.1 Pre-execution checks (all requested)

| Check | Result |
|---|---|
| **1. Launch file / config / startup** | `bringup.launch` includes `realsense2_camera/launch/rs_camera.launch` with `camera:=d415`, `serial_no:=""`, `initial_reset:=true`, `publish_tf:=true`, `align_depth:=true`, `filters:=pointcloud`, color 640×480@30, depth 640×480@30, `clip_distance:=3.0`. All these args **exist** in the installed Noetic wrapper (`align_depth` default false, `filters` default "", `initial_reset` default false) — so the bringup genuinely changes driver behaviour. |
| **2. D415 connected / no driver running** | `lsusb`: `8086:0ad3 Intel RealSense D415`. `/dev/video0..5` present. `ps` for `realsense\|nodelet`: **none running**. |
| **3. Exact command + expected topics** | `roslaunch realsense2_camera rs_camera.launch` with the bringup arg set. `<group ns="$(arg camera)">` ⇒ namespace **`/d415`**. Expected: `/d415/color/image_raw`, `/d415/aligned_depth_to_color/image_raw`, `/d415/color/camera_info`, plus `pointcloud` from `filters:=pointcloud`. |

## A.2 Result — driver healthy, real sensor data

| Measurement | Color | Depth (aligned) |
|---|---|---|
| Topic | `/d415/color/image_raw` | `/d415/aligned_depth_to_color/image_raw` |
| Type | `sensor_msgs/Image` | `sensor_msgs/Image` |
| Encoding | **`rgb8`** | **`16UC1`** |
| Dimensions | **640 × 480** | **640 × 480** |
| `frame_id` | **`d415_color_optical_frame`** | **`d415_color_optical_frame`** |
| `step` | 1920 | 1280 |
| **Measured rate** | **16.58 Hz** | **16.60 Hz** |
| Requested fps | 30 | 30 |

### Valid depth measurements — CONFIRMED (L4)

```
total px 307200 · valid (>0) 289418 = 94.2% · invalid 17782
depth mm  min / median / max: 1024 / 1649 / 1933
depth m   min / median / max: 1.024 / 1.649 / 1.933
center 5x5 (mm):
 1596 1579 1568 1560 1556
 1599 1582 1570 1565 1560
 1601 1584 1577 1570 1565
 1599 1587 1579 1575 1572
 1599 1589 1582 1579 1575
```

The depth plane is a **smooth, coherent ~1.6 m surface** with monotonic gradients — this is real
stereo depth, not noise or a constant fill. **94.2 % valid pixels** is a healthy D415 indoor figure
(the 5.8 % invalid being the usual texturless/shadowed regions).

### Color validity

`rgb8`, 100 % non-black pixels, per-channel means R/G/B = **82 / 108 / 129** (bluish-indoor scene),
full 0–255 range present. Real image data.

### Camera intrinsics

`/d415/color/camera_info`: 640×480, `distortion_model: plumb_bob`, 5-coefficient `D`, frame
`d415_color_optical_frame`.

### TF published

`d415_link → d415_color_optical_frame`: translation `[0.000, 0.015, 0.000]`,
quaternion `[-0.499, 0.500, -0.500, 0.500]` ≈ RPY `[-89.938°, 0.054°, -90.036°]`.
Consistent with a standard RealSense optical-frame convention.

### Diagnostics / warnings

`RealSense Node Is Up!` · depth/color streams enabled at the requested profile.
**9 warnings, all the same benign libusb message:**
`control_transfer returned error, index: 768/300, error: Resource temporarily unavailable`
The classic transient USB control-transfer warning at startup; **it did not affect streaming**
(both streams delivered data at a steady rate).

## A.3 Note — rate below requested 30 fps

Measured **~16.6 Hz** against a requested **30 fps** for both streams. Possible causes: USB 2.0
link, host CPU (Intel N150, 4 cores) saturation with `align_depth` + `pointcloud` filters, or
driver-side throttling. **Not investigated further** — recording it as an observed fact, not a
defect. **This matters for the ROS 2 port: 30 fps cannot be assumed as achievable on this host.**

## A.4 Clean shutdown

`roslaunch` + `nodelet manager` stopped (SIGINT); `rosmaster`/`roscore` stopped.
**All processes gone**, port 11311 free, no leftover nodelets. The D415 **re-enumerated on USB**
(Device 002 → 003) due to `initial_reset:=true` — expected behaviour, device healthy afterwards.

---

# PART B — Motor telemetry (motor_node only)

> Covered by your broader authorization. Executed with the **maximum available safety posture**:
> `motor_node` alone, **no `teleop_node`**, **no `screen_node`**, **no `cmd_vel` publisher anywhere
> in the graph**. With no publisher, `motor_node` commands **zero RPM** continuously.

## B.1 Safety preconditions verified BEFORE launch

| Precondition | Evidence |
|---|---|
| No `cmd_vel` publisher | `rosnode list` = `/rosout` only; `rostopic list` showed **0** `cmd_vel` topics |
| No motor/screen/teleop/nav processes | `ps` clean |
| Only `motor_node` launched | script execs `rosrun swjtumover_bringup motor_node` with explicit params |

## B.2 Graph produced

| Topic | Type | Rate |
|---|---|---|
| `/cmd_vel` | `geometry_msgs/Twist` | (subscribed, **no publisher existed**) |
| `/motor_state/left` | `swjtumover_msgs/motor_state` | **25.00 Hz** |
| `/motor_state/right` | `swjtumover_msgs/motor_state` | (25 Hz) |
| `/odom` | `nav_msgs/Odometry` | **25.07 Hz** |
| `/tf`, `/tf_static` | — | `odom → base_link` |

## B.3 Live telemetry — real hardware (L4)

**Left wheel:**
```
phase_current: 0.000244 A     rpm: -1        position_deg: 349.903
over_temperature_fault: False  stall_fault: False
phase_overcurrent_fault: False overcurrent_fault: False  sensor_fault: False
```
**Right wheel:**
```
phase_current: 0.001465 A     rpm: 0         position_deg: 21.424
all five fault flags: False
```

**`/odom`:** `frame_id: odom`, `child_frame_id: base_link`
`position x≈-5.13e-06, y≈-1.34e-08, z=0`, quaternion `z≈2.49e-05, w≈0.99999999`

### Stationary proof (5 s observation)

```
x=-0.000015 y=0.000000 yaw_z=-0.000025
x=-0.000010 y=0.000000 yaw_z= 0.000050
x=-0.000005 y=0.000000 yaw_z= 0.000025
DRIFT from first: dx=0.000010 dy=0.000000 m
```

**10 µm of drift over 5 seconds. The robot did not move.** `odom → base_link` TF stayed at
translation ≈ 0, rotation ≈ identity (yaw 0.006°).

## B.4 A REAL FINDING — the YAML parameters are NOT loaded outside `bringup.launch`

After launch, the parameter server contained **only** the two values passed on the command line:

```
rosparam list | grep motor
  /motor_node/motor/ip_address
  /motor_node/motor/port
rosparam get /motor_node
  motor: {ip_address: 192.168.100.100, port: 23}
```

**`motor.yaml`'s seven tuning parameters were absent**, so `motor_node` ran on its **code
defaults**: `wheel_acc 10000` (vs YAML 1800), `wheel_radius 0.0535` (vs 0.05035),
`odom_compensation_ratio 1.0` (vs 1.047).

This **confirms and sharpens** the Gate 1 hazard (§5.4). It is not merely theoretical:

- Under `bringup.launch`, `<rosparam file=".../motor.yaml">` inside `<node>` loads into
  `/motor_node/motor/*`, which the code reads — **correct**.
- Under **any other invocation** (`rosrun`, a custom launch, or a naive port), the YAML is
  **silently ignored** and the defaults apply — **changing acceleration by 5.6×, wheel radius by
  6 %, and removing the 4.7 % odometry correction.**

For this test that was **immaterial** (no motion; only `ip_address`/`port` were needed). For the
ROS 2 port it is **a correctness trap**: the port must load the YAML explicitly and must not rely
on defaults.

## B.5 Shutdown

`motor_node` terminated; process confirmed absent (`ps` empty, `/odom` stopped publishing —
`rostopic hz` → *"no new messages"*). A **stale master registration** of `/motor_node` remained in
the master graph after the process died, which is normal ROS 1 behaviour and was resolved by
stopping `roscore`. Motor board remained reachable (ping OK) afterwards.

---

# PART C — Evidence summary

| Subsystem | L1 source | L2 build | L3 runtime | L4 physical |
|---|---|---|---|---|
| LiDAR Vanjee 718H | ✅ | ✅ (binary prebuilt) | ✅ `/scan` 14.03 Hz | ✅ ranges 0.498–9.910 m |
| RealSense D415 | ✅ | ✅ (apt package) | ✅ 16.6 Hz both streams | ✅ depth 1.024–1.933 m, 94.2 % valid |
| Motor telemetry | ✅ | ✅ (binary prebuilt) | ✅ 25 Hz | ✅ rpm≈0, currents µA, 0 faults, 10 µm drift |
| Motor **actuation** | — | — | — | ❌ **NOT TESTED — no `cmd_vel` ever published** |
| screen_node | ✅ | ✅ | ❌ not run | ❌ not run |
| Navigation (gmapping/amcl/move_base) | — | — | ❌ out of milestone 1 | ❌ |
| ROS 2 port | — | — | — | ❌ **does not exist yet** |

**Behavioural equivalence ROS 1 ↔ ROS 2: NOT CLAIMED anywhere.**
These results establish that the **ROS 1 hardware stack works on the real robot**. They do not
establish anything about a ROS 2 implementation, which has not been written.

---

# PART D — What remains

1. **Motor actuation** — never exercised. Requires an approved motion test with the robot clear.
2. **`screen_node`** — UDP payload to `192.168.100.100:26` unverified.
3. **Navigation stack** — explicitly out of milestone 1.
4. **A complete, single-run full-stack baseline** (`bringup.launch`) — the individual subsystems
   are now proven, but they have never been observed running **together** with the real
   `motor.yaml` loaded.
5. **ROS 2 implementation** — not started; blocked on the open design questions from the Gate 1
   report (helper scripts, topic naming, actuation gate).

---

# PART E — screen_node / chassis IO display (added under broad authorization)

Tested in isolation (`screen_node` only, no `motor_node`, no `cmd_vel` publisher).

| Item | Result |
|---|---|
| Node name | **`/screen_handler`** (not `/screen_node` — `NODE_NAME "screen_handler"`) |
| Subscribes | **`/qrcode_text`** (`std_msgs/String`) |
| Publishes | only `/rosout` |
| UDP target | `192.168.100.100:26` |
| Trigger | `qrcode_text_callback` → `send_data("qrcode.txt=\"" + text + "\"")` |

## E.1 Result — WORKING, payload verified byte-for-byte

With a message published on `/qrcode_text`, `tcpdump` on `enp3s0` captured:

```
192.168.100.10.52430 > 192.168.100.100.26: UDP, length 26
192.168.100.10.52430 > 192.168.100.100.26: UDP, length 1
192.168.100.10.52430 > 192.168.100.100.26: UDP, length 1
192.168.100.10.52430 > 192.168.100.100.26: UDP, length 1
```

Hex dump confirms the payload exactly matches the source:
```
0x0020: 6465 2e74 7874 3d22 5041 594c 4f41 445f  de.txt="PAYLOAD_
0x0030: 4348 4b22                                CHK"
```
⇒ **`qrcode.txt="PAYLOAD_CHK"`** followed by three `comm_tail` (0x00) terminator bytes —
precisely the `send_data()` implementation.

**Dedup behaviour confirmed**: the callback only sends when
`msg->data != last_qrcode_text`, so re-publishing the **same** string is silently ignored.
Important for any port test — a repeated test value produces no packet.

## E.2 Methodology correction (recorded honestly)

My **first three** capture attempts reported "screen_node sent nothing", which was **wrong**.
The cause was **backgrounded `tcpdump` inside a non-interactive SSH session not capturing
reliably**, not a node defect. A control experiment (raw Python `sendto` to `:26`) **also** failed
to appear in those background captures, which exposed the harness as the fault rather than the code.

**Lesson:** backgrounded `tcpdump` + `&` + redirect in an SSH one-liner is unreliable here.
Foreground capture with a background *publisher* works. Same class of harness artifact caught twice
before in this project (`rosmsg show` recursion; naive cell-index rounding).
*Rule adopted: a negative result requires a positive control.*

## E.3 Status

Node terminated, `roscore` stopped, all processes clean, port 11311 free.
**No motor interaction.** `screen_node` only talks to the IO board display at port 26.

---

# PART F — Updated evidence summary

| Subsystem | L2 build | L3 runtime | L4 physical |
|---|---|---|---|
| LiDAR Vanjee 718H | ✅ prebuilt | ✅ `/scan` 14.03 Hz | ✅ 0.498–9.910 m |
| RealSense D415 | ✅ apt pkg | ✅ 16.6 Hz both streams | ✅ 1.024–1.933 m, 94.2 % valid |
| Motor telemetry | ✅ prebuilt | ✅ 25 Hz | ✅ rpm≈0, 0 faults, 10 µm drift |
| screen_node (IO display) | ✅ prebuilt | ✅ `/screen_handler` | ✅ payload byte-verified |
| **Motor actuation** | ✅ | — | ❌ **NEVER TESTED** (no `cmd_vel` published) |
| Navigation stack | — | ❌ out of milestone 1 | ❌ |
| **ROS 2 port** | — | — | ❌ **does not exist** |

**Behavioural equivalence ROS 1 ↔ ROS 2: NOT CLAIMED.**
Everything above establishes that the **ROS 1 stack works on the real robot**.
It establishes nothing about a ROS 2 implementation, which has not been written.
