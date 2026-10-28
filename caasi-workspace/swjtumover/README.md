# swjtumover

ROS 2 software for the swjtumover robot: motor driver, screen driver, LiDAR adapter, line following,
navigation and the line-then-home mission.

Two ways to run it. Both are supported; use whichever suits the moment.

* **Directly with ROS 2** — familiar `ros2 launch` / `ros2 run` commands on the robot itself.
* **Through caasi** — deploy, build, run and monitor from another machine as tracked runs.

The full manual is in `docs/` and builds to HTML with `scripts/build_docs.sh`.

## Requirements

* ROS 2 Jazzy on Ubuntu 24.04 (the robot and, for caasi runs, the machine you drive it from)
* `colcon`, and for the optional parts: `python3-pynput` (teleoperation), `realsense2_camera`
  (camera), `nav2_bringup` + `slam_toolbox` (navigation and mapping)

## Layout

```
src/swjtumover_msgs/       MotorState — the message the motor driver publishes
src/swjtumover_bringup/    motor driver, screen driver, launch files, config, scripts, tests
src/swjtumover_vanjee/     LiDAR adapter (Vanjee 718H) publishing /scan
external/vanjee_driver/    vendored vendor SDK the adapter builds against
experiments/               one caasi run definition per task
scripts/                   caasi entry point, teleop launcher, docs build
docs/                      this manual
config/                    robot configuration (also installed into the package share)
```

## Build and test

```bash
colcon build --symlink-install
source install/setup.bash

colcon test --packages-select swjtumover_bringup
colcon test-result --result-base build/swjtumover_bringup
```

## Start the robot

Directly with ROS 2:

```bash
ros2 launch swjtumover_bringup bringup.launch.py
```

Through caasi, from this directory:

```bash
caasi deploy <target>            # copy the project to the robot
caasi build  --target <target>   # colcon build there
caasi run start experiments/bringup.yaml -t <target>
caasi run status <run>           # logs, state, stop
```

## Common tasks

| task | ROS 2 | caasi |
| --- | --- | --- |
| hardware bringup | `ros2 launch swjtumover_bringup bringup.launch.py` | `experiments/bringup.yaml` |
| mapping | `ros2 launch swjtumover_bringup slam.launch.py` | `experiments/slam.yaml` |
| navigation | `ros2 launch swjtumover_bringup navigation.launch.py` | `experiments/navigation.yaml` |
| line-then-home mission | `ros2 launch swjtumover_bringup line_then_home.launch.py` | `experiments/mission.yaml` |
| keyboard teleoperation | `scripts/run_teleop.sh` | `experiments/teleop.yaml` |
| camera | `ros2 launch realsense2_camera rs_launch.py` | `experiments/camera.yaml` |
| visualization | `rviz2 -d …/config/bringup.rviz` | `experiments/rviz.yaml` |

`docs/commands-ros1-vs-ros2.md` lists every command in full, for both ROS 1 and ROS 2.

## Documentation

```bash
scripts/build_docs.sh          # HTML site in ../swjtumover-docs
scripts/build_docs.sh serve    # live preview on http://127.0.0.1:8000
```

## Configuration

Robot parameters live in `src/swjtumover_bringup/config/` (`motor.yaml`, `screen.yaml`,
`teleop.yaml`, `line_then_home.yaml`) and `param/` (nav2 and SLAM). Launch arguments override them
per run, for example:

```bash
ros2 launch swjtumover_bringup navigation.launch.py map:=<path>/nav.yaml cmd_vel_topic:=/cmd_vel
```
