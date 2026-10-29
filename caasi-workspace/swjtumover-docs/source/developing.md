# Developing

The tasks this robot ships with were written the same way you will write your own: a small Python
node, a launch or experiment entry that runs it, and a caasi command that starts it here or on the
robot. This chapter walks through that whole path once, with a complete program.

Nothing here needs ROS 1 experience. Each ROS 2 idea is explained where it first appears.

## How a task is put together

Three pieces, in three places:

| piece | where | what it is |
| --- | --- | --- |
| the **node** | `src/swjtumover_bringup/scripts/` | the Python program that does the work |
| the **entry** | `experiments/<name>.yaml` | how caasi starts it, with a name and a log |
| the **settings** | `config/*.yaml`, or a launch file in `launch/` | anything you want to change without editing code |

The existing tasks are exactly this: `scripts/line_then_home.py` is the mission, and
`experiments/mission.yaml` is how it is started.

## Your first node

This one only *listens*: it watches `/odom`, adds up the distance travelled, and prints it once a
second. It never commands the motors, so you can run it while the robot is standing still, or on your
own computer with no robot at all.

Create the file `src/swjtumover_bringup/scripts/distance_report.py`:

```python
#!/usr/bin/env python3
"""Report how far the robot has travelled, from odometry alone.

Subscribes to /odom and prints the running distance once a second. Read-only: it publishes nothing,
so it cannot move the robot.
"""

import math

import rclpy
from nav_msgs.msg import Odometry
from rclpy.node import Node


class DistanceReport(Node):
    def __init__(self) -> None:
        super().__init__("distance_report")
        # One setting, read when the node starts: seconds_to_run.
        self.declare_parameter("seconds_to_run", 10.0)
        self.seconds_to_run = float(self.get_parameter("seconds_to_run").value)

        self.total = 0.0
        self.last = None
        self.elapsed = 0.0

        # subscribe() says: call self.on_odom every time a message arrives on /odom.
        self.create_subscription(Odometry, "/odom", self.on_odom, 10)
        # A timer that fires every second, to print and to decide when to stop.
        self.create_timer(1.0, self.report)
        self.get_logger().info(f"reporting for {self.seconds_to_run:.0f} s")

    def on_odom(self, msg: Odometry) -> None:
        pose = msg.pose.pose.position
        here = (pose.x, pose.y)
        if self.last is not None:
            # Straight-line distance between two consecutive positions.
            self.total += math.hypot(here[0] - self.last[0], here[1] - self.last[1])
        self.last = here

    def report(self) -> None:
        self.elapsed += 1.0
        self.get_logger().info(f"travelled {self.total:.2f} m")
        if self.elapsed >= self.seconds_to_run:
            self.get_logger().info("done")
            raise SystemExit(0)


def main() -> int:
    rclpy.init()
    node = DistanceReport()
    try:
        rclpy.spin(node)          # keep running until the node is stopped
    except SystemExit:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

What each part is, in ROS 2 terms:

| line | meaning |
| --- | --- |
| `class DistanceReport(Node)` | a **node**: one program doing one job |
| `create_subscription(Odometry, "/odom", …)` | receive every message published on `/odom` |
| `declare_parameter("seconds_to_run", 10.0)` | a **parameter**: a setting an operator can override at start-up |
| `create_timer(1.0, self.report)` | call `report` once a second |
| `rclpy.spin(node)` | hand control to ROS 2 until something stops the node |

Comments and log strings are in English throughout this project — the ROS 1 code was in Chinese, and
the ROS 2 side is kept in one language so logs can be read by anyone on the team.

## Make it runnable

Two steps, both in the package.

**1. Tell the build to install it.** Open `src/swjtumover_bringup/CMakeLists.txt` and add your file to
the existing `install(PROGRAMS …)` list:

```cmake
install(PROGRAMS
  scripts/teleop_node.py
  scripts/obstacle_rplidar.py
  scripts/omove_following_feng.py
  scripts/line_then_home.py
  scripts/distance_report.py        # your new node
  DESTINATION lib/${PROJECT_NAME})
