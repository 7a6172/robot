# Commands and workflows: ROS 1 vs ROS 2

Every command the ROS 1 robot was operated with, next to what to run now, plus what to look at to
know it worked. Use it to run the same experiment on both systems and compare.

Three columns of "how":

* **ROS 1** — the original command on the Noetic machine.
* **ROS 2** — the same thing directly on Jazzy.
* **caasi** — the same thing as a tracked, monitorable run from the workstation.

## 1. Bringup

| | command |
| --- | --- |
| ROS 1 | `roslaunch swjtumover_bringup bringup.launch` |
| ROS 2 | `ros2 launch swjtumover_bringup bringup.launch.py` |
| caasi | `caasi run start experiments/bringup.yaml -t swjtumover05` |

**Check:** `ros2 topic hz /scan` ≈ 14 Hz · `ros2 topic hz /odom` ≈ 50 Hz ·
`ros2 topic echo /motor_state/left --once` → all five fault flags `false` · `base_link → lidar_link`
is `z = 0.14114 m`, `roll = 1.500°`.

**Difference to expect:** the LiDAR must start first (UDP 7000). `bringup.launch.py` does that
itself; if you start nodes by hand, start the LiDAR adapter before anything else.

## 2. Teleoperation

| | command |
| --- | --- |
| ROS 1 | `rosrun swjtumover_bringup teleop_node.py` |
| ROS 2 | `~/caasi/robots/swjtumover05/scripts/run_teleop.sh` |
| caasi | `caasi run start experiments/teleop.yaml -t swjtumover05` (needs `DISPLAY`) |

Arrow keys: up/down drive, left/right turn. Speeds from `config/teleop.yaml`: **0.2 m/s**,
**0.4 rad/s**, accelerating at 0.2 / 0.4 per second.

**Check:** `ros2 topic echo /cmd_vel` shows `linear.x` reaching ±0.2 while a key is held, and 0 when
released. With the robot on a box `/odom` still moves — odometry comes from the wheel encoders.

**Difference to expect:** the session is Wayland, so **click the rviz window first** — `pynput` reads
X11 events and needs an Xwayland window focused. Running the node without a display exits with
code 3 and says so.

## 3. rviz

| | command |
| --- | --- |
| ROS 1 | `rosrun rviz rviz -d $(rospack find swjtumover_bringup)/config/bringup.rviz` |
| ROS 2 | `rviz2 -d $(ros2 pkg prefix swjtumover_bringup)/share/swjtumover_bringup/config/bringup.rviz` |
| caasi | see `experiments/rviz.yaml` for the exact environment |

**Check:** the robot body appears, `/scan` draws as red points, the camera image draws, the
`/map` panel fills once something publishes a map.

**Differences to expect** (all deliberate, all in `config/bringup.rviz`):

* ROS 2 display classes are `rviz_default_plugins/...`; the ROS 1 file (`bringup_ros1.rviz`) loads
  **no** displays at all under rviz 2.
* fixed frame is `odom`, because `map` only exists once `amcl` or `slam_toolbox` runs.
* `/robot_description` is a **latched topic** here, so the display asks for Transient Local; ROS 1
  read it from the parameter server.
* camera topic is `/camera/camera/color/image_raw`, not `/d415/...`.
* the two costmap panels are **off** by default; they need nav2.
* the occupancy-grid shader fails to link on this GL stack (upstream rviz issue), so the map panel
  may stay empty even with `/map` publishing.

## 4. Mapping

| | command |
| --- | --- |
| ROS 1 | `roslaunch swjtumover_bringup bringup_gmapping.launch` |
| ROS 2 | `ros2 launch swjtumover_bringup slam.launch.py` |
| caasi | `caasi run start experiments/slam.yaml -t swjtumover05` |

**Check:** `ros2 lifecycle get /slam_toolbox` → `active` · `ros2 topic hz /map` ≈ 0.33 Hz ·
`map → odom` exists · drive the robot and the map grows.

**Difference to expect:** `slam_toolbox` is a **lifecycle** node; the launch activates it. gmapping
had none. Map texture and loop closure differ — compare scan-to-map alignment (2.5 cm on both here),
not pixel counts.

### Saving a map

| | command |
| --- | --- |
| ROS 1 | `rosrun map_server map_saver -f ~/maps/map` |
| ROS 2 | `ros2 service call /slam_toolbox/save_map slam_toolbox/srv/SaveMap "{name: {data: '/home/swjtumover/maps/map'}}"` |

The directory must exist first. `map_saver_cli` does **not** work against slam_toolbox here.

## 5. Navigation

| | command |
| --- | --- |
| ROS 1 | `roslaunch swjtumover_bringup map_server.launch` + `amcl.launch` + `move_base.launch` |
| ROS 2 | `ros2 launch swjtumover_bringup navigation.launch.py` |
| caasi | `caasi run start experiments/navigation.yaml -t swjtumover05` |

**Check:** all seven lifecycle nodes `active` (`map_server`, `amcl`, `planner_server`,
`controller_server`, `behavior_server`, `bt_navigator`, `velocity_smoother`) · send a goal and the
robot drives there.

**Differences to expect:**

* nav2 **waits for a pose**. Publish `/initialpose` (the "2D Pose Estimate" equivalent) or pass
  `set_initial_pose:=true initial_pose_x:=… initial_pose_y:=…`.
* nav2 publishes **`/cmd_vel/nav`**, not `/cmd_vel` — the mission node is the only publisher of
  `/cmd_vel`. For a standalone navigation test add `cmd_vel_topic:=/cmd_vel`.
