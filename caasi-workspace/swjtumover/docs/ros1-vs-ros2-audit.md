# ROS 1 → ROS 2 audit: swjtumover

Detailed comparison of the ROS 1 package (`swjtumover_bringup`, `swjtumover_msgs`,
`vanjee_lidar_sdk`, Noetic / Ubuntu 20.04) against the migrated ROS 2 project (Jazzy / Ubuntu
24.04). Written after the hardware verification, so every claim marked *measured* was observed on
the robot.

## 1. Method and sources

| side | source |
| --- | --- |
| ROS 1 | the originals preserved in this project under `**/ros1_reference/` and `*_ros1.yaml` (24 files), plus the interface and behaviour captured from the live ROS 1 robot |
| ROS 2 | this project, as deployed and built on `swjtumover05` |
| runtime evidence | node/topic/service listings and rate measurements taken on the robot for both systems |

ROS 1 originals kept for comparison: `motor_node.cpp`, `motor_node_original_ros1.cpp`,
`screen_node.cpp`, `crc8_maxim.cpp`, the six launch files, `line_then_home.py`,
`obstacle_rplidar.py`, `omove_following{,_1,_feng}.py`, `exam_*`, `assessment_run.py`, `ok.py`,
`test.py`, plus `motor_ros1.yaml`, `screen_ros1.yaml`, `teleop_ros1.yaml` and the five ROS 1
`param/*.yaml` costmap/planner files.

**Audit gap:** the ROS 1 `teleop_node.py` itself was never copied as a reference (only its
parameter file). Its parameters are compared below from `teleop_ros1.yaml`; a line-by-line diff of
that script has to wait until the ROS 1 machine is reachable again.

## 2. File inventory

| ROS 1 file | ROS 2 | status |
| --- | --- | --- |
| `src/motor_node.cpp` | `src/motor_node.cpp` | ported, protocol and odometry maths unchanged |
| `include/utils/motor_safety.h` | `include/utils/motor_safety.h` | ported unchanged (came from `swjtumover01`) |
| `src/screen_node.cpp` | `src/screen_node.cpp` | ported, three-tail-byte framing unchanged |
| `src/utils/crc8_maxim.cpp` | `src/utils/crc8_maxim.cpp` | copied, ROS dependency removed |
| `msg/MotorState.msg` | `msg/MotorState.msg` | same nine fields, same order |
| `launch/bringup.launch` | `launch/bringup.launch.py` | ported |
| `launch/bringup_gmapping.launch` | `launch/slam.launch.py` | ported (gmapping → slam_toolbox) |
| `launch/map_server.launch` + `amcl.launch` + `move_base.launch` | `launch/navigation.launch.py` | merged into nav2 |
| `launch/line_then_home.launch` | `launch/line_then_home.launch.py` | ported |
| `launch/line_then_home_loop.launch` | — | not ported: a looping wrapper around the same launch |
| `launch/map_save.launch` | — | replaced by the `save_map` service (see §6) |
| `launch/exam_project.launch` | — | exam material, out of scope by decision |
| `scripts/line_then_home.py` | `scripts/line_then_home.py` | ported, states and arbitration preserved |
| `scripts/obstacle_rplidar.py` | `scripts/obstacle_rplidar.py` | ported, constants unchanged |
| `scripts/omove_following_feng.py` | `scripts/omove_following_feng.py` | ported, vision pipeline unchanged |
| `scripts/teleop_node.py` | `scripts/teleop_node.py` | ported, three-way backend classification |
| `scripts/omove_following.py`, `omove_following_1.py` | — | superseded variants of `_feng` |
| `scripts/exam_*.py`, `assessment_run.py`, `ok.py`, `test.py` | — | exam/scratch material, out of scope |
| `urdf/robot_description.urdf`, meshes | same | copied byte-identically |
| `rviz/bringup.rviz` | same | copied |
| costmap/planner `param/*.yaml` | `param/nav2_params.yaml` | converted (§5) |
| — | `src/swjtumover_vanjee/` | **new**: thin LiDAR adapter replacing the vendor ROS 1 node |
| — | `experiments/`, `scripts/caasi_launch.py` | **new**: caasi entry points (§7) |

## 3. Interface audit, node by node

### motor driver

| interface | ROS 1 | ROS 2 | verdict |
| --- | --- | --- | --- |
| publish `odom` | yes | yes | same |
| publish `motor_state/left`, `motor_state/right` | yes | yes | same |
| subscribe `cmd_vel` | yes | yes | same |
| TF `odom → base_link` | yes | yes | same |
| parameters `motor.*` | 9 | 9 + 2 | 2 added (§4) |

### screen driver

| interface | ROS 1 | ROS 2 | verdict |
| --- | --- | --- | --- |
| subscribe `qrcode_text` | yes | yes | same |
| UDP to the display | port 26, three `0xff` tails | same | same |

