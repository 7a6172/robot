# Concepts

Short definitions of everything the rest of the manual assumes. Skip what you already know.

## ROS 2 in ten lines

ROS 2 is the framework the robot's programs are built on. Programs are **nodes**; they talk to each
other over named channels.

| word | meaning |
| --- | --- |
| **node** | one program doing one job, e.g. `motor_node` talks to the motor board |
| **topic** | a named stream of messages, e.g. `/scan` carries LiDAR readings 14 times a second |
| **message** | the data on a topic: a LiDAR scan, an odometry pose, a velocity command |
| **service** | a request/response call, e.g. "start the mission" and its answer |
| **action** | a long-running request with progress, e.g. "navigate to this point" |
| **launch file** | a script that starts several nodes with the right settings |
| **parameter** | a named setting a node reads at start-up, e.g. wheel radius |
| **TF** | the tree of coordinate frames; it lets a LiDAR reading be placed in the map |
| **lifecycle** | a node that must be *activated* before it works (navigation and mapping nodes) |
| **bag** | a recording of topics, so you can replay exactly what happened |

Commands you will use:

```bash
ros2 node list                     # what is running
ros2 topic list                    # what channels exist
ros2 topic hz /scan                # how often a topic publishes
ros2 topic echo /odom --once       # print one message
ros2 service call <name> <type> "{}"   # call a service
ros2 launch swjtumover_bringup bringup.launch.py
```

Coming from ROS 1, the names simply gained `ros2`:

| ROS 1 | ROS 2 |
| --- | --- |
| `roslaunch pkg file.launch` | `ros2 launch pkg file.launch.py` |
| `rosrun pkg node` | `ros2 run pkg node` |
| `rostopic` / `rosservice` / `rosnode` / `rosbag` | `ros2 topic` / `ros2 service` / `ros2 node` / `ros2 bag` |
| `rosparam` | parameters are per node: `ros2 param get` |
| parameter server | no global server; settings live with each node |
| `tf_echo` (from `tf`) | `tf2_echo` (from `tf2_ros`) |

## caasi in ten lines

caasi is the tool that puts the software on a robot and runs it from your computer.

| word | meaning |
| --- | --- |
| **project** | this repository. caasi reads `caasi.yaml` to learn what it needs |
| **target** | a machine caasi can reach: the robot, or a workstation. You create one with `caasi node enroll` |
| **deployment** | a copy of the project on the target, under `~/caasi/robots/<project>` |
| **build** | running `colcon build` on the target, recorded so runs know which build they used |
| **run** | one task started through caasi, with a name, a log, and an exit code |
| **exec** | a one-off command on the target, for quick checks |
| **scope** (`--for bringup`) | which part of the project you are asking about when checking dependencies |

A run is the thing you watch: `caasi run status <run>`, `caasi logs <run> -f`, `caasi run stop <run>`.

## Words used in this manual

* **bringup** — starting the robot's basic drivers: motors, screen, LiDAR.
* **mapping** — driving around to build a map of the space.
* **navigation** — telling the robot to go to a point on that map.
* **mission** — the whole task: follow the line, stop, then navigate back to where it started.
* **odometry** — the robot's estimate of how far it has moved, from wheel rotation.
* **localisation** — working out where the robot is on the map.
* **costmap** — a grid navigation uses to know what is free, blocked and risky.
