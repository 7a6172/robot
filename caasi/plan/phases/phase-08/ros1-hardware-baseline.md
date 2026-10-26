# Phase 8 — ROS 1 Hardware Baseline (measured on the robot)

**Date:** 2026-10-26
**Environment:** `swjtumover05`, Ubuntu 20.04.6, ROS Noetic, `/opt/ros/noetic`, 283 packages.
Workspace `~/swjtumover/swjtumover_ws` (prebuilt). Devices reachable:
`192.168.100.100` (motor+IO), `192.168.110.100` (LiDAR), RealSense D415 on USB.
Disk: 17 GB free on `/` (57 GB total, 70 % used).

**Rules honoured:** ROS 1 source and installation untouched; nothing installed; no reboot; no
persistent device reconfiguration; only read/get traffic to the LiDAR. Motor tests were run with
the robot on its support, wheels clear, with an explicit zero after every pulse and a detached
zero-loop armed first. All test drivers live in `/tmp` on the robot, not in the project.

> Evidence levels: **L4** measured on the physical robot · **L1** source only.
> Raw captures remain on the robot under `/tmp/evidence`, `/tmp/wt_*`, `/tmp/char_ev`,
> `/tmp/lidar_ev`, `/tmp/rs_ev`; only summaries are recorded here.

---

## 1. The single most important finding

**`motor_node` loads no configuration at all when started with `rosrun`.** With no launch file and
no `rosparam load`, `rosparam get /motor_node` returns *"Parameter [/motor_node] is not set"* and the
node runs on compiled-in defaults:

| Parameter | Code default | Robot `motor.yaml` | Error if defaulted |
|---|---|---|---|
| `chassis_radius` | 0.225 | **0.103** | **+118 %** |
| `wheel_radius` | 0.0535 | **0.05035** | +6.2 % |
| `wheel_acc` | 10000 | **1800** | ×5.6 |
| `odom_compensation_ratio` | 1.0 | **1.047** | −4.5 % |
| `control_freq` | 100 | **50** | ×2 |

Every measurement below was taken **with `motor.yaml` explicitly loaded first**, because the real
deployment path (`bringup.launch`) loads it. This is a latent hazard in ROS 1, not a defect in the
measurement: anything that starts the node outside the launch file silently drives with ~2× the
track width.

---

## 2. Motor controller and odometry — L4

Commanded 0.15 m/s straight for 2.001 s, sampled at ~25 Hz from the node's own telemetry:

| Metric | Left | Right |
|---|---|---|
| Steady-state rpm (mean / median) | 27.7 / 28.0 | 28.7 / 29.0 |
| Expected rpm for 0.15 m/s, r = 0.05035 | **28.4** | **28.4** |
| Rotation during pulse | −312.3° | −309.5° |
| Implied tread distance | 0.2744 m | 0.2719 m |
| Motion detected after command | 179 ms | 158 ms |
| **At rest after explicit zero** | **88 ms** | **87 ms** |

| Odometry | Value |
|---|---|
| Type / frames | `nav_msgs/Odometry`, `odom` → `base_link` |
| Δx over the run | **+0.2786 m** (0.928 × commanded 0.300 m) |
| Δy | +0.0017 m |
| Residual at rest | 0 rpm (±1) |

**The 7 % shortfall is latency, not calibration.** 2.001 s commanded − ~0.17 s latency = 1.83 s ×
0.15 m/s = **0.275 m**, which matches the measured tread (0.274 m) and odometry (0.279 m). rpm
scaling itself agrees with `60/(2πr)` to within 2 %.

### Single-wheel pulses (0.5 s, differential trick)

Left-wheel-only was achieved exactly: with `chassis_radius` loaded,
`linear.x = +0.025, angular.z = −0.025/0.103` yields `speed_right = 0`, `speed_left = +0.05 m/s`.

| Test | Moving wheel peak rpm | Moving wheel Δposition | Non-moving wheel | odom Δx |
|---|---|---|---|---|
| right forward | +13 | **−22.90°** | left 0.01° | +0.00309 m |
| right reverse | **−13** | **+22.68°** | left 0.01° | **−0.00300 m** |
| both forward | L +16 / R +12 | L −20.36° / R −24.56° | — | +0.01319 m |

**Sign conventions (definitive):**
- positive `linear.x` → **positive rpm** and **decreasing `position_deg`** (the two disagree in sense)
- positive `linear.x` → **positive odom x**
- reverse mirrors both, to within 3 % magnitude
- `angular.z` positive turns right wheel forward, left wheel backward

### ROS 2 acceptance criteria derived from this
1. Same topic names/types: `/odom` `nav_msgs/Odometry`, `odom`→`base_link`.
2. rpm ≈ `v·60/(2πr)` within 5 % at steady state.
3. Command→motion latency of the same order (~0.15–0.2 s); document the ROS 2 figure.
4. **Stop within ~100 ms of an explicit zero, and reach 0 rpm.** *(ROS 2 additionally has the
   watchdog; ROS 1 has none.)*
5. Reproduce the sign conventions above, or document a deliberate divergence.
6. Reject running with defaulted geometry (ROS 2 already fails closed).

---

## 3. LiDAR (Vanjee 718H) — L4

Driver `vanjee_lidar_sdk`, config `swjtumover_bringup/config/lidar.yaml` passed explicitly.

