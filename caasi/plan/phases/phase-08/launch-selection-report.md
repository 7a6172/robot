# Hardware launch selection — swjtumover profile

Scope: which components `hardwares/bringup.launch.py` selects for the physical robot. Not a
stationary bringup, not navigation.

## The defect

`hardware:=swjtumover` was validated and then ignored.

* `lidar_driver` and `io_driver` were declared as launch arguments, checked against the
  profile by an OpaqueFunction, and then **never used**: the node list was hardcoded to two
  `bluesea2_node` instances plus `io_board_handler`.
* Their defaults were the lab drivers, so `hardware:=swjtumover` on its own actually failed
  the check ("expects lidar_driver:='vanjee', got 'bluesea2'"), and the only way to get past
  it produced a launch that started the wrong hardware.
* The Vanjee node and the screen handler did not appear in the launch file at all.

So the profile selected a parameter file, and nothing else.

## The change

A profile now describes its drivers as well as its parameter file:

```python
HARDWARE_PROFILES = {
    'openmover_lab': {'yaml': 'hardwares.yaml',          'lidar_driver': 'bluesea2', 'io_driver': 'io_board'},
    'swjtumover':    {'yaml': 'hardware/swjtumover.yaml', 'lidar_driver': 'vanjee',   'io_driver': 'screen'},
}
```

* `_resolve_hardware` resolves empty driver arguments from the profile via
  `SetLaunchConfiguration`, so `hardware:=swjtumover` alone is sufficient, and a contradicting
  explicit driver still fails.
* Every hardware node is gated on the resolved selection **and** real mode, so a profile's
  drivers cannot start under another profile.
* `vanjee_scan_node` and `screen_handler.py` exist in the launch description for the first
  time.
* `laserscan_multi_merger` runs only for the two-bluesea fit. Merging two topics that do not
  exist would replace a working `/scan` with an empty one.
* Consumers subscribe the merged topic by name; for the single-scanner fit that name resolves
  to `/scan`, so downstream stays wired without a second scan type.
* The profile fails by name when its parameter file is missing, and when the selected driver
  package is not installed.

Per-robot configuration moved into the profile file, not the launch file:

* `vanjee_lidar_node` — `192.168.110.10` / `192.168.110.100`, ports 7000/5000, `lidar_link`,
  `scan`, 0.25–25 m, wall-clock stamps.
* `screen_handler` — `192.168.100.100:26`, control 5 Hz.

Screen port 26 vs motor port 23 on the same host address is asserted by a test: the IO
endpoint must not be able to address the motor controller.

## Selected inventory (verified on the robot, from the deployed launch file)

| profile | components |
| --- | --- |
| `swjtumover` | `vanjee_scan_node`, `screen_handler.py`, `motor_handler`, `obstacle_handler`, `robot_state_publisher`, `joint_state_publisher`, `static_transform_publisher`, `speaker_handler.py`, `teleop_handler.py`, localization include |
| `openmover_lab` | `bluesea2_node` ×2, `io_board_handler`, `laserscan_multi_merger`, + the same common set |

Neither starts the other's drivers. Simulation (`system_mode:=0`) starts none of the hardware
drivers, and the Gazebo include is still resolved lazily, so a robot without `ros_gz_sim`
loads the file.

## Validation

* 20 tests in `src/openmover/test/test_hardware_launch_selection.py`, run through
  `colcon test` (21 with the summary) and again **on the robot** against the deployed tree:
  both 0 failures.
* `ros2 launch openmover bringup.launch.py hardware:=nonexistent` →
  `unknown hardware profile 'nonexistent'; known profiles: ['openmover_lab', 'swjtumover']`,
  exit 1, no node started.
* `hardware:=swjtumover lidar_driver:=bluesea2` → rejected with the mutually-exclusive
  message, exit 1, no node started.
* LiDAR path re-validated after the change: `/scan` live at 14.019 Hz, 1440 samples,
  `lidar_link`, ±π at 0.004363323, 0.25–25 m, 1340 finite / 100 NaN, monotonic wall-clock
  stamps. One publisher, one driver process.
* Managed run stopped cleanly; no hardware process left, port 7000 released.

## Deliberately not done

`motor_handler` and `screen_handler` were **selected but not started**: starting them would
mean touching actuation-adjacent processes or sending screen payloads, neither of which this
milestone authorises. Their selection, parameters and fail-closed defaults are verified
through the launch configuration only. The full hardware stack is therefore not yet validated
as running.

`localization_confidence_handler` subscribes the merged topic `openmover/hardware/lidar/scan`
inside the localization include. That include does not accept a scan-topic argument, so on
the single-scanner fit it is not yet remapped to `/scan`. Follow-up for the stationary
bringup milestone.

---

# Follow-up: scan stream → localization, TF ownership, stationary validation

## Scan → localization

