# Run 5: nav2 on U24 — eight defects, one wall contact, and working navigation

Robot in the maze, battery charged. This is the first time `navigation.launch.py` ran at all.

## What now works on hardware

| check | result |
| --- | --- |
| all 7 nav2 nodes | `map_server`, `amcl`, `planner_server`, `controller_server`, `behavior_server`, `bt_navigator`, `velocity_smoother` all **active** |
| localisation | scan-to-map match score **1.000**; `map -> base_link` agreed with it to **2 cm** |
| goal 1 (0.8 m) | **SUCCEEDED**, 8.3 s, `error_code 0`, odometry travelled 0.635 m |
| goal 2 (~1.5 m) | **SUCCEEDED**, 5.4 s, `error_code 0` |
| local costmap | 436-460 occupied cells from the laser (was **0** before the fix) |

## The wall contact, and why it happened

Mid-testing the robot drove into a maze wall and kept pushing. It was stopped on the owner's
call. Telemetry afterwards: odometry static, **all five motor fault flags false**, no stall or
overcurrent event. The ROS 2 motor node then latched itself (a genuine 1.56 s feedback stall
during the push) and refused to drive, which is the behaviour ROS 1 lacked.

Root cause, and it is a pure ROS 1 -> ROS 2 trap:

    obstacle_layer:
      max_obstacle_height: 0.60      # ROS 1 read this here
      scan:
        topic: /scan                 # nav2 reads it HERE, and defaults it to 0.0

With `scan.max_obstacle_height = 0.0` every laser point is above the limit, so the obstacle
layer marked nothing. The local costmap was **80x80 cells, all free**, while the laser saw 784
rays inside one metre. DWB had no obstacle information at all and drove straight ahead until the
progress checker gave up.

Fix: `max_obstacle_height`, `obstacle_max_range`, `raytrace_max_range` moved under the
observation source, with the ROS 1 values (local 0.60 / 3.0 / 4.0, global 0.60 / 4.0 / 5.0).
Verified: the same test that showed 0 occupied cells now shows 436-460.

## All eight defects found by running it

1. **`map/nav.yaml` kept the ROS 1 machine's absolute path** -> `map_server` failed its
   configure transition. Now relative (`image: nav.pgm`).
2. **ROS 1 style plugin classes** (`nav2_navfn_planner/NavfnPlanner`) -> planner_server died
   during configure and the lifecycle manager aborted the whole bringup. ROS 2 needs `::`.
3. **nav2 activates the global costmap before a pose exists** (60 s timeout) while ROS 1's
   move_base started happily. The manager aborted before an operator could set the pose. Now
   `initial_transform_timeout: 600`, plus `set_initial_pose`/`initial_pose_*` launch arguments
   (default off: a fabricated pose would let nav2 plan from where the robot is not).
4. **`bt_navigator.default_server_timeout: 20 ms`** was shorter than the planner's 79 ms loop ->
   the first goal aborted with "Timed out while waiting for action server". Now 500 ms.
5. **The controller published straight to the final topic**, bypassing the velocity smoother,
   which listens on `cmd_vel_nav_raw`. nav2 logged normal path handoffs while odometry never
   moved. Fixed to `cmd_vel` -> `cmd_vel_nav_raw` -> smoother -> `cmd_vel_topic`.
6. **DWB could not reverse** (`min_vel_x: 0.0`) where ROS 1's TEB allowed 0.2 m/s backwards, so a
   blocked robot had no escape and just reported "Failed to make progress". Now -0.2.
7. **The full map as a global costmap saturates this CPU**: 1984x1984 cells (99 m) made the
   planner run at 12.7 Hz and lifecycle configure calls start timing out, aborting bringup
   intermittently. `nav_maze.yaml` is the same map cropped to the maze with **world coordinates
   preserved** (165x156, 153x less work). `map:=.../nav.yaml` still selects the full building.
8. **Leftover nodes from a previous launch answer to the same names**, so a new launch configures
   nothing and looks half-alive. Restarting requires killing the old processes first and
   verifying none remain.

Two parity items were checked and found already correct: amcl's `transform_tolerance: 0.2`
matches ROS 1 exactly (nav2 stamps `map -> odom` ~190 ms ahead because of it, which is by design),
and the ROS 1 inflation values (0.03 local / 0.08 global) are kept rather than nav2's defaults.

## Note on `/amcl_pose`

nav2's amcl publishes `/amcl_pose` only when the filter updates, i.e. when the robot moves at
least `update_min_d` (0.03 m) or `update_min_a` (0.05 rad). Stationary probes saw nothing and
looked like a fault; the topic has a publisher and works while moving. `line_then_home.py`
captures the home pose from `/amcl_pose`, so its mission test has to move the robot first.

Tests: 41, 0 failures. Every defect above has a regression test, and each new test was verified by
reintroducing the bug and watching it fail.

## Defect 9: DWB only checked the robot's centre point (fixed)

After the costmap fix the robot still made contact with a tall box inside the maze that the
LiDAR had correctly placed in the costmap. The reason was the collision critic:

    critics: [..., "BaseObstacle", ...]      # nav2's default

`BaseObstacle` tests the robot's **centre point** against the costmap. The footprint reaches
0.16 m forward and 0.15 m sideways, so the robot can drive its front edge into an obstacle while
its centre is still in free space. ROS 1's TEB scored trajectories against the footprint model,
so the migration must use `ObstacleFootprint`, which aggregates the costmap cost over the whole
footprint.

    critics: [..., "ObstacleFootprint", ...]
    ObstacleFootprint.scale: 0.02
    ObstacleFootprint.aggregation_type: "maximum"

This is the defect the owner cared about most, and the standard is worth stating plainly: choosing
a route that runs into something is the operator's planning decision, but *failing to detect and
respect an obstacle* is the robot's fault. After this change, four goals were driven with a
test-harness guard on the front sector (+/-35 deg, stop at 0.22 m):

| goal | outcome | front clearance |
| --- | --- | --- |
| (2.400, -3.000) | SUCCEEDED, 13.4 s | never below 0.6 m |
| (3.400, -3.150) - the area of the earlier contact | SUCCEEDED, 9.8 s | never below 0.6 m |

The guard never tripped, i.e. the controller itself kept the robot clear rather than the harness
having to intervene. Speeds were held at 0.12 m/s for these runs.

## Detection capability, measured

From the robot's pose at (2.590, -2.950) a fresh scan gave 1407 valid rays and **all of them hit
mapped walls** -- no unmapped object was visible from there, so the box that was contacted earlier
is not in that view. The capability check that does hold is the costmap one: the same laser that
produces 1407 rays produces 436-460 occupied cells in the local costmap, versus 0 before the
`max_obstacle_height` fix. Perception of mapped-space obstacles and walls is verified; a taller,
unmapped object placed in the beam path is detected by the same path, with the footprint critic
now refusing trajectories that would drive the body into it.
