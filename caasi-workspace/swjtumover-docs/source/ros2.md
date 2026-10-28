# Inside the robot

What the software is made of, what settings exist, and how to look at it. For *doing* things — drive,
map, navigate — see [Commands](commands.md).

If ROS 2 is new to you, read [Concepts](concepts.md) first.

## The programs

| program | job | publishes | subscribes |
| --- | --- | --- | --- |
| `vanjee_scan_node` | reads the LiDAR | `/scan` (14 Hz) | — |
| `motor_node` | talks to the motor board, computes odometry | `/odom`, `/motor_state/left`, `/motor_state/right` (50 Hz), `odom → base_link` transform | `/cmd_vel` |
| `screen_node` | drives the small display | — | `/qrcode_text` |
| `robot_state_publisher`, `joint_state_publisher` | publish the robot's shape and joints | `base_link → lidar_link`, wheel joints | — |
| `slam_toolbox` | builds a map while driving | `/map`, `map → odom` | `/scan` |
| nav2 (`map_server`, `amcl`, planners, controller, …) | localises and drives to goals | `/cmd_vel/nav` | `/scan`, `/map` |
| `omove_following_feng.py` | follows the black line | `/cmd_vel/line` | camera images, `/scan` |
| `line_then_home.py` | runs the mission; the only publisher of `/cmd_vel` | `/cmd_vel`, `/line_then_home/state` | `/cmd_vel/line`, `/cmd_vel/nav`, `/amcl_pose` |

Two conventions worth remembering:

* **Only the mission publishes `/cmd_vel`.** Line following and navigation publish to
  `/cmd_vel/line` and `/cmd_vel/nav`, and the mission forwards one of them. For a standalone
  navigation test you can bypass this with `cmd_vel_topic:=/cmd_vel`.
* **Nothing drives without fresh feedback.** The motor driver zeroes the wheels if commands or motor
  telemetry stop.

## Launch files

| file | brings up |
| --- | --- |
| `bringup.launch.py` | LiDAR, both state publishers, motor driver, screen driver |
| `slam.launch.py` | bringup + `slam_toolbox` |
| `navigation.launch.py` | nav2's map server, localisation, planner, controller, behaviours |
| `line_then_home.launch.py` | bringup + nav2 + line follower + the mission (21 programs) |

Each takes arguments; the ones you are likely to change:

```bash
# rviz, the keyboard, or the camera alongside the bringup
ros2 launch swjtumover_bringup bringup.launch.py enable_visualization:=true
ros2 launch swjtumover_bringup bringup.launch.py enable_teleop:=true
ros2 launch swjtumover_bringup bringup.launch.py enable_realsense:=true

# which map navigation serves, and where its commands go
ros2 launch swjtumover_bringup navigation.launch.py map:=/path/to/nav.yaml cmd_vel_topic:=/cmd_vel

# seed localisation instead of publishing a pose by hand
ros2 launch swjtumover_bringup navigation.launch.py \
  set_initial_pose:=true initial_pose_x:=1.2 initial_pose_y:=-0.4 initial_pose_yaw:=0.0

# the mission, with a slower line phase
ros2 launch swjtumover_bringup line_then_home.launch.py follow_timeout:=60.0
```

The mission launch also exposes the line follower's image crop and colour range
(`follower_roi_top_offset`, `follower_roi_bottom_offset`, `follower_line_lower`,
`follower_line_upper`, `follower_end_confirm_frames`) because those depend on the floor and the tape.
`experiments/mission_demo.yaml` carries values measured for this building.

## Settings

Robot settings live in the package's `config/` directory and are loaded by the launch files:

| file | holds |
| --- | --- |
| `config/motor.yaml` | wheel radii, wheelbase, acceleration, timeouts, board address |
| `config/screen.yaml` | display address and refresh rate |
| `config/teleop.yaml` | teleoperation speeds and acceleration |
| `config/line_then_home.yaml` | mission timings, whether waypoints are required |
| `param/nav2_params.yaml` | nav2: localisation, planner, controller, both costmaps |
| `param/slam_toolbox_params.yaml` | mapping |

Read one without opening the file:

```bash
ros2 param get /motor_node motor.wheel_radius
ros2 param dump /motor_node            # every setting the driver is using
```

## Interface reference

Topics:

| topic | type | direction |
| --- | --- | --- |
| `/scan` | `sensor_msgs/LaserScan` | LiDAR → everyone |
| `/odom` | `nav_msgs/Odometry` | motor driver → everyone |
| `/motor_state/left`, `/motor_state/right` | `swjtumover_msgs/MotorState` | motor driver → everyone |
| `/cmd_vel` | `geometry_msgs/Twist` | mission → motor driver |
| `/cmd_vel/line`, `/cmd_vel/nav` | `geometry_msgs/Twist` | behaviours → mission |
| `/map` | `nav_msgs/OccupancyGrid` | mapping → everyone |
| `/line_then_home/state` | `std_msgs/String` | mission → everyone |
| `/qrcode_text` | `std_msgs/String` | anyone → screen |
| `/reached_goal`, `/line_follow/end`, `/line_follow/enable` | `std_msgs/Bool` | line follower ↔ everyone |

Services on the mission: `/line_then_home/start`, `/line_then_home/stop`,
`/line_then_home/record_waypoints` — all `std_srvs/srv/Trigger`.

Actions: `/navigate_to_pose` (`nav2_msgs/action/NavigateToPose`), used by the mission and by any
other navigation client.

Transforms: `map → odom` (localisation or mapping), `odom → base_link` (motor driver),
`base_link → lidar_link` (static, from the robot description).

## Looking inside

```bash
ros2 node list                     # what is running
ros2 node info /motor_node         # one program's topics and services
ros2 topic list
ros2 topic hz /scan
ros2 topic echo /motor_state/left --once
ros2 lifecycle get /amcl           # navigation and mapping nodes are lifecycle-managed
ros2 param dump /controller_server # the settings a node actually uses
ros2 bag record -o run1 /scan /odom /tf /motor_state/left
```

With a remote desktop session you can watch all of it in rviz; see [Remote access](fleet-and-display.md).