### line follower (`omove_following_feng`)

| interface | ROS 1 | ROS 2 | verdict |
| --- | --- | --- | --- |
| publish `/cmd_vel` | yes | yes (`cmd_vel`, remapped to `/cmd_vel/line` by the mission) | same |
| publish `/lane_image`, `/line_follow/end` | yes | yes | same |
| subscribe `/line_follow/enable` | yes | yes | same |
| subscribe colour + depth image | yes | yes | same, topic names differ by camera driver (§6) |
| end-of-run signal | ROS 1 set **the global parameter** `/reached_goal` | ROS 2 publishes the **topic** `/reached_goal` (transient local) | **different**, deliberate |
| subscribe `/scan` for an obstacle stop | *none* | added | **new**, safety (§6) |

### mission supervisor (`line_then_home`)

| interface | ROS 1 | ROS 2 | verdict |
| --- | --- | --- | --- |
| publish `/cmd_vel` | yes | yes | same |
| publish `~state` | `/line_then_home/state` | `/line_then_home/state` | same, *measured* |
| subscribe `/cmd_vel/line`, `/cmd_vel/nav` | yes | yes | same |
| subscribe `/amcl_pose`, `/clicked_point`, `/line_follow/end` | yes | yes | same |
| services `~start`, `~stop`, `~record_waypoints` | yes | `/line_then_home/{start,stop,record_waypoints}` | same, *measured* |
| client `navigate_to_pose` | move_base action | nav2 action | same contract |

### obstacle guard

`/cmd_vel` out, `/scan` in, constants `0.2 m/s`, `0.8 m`, `0.05` error, ±10° — identical, and
*measured* behaving the same (`Stop!` at 0.847 m against a 0.850 m threshold).

## 4. Parameter parity

Motor, compared value for value against `motor_ros1.yaml`:

| parameter | ROS 1 | ROS 2 | |
| --- | --- | --- | --- |
| `control_freq` | 50 | 50 | same |
| `ip_address` / `port` | 192.168.100.100 / 23 | same | same |
| `wheel_max_speed_rpm` / `wheel_acc` | 300 / 1800 | same | same |
| `chassis_radius` / `wheel_radius` | 0.103 / 0.05035 | same | same |
| `odom_compensation_ratio` | 1.047 | 1.047 | same |
| `publish_tf` | true | true | same |
| `cmd_vel_timeout` | *absent* | **0.5 s** | added |
| `motor_feedback_timeout` | *absent* | **0.5 s** | added |

The two additions are the watchdog from `swjtumover01`'s `motor_safety.h`. Their absence in ROS 1
is exactly why a killed process could leave the robot driving — the incident that started this
work.

`screen.*` (control_freq 5, port 26) and `teleop.*` (velocity_x 0.2, velocity_yaw 0.4, max_x_acc
0.2, max_yaw_acc 0.4) are identical; only the YAML nesting differs (`<node>: ros__parameters:`) as
ROS 2 requires.

## 5. Navigation: ROS 1 stack → nav2

| ROS 1 | ROS 2 | notes |
| --- | --- | --- |
| `map_server` + `nav.yaml` | `nav2_map_server` + same map | identical map, resolution 0.05, origin preserved |
| `amcl` (particles 2000-5000, likelihood_field_prob, beamskip) | `nav2_amcl` | same particle counts, model and `transform_tolerance: 0.2` |
| `global_planner/GlobalPlanner` | `nav2_navfn_planner::NavfnPlanner` | NavFn either way |
| **TEB** local planner | **DWB** | no maintained ROS 2 TEB port assumed; kinematics carried over |
| `global_costmap` (static+obstacle+inflation, track_unknown_space) | same three layers | values matched |
| `local_costmap` (4×4 m rolling, 0.05) | same | values matched |
| — | `behavior_server`, `bt_navigator`, `velocity_smoother` | nav2 structural requirements |
| `move_base` → `/cmd_vel/nav` | velocity smoother → `/cmd_vel/nav` | arbitration preserved |
| `slam_gmapping` | `slam_toolbox` | particle filter → pose graph |

Costmap values taken from the ROS 1 files: `max_obstacle_height 0.60`, local `obstacle_range 3.0` /
`raytrace 4.0`, global `4.0` / `5.0`, inflation `0.03/10.0` local and `0.08/8.0` global, footprint
`[[0.16,0.15],[0.16,-0.15],[-0.16,-0.15],[-0.16,0.15]]`.

## 6. Deliberate differences

1. **TEB → DWB.** No maintained ROS 2 TEB port is assumed to exist on the robot. Kinematics copied
   into DWB (`max_vel_x 0.6`, `max_vel_theta 1.0`, `acc_lim_x 0.5`, reverse `-0.2`) and the ROS 1
   TEB file kept for reference. Trajectory shape will differ.
