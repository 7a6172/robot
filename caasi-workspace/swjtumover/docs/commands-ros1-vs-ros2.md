# Commands and workflows

Every command needed to operate the robot, in three forms:

* **ROS 1** — the original software on the Noetic machine, for reference and comparison.
* **ROS 2** — the same task directly on the robot.
* **caasi** — the same task as a tracked run, driven from your machine.

Use whichever suits the moment. caasi adds records and remote operation; the ROS 2 commands are
equivalent and always available.

`<target>` is the execution target name you enrolled in caasi. `<install>` is the package share
directory, `$(ros2 pkg prefix swjtumover_bringup)/share/swjtumover_bringup`.

## Bringup

| | command |
| --- | --- |
| ROS 1 | `roslaunch swjtumover_bringup bringup.launch` |
| ROS 2 | `ros2 launch swjtumover_bringup bringup.launch.py` |
| caasi | `caasi run start experiments/bringup.yaml -t <target>` |

Checks: `/scan` about 14 Hz, `/odom` about 50 Hz, all five fault flags false at rest,
`base_link → lidar_link` at z = 0.14114 m with 1.5° of roll.

Notes: the LiDAR must own UDP 7000 before other nodes start; `bringup.launch.py` handles the order.

## Teleoperation

| | command |
| --- | --- |
| ROS 1 | `rosrun swjtumover_bringup teleop_node.py` |
| ROS 2 | `scripts/run_teleop.sh` |
| caasi | `caasi run start experiments/teleop.yaml -t <target>` |

Arrow keys drive and turn. Speeds come from `config/teleop.yaml`: 0.2 m/s, 0.4 rad/s, accelerating at
0.2 / 0.4 per second.

Checks: `/cmd_vel` shows `linear.x` reaching ±0.2 while a key is held and zero when released.

Note: on a Wayland desktop the keyboard is only received while an X11 window has focus — click the
rviz window first. Without any display the node exits with code 3 and says so.

## Visualization

| | command |
| --- | --- |
| ROS 1 | `rosrun rviz rviz -d $(rospack find swjtumover_bringup)/config/bringup.rviz` |
| ROS 2 | `rviz2 -d <install>/config/bringup.rviz` |
| caasi | `caasi run start experiments/rviz.yaml -t <target>` |

Checks: the robot body, `/scan` and the camera image draw with only the bringup running. The `/map`
panel fills once something publishes a map; the two costmap panels need nav2 and are off by default.

Note: rviz 2 names its displays differently from rviz 1, so the ROS 1 configuration is kept beside
the current one as `config/bringup_ros1.rviz` for comparison.

## Mapping

| | command |
| --- | --- |
| ROS 1 | `roslaunch swjtumover_bringup bringup_gmapping.launch` |
| ROS 2 | `ros2 launch swjtumover_bringup slam.launch.py` |
| caasi | `caasi run start experiments/slam.yaml -t <target>` |

Checks: `/slam_toolbox` reports `active`, `/map` publishes at roughly 0.3 Hz, `map → odom` exists,
and the map grows as the robot moves.

Saving a map:

| | command |
| --- | --- |
| ROS 1 | `rosrun map_server map_saver -f ~/maps/map` |
| ROS 2 | `ros2 service call /slam_toolbox/save_map slam_toolbox/srv/SaveMap "{name: {data: '/home/swjtumover/maps/map'}}"` |

The target directory must exist. `nav2_map_server`'s `map_saver_cli` does not work against
slam_toolbox.

## Navigation

| | command |
| --- | --- |
| ROS 1 | `roslaunch swjtumover_bringup map_server.launch`, `amcl.launch`, `move_base.launch` |
| ROS 2 | `ros2 launch swjtumover_bringup navigation.launch.py` |
| caasi | `caasi run start experiments/navigation.yaml -t <target>` |

Checks: all seven nodes `active` (`map_server`, `amcl`, `planner_server`, `controller_server`,
`behavior_server`, `bt_navigator`, `velocity_smoother`), and a goal is reached.

Notes:

* publish `/initialpose` first — nav2 waits for a pose before activating its costmaps.
* navigation publishes `/cmd_vel/nav`; the mission node owns `/cmd_vel`. For a standalone test add
  `cmd_vel_topic:=/cmd_vel`.
* the default map is the maze region (`nav_maze.yaml`); `map:=<path>/nav.yaml` serves the whole site.

## Line-then-home mission

