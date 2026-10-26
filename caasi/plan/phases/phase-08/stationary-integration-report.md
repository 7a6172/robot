# Phase 8 — Stationary ROS 2 Integration Report (robot, 2026-10-26)

**Objective:** validate the real ROS 2 integration on `swjtumover05` against the measured
ROS 1 baseline, with motor actuation disabled.

**Environment:** Ubuntu 24.04.5 / Jazzy, Intel N150 (4 cores), 7 GiB, deployed at
`/home/swjtumover/caasi-deployments/openmover`, project rev `3dee4dd89f` → now `05cd4b6`.
Devices reachable on the internal links (motor/IO 1.4 ms, LiDAR 0.9 ms). **Robot stationary
throughout; no actuation, no pulses, no navigation.**

---

## 1. What ran through caasi

| Step | Command | Outcome |
|---|---|---|
| Register target | `caasi target list` (after adding `~/.config/caasi/config.yaml`) | target `swjtumover05` present |
| Reachability | `caasi target check swjtumover05` | **ONLINE**, ping 83.8 ms, probe 1581 ms, capabilities `ros2, ros2:jazzy` |
| Discovery | `caasi target inspect swjtumover05` | CPU N150/4, 7.5 GiB, no GPU, Ubuntu 24 / kernel 6.8.0-147, Python 3.12.3, ROS 2 jazzy |
| Deploy | `caasi deploy swjtumover05` | **VERIFIED**, 838 files / 40.5 MiB |
| Build | `caasi build --target swjtumover05` | **all 9 packages**, 366.15 s |
| Selective rebuild | `caasi build --target swjtumover05 -p openmover` | **20.89 s** |

Everything above is caasi-managed. Everything below (starting nodes, sampling topics) was
**manual SSH + direct `ros2` commands** — recorded as gaps in §5.

---

## 2. Verified on the robot

### 2.1 Actuation gate — CLOSED (verified through both factors)

```
actuation_enabled=false（默认禁用；非显式 true 一律禁用）
环境条件未满足（CAASI_MOTOR_ACTUATION 缺失或不为 "1"），物理驱动保持禁用
物理驱动禁用（缺少: 参数与环境变量）。遥测与日志照常，只发送零速度指令
```

- The robot's profile `config_defaults/hardware/swjtumover.yaml` contains **no**
  `actuation_enabled` key — only a comment explaining why (verified by grep on the target).
- `CAASI_MOTOR_ACTUATION` was **unset** in the launch environment.
- Permission was therefore denied on both factors, and the node still ran and published.

### 2.2 Telemetry at rest

| Topic | Rate | Values |
|---|---|---|
| `/openmover/hardware/odom` | **43.81 Hz** | x 0.00887, y 2.6e-05, quaternion w 0.99990 |
| `/openmover/hardware/motor_state/left` | **42.75 Hz** | rpm 1, phase_current 0.129, all five fault flags false |
| `/openmover/hardware/motor_state/right` | **42.84 Hz** | (same shape) |

### 2.3 Screen handler

```
screen_handler ready -> 192.168.100.100:26 at 5.0 Hz (socket ok)
/qrcode_text subscribed
```

Endpoint and rate match the measured ROS 1 configuration. **No payload was sent**: the node
only transmits when the text changes, and nothing was published during the test.

### 2.4 IO-board guards (runtime, on the robot)

| Configuration | Result |
|---|---|
| `robot.port` omitted | **exit 1**, "缺少必需参数… 缺失: robot.port" |
| `robot.port:=23` | **exit 1**, "robot.port=23 是电机控制器的端口，IO 板必须使用 26。拒绝启动…" |
| `robot.port:=26` | accepted (exit 124 = running); pointed at **127.0.0.1**, so the live IO board was *not* contacted |

The third case deliberately avoided the real board: the IO frame carries lift/LED/BMS fields
whose physical effect is not established, so it was aimed at loopback.

### 2.5 Watchdog

Configured and logged: `指令看门狗超时 = 0.50 s`. Not exercised with motion (no actuation
this milestone) — its behaviour was proven earlier on the workstation (87 nonzero frames
while commanded → 0 after the source stopped).

---

## 3. Deviations from the ROS 1 baseline — and one real gap