* the default map is the **cropped maze map** (`nav_maze.yaml`); `map:=…/nav.yaml` restores the
  whole building, which is much slower as a nav2 costmap.
* bring nav2 up **before** the camera: at 30 Hz during bringup the lifecycle manager stalls on DDS
  timeouts.

## 6. Line-then-home mission

| | command |
| --- | --- |
| ROS 1 | `roslaunch swjtumover_bringup line_then_home.launch` |
| ROS 2 | `ros2 launch swjtumover_bringup line_then_home.launch.py` |
| caasi | `caasi run start experiments/mission.yaml -t swjtumover05` |

Services, identical names to ROS 1:

| | command |
| --- | --- |
| ROS 1 | `rosservice call /line_then_home/start "{}"` |
| ROS 2 | `ros2 service call /line_then_home/start std_srvs/srv/Trigger "{}"` |
| caasi | `caasi run start experiments/mission_start.yaml -t swjtumover05` |

Same for `stop` and `record_waypoints`. State: `ros2 topic echo /line_then_home/state` →
`IDLE`, `FOLLOW`, `STOP`, `NAV`, `DONE`, `FAILED`.

**Check:** `start` returns `success=True, 'task started: following the line'`; the state moves
through `FOLLOW → STOP → NAV → DONE`; the robot ends at the pose it started from.

**Differences to expect:**

* `~start` needs a home pose. ROS 1's amcl published `/amcl_pose` continuously; nav2's publishes
  only once the robot has moved, so the mission also accepts the `map → base_link` transform.
* on this floor the tape widens into the near field, which makes the end-of-line test fire at once.
  `experiments/mission_demo.yaml` uses the calibration measured here:
  `follower_roi_bottom_offset:=70`, `follower_end_confirm_frames:=100000`, `follow_timeout:=40.0`.
* publishing `/cmd_vel` yourself while the mission runs does nothing — it owns that topic.

## 7. Line follower alone

| | command |
| --- | --- |
| ROS 1 | `python3 omove_following.py` |
| ROS 2 | `ros2 run swjtumover_bringup omove_following_feng.py --ros-args -p color_topic:=/camera/camera/color/image_raw -p depth_topic:=/camera/camera/depth/image_rect_raw` |
| caasi | `caasi run start experiments/line_follower.yaml -t swjtumover05` |

**Check:** with the line in view it publishes `linear.x = 0.12` and a steering term
`-yaw * 0.6`; with no line it publishes zero.

**Differences to expect:** ROS 1 signalled completion by setting the **global parameter**
`/reached_goal`; ROS 2 publishes the **topic** `/reached_goal`. Clearing it: publish `true` on
`/line_follow/enable`. A body-aware obstacle stop was **added**: it holds zero when the centre
clearance drops below 0.28 m (0.16 m body + 0.12 m margin). Vision constants are parameters now,
with the ROS 1 values as defaults.

## 8. Obstacle guard alone

| | command |
| --- | --- |
| ROS 1 | `python3 obstacle_rplidar.py` |
| ROS 2 | `ros2 run swjtumover_bringup obstacle_rplidar.py` |
| caasi | `caasi run start experiments/obstacle_guard.yaml -t swjtumover05` |

**Check:** it drives forward at 0.2 m/s, logs `Go!` while clear, and stops when the ±10° front
sector is closer than 0.85 m.

## 9. Camera

| | command |
| --- | --- |
| ROS 1 | `roslaunch realsense2_camera rs_camera.launch` (published `/d415/...`) |
| ROS 2 | `ros2 launch realsense2_camera rs_launch.py` (publishes `/camera/camera/...`) |
| caasi | `caasi run start experiments/camera.yaml -t swjtumover05` |

Start it **after** nav2 has reached `active`, and before starting the mission.

## 10. Inspection

| task | ROS 1 | ROS 2 |
| --- | --- | --- |
| topic rate | `rostopic hz /scan` | `ros2 topic hz /scan` |
| one message | `rostopic echo -n1 /odom` | `ros2 topic echo /odom --once` |
| node list | `rosnode list` | `ros2 node list` |
| service call | `rosservice call /x "{}"` | `ros2 service call /x std_srvs/srv/Trigger "{}"` |
| record | `rosbag record -O out.bag /scan /odom` | `ros2 bag record -o out /scan /odom` |
| TF lookup | `rosrun tf tf_echo base_link lidar_link` | `ros2 run tf2_ros tf2_echo base_link lidar_link` |
| lifecycle | — (no lifecycle in ROS 1) | `ros2 lifecycle get /amcl` |

## 11. Not ported

Exam and scratch material, by decision: `exam_*.py`, `exam_project.launch`, `assessment_run.py`,
`ok.py`, `test.py`, and the superseded `omove_following.py` / `omove_following_1.py`. They remain in
`**/ros1_reference/` for comparison.

## 12. A verification run you can repeat on both systems

1. **Bringup** — `/scan` 14 Hz, `/odom` 50 Hz, fault flags false, TF values as above.
2. **Teleop** — arrow up reaches `linear.x = 0.2`; on the ground it moves 0.06 m/s-equivalent
   distances; wheel odometry changes.
3. **rviz** — body, laser and camera all draw.
4. **Mapping** — drive for a minute, save the map, measure the scan-to-map alignment.
5. **Navigation** — set a pose, send a goal, confirm the robot arrives.
6. **Mission** — `start`, watch `FOLLOW → STOP → NAV → DONE`.
7. **Obstacle guard** — block the front and confirm it stops inside 0.85 m.

The numbers to compare are in `docs/ros1-vs-ros2-audit.md` §9.