| | command |
| --- | --- |
| ROS 1 | `roslaunch swjtumover_bringup line_then_home.launch` |
| ROS 2 | `ros2 launch swjtumover_bringup line_then_home.launch.py` |
| caasi | `caasi run start experiments/mission.yaml -t <target>` |

Services keep their ROS 1 names:

| action | ROS 1 | ROS 2 | caasi |
| --- | --- | --- | --- |
| start | `rosservice call /line_then_home/start "{}"` | `ros2 service call /line_then_home/start std_srvs/srv/Trigger "{}"` | `experiments/mission_start.yaml` |
| stop | `…/stop` | `…/stop` | `experiments/mission_stop.yaml` |
| record waypoints | `…/record_waypoints` | `…/record_waypoints` | `experiments/mission_record_waypoints.yaml` |

State: `ros2 topic echo /line_then_home/state` — `IDLE`, `FOLLOW`, `STOP`, `NAV`, `DONE`, `FAILED`.

Checks: `start` answers `success=True`; the state moves `FOLLOW → STOP → NAV → DONE`; the robot ends
at the pose it started from.

Notes:

* the mission needs a home pose. It uses `/amcl_pose` when available and otherwise the
  `map → base_link` transform, so a pose must be set first.
* the follower's crop and colour range are launch arguments; `experiments/mission_demo.yaml` carries
  the values measured for the site's floor.
* publishing `/cmd_vel` while the mission runs has no effect — it is the only publisher there.

## Line follower alone

| | command |
| --- | --- |
| ROS 1 | `python3 omove_following.py` |
| ROS 2 | `ros2 run swjtumover_bringup omove_following_feng.py --ros-args -p color_topic:=/camera/camera/color/image_raw -p depth_topic:=/camera/camera/depth/image_rect_raw` |
| caasi | `caasi run start experiments/line_follower.yaml -t <target>` |

Checks: with the line in view it publishes `linear.x = 0.12` with a steering term; with no line it
publishes zero. It also stops when the centre clearance falls below 0.28 m.

Notes: completion was a ROS 1 global parameter and is now the topic `/reached_goal`;
`/line_follow/enable` clears it. Crop and colour range are parameters, defaulting to the ROS 1
values.

## Obstacle guard alone

| | command |
| --- | --- |
| ROS 1 | `python3 obstacle_rplidar.py` |
| ROS 2 | `ros2 run swjtumover_bringup obstacle_rplidar.py` |
| caasi | `caasi run start experiments/obstacle_guard.yaml -t <target>` |

Checks: it drives forward at 0.2 m/s and stops when the ±10° front sector is closer than 0.85 m.

## Camera

| | command |
| --- | --- |
| ROS 1 | `roslaunch realsense2_camera rs_camera.launch` (published `/d415/...`) |
| ROS 2 | `ros2 launch realsense2_camera rs_launch.py` (publishes `/camera/camera/...`) |
| caasi | `caasi run start experiments/camera.yaml -t <target>` |

Start it after nav2 is `active` and before starting the mission.

## Inspection

| task | ROS 1 | ROS 2 |
| --- | --- | --- |
| topic rate | `rostopic hz /scan` | `ros2 topic hz /scan` |
| one message | `rostopic echo -n1 /odom` | `ros2 topic echo /odom --once` |
| node list | `rosnode list` | `ros2 node list` |
| service call | `rosservice call /x "{}"` | `ros2 service call /x std_srvs/srv/Trigger "{}"` |
| record | `rosbag record -O out.bag /scan /odom` | `ros2 bag record -o out /scan /odom` |
| transform | `rosrun tf tf_echo base_link lidar_link` | `ros2 run tf2_ros tf2_echo base_link lidar_link` |
| lifecycle state | — | `ros2 lifecycle get /amcl` |

## Not included

The ROS 1 exam and scratch scripts (`exam_*.py`, `exam_project.launch`, `assessment_run.py`, `ok.py`,
`test.py`) and the superseded `omove_following.py` variants are not part of this package.

## A run to repeat on both systems

1. **Bringup** — `/scan` 14 Hz, `/odom` 50 Hz, fault flags false, transform values as above.
2. **Teleoperation** — arrow up reaches `linear.x = 0.2`; odometry responds.
3. **Visualization** — body, laser and camera all draw.
4. **Mapping** — drive for a minute, save the map, inspect the result.
5. **Navigation** — set a pose, send a goal, confirm the robot arrives.
6. **Mission** — `start`, watch `FOLLOW → STOP → NAV → DONE`.
7. **Obstacle guard** — block the front and confirm it stops inside 0.85 m.