The merged topic `openmover/hardware/lidar/scan` is the intentional shared interface:
cartographer, `localization_confidence_handler` and `obstacle_handler` all consume it. The
physical fit has a single 360° scanner publishing `/scan`, so the interface name — not the
data — was wrong for this robot. No merger and no duplicate publisher were added.

The topic is now a launch decision threaded through the stack:

* `localization.launch.py` declares `scan_topic` and forwards it to the mode server.
* `localization_mode_server_handler.py` declares `scan_topic` and passes it into the
  `LaunchHandle` that starts the localization launch file.
* `carto_localization.launch.py` declares `scan_topic` (default unchanged) and uses it in the
  `('scan', …)` remap.
* `localization_confidence_handler` reads `localization_confidence.scan_topic` instead of a
  hardcoded topic (default unchanged, so existing maps are unaffected).
* `bringup.launch.py` passes the same resolved topic it gives the consumers, so the processor
  and the scan source cannot disagree.

Every default reproduces the previous behaviour, so the lab fit and existing maps are
untouched.

## TF ownership of odom → base_link

Single authoritative publisher: **`localization_handler`**
(`src/localization/localization_handler.cpp`, `sendTransform`, child `LOCALIZATION_BASE_LINK`
= `base_link`). It subscribes `openmover/hardware/odom` (published by `motor_handler` or
`simulation_handler`) and `openmover/hardware/twist`. `localization_confidence_handler`
constructs a `TransformBroadcaster` but never uses it, and it runs only in the navigation and
mapping apps, not in bringup. No other component writes that transform.

Measured on the robot, stationary, actuation disabled: parent `odom`, child `base_link`,
116 samples over 8 s, all values finite, quaternion norm exactly `1.000000000` (min = max),
x travel 40 µm, y 12 nm, z 0, stamps monotonic every 180–236 ms, wall-clock offset −0.28 s.
The ROS 1 invalid-quaternion defect is not reproduced on this path.

