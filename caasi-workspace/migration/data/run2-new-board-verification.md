# Run 2: maze mapping and motion check with the replacement motor controller

Purpose: confirm the swapped-in controller works correctly on the robot in the maze, and capture
fresh reference data. Robot on Ubuntu 20.04 / Noetic, back in the puzzle maze.

## Safety sequence, in this order before any command

The board failure earlier came from a latched command, so nothing was commanded until the
controller had been proven to answer:

1. ping and ARP: `192.168.100.100` answered in **1.08 ms**, MAC `00:04:a3:00:01:df`.
2. protocol probe using **exactly** the production driver's frame (`acc` computed from
   wheel_acc 1800, `byte7 = 0x00`, zero speed, 50 Hz): **291 of 292 frames answered, all with
   valid CRCs**.
3. stack up, then telemetry checked *before* motion: `/odom` **50 Hz**, `/motor_state` 50 Hz,
   `/scan` 14 Hz, `rpm 0`, and every fault flag (`over_temperature`, `stall`,
   `phase_overcurrent`, `overcurrent`, `sensor`) **False**.
4. only then exploration, with the explorer's own telemetry watchdog armed.

No probe variant other than the production frame was used this time.

## Mapping

Same procedure as run 1: `slam_gmapping` at 0.05 m with the ROS 1 parameters, the bounded
reactive explorer, and a bag recorded throughout.

| measurement | run 1 (backup board) | run 2 (this board) |
| --- | --- | --- |
| duration / commanded travel | 111 s / 10.99 m | **93 s / 7.77 m** |
| odometry path length | 6.93 m | **8.04 m** |
| occupied cells in the map | 1082 | 917 |
| walls span | 6.2 × 6.2 m | 5.9 × 4.8 m |
| **median scan-to-map offset** | 2.6 cm | **2.5 cm** |
| scan snapshots recorded | 25 | 24 |
| `map -> odom` corrections | 2995 | 2795 |

The scan-to-map offset is the number that matters: the laser hits land within half a map cell of
the walls the robot drew, so the map and the live sensor agree. Run 2 matches run 1 (2.5 vs 2.6
cm) on a different exploration path, which is the consistency check that the controller swap did
not degrade anything.

## Motion scale, with the replacement controller

Same bounded probe used for the ROS 1 reference (0.06 m/s for 6 s each way, zero stream after):

| direction | measured | ratio | yaw drift |
| --- | --- | --- | --- |
| forward | 0.3462 m | **0.9616** | +0.0033 rad |
| reverse | 0.3479 m | **0.9663** | +0.0168 rad |

Earlier on this robot (also a working controller) the same test gave 0.3396 / 0.3399 m at ratio
0.943 with ±0.07–0.09 rad of yaw drift. The distance ratios agree within ~2%, which is
robot/floor variation; the much lower yaw drift now suggests the larger drift seen earlier was
not a chassis trait but the degrading controller.

## Explorer behaviour change

The first explorer turned at 0.6 rad/s with no anti-oscillation and accumulated 182 turn ticks in
111 s — that is what looked like "circling too fast". The version used here turns at 0.4 rad/s,
requires the same clearance before advancing, and adds a **telemetry watchdog**: if odometry
stops arriving for 1 s it publishes zero and exits, so a controller that has stopped answering is
never left receiving motion commands. It also always ends with a 3 s zero stream and is never
killed mid-command.

## Verdict

The replacement controller works: it answers the protocol, streams 50 Hz telemetry with all
fault flags clear, drives to within 4% of the commanded distance, and produces a map whose scans
align to 2.5 cm. Fresh data (map, 140 s bag, 6931 odometry poses, 24 scan snapshots) is stored in
this directory for the ROS 1 / ROS 2 comparison.