2. **gmapping → slam_toolbox.** Both provide `map → odom`; a particle filter and a pose graph do not
   produce identical maps. Measured scan-to-map alignment is nevertheless identical (2.5 cm).
3. **`/reached_goal` parameter → topic.** ROS 1 signalled completion through a global parameter,
   which ROS 2 has no equivalent for across processes. A transient-local `Bool` topic carries the
   same meaning; anything that read the parameter must subscribe instead.
4. **Camera topics.** ROS 1 used `/d415/color/image_raw`; `realsense2_camera` on Jazzy publishes
   `/camera/camera/color/image_raw`. Handled with the follower's `color_topic` / `depth_topic`
   parameters, not a code change.
5. **rviz and teleoperation are arguments, not hardcoded.** ROS 1's `bringup.launch` always started
   rviz, which simply fails on a headless robot. Both default to `false`.
6. **LiDAR started first** (`lidar_bind_lead`), because on this machine every ROS 2 process tries to
   bind UDP 7000 and the adapter must win.
7. **Thin LiDAR adapter** instead of the vendor ROS 1 node: the same `/scan` contract, ~350 lines
   against a vendored SDK that has no ROS 2 build.
8. **Body-aware obstacle stop added to the line follower.** ROS 1 had none. See §8.
9. **Cropped maze map** (`nav_maze.yaml`) as the navigation default, because the full 99 m map as a
   nav2 global costmap saturates this CPU. World coordinates are preserved, so goals are
   interchangeable; `map:=.../nav.yaml` restores the full building.
10. **`footprint_padding` 0.02 → 0.06.** The body mesh is exactly 0.32 × 0.30, so ROS 1's padding
    left 2 cm; the maze has 0.70 m median corridor clearance, so the extra margin costs nothing.
11. **Obstacle-layer parameters nested per source.** ROS 1 read them at the layer level; nav2 reads
    them per observation source. Same values, different nesting — and getting this wrong silently
    produced an empty costmap.
12. **Map saving** uses `slam_toolbox/save_map` rather than `map_saver`; `map_saver_cli` fails
    against slam_toolbox here even with a longer subscribe timeout.
13. **The mission's home pose can come from TF.** ROS 1's amcl published `/amcl_pose`
    continuously; nav2's publishes only when the filter updates, which cannot happen before the
    mission enables the follower. `/amcl_pose` remains the primary source, with `map -> base_link`
    as the equivalent fallback.
14. **The mission launch's camera topics are arguments** (`/camera/camera/...`), because ROS 1's
    `/d415/...` does not exist under `realsense2_camera` on Jazzy. Its `autostart_mission`
    argument was removed: ROS 1 started the mission only through the service, and an unattended
    auto-start that drives the robot is not something to add unasked.

## 7. caasi integration

Every ROS 1 shell command now has an entry point (see `docs/caasi-commands.md`): bringup,
bringup+teleop, bringup+rviz, SLAM, navigation, mission, line follower, obstacle guard, teleop and
rviz. Deployment and build go through `caasi deploy` / `caasi build --target`. A caasi defect that
breaks `caasi run start` on remote robot targets is documented there.

## 8. Defects found during the migration

All thirteen were found by running the system, not by reading it. Each has a regression test.

| # | defect | how it showed up |
| --- | --- | --- |
| 1 | integer YAML for a double parameter rejected | node refused to start: `control_freq: 50` |
| 2 | UDP 7000 ordering | LiDAR could not bind; no `/scan` |
| 3 | ROS 1 vendor YAML passed to a ROS 2 node | LiDAR node aborted: "no ros__parameters" |
| 4 | slam_toolbox lifecycle never activated | no `/map`, no `map → odom`, no error |
| 5 | absolute ROS 1 path in `nav.yaml` | `map_server` failed its configure transition |
| 6 | ROS 1 plugin class separators (`pkg/Class`) | planner died; whole bringup aborted |
| 7 | costmap activated before a pose exists | lifecycle manager aborted after 60 s |
| 8 | `default_server_timeout` 20 ms < planner loop | first goal aborted before planning |
| 9 | controller bypassed the velocity smoother | nav2 logged success, wheels never turned |
| 10 | DWB could not reverse | "Failed to make progress", no escape |
| 11 | 99 m map as global costmap | planner 12.7 Hz, lifecycle timeouts |
| 12 | `BaseObstacle` checks only the centre point | robot drove its corner into a box |
| 13 | ROS 1 `~` private names | mission node died at start-up; then `/start` instead of `/line_then_home/start` |
| 14 | mission launch: unforwarded argument, dead argument, ROS 1 camera topics, wrong default map | follower would never receive an image; `lidar_bind_lead` disagreed with the bringup |
| 15 | the mission was unstartable on ROS 2: nav2 amcl publishes `/amcl_pose` only on filter updates, so the pose precondition deadlocked against the mission being the thing that moves the robot | `/line_then_home/start` refused with "no /amcl_pose received yet" while `map -> base_link` was available |
| 16 | `meshes/` was never installed although the URDF references it 8 times | rviz drew a robot with no body; nothing in the build or logs complained |