| # | Item | ROS 1 (measured) | ROS 2 (measured) | Assessment |
|---|---|---|---|---|
| D1 | Telemetry rate | 25.0–27.7 Hz | **~43 Hz** | Different loop derivation; not wrong, but the ROS 2 rate should be explained or aligned. Recorded. |
| D2 | **`odom → base_link` TF** | published by `motor_node` | **NOT published** — `tf2_echo`: *Invalid frame ID "odom" … frame does not exist* | **Integration gap.** ROS 2 moved this TF to `localization_handler`; with only `motor_handler` running there is no odometry TF at all. The full stack needs the localization node up, or `motor_handler` needs a TF broadcaster. |
| D3 | odom x at rest | ~2e-05 | **8.9 mm** | Small nonzero offset at rest. Unexplained; worth checking whether odometry is seeded from the board's persisted position. |
| D4 | Shutdown | (not measured) | **SIGINT did not stop the node within 3 s**; SIGTERM did | Recorded. On the workstation the same node exits on SIGINT with a SIGSEGV after the flush; here it simply kept running. Shutdown behaviour needs a deliberate fix. |
| D5 | `/scan` | 14.03 Hz, 1440 samples, `lidar_link` | **NOT PRODUCED** | **Not validated.** No ROS 2 Vanjee node exists yet — the thin node is not implemented. |

### 3.1 The launch is not yet driver-switching (important scope statement)

`bringup.launch.py` gained `hardware` / `lidar_driver` / `io_driver` arguments with validation
(unknown profile and contradictions are rejected), **but the node entries were not rewired**.
With `hardware:=swjtumover` it still starts `bluesea2_node` ×2 and `io_board_handler`, not
`vanjee` + `screen_handler`.

Consequently **the full bringup was not run**, and this milestone validated the nodes
individually instead. Calling §2 a "stationary bringup" would overstate it.

---

## 4. caasi defects and gaps found by doing real work

| ID | Gap | Detail | Impact |
|---|---|---|---|
| **C1** | `deploy` does not create the destination's parent directory | `rsync: mkdir … failed: No such file or directory` (code 11) on a fresh robot | First deploy to any new robot fails; requires a manual `mkdir -p` |
| **C2** | `~` in `deployment_root` is not expanded | Remote paths are single-quoted, so `cat > '~/…/x'` created a **literal `~` directory**; metadata landed there and verification failed | The documented default (`~`) is broken for remote targets |
| **C3** | `deploy` changed-file list is incomplete | Reported `Changed Files: 1 (.caasi-deployment.json)` while 41.4 KiB of source was also transferred | Provenance understates what changed |
| **C4** | Console script shebang is stale | `.venv/bin/caasi` points at `/home/zar/Documents/phd/robot/...`; must run `python -m caasi.cli.main` | Caasi is not invocable as documented |
| **C5** | No dependency report | The whole `colcon` → `nav2_costmap_2d`/`octomap` → `osqp-vendor` discovery loop was manual, one round-trip at a time | This is exactly the `caasi target deps` gap already proposed |
| **C6** | No generic remote ROS 2 execution | Starting nodes and sampling topics needed raw SSH | `caasi ros … --target` covers *observation* but not starting a runtime; `run`/`workload` needs a declared experiment |

---

## 5. Acceptance-criteria ladder — where we actually are

| Level | Claim | Status |
|---|---|---|
| L0 | Registered | **✅** |
| L1 | Reachable | **✅** measured |
| L2 | Discovered | **✅** measured |
| L3 | ROS 2 works through caasi | **⚠️ partial** — deploy and build are caasi-managed; running/observing was manual (C6) |
| L4 | Hardware validated | **⚠️ partial** — motor telemetry, IO guards, screen config validated; **`/scan` not produced**; TF gap (D2) |
| L5 | Fleet operation | **❌** not attempted; only one robot registered |

---

## 6. Next highest-priority gaps

1. **Vanjee ROS 2 thin node** — without it there is no `/scan`, and the LiDAR (the robot's
   primary sensor) is unvalidated. Its feasibility is already proven (driver builds unmodified,
   emits `ScanData`); this is the single blocking item for L4.
2. **Wire the launch driver switch** — make `hardware:=swjtumover` actually start
   `vanjee` + `screen_handler`, so the *bringup* (not individual nodes) can be validated.
3. **Fix D2 (`odom → base_link`)** — decide whether `motor_handler` publishes it or whether the
   bringup always includes `localization_handler`; today neither happens in isolation.
4. **caasi C1/C2** — two small deploy bugs that make a fresh robot fail; worth fixing before
   any fleet work, since every new robot hits both.
5. **caasi C5** — `target deps`, the read-only dependency report (already approved in principle;
   extend the existing check machinery rather than adding a parallel command).

**Nothing here claims equivalence.** Motor and IO behaviour are validated against measured
ROS 1 values; `/scan` and TF are explicitly not validated.
