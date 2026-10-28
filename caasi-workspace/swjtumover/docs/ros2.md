# Running with ROS 2

## Build

```bash
cd <project>
colcon build --symlink-install
source install/setup.bash
```

Three packages build: `swjtumover_msgs`, `swjtumover_vanjee`, `swjtumover_bringup`.

Run the tests:

```bash
colcon test --packages-select swjtumover_bringup
colcon test-result --result-base build/swjtumover_bringup
```

## Start the hardware

```bash
ros2 launch swjtumover_bringup bringup.launch.py
```

This starts the LiDAR adapter first, then `robot_state_publisher`, `joint_state_publisher`,
`motor_node` and `screen_node`. Check it:

```bash
ros2 topic hz /scan       # ~14 Hz
ros2 topic hz /odom       # ~50 Hz
ros2 topic echo /motor_state/left --once
```

Optional components are launch arguments, all off by default because the robot is headless:

```bash
ros2 launch swjtumover_bringup bringup.launch.py enable_visualization:=true   # needs DISPLAY
ros2 launch swjtumover_bringup bringup.launch.py enable_teleop:=true          # needs DISPLAY
ros2 launch swjtumover_bringup bringup.launch.py enable_realsense:=true
```

## Mapping

```bash
ros2 launch swjtumover_bringup slam.launch.py
```

Saving the map — slam_toolbox's own service, and the directory must exist:

```bash
mkdir -p ~/maps
ros2 service call /slam_toolbox/save_map slam_toolbox/srv/SaveMap \
  "{name: {data: '/home/swjtumover/maps/map'}}"
```

`ros2 run nav2_map_server map_saver_cli` does **not** work against slam_toolbox here.

## Navigation

```bash
ros2 launch swjtumover_bringup navigation.launch.py
```

nav2 comes up **waiting for a pose**. Give it one the same way you would click "2D Pose Estimate"
in rviz:

```bash
ros2 topic pub --once /initialpose geometry_msgs/msg/PoseWithCovarianceStamped \
  "{header: {frame_id: map}, pose: {pose: {position: {x: 2.85, y: -2.77, z: 0.0}, orientation: {w: 1.0}}}}"
```

Then all seven nav2 nodes activate. Send a goal with rviz, or:

```bash
ros2 action send_goal /navigate_to_pose nav2_msgs/action/NavigateToPose \
  "{pose: {header: {frame_id: map}, pose: {position: {x: 2.0, y: -2.0, z: 0.0}, orientation: {w: 1.0}}}}"
```

Two things to know:

* By default nav2 publishes `/cmd_vel/nav`, **not** `/cmd_vel` — the mission node owns `/cmd_vel`
  and arbitrates. For a standalone navigation test add `cmd_vel_topic:=/cmd_vel`.
* Navigation uses `map/nav_maze.yaml` (the maze region of the ROS 1 map, world coordinates
  preserved). Use `map:=<...>/nav.yaml` for the full building; the global costmap then covers 99 m
  and the planner slows down considerably on this CPU.

## The line-then-home mission

```bash
ros2 launch swjtumover_bringup line_then_home.launch.py
ros2 service call /line_then_home/start std_srvs/srv/Trigger "{}"
ros2 service call /line_then_home/stop std_srvs/srv/Trigger "{}"
ros2 service call /line_then_home/record_waypoints std_srvs/srv/Trigger "{}"
ros2 topic echo /line_then_home/state        # IDLE, FOLLOW, STOP, NAV, DONE, FAILED
```

The mission refuses to start until it has seen `/amcl_pose`, because it needs the home pose.

## Single behaviours

```bash
ros2 run swjtumover_bringup obstacle_rplidar.py     # drive forward, stop inside 0.85 m
ros2 run swjtumover_bringup omove_following_feng.py # follow the black line
ros2 run swjtumover_bringup teleop_node.py          # keyboard, needs DISPLAY
```

The line follower needs colour and depth images; on Jazzy the RealSense publishes them under
`/camera/camera/...`, so pass the topics:

```bash
ros2 run swjtumover_bringup omove_following_feng.py --ros-args \
  -p color_topic:=/camera/camera/color/image_raw \
  -p depth_topic:=/camera/camera/depth/image_rect_raw
```

It stops itself when the line is lost, when its front sector is closer than 0.28 m, and when it
decides the line has ended (that latch is cleared by publishing `true` on `/line_follow/enable`).

## Topics at a glance

| topic | direction | rate |
| --- | --- | --- |
| `/scan` | from the LiDAR | 14 Hz |
| `/odom`, `/motor_state/left`, `/motor_state/right` | from `motor_node` | 50 Hz |
| `/cmd_vel` | to `motor_node` — the only actuation path | — |
| `/cmd_vel/line`, `/cmd_vel/nav` | arbitration inputs to the mission | — |
| `/line_then_home/state` | mission state | on change |
| `/qrcode_text` | to `screen_node` | on change |
