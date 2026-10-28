# Run 6: task scripts on U24 — obstacle guard, line follower, mission interface, teleop

## Geometry, settled from the model rather than by guessing

The owner described the body as square with the LiDAR centred. Measured from the URDF and the STL
meshes rather than assumed:

| link | mesh extent | offset from base_link |
| --- | --- | --- |
| `base_link` (the body) | **0.320 x 0.300 x 0.089 m** | (0, 0, 0) |
| `lidar_link` | 0.068 x 0.051 x 0.044 | **(0, 0, 0.14114)** - centred on top |
| `wheel_left/right` | 0.101 x 0.055 x 0.101 | y = +-0.103 (outer edge 0.131) |
| four ball casters | 0.060 cube | x = +-0.108, y = +-0.100 |

So the robot fits inside **0.32 x 0.30 m**, all wheels and casters are inside that, and the LiDAR
is exactly on the centre axis. The ROS 1 footprint `[[0.16,0.15],[0.16,-0.15],[-0.16,-0.15],
[-0.16,0.15]]` was therefore numerically correct - and carried **no margin at all** beyond
`footprint_padding: 0.02`.

## The consequence, which caused a wall contact

Because the LiDAR sits at the centre, **every range it reports is measured to the centre, not to
the body edge**. The body still reaches 0.16 m further forward. Stopping when the raw range drops
below 0.22 m therefore leaves just 6 cm of real clearance, and at the 0.25 m the test guard was
reporting the body front was 9 cm from the boundary. The follower kept re-acquiring the line and
commanding short pushes, and the robot crept into contact.

Three fixes, all verified:

1. **The line follower now has an obstacle stop**, measured from the body:
   `OBSTACLE_STOP_DISTANCE = BODY_HALF_LENGTH (0.16) + OBSTACLE_MARGIN (0.12) = 0.28 m`.
   ROS 1's follower had no obstacle check whatsoever - only "line lost" and "end of line" - so
   this is a deliberate safety addition, recorded here rather than passed off as a port.
   Verified on the robot at the exact spot of the contact:
   `obstacle stop: centre clearance 0.25 m < 0.28 m ... holding zero`, robot moved 0.04 m then held.
2. **nav2 footprint padding 0.02 -> 0.06** in both costmaps (effective footprint 0.44 x 0.42).
   The maze's median corridor clearance is 0.70 m, and 83 % of free space stays reachable.
3. The test harness's own guard threshold was the same mistake and is corrected.

## obstacle_rplidar guard - verified

Bounded 15 s run. The node drove forward, logged `Go! 1.033 m` while clear, then
`Stop! 0.847 m < 0.850 m` and held. Odometry reached 0.219 m and did not change afterwards. The
ROS 1 constants (0.2 m/s, 0.8 m + 0.05 m error, +-10 deg sector) behave exactly as before.

## Line follower - verified

| check | result |
| --- | --- |
| vision on a live frame, follower's own crop + BGR thresholds | **6147** line-coloured pixels, centroid x=817/1279 |
| commanding | `/cmd_vel` 0.12 m/s with `angular.z = -yaw*0.6` |
| motion achieved | **0.58 m travelled with 0.18 m lateral drift** - it steered along the line |
| fail-safe | publishes zero whenever the line is not detected |
| end-of-line latch | trips at `end_confirm_frames: 1` (the ROS 1 default), latches `/reached_goal`, needs `/line_follow/enable` to clear - same as ROS 1 |

Camera topics differ from ROS 1: realsense2_camera publishes `/camera/camera/color/image_raw`
where ROS 1 used `/d415/color/image_raw`, so the follower is started with
`-p color_topic:=... -p depth_topic:=...` rather than a code change.

## Mission supervisor - interface now correct, one real port bug

ROS 1 expanded its private names to `/line_then_home/{state,start,stop,record_waypoints}`.
Two ROS 2 mistakes were found by running it:

1. `create_publisher(String, '~state')` raised `InvalidTopicNameException` - **ROS 2 has no `~`
   syntax** - and the node exited at start-up, so the whole supervisor was dead on arrival.
2. Plain relative names are **not** equivalent: they resolve against the node's namespace, so
   `start` became `/start` instead of `/line_then_home/start`. The names are now built from
   `'/' + self.get_name()`, which reproduces the ROS 1 expansion exactly.

Verified on the robot: `/line_then_home/start`, `/line_then_home/stop`,
`/line_then_home/record_waypoints` and `/line_then_home/state` all exist, and
`ros2 service call /line_then_home/start` answers correctly - it refused with
"no /amcl_pose received yet", which is the intended precondition since navigation was not running
for that test. The full FOLLOW -> NAV sequence still needs the complete stack.

## Teleop - verified for the only thing possible headless

`pynput` is installed but there is no X server, and the node's three-way backend classification
caught that precisely:

    cannot start: 'pynput' is installed but cannot attach to a window server
    (ImportError: ... failed to acquire X connection)
    Teleoperation needs an operator session with DISPLAY or WAYLAND_DISPLAY set.

Exit code **3**, as designed. No motion was commanded. Verifying actual key handling needs a
display (Xvfb would have to be installed on the robot).
