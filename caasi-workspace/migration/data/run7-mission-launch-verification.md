# Run 7: the mission launch, executed for the first time

`line_then_home.launch.py` had never been run -- only the mission node on its own. Reading it before
running it exposed three defects and one dead argument; running it confirmed the fixes and showed
exactly how far the stack gets on a low battery.

## Defects found by reading, fixed before the run

1. **`lidar_bind_lead` was declared but never forwarded** to the bringup include. It set the
   `TimerAction` period, while the bringup kept its own 3 s default, so the two disagreed the moment
   anyone changed the argument.
2. **`autostart_mission` was declared and never used.** It was my invention, not ROS 1's: the
   mission starts through `/line_then_home/start`, as the shell history shows. A dead argument is
   worse than none because it looks configurable, so it was removed rather than implemented --
   an auto-start path that drives the robot unattended is not something to add unasked.
3. **The line follower kept its ROS 1 camera defaults** (`/d415/color/image_raw`,
   `/d415/depth/image_rect_raw`). On Jazzy `realsense2_camera` publishes `/camera/camera/...`, so the
   follower would never have received an image: it would simply never move, with no error.
   `color_topic` and `depth_topic` are now launch arguments with the Jazzy defaults.
4. **The default map was `nav.yaml`**, the 99 m building map, while `navigation.launch.py` already
   defaulted to the cropped maze map. Now consistent.

## What running it proved

Started through caasi (`caasi run start experiments/mission.yaml -t swjtumover05`), stationary:

| check | result |
| --- | --- |
| processes | **15 started, 0 died** |
| node set | **21 nodes**: bringup (motor, screen, LiDAR adapter, 2 state publishers), all of nav2, the mission and the follower |
| mission state | **IDLE** |
| mission services | `/line_then_home/{start,stop,record_waypoints}` present |
| `record_waypoints` | `success=True`, "Waypoints cleared. Click them in return order; the start point is appended after the last one." |
| `stop` | `success=True`, "stopped" |
| follower | `enabled = False` -- cannot drive until the mission enables it |
| map served | **`nav_maze.pgm`, 165 x 156** -- the cropped default is in effect |

`~start` was deliberately **not** called: it enables the follower, and the owner's instruction for
this session was no motion. It also would have been refused, because `/amcl_pose` never arrives
without odometry.

## Why nav2 did not fully activate, and why that is correct

The board is on a low battery, so it stopped answering the protocol (it still pings, 0.97 ms). The
chain is visible in the log:

    motor feedback timeout, locked to zero speed; left gap 217.268 s
    global_costmap: Timed out waiting for transform from base_link to map
                    (Invalid frame ID "map" ... frame does not exist)

No board → no telemetry → the motor node latches and stops publishing `/odom` → no
`odom -> base_link` → amcl cannot produce `map -> odom` → nav2's global costmap keeps waiting, as
designed. `/scan` kept working throughout (14 Hz, with 0.38 s gaps under load). Nothing here is a
launch defect: with a charged board the same launch brought all seven nav2 nodes to `active` when
the pose was set during run 5.

## Still outstanding

The full round trip (FOLLOW → STOP → NAV → DONE) needs a charged robot positioned on the line, with
permission to move. Everything up to that point is verified.
