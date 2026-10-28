# swjtumover (ROS 2)

ROS 2 Jazzy migration of the robot's original ROS 1 workspace (`~/swjtumover/swjtumover_ws`).
Built and managed through caasi like any other project.

```
caasi.yaml                 project manifest (requires: ros2 jazzy; pynput optional)
plan/migration-plan.md     difference audit, what is ported, what is not, and why
src/swjtumover_msgs        MotorState message (nine fields, same as ROS 1)
src/swjtumover_bringup     motor_node, screen_node, teleop_node.py, line follower,
                           obstacle guard, mission node, 4 launch files, config, param, urdf
src/swjtumover_vanjee      thin LaserScan adapter over the vendored Vanjee driver
external/vanjee_driver     unmodified vendor source (ROS-independent), used header-only
```

## Build and test

```bash
cd caasi-workspace/swjtumover
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install
colcon test --packages-select swjtumover_bringup
```

31 tests, 0 failures. They are migration tests, not feature tests: topic names, protocol
constants, the line follower's vision constants, odometry maths, message field order, parameter
values against the ROS 1 YAML, nav2/AMCL values converted from the ROS 1 costmaps and TEB
config, and the launch selection including the `/cmd_vel` arbitration.

## Run

```bash
# hardware only
ros2 launch swjtumover_bringup bringup.launch.py

# mapping (slam_toolbox, replaces gmapping)
ros2 launch swjtumover_bringup slam.launch.py

# localisation + navigation (map_server + amcl + move_base replacement)
ros2 launch swjtumover_bringup navigation.launch.py map:=/path/to/nav.yaml

# the mission: follow the line, then navigate home through the recorded waypoints
ros2 launch swjtumover_bringup line_then_home.launch.py
ros2 service call /line_then_home/record_waypoints std_srvs/srv/Trigger
ros2 service call /line_then_home/start std_srvs/srv/Trigger
ros2 service call /line_then_home/stop std_srvs/srv/Trigger

# standalone behaviours
ros2 run swjtumover_bringup omove_following_feng.py --ros-args -p gui:=true
ros2 run swjtumover_bringup obstacle_rplidar.py
```

The LiDAR starts first and the rest follows after `lidar_bind_lead` seconds (default 3), because
every ROS 2 process binds UDP 7000 here and the driver must own it first.

## ROS 1 sources kept for comparison

`src/swjtumover_bringup/src/ros1_reference/` holds the ROS 1 `motor_node.cpp`,
`screen_node.cpp`, `motor_node_original_ros1.cpp` and the CRC helper exactly as they are on the
robot. The parity tests read them, so any future change to the ROS 2 side that silently breaks
the interface will fail a test rather than a field trial.

## Saving a map

ROS 1 saved maps with `rosrun map_server map_saver -f <prefix>`. On ROS 2 the equivalent for this
stack is slam_toolbox's own service, which needs the target directory to exist:

```bash
mkdir -p ~/maps
ros2 service call /slam_toolbox/save_map slam_toolbox/srv/SaveMap \
  "{name: {data: '/home/swjtumover/maps/map'}}"
```

`ros2 run nav2_map_server map_saver_cli -f <prefix>` does **not** work against slam_toolbox here
(`Failed to spin map subscription`) even though `/map` is RELIABLE + TRANSIENT_LOCAL, and it does
not improve with a longer `map_subscribe_timeout`. Verified on the robot; use the service.

`slam_toolbox` is a lifecycle node, so `slam.launch.py` runs a `nav2_lifecycle_manager` to
configure and activate it. Without that it starts unconfigured -- no `/scan` subscription and no
`/map` -- while the launch still looks healthy.

## Running through caasi

Every ROS 1 shell command has a caasi entry point in `experiments/`, so bringup, SLAM, navigation,
the mission, the line follower, the obstacle guard, teleop and rviz are all deployable, runnable
and monitorable rather than untracked terminals. See `docs/caasi-commands.md` for the table of
commands and for the current limitation of `caasi run start` on remote robot targets.

## Audit

`docs/ros1-vs-ros2-audit.md` compares the ROS 1 package with this project: file inventory, interface audit per node, parameter parity, the nav2 mapping, every deliberate difference, the thirteen defects found during the migration, the verification matrix and what is still outstanding.
