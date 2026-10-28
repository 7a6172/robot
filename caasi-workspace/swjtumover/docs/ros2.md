# Running on the robot

Everything here runs on the robot itself, with ROS 2 Jazzy.

## Build

```bash
colcon build --symlink-install
source install/setup.bash
```

Run the tests:

```bash
colcon test --packages-select swjtumover_bringup
colcon test-result --result-base build/swjtumover_bringup
```

## Hardware bringup

```bash
ros2 launch swjtumover_bringup bringup.launch.py
```

Starts the LiDAR adapter first, then `robot_state_publisher`, `joint_state_publisher`, `motor_node`
and `screen_node`.

```bash
ros2 topic hz /scan                       # ~14 Hz
ros2 topic hz /odom                       # ~50 Hz
ros2 topic echo /motor_state/left --once   # fault flags false at rest
```

Optional parts are launch arguments, all off by default because the robot is normally headless:

```bash
ros2 launch swjtumover_bringup bringup.launch.py enable_visualization:=true   # rviz
ros2 launch swjtumover_bringup bringup.launch.py enable_teleop:=true          # keyboard
ros2 launch swjtumover_bringup bringup.launch.py enable_realsense:=true       # camera
```

## Teleoperation

```bash
scripts/run_teleop.sh
```

Arrow keys drive and turn: 0.2 m/s and 0.4 rad/s, accelerating at 0.2 / 0.4 per second. The script
resolves the display and X cookie itself and loads `config/teleop.yaml`.

If the keys do nothing, give an X11 window focus first — on a Wayland desktop `pynput` only receives
keys while an Xwayland window is focused.

## Mapping

```bash
ros2 launch swjtumover_bringup slam.launch.py
```

Check it with `ros2 lifecycle get /slam_toolbox` (expect `active`) and `ros2 topic hz /map` (about
0.3 Hz once the robot moves).

Save the map with slam_toolbox's service; the directory must already exist:

```bash
mkdir -p ~/maps
ros2 service call /slam_toolbox/save_map slam_toolbox/srv/SaveMap \
  "{name: {data: '/home/swjtumover/maps/map'}}"
```

`nav2_map_server`'s `map_saver_cli` does not work against slam_toolbox; use the service above.

## Navigation

```bash
ros2 launch swjtumover_bringup navigation.launch.py
```

nav2 comes up waiting for a pose. Give it one, the equivalent of rviz's "2D Pose Estimate":

```bash
ros2 topic pub --once /initialpose geometry_msgs/msg/PoseWithCovarianceStamped \
  "{header: {frame_id: map}, pose: {pose: {position: {x: 2.85, y: -2.77, z: 0.0}, orientation: {w: 1.0}}}}"
```

All seven nav2 nodes then become `active`: `map_server`, `amcl`, `planner_server`,
`controller_server`, `behavior_server`, `bt_navigator`, `velocity_smoother`.

Send a goal with rviz, or:

```bash
ros2 action send_goal /navigate_to_pose nav2_msgs/action/NavigateToPose \
  "{pose: {header: {frame_id: map}, pose: {position: {x: 2.0, y: -2.0, z: 0.0}, orientation: {w: 1.0}}}}"
```

Two things to know:

* nav2 publishes **`/cmd_vel/nav`**, not `/cmd_vel`. The mission node owns `/cmd_vel` and arbitrates
  between the line follower and navigation. For a standalone navigation test, add
  `cmd_vel_topic:=/cmd_vel`.
* the default map is `map/nav_maze.yaml`, the maze region of the site map with world coordinates
  preserved. `map:=<path>/nav.yaml` uses the whole building, which is slower as a nav2 costmap.

Useful launch arguments: `set_initial_pose:=true initial_pose_x:=… initial_pose_y:=…
initial_pose_yaw:=…`.

## The line-then-home mission

```bash
ros2 launch swjtumover_bringup line_then_home.launch.py

ros2 service call /line_then_home/start std_srvs/srv/Trigger "{}"
ros2 service call /line_then_home/stop std_srvs/srv/Trigger "{}"
ros2 service call /line_then_home/record_waypoints std_srvs/srv/Trigger "{}"
ros2 topic echo /line_then_home/state        # IDLE, FOLLOW, STOP, NAV, DONE, FAILED
```

That one launch brings up the hardware bringup, all of nav2, the line follower and the mission
together — 21 nodes.

| argument | default | purpose |
| --- | --- | --- |
| `map` | `map/nav_maze.yaml` | map to serve |
| `color_topic`, `depth_topic` | `/camera/camera/...` | images for the line follower |
| `start_hardware` | `true` | set `false` if the bringup already runs |
| `lidar_bind_lead` | `3.0` | passed to the bringup so the LiDAR wins UDP 7000 |
| `follower_roi_top_offset`, `follower_roi_bottom_offset` | `100`, `0` | the follower's image crop |
| `follower_line_lower`, `follower_line_upper` | `[10,20,10]`, `[40,50,40]` | its colour range |
| `follower_end_confirm_frames` | `5` | frames before the end of the line counts |
| `follow_timeout` | `300.0` | seconds of following before moving on |

The follower starts disabled and is enabled by `/line_then_home/start`, so the mission remains the
only publisher of `/cmd_vel`. Start the robot on the line with a valid pose; the mission records
where it started and returns there.

## Individual behaviours

```bash
ros2 run swjtumover_bringup obstacle_rplidar.py      # forward, stop inside 0.85 m
ros2 run swjtumover_bringup omove_following_feng.py  # follow the black line
ros2 run swjtumover_bringup teleop_node.py           # keyboard
```

The line follower needs colour and depth images; with `realsense2_camera`:

```bash
ros2 run swjtumover_bringup omove_following_feng.py --ros-args \
  -p color_topic:=/camera/camera/color/image_raw \
  -p depth_topic:=/camera/camera/depth/image_rect_raw
```

It drives at 0.12 m/s and steers in proportion to the line's offset. It stops when the line is lost,
when the front sector closes to 0.28 m, and when it decides the line has ended — publishing `true`
on `/line_follow/enable` clears that.

## Visualization

```bash
rviz2 -d "$(ros2 pkg prefix swjtumover_bringup)/share/swjtumover_bringup/config/bringup.rviz"
```

The robot model, `/scan` and the camera image draw as soon as the bringup is running. The map panel
fills once something publishes `/map`. The two costmap panels are off by default because they need
nav2.

## Camera

```bash
ros2 launch realsense2_camera rs_launch.py
```

It publishes under `/camera/camera/...`. Start it after nav2 has reached `active`.
