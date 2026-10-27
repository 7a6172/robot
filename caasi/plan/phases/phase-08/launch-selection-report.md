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
