# swjtumover (ROS 2)

ROS 2 Jazzy migration of the robot's original ROS 1 workspace (`~/swjtumover/swjtumover_ws`).
Built and managed through caasi like any other project.

```
caasi.yaml                 project manifest (requires: ros2 jazzy; pynput optional)
plan/migration-plan.md     difference audit, what is ported, what is not, and why
src/swjtumover_msgs        MotorState message (nine fields, same as ROS 1)
src/swjtumover_bringup     motor_node, screen_node, teleop_node.py, launch, config, urdf
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

17 tests, 0 failures. They are migration tests, not feature tests: topic names, protocol
constants, odometry maths, message field order, parameter values against the ROS 1 YAML, and
the launch selection.

## Run

```bash
ros2 launch swjtumover_bringup bringup.launch.py
ros2 launch swjtumover_bringup bringup.launch.py enable_teleop:=true enable_visualization:=true
```

The LiDAR starts first and the rest follows after `lidar_bind_lead` seconds (default 3), because
every ROS 2 process binds UDP 7000 here and the driver must own it first.

## ROS 1 sources kept for comparison

`src/swjtumover_bringup/src/ros1_reference/` holds the ROS 1 `motor_node.cpp`,
`screen_node.cpp`, `motor_node_original_ros1.cpp` and the CRC helper exactly as they are on the
robot. The parity tests read them, so any future change to the ROS 2 side that silently breaks
the interface will fail a test rather than a field trial.
