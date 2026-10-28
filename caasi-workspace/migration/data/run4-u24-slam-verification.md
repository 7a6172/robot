# Run 4: slam_toolbox on U24, maze mapping, migrated ROS 2 stack

Battery charged. Same bounded procedure as the ROS 1 reference: telemetry verified before any
command, bounded exploration, bag recorded throughout.

## Pre-flight (safety order)

| check | result |
| --- | --- |
| boot: U24 / Jazzy, both NICs | up, uptime 147 min |
| **battery**, protocol probe with the production frame | **289 / 292 replies (99.0 %)** |
| board ping | 1.25 ms, 0 % loss |
| LiDAR ping | up |
| stray processes / port 7000 | none / free |
| packags needed for this step | all present after the owner's apt install |

Telemetry before motion: `/scan` 14 Hz, `/odom` 50 Hz, `/motor_state` **44.6 Hz per motor**,
median gap 20.0 ms, **max gap 60 ms**, **0 fault messages**. TF `odom -> base_link` identity and
`base_link -> lidar_link` 0.141 m / 1.500 deg, as on ROS 1. `screen_node` reported UDP connected.

## Mapping run

Bounded explorer, 90 s, same safety envelope as before.

| measurement | ROS 1 gmapping (run 2) | ROS 2 slam_toolbox (run 1) |
| --- | --- | --- |
| duration / commanded travel | 93 s / 7.77 m | 93 s / 6.28 m |
| odometry rate | 49.6 Hz | **49.3 Hz** |
| odometry path length | 8.04 m | 7.61 m |
| map cells | 992 x 992 (gmapping default +-25 m box) | 92 x 91 (tightly cropped) |
| occupied cells | 917 | 754 |
| walls span | 5.9 x 4.8 m | 4.6 x 4.5 m |
| **median scan-to-map offset** | **2.5 cm** | **2.5 cm** |
| map->odom corrections | 2795 | 7865 |
| feedback timeouts during the run | n/a | **0** |

The scan-to-map offset is the quality metric that matters and it is identical: the live laser
hits land within half a map cell of the walls the map contains. Map size differs only because
gmapping allocates a fixed +-25 m grid while slam_toolbox crops to the explored area -- compare
occupied *density*, not pixel counts.

## Defect 4: slam_toolbox is a lifecycle node; the launch never activated it (fixed)

`slam.launch.py` started `sync_slam_toolbox_node` and it came up **unconfigured**:

    ros2 node info /slam_toolbox
      Subscribers: /parameter_events (only)
      Publishers:  /parameter_events, /rosout, transition_event (only)

No `/scan` subscription, no `/map` publisher, and nothing in the log to say so -- the launch
looked perfectly healthy. `ros2 lifecycle set /slam_toolbox configure` then `activate` turned it
into a working mapper immediately (`/map` at 3 s, `map -> odom` published), which confirmed the
parameters were right and only the lifecycle was missing. ROS 1's gmapping started mapping as
soon as it launched, so this had no ROS 1 counterpart to warn us.

The launch now runs `nav2_lifecycle_manager` with `autostart: true` for `slam_toolbox`, the same
way navigation.launch.py already did for nav2 -- an inconsistency inside my own work. Regression
test added and verified by removing the manager from the description (2 failures) and restoring
it (34/34 green).

## Map saving differs from ROS 1 (recorded, not hidden)

ROS 1 used `rosrun map_server map_saver -f <prefix>`. On ROS 2:

* `ros2 run nav2_map_server map_saver_cli -f <prefix>` **fails here** -- `Failed to spin map
  subscription` -- even though `/map` from slam_toolbox is RELIABLE + TRANSIENT_LOCAL, which is
  what map_saver asks for, and even with `map_subscribe_timeout:=20.0`.
* `ros2 service call /slam_toolbox/save_map slam_toolbox/srv/SaveMap "{name: {data: '<dir>/map'}}"` **works** (`result=0`, writes `map.pgm` + `map.yaml`) **provided the directory already
  exists**; it does not create it, and returns `result=255` when it is missing.

So the documented way to save a map from this stack is the `save_map` service. The map used above
was additionally extracted from the bag, which is robust and gives the trace data too.

## Verdict

The ROS 2 stack now does what the ROS 1 one did: maps the maze, with the same 2.5 cm scan-to-map
alignment, at the same odometry rate, with the same TF contract, and with a watchdog ROS 1 never
had. Mapping parity: **confirmed**. Navigation (nav2) remains unproven on hardware.
