# Phase 8 — Vanjee Feasibility, IO-Board Fix, and Jazzy Readiness

**Date:** 2026-10-26
**Scope:** the two authorized workstation tasks, plus the Ubuntu 24 / Jazzy inspection and
dependency plan. No packages installed, no robot configuration changed, no device traffic.

---

## 1. Vanjee thin-node feasibility — **CONFIRMED at build level**

### 1.1 The driver builds unmodified

`vanjee_driver` (plain CMake, the layer under the vendor's ROS wrapper) compiles with **no source
changes** — just two arguments:

```bash
cmake ../vanjee_driver -DCMAKE_BUILD_TYPE=Release \
      -DCOMPILE_LIB=ON \
      -Dvanjee_driver_DIR=<src>/vanjee_driver/cmake
make -j2
# -> lib/lib/libvanjee_lidar_driver_lib.so   (1.2 MB)
```

Two things had to be discovered by building, not by reading:

- `COMPILE_LIB` defaults to **OFF**, so a plain configure produces **no targets at all** (an
  apparently successful configure followed by an empty `make`).
- `lib/lib/CMakeLists.txt:70` calls `find_package(vanjee_driver REQUIRED)` on **itself**. That
  resolves only in config mode, so `CMAKE_MODULE_PATH` does not work — `vanjee_driver_DIR` must
  point at the source `cmake/` directory where the config template is generated.

Both are build *invocations*, not patches. **No fork, no vendored copy in the CAASI tree.**

### 1.2 ROS dependency status

| Layer | ROS coupling |
|---|---|
| `vanjee_driver` (decoder, socket, protocol) | **none** — `grep` for `rclcpp` / `ros/ros.h` / `catkin` returns nothing |
| scan message types | driver ships its own `msg/scan_data_msg.hpp` and `decoder_vanjee_718h.hpp` emits `ScanData` for the 718h |
| ROS publishing (`source_scandata_ros.hpp`) | SDK layer, **not needed** by a thin node |

So the scan path is reachable **without `vanjee_lidar_msg`** (the catkin-only package) and without
the SDK's ROS wrapper — confirming the earlier assessment.

### 1.3 What the thin node must do

1. Include `vanjee_driver` headers; instantiate the 718h driver through `api/lidar_driver.hpp`.
2. Register the **ScanData** callback (the driver provides scan data for this model).
3. Convert `ScanData` → `sensor_msgs/msg/LaserScan`. The reference conversion in
   `source_scandata_ros.hpp` is ~25 lines: degrees→radians for the angles, `emplace_back` of
   ranges/intensities, timestamp split into `sec`/`nanosec`, `frame_id` from config.
4. Publish on a configurable topic with a configurable frame id.

**Remaining feasibility risk (small, but honest):** the conversion must reproduce the exact fields
measured from ROS 1 (§4 of the baseline report): 1440 samples, ±π, increment 0.004363323,
`range_min` 0.25, `range_max` 25.0, **wall-clock** stamps, `NaN` (not `inf`) for no-return. Those are
assertions for the thin node's tests, not assumptions.

**Not yet done:** the node itself, and any test against a recorded/synthetic packet source. The
build and the API surface are proven; the node is the next unit of work.

---

## 2. IO-board default-port hazard — **FIXED** (commit `7759f14`)

`io_board_handler` targeted `192.168.100.100:23` when `robot.port` was omitted, because the
parameter defaulted to the **motor controller's** port. Changed:

| Rule | Behaviour |
|---|---|
| `robot.ip_address`, `robot.port` | **required**; absence is a startup error naming the key |
| `robot.port == 23` | **refused outright** with an explanation, even if set explicitly |
| port outside 1..65535 | refused |
| non-integer port / empty address | refused |

`26` remains the documented IO destination and is preserved when configured.

**9 tests** (`caasi/tests/test_io_board_config.py`), UDP sink only, no device traffic: missing port,
missing address, empty address, port 23, three out-of-range ports, a string port, and a positive
case proving frames follow the configured destination and only that destination.

Two of my own mistakes were caught by these tests and are worth recording:
- I re-declared `robot.control_freq`, which already exists further down, and the node aborted with
  `ParameterAlreadyDeclaredException`. Verified against the unmodified file that the duplicate was
  mine, not pre-existing.
- My first "destination" assertion read `addr[1]` from `recvfrom`, which is the *sender's*
  ephemeral port, not the destination. Corrected.

---

## 3. Ubuntu 24 / Jazzy inspection

| Item | Value |
|---|---|
| OS / kernel / arch | Ubuntu **24.04.5 LTS**, 6.8.0-147-generic, amd64 |
| Disk | 59 G total, **43 G free** (23 % used) |
| CPU / RAM | 4 cores (Intel N150), 7 GiB |
| ROS 2 | Jazzy, **298 packages** installed |
| Interfaces | `wlp2s0` 10.212.19.95/24, `tailscale0` — **only** |
| RealSense | present on USB (`8086:0ad3`) |

### 3.1 Blocking finding: the internal device NICs are down

`enp1s0` and `enp3s0` are **administratively down with no addresses**, and
`/etc/netplan/` contains only `50-cloud-init.yaml` with **no device stanza**. Consequently, from
Ubuntu 24:

```
192.168.100.100  UNREACHABLE   (motor + IO board)
192.168.110.100  UNREACHABLE   (Vanjee LiDAR)
```

On Ubuntu 20 the same two NICs were up as `192.168.110.10/24` and `192.168.100.10/24` and both
devices answered — so this is missing configuration, not a hardware change. **No hardware
validation on Ubuntu 24 is possible until those addresses are configured**, which is a network
change requiring explicit authorization.

### 3.2 Dependency split

**Required on the physical robot** (launch-critical):

| Package | Status | Why |
|---|---|---|
| `ros-jazzy-joint-state-publisher` | missing (2.4.3 available) | `bringup.launch.py` starts it |
| `ros-jazzy-realsense2-camera` | missing (4.58.4 available) | RealSense D415 driver |
| `librealsense2-udev-rules` | to confirm | device permissions for the D415 |
| `ros-jazzy-nav2-map-server`, `ros-jazzy-nav2-lifecycle-manager` | missing | map loading in `modules/mapping/map_server.launch.py` |
| `ros-jazzy-cartographer-ros` | missing | localization/mapping modules |
| `ros-jazzy-rviz2` | missing | optional (visualisation only) |

**Simulation-only — not needed on the robot:** `ros-jazzy-ros-gz-sim`,
`ros-jazzy-ros-gz-bridge`, `ros-jazzy-xacro` (only used by `warehouse_simulation`).

Already installed and sufficient: `robot_state_publisher`, `tf2_ros`.

### 3.3 Proposed installation (awaiting authorization)

```bash
sudo apt update
sudo apt install -y \
  ros-jazzy-joint-state-publisher \
  ros-jazzy-realsense2-camera \
  ros-jazzy-nav2-map-server \
  ros-jazzy-nav2-lifecycle-manager \
  ros-jazzy-cartographer-ros
```

Risks and notes:
- 43 GB free is ample; these packages are small (tens of MB).
- All five resolve from the already-configured `ros2.sources` repo, so **no new apt source is added**.
- `realsense2-camera` pulls `librealsense2`; the D415 needs its udev rules, which usually ship with
  it. Worth checking `lsusb` permissions after install rather than assuming.
- Deliberately **excluded**: `ros_gz_*` (simulation), `xacro` (simulation only), `nav2_bringup`
  (the project uses its own planner; only the map server/lifecycle pieces are referenced).

**I have not installed anything.** This needs your authorization, or you can run it yourself.

---

## 4. Corrections to earlier assumptions

- **Ethernet:** clarified that *internal* hardware links (LiDAR on `192.168.110.0/24`, motor/IO on
  `192.168.100.0/24`) do use Ethernet cables; only *external* connectivity (router/internet) is
  Wi-Fi-only. This matches the Ubuntu 20 measurements exactly and confirms §3.1 is a configuration
  gap rather than a design change.
- Earlier in this phase I recorded the workstation as routing toward `192.168.100.0/24`. That is
  still true and is why every ROS 2 test here uses `127.0.0.1` sinks.