```

**2. Build.** Locally:

```bash
cd <project>
colcon build --symlink-install --packages-select swjtumover_bringup
source install/setup.bash
```

On the robot, through caasi:

```bash
caasi deploy                    # copies the new file
caasi build                     # rebuilds there
```

## Run it locally (on your own computer)

With the workspace sourced (`source install/setup.bash`), the ordinary ROS 2 way:

```bash
ros2 run swjtumover_bringup distance_report.py
ros2 run swjtumover_bringup distance_report.py --ros-args -p seconds_to_run:=3.0
```

| argument | meaning |
| --- | --- |
| `--ros-args -p name:=value` | set a parameter for this run only |
| `<node> --ros-args -r /odom:=/odom_filtered` | remap a topic name |

Without a running robot there will be no `/odom`, so it prints `travelled 0.00 m` and stops after ten
seconds. That is the right result: your node works, there is simply nothing to listen to.

## Run it remotely (on the robot)

caasi starts it the same way it starts the shipped tasks, so it gets a name, a log and an exit code.
Create `experiments/distance_report.yaml`:

```yaml
# Run with: caasi run start experiments/distance_report.yaml    [-t <target>]
name: swjtumover-distance-report
backend: python
script: ../scripts/caasi_launch.py
args:
- run
- distance_report.py
- --ros-args
- -p
- seconds_to_run:=20.0
description: Prints the distance travelled, from odometry, for 20 seconds. Read-only.
```

| field | meaning |
| --- | --- |
| `name` | how the run is listed and stopped |
| `backend` | `python` runs the script with the project's ROS 2 environment |
| `script` | `caasi_launch.py` is the launcher every entry point uses; it sources ROS 2 first |
| `args` | `run <executable>` maps to `ros2 run swjtumover_bringup <executable>` |

Start it, watch it, stop it:

```bash
caasi run start experiments/distance_report.yaml -t swjtumover05
caasi logs -f                       # the newest run; Ctrl+C only stops watching
caasi run status latest             # running / stopped / failed
caasi run stop latest               # actually stop it
```

**Anything that starts a node belongs in `experiments/`.** That is what makes it repeatable: the same
command works locally (`-t local`, or no target at all), the output is kept, and the exit code tells
you whether it really worked. The ROS 1 workflow opened a terminal, typed a command, and lost all of
that.

## Debugging while you develop

| question | command |
| --- | --- |
| is my node publishing? | `caasi ros2 list topics` |
| what does one message look like? | `caasi ros2 topic /odom --echo --once` |
| what is it connected to? | `caasi ros2 node /distance_report` |
| is my node even running? | `caasi ros2 list nodes` |
| what did it print? | `caasi logs <run>` |
| only the errors | `caasi logs <run> --errors` |
| how fast is a topic? | `caasi exec --ros -- ros2 topic hz /odom` |
| record it and replay later | `caasi exec --ros -- ros2 bag record -o /tmp/run1 /odom /scan` |

Add `-t swjtumover05` when no target is chosen. Two tools are worth knowing at this point:

```bash
caasi run list                   # every run you have started, with its status
caasi exec --ros -- ros2 bag info /tmp/run1   # what a recording contains
```

## The tasks that already exist

Read them in this order; each adds one idea to the one before.

| file | what it shows |
| --- | --- |
| `scripts/obstacle_rplidar.py` | subscribing to `/scan`, deciding, publishing to `/cmd_vel` |
| `scripts/teleop_node.py` | reading the keyboard, publishing velocity, stopping when a key is released |
| `scripts/omove_following_feng.py` | vision: finding a line in the camera image and steering to it |
| `scripts/line_then_home.py` | the whole mission: states, a service to start it, nav2 goals, timeouts |
| `src/motor_node.cpp` | the actuator path, with its watchdog: what happens when commands stop arriving |

The ROS 1 originals of the last two are kept beside them as `*_ros1.py` / `config/*_ros1.yaml`, so you
can compare what changed. Topic names, parameters and behaviour were preserved deliberately; where ROS 2
needed something different, the difference is commented in the file.

## House rules

* **Comments and log strings in English.** The ROS 1 files stay as they were, as references.
* **Publishing to `/cmd_vel` moves the robot.** Only one program should publish there at a time —
  `/cmd_vel/line` and `/cmd_vel/nav` are the arbitrated paths the mission uses.
* **Publish rates and timeouts, not hope.** The motor node zeroes the wheels if commands stop arriving;
  do not disable that.
* **Test on a stand first.** Wheels off the ground answer most questions before the robot can damage
  anything.
* **Anything you want to keep goes in an experiment file**, so a colleague can run it with one command.

When your node works, the next useful step is usually to look at [Commands](commands.md) for how the
shipped tasks are driven, and [Troubleshooting](troubleshooting.md) for when the robot misbehaves.
