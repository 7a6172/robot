# swjtumover → ROS 2 migration plan

Migrating the ROS 1 workspace `~/swjtumover/swjtumover_ws` (Ubuntu 20.04 / Noetic) to ROS 2
Jazzy, as a caasi project of its own, independent of the larger `openmover` project.

Source of truth: **`swjtumover01` (10.212.19.194)**, because it is a verified superset of
`swjtumover05`. Its `src/motor_node_original.cpp` is byte-identical to `swjtumover05`'s
`motor_node.cpp`, so nothing unique to `swjtumover05` is lost, and the newer node carries the
command watchdog and feedback timeout that the incident proved necessary.

## Why this package and not openmover

`swjtumover_bringup` is genuinely small: motor driver 661 lines, screen driver 170, CRC helper
46, teleop 165, one message, one launch file, four config files and one URDF. The openmover
migration is paused while this lands.

## Difference audit (swjtumover05 vs swjtumover01)

`~/swjtumover` trees compared by sha256: **692 files identical, 7 changed, 5 only in A, 13 only
in B**.

| category | detail |
| --- | --- |
| only in A (5) | `final.py`, `nav_goal.py`, `ok2.py`, `scan_filter_120deg.py`, `omove_following（复件）.py` (a copy) |
| only in B (13) | `motor_safety.h`, `motor_node_original.cpp`, `line_then_home{,_loop}.launch`, `line_then_home.py`, `exam_full.py`, `assessment_run.py`, `omove_following_{1,feng}.py`, `test.py`, `gmapping.rviz`, `return_waypoints.yaml`, `exam_goals.yaml` |
| changed | `motor_node.cpp` (safety), `CMakeLists.txt` (2 extra scripts), `bringup.launch` (adds `enable_teleop`), `omove_following.py` (stop-and-exit counter, gains, thresholds), `obstacle_rplidar.py` (whitespace), `exam_goals.yaml`, `map/nav.pgm` (data) |

So: B = A + safety hardening + task scripts (line following, exam, navigation goals).

## What has been migrated

| ROS 1 | ROS 2 | notes |
| --- | --- | --- |
| `src/motor_node.cpp` (661 lines) | `src/swjtumover_bringup/src/motor_node.cpp` (588) | protocol, CRC, odometry maths, covariance, left/right alternation unchanged; `motor_safety.h` carried over; the unused `TransformListener` dropped |
| `src/screen_node.cpp` (170) | `src/screen_node.cpp` (~190) | same `qrcode.txt="…"` + three **0xff** tail bytes, same `/qrcode_text` topic, duplicate suppression kept; send errors now reported instead of swallowed |
| `scripts/teleop_node.py` (165) | `scripts/teleop_node.py` (~230) | same ramp, brake-on-flip, release debounce and zero-flush; adds a keyboard-backend check so a headless robot fails with a reason instead of a traceback |
| `utils/crc8_maxim` | `src/utils/crc8_maxim.cpp` | made ROS-free (it only ever needed `cstdint`) |
| `swjtumover_msgs/motor_state.msg` | `swjtumover_msgs/msg/MotorState.msg` | same nine fields, same order and types; package reduced from a 20-dependency catkin package to `std_msgs` only |
| `launch/bringup.launch` | `launch/bringup.launch.py` | see below |
| `config/*.yaml` | `config/*.yaml` | converted from the ROS 1 private-namespace form (`~motor/*`) to ROS 2 per-node form, keeping the parameter names `motor.*`, `screen.*`, `teleop.*`; the ROS 1 files are kept as `*_ros1.yaml` and the tests assert value-for-value equality |
| `urdf/robot_description.urdf` | same file, verbatim | the measured lidar mount (`0.14114 m`, `0.02618 rad`) is asserted by a test |
| `vanjee_lidar_sdk` (ROS 1 vendor wrapper) | `swjtumover_vanjee` | thin adapter over the vendor's ROS-free driver (vendored under `external/`), already validated on this exact LiDAR at 1440 samples / 14 Hz / `lidar_link` |

### Launch behaviour differences, all deliberate

* **LiDAR first, on a timer lead.** In this environment every ROS 2 process binds UDP 7000 and
  the Vanjee sends its scans to `192.168.110.10:7000`; the driver must own it first. Argument
  `lidar_bind_lead` (default 3 s). Measured, not guessed.
* **Optional components are arguments.** `enable_teleop`, `enable_realsense` and
  `enable_visualization` all default to `false`. ROS 1 hardcoded rviz on, which cannot work on
  a headless robot.
* **Teleop does not respawn.** ROS 1 respawned it, which on a headless robot is an endless
  restart loop that looks healthy.

## What is NOT migrated yet, and why

| item | status | reason |
| --- | --- | --- |
| Task scripts (line following, exam, nav goals, `obstacle_rplidar`) | not ported | ~2,500 lines of ROS 1 + OpenCV; explicitly out of the agreed first pass |
| Navigation stack (`gmapping`, `amcl`, `move_base`, costmap/planner params) | not ported | no direct ROS 2 equivalent; needs cartographer/nav2 and new parameter sets. A separate decision |
| RealSense D415 | wired but off by default | the ROS 2 wrapper must be present and its argument names differ from ROS 1; not validated |
| `rviz` configs | file copied, unused | needs a display |

## Environments

* Dev machine: builds and tests run here (17 tests, 0 failures).
* Robots are **read-only** for this task. Deploy and hardware validation are pending, and will
  go through `caasi deploy` / `caasi build` / `caasi exec` exactly as the openmover work did —
  no ad-hoc SSH.

## Next steps, in order

1. Deploy to `swjtumover05` (on U24) with `caasi deploy swjtumover` and build with
   `caasi build --target swjtumover05`.
2. Stationary validation: `/scan` contract, `/odom` at 50 Hz, `motor_state` fault flags clear,
   `odom → base_link` TF geometry.
3. Motion parity against the ROS 1 reference already measured on this robot
   (0.06 m/s × 6 s → 0.3396 m / 0.3399 m, ratio 0.943).
4. Then decide on the task scripts and the navigation stack.