| Item | Measured |
|---|---|
| Type / addressing | `vanjee_718h`, lidar `192.168.110.100`, host `192.168.110.10`, MSOP 5000 → host 7000 |
| Rate | **14.029 Hz** |
| Samples per scan | **1440** |
| Frame / angles | `lidar_link`, ±π, increment 0.004363323 rad |
| `scan_time` / `time_increment` | 0.071428575 s / 4.96e-05 s |
| Range limits | 0.25 / 25.0 m |
| Returns | 1325 finite, 0 `inf`, 115 `NaN` |
| Range min/median/max | 0.425 / 2.800 / 9.934 m |
| Timestamps | **monotonic, wall clock** (offset 0 s), period 71.53 ms → `use_lidar_clock: false` |
| Warnings | 1 × `ERRCODE_MSOPTIMEOUT` (transient at start-up, stream unaffected) |

Matches the phase-8 capture (14.03 Hz, 1440 samples) — reproducible.

**ROS 2 acceptance criteria:** `/scan` `sensor_msgs/LaserScan`; `lidar_link`; 1440 samples;
±π at 0.004363323 rad; 0.25–25.0 m; ~14 Hz; **wall-clock** stamps (not device clock);
`NaN` for no-return (not `inf`).

---

## 4. RealSense D415 — L4

Launched with the same arguments `bringup.launch` uses (`align_depth`, `pointcloud`,
`clip_distance 3.0`, 640×480@30).

| Item | Value |
|---|---|
| Color | `rgb8` 640×480, **16.60 Hz** (30 requested) |
| Aligned depth | `16UC1` 640×480, **16.59 Hz** |
| Frame id (both) | `d415_color_optical_frame` |
| Camera info | `plumb_bob`, 640×480, fx **608.405**, cx **317.537** |
| Depth valid pixels | 53.0 % this run (94.2 % in the phase-8 capture — scene dependent) |
| Depth range | 1253 / 1919 / 2991 mm (max truncated by `clip_distance 3.0`) |
| TF | `d415_link` → `d415_color_frame`, `d415_depth_frame`, `d415_aligned_depth_to_color_frame`; then to the matching `_optical_frame`s |
| Warnings | 8 (libusb `control_transfer … Resource temporarily unavailable`, benign) |

**ROS 2 acceptance criteria:** same frame ids and TF chain; `rgb8`/`16UC1`; aligned depth topic;
plumb_bob intrinsics of the same order; **do not assume 30 fps** (≈16.6 Hz observed on this host);
document achieved rates rather than the requested ones.

---

## 5. TF — L4

- `odom` → `base_link` resolves; identity at rest, updated at ~1 Hz.
- Camera publishes its own subtree under `d415_link`.
- **Defect observed (ROS 1):** `motor_node` intermittently broadcasts
  `TF_DENORMALIZED_QUATERNION` with quaternion `(0,0,0,0)` for `base_link`, which `tf2` rejects and
  discards. Seen repeatedly during the pulse runs, absent in the passive capture. Not investigated
  further; recorded because a ROS 2 implementation must not inherit it, and because it means the
  TF chain can silently drop out.

---

## 6. Screen / QR — L4 (from phase 8, not repeated)

`qrcode.txt="<text>"` followed by three `0x00` terminators, four separate datagrams, destination
`192.168.100.100:26`, duplicates suppressed. Already reproduced byte-identically by the ROS 2
`screen_handler`. No further evidence needed.

---

## 7. IO board — **not measured this pass**

`io_board_handler` is a lab node; the robot uses `screen_node` on the same port. Passive inspection
only, because the lab node's frame carries lift/LED/BMS fields whose physical effect was not
established. **Deliberately not exercised** — it could energise outputs. Next step, if wanted: a
read-only capture of what arrives *from* `192.168.100.100:26` while `screen_node` runs.

---

## 8. Status of every baseline item

| Item | Status |
|---|---|
| Motor telemetry, scaling, signs | **verified** |
| Motor latency / stop behaviour | **verified** |
| Odometry scaling and direction | **verified** (shortfall explained by latency) |
| Effective runtime configuration | **verified** — and found to be *absent* without the launch file |
| LiDAR configuration, rate, scan characteristics | **verified** |
| LiDAR timestamp convention | **verified** (wall clock) |
| RealSense streams, intrinsics, TF | **verified** |
| RealSense achieved frame rate | **verified** (~16.6 Hz, not 30) |
| TF tree and mounting | **verified**, with one intermittent ROS 1 defect recorded |
| Screen/QR protocol | **verified** (phase 8, reproduced in ROS 2) |
| IO board behaviour | **missing** — deliberately not exercised |
| Startup order / recovery | **partially verified** (start-up times measured; recovery not provoked) |
| QoS-independent ROS 1 behaviour | **not applicable** (ROS 1 has no QoS) |

## 9. Remaining gaps, prioritised

1. **IO board** — needs a decision on whether to capture its inbound traffic only.
2. **TF quaternion defect** — reproduce deliberately, decide whether ROS 2 needs a guard.
3. **Camera frame rate** — confirm whether ~16.6 Hz is a host/USB limit or a setting, so the ROS 2
   configuration targets a reachable value.
4. **LiDAR `ERRCODE_MSOPTIMEOUT`** — benign here, but worth confirming it does not scale with load.