`odom → base_link` becomes available with `motor.actuation_enabled=false`: the odometry comes
from the motor controller's telemetry, which is read over TCP and does not require the drive
permission. `motor_handler` logged `物理驱动禁用（缺少: 参数与环境变量）… 只发送零速度指令`
("physical actuation disabled (missing: parameter and environment variable) … zero velocity
only") for the whole run.

## Stationary validation (what was actually started)

| component | started | why |
| --- | --- | --- |
| `vanjee_scan_node` | yes | scan source |
| `motor_handler` (actuation denied) | yes | odometry/TF source; gate inspected first |
| `localization_handler` | yes | the `odom → base_link` owner |
| `static_transform_publisher base_link→lidar_link` | yes | what bringup provides |
| `carto_localization.launch.py scan_topic:=/scan` | yes | the real scan consumer |
| `screen_handler` | **no** | would send display payloads |
| `speaker_handler` | **no** | would play audio |
| `obstacle_handler`, `teleop_handler` | **no** | not needed to prove the path |

Evidence that localization receives and processes real scans: `/scan` had publisher 1 /
subscriber 1 (cartographer); cartographer logged `Added trajectory with ID '1'` and then
continuously `range_data_collator.cc:82 Dropped 25 earlier points`, which only happens while
ingesting scan messages; `openmover/localization/pose_aft_mapped` published at ~186 Hz. So
this is processed sensor data, not merely a subscription.

## Configuration findings

* **`speaker_handler` sound assets are absent.** `$HOME/openmover_robot/sounds` does not exist
  on the robot and the package ships no `sounds` directory. The handler used to log "start
  playback" and then swallow the exception, so a missing file looked like success. It now
  logs a warning naming the missing path and does not claim playback.
* Screen endpoint `192.168.100.100:26` is configured in the profile and asserted by a test to
  differ from the motor controller's port 23 on the same host address. No payload was sent.
* `caasi target deps swjtumover05 --for bringup` → 4 installed, 0 missing, 2 optional-absent
  (the simulation-only pair). `--for sim` still reports `ros_gz_sim`/`ros_gz_bridge` as
  required-but-missing, so they stay optional for physical bringup.

---

# Follow-up: integrated stationary bringup, ordering defect, handler hardening

## The blocking defect: every ROS 2 process takes UDP 7000

The Vanjee 718H sends its scan stream to `192.168.110.10:7000`. Measured on the robot: **a
bare `rclpy` node with no OpenMover code binds `0.0.0.0:7000`**, in every ROS domain tested
(0/1/2/7 → the DDS ports move to 7650/7900/9150, the 7000 socket does not). That socket is
held **without `SO_REUSEADDR`**, so nothing else can bind the port afterwards — verified
directly: a specific-address bind with `SO_REUSEADDR` against the running stack fails with
`EADDRINUSE`.

Consequences, measured in the full launch:

* before the fix, `localization_handler` won the port first and `vanjee_scan_node` exited
  immediately: `FATAL cannot bind 192.168.110.10:7000`, no `/scan` at all
* the DDS side *tolerates* losing the port, so starting the driver first leaves the rest of
  the stack fully functional (graph, `/scan`, TF and odometry all verified afterwards)

Fix: the launch starts `vanjee_scan_node` immediately and everything else behind a
`TimerAction(period=lidar_bind_lead)` (default 3 s). This is deterministic ordering, not a
retry loop. `lidar_bind_lead` is a launch argument so a slower machine can widen it.

Not a fix, and deliberately avoided: `SO_REUSEPORT` tricks, disabling DDS, or setting
`StrictHostKeyChecking` style shortcuts. Switching RMW would also solve it but
`rmw_cyclonedds_cpp` is not installed on the robot (checked), so that is an installation
decision, not a code change.

## Diagnostic path

`ros2 run openmover stack_check.py` (installed, read-only, exits 1 on any required failure)
checks in one run: LiDAR socket ownership, scan rate/samples/frame/angles/ranges/stamps/
invalid-sample distribution, publisher and subscriber counts with a graph settle period, the
`odom -> base_link` and `base_link -> lidar_link` transforms (finiteness, quaternion norm,
stationary drift, monotonic stamps), TF publisher inventory and odometry freshness. A test
asserts it contains no publisher, no `.publish(`, no service call and no `cmd_vel`.

## Measured results (stationary tier, actuation disabled)

| item | result |
| --- | --- |
| UDP 7000 owner | `vanjee_scan_node` at `192.168.110.10:7000` |
| `/scan` | 14.035–14.045 Hz, 1440 samples, `lidar_link` |
| angles / ranges | ±3.141592741, increment 0.004363323, 0.25–25.0 m |
| samples | 1354 valid / 86 no-return / 0 infinite |
| stamps | monotonic, +0.004 s from wall clock |
| publishers / subscribers | 1 / 1 (`obstacle_handler`) |
| `odom -> base_link` | 45 samples, drift 40 µm, quaternion norm 1.000000000 |
| `base_link -> lidar_link` | static, drift 0 |
| odometry | 42 Hz, age 0.00 s |
| `/tf` publishers | `localization_handler`, `robot_state_publisher` |
| `openmover/navigation/obstacle` | 20.0 Hz |

`stack_check` reported **all required checks passed**.

## Bringup tiers

| tier | arguments | starts |
| --- | --- | --- |
| diagnostic / stationary | `interaction:=false` | driver, robot_state_publisher, joint_state_publisher, static TF, localization, motor_handler, obstacle_handler |
| full | `interaction:=true` (default) | the above plus screen display, speaker, teleoperation |

`interaction` also gates the screen handler, which writes to the display board over the
network.

## Component defects fixed

* **teleoperation could not fail visibly.** `pynput` is not installed on the robot and there
  is no `DISPLAY`; the node died on import while the launch declared `respawn=True`, i.e. an
  endless restart loop that looks like a running component. It now checks the backend before
  starting, prints one actionable line, exits 3 (module missing) or 4 (no display), and the
  launch no longer respawns it. Observed in the full tier: `cannot start: the 'pynput'
  Python module is not available ... (teleop:=false)`, `process has died [exit code 3]`.
* **speaker reported success for a missing file.** It logged "starting playback" and swallowed
  the exception. It now distinguishes no-backend, empty name, missing file and playback
  failure, naming the path. Observed: `音频后端不可用，播放功能禁用（ModuleNotFoundError: No
  module named 'pygame'）` — the node keeps running and service requests fail visibly.
* **screen wire format was untestable.** The framing (`qrcode.txt="..."` + three NUL tails)
  is now a pure function with tests, and sending is one datagram per frame. No payload was
  sent to the robot: `/qrcode_text` has zero publishers, and the only "send" line in the log
  is `motor_handler`'s zero-velocity warning.

## Environmental prerequisites for the full tier

* `python3-pynput` (teleoperation) and `python3-pygame` + an audio device (speaker) — neither
  is installed; both need authorisation.
* An operator session with `DISPLAY`/`WAYLAND_DISPLAY` for teleoperation.
* Sound assets: `$HOME/openmover_robot/sounds` does not exist and the package ships no
  `sounds` directory.

## Still not validated

* **Real-map localization.** The only map shipped is `maps_defaults/simulation/` (a 0.02 m
  grid with origin −11.40, −7.47). No physical-environment map exists, and producing one
  needs a SLAM run with the robot moving. Cartographer was previously shown to ingest live
  scans against that simulation pbstream; that is not real-map localization.
* The URDF shipped is the **lab** two-bluesea fit (`lidar_forward_link`, `lidar_rear_link`);
  it has no `lidar_link`, which is why the static publisher owns that frame for this profile.
  A per-profile URDF is a modelling change, not made here.