Plus one safety addition (body-aware obstacle stop) and one caasi defect.

## 9. Verification matrix

| capability | ROS 1 | ROS 2 | evidence |
| --- | --- | --- | --- |
| motor protocol + telemetry | measured | **measured** | 292/293 frames, 50 Hz, faults clear |
| odometry rate | 25.2 Hz (Noetic bringup) | **50 Hz** | `ros2 topic hz` |
| odometry scale | 0.3462 m / 0.3479 m for 0.36 m | **0.3452 / 0.3462** | 0.29 % / 0.49 % apart |
| in-place rotation | 0.5096 rad at ratio 1.0191 | **0.5091 rad at 1.0182** | 0.05 % apart |
| `/scan` contract | 1440 samples, ±π, 14.03 Hz | **1440, ±π, 14.04 Hz, 0.25-25 m, increment 0.004363323** | re-measured on the deployed build, identical |
| TF `base_link → lidar_link` | 0.14114 m, 1.5° | **0.14114 m, 1.500°** | identical |
| mapping | gmapping, 2.6 cm alignment | **slam_toolbox, 2.5 cm** | equivalent quality |
| navigation | move_base + TEB | **nav2, 4 goals succeeded** | `error_code 0`, clearance > 0.6 m |
| obstacle guard | 0.2 m/s, stop 0.85 m | **same, measured** | `Stop!` at 0.847 m |
| line follower | vision + 0.12 m/s | **same, measured** | in the mission: 0.5 m travelled, steering w=-0.23..-0.11, body-aware stop at 0.27 m |
| mission supervisor | services + state machine | **round trip verified with motion** | FOLLOW 0.12 m/s steering along the tape, STOP on timeout, NAV reversing home, DONE |
| mission launch (single command) | `line_then_home.launch` | **21 nodes, mission IDLE, services answering, cropped map loaded** | run 7 |
| teleop | keyboard | **keys verified with a display** | exit 3 headless; with a display, Up gave `linear.x = 0.200`, exactly the configured `velocity_x` |
| rviz | `bringup.rviz` | **starts and renders** | OpenGL 4.5, zero mesh-loading errors, 8 meshes present |
| map saving | `map_saver` | **`save_map` service** | `result=0` |

## 10. Outstanding

1. **ROS 1 `teleop_node.py` line-by-line diff** is the one remaining audit gap: its parameters are
   compared in §4 and the ROS 2 node is verified on hardware, but the script itself was never copied
   as a reference, so a source diff needs the ROS 1 machine.
2. **TEB-specific behaviour** (its obstacle-distance weighting) is not reproduced by DWB. A task that
   depended on the exact ROS 1 trajectories needs re-tuning.
3. **Line vision is calibrated per floor.** The crop, colour range, end-of-line frame count and
   follow timeout are launch arguments defaulting to the ROS 1 values;
   `experiments/mission_demo.yaml` carries the calibration measured for this maze.

### A note on teleop's defaults

The script's own declared defaults are `velocity_x 0.4 / velocity_yaw 0.8 / max_x_acc 0.5`, while
`config/teleop.yaml` (the ROS 1 values, loaded by `bringup.launch.py` exactly as ROS 1 did) has
`0.2 / 0.4 / 0.2`. Launching normally therefore gives the ROS 1 speeds, verified at 0.200 m/s; running
the node bare gives twice that. Recorded rather than changed, because the ROS 1 script is not
available to say which value its own defaults held.

### Operational findings that are not defects in this package

* **nav2's lifecycle manager is unreliable on this robot under load** (`failed to send response to
  /map_server/change_state (timeout)` -- an RMW response timeout, not a resource shortage). A clean
  restart brings all seven nodes to `active`.
* **Order matters**: bringup/nav2 first, then a pose, then the camera, then the mission. With the
  camera at 30 Hz during bringup the configure transitions crawl.
* **The mission node owns `/cmd_vel`** and holds it at zero while IDLE, so publishing `/cmd_vel`
  yourself does nothing. That arbitration is preserved from ROS 1.
* **A silent motor board cascades**: no telemetry means the driver latches, so no `odom -> base_link`,
  so amcl cannot publish `map -> odom`, so nav2 waits. Every stage fails safe.
* **A GUI needs the session's X cookie.** `DISPLAY=:0` alone is refused ("Authorization required");
  the working combination here is `XAUTHORITY=/run/user/1000/.mutter-Xwaylandauth.*`, which is how
  rviz and teleop were verified.
