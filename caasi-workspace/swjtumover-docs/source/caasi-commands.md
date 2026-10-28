# Running with caasi

caasi deploys the project to a robot, builds it there, and runs each task as a tracked process you
can watch, read and stop from your own machine.

After the robot is enrolled (its SSH access set up and its host key recorded), everything below is
driven from the project directory on your machine. No addresses or credentials are repeated per
command.

## First time on a robot

```bash
caasi deploy <target>             # copy the project to the robot
caasi build --target <target>     # colcon build there, recorded against the deployment
```

`caasi deploy --status` shows what is deployed and whether it verified.

## Run entry points

Each task is one file in `experiments/`. They all go through `scripts/caasi_launch.py`, which sources
the ROS environment and then `exec`s the real command, so `caasi run stop` reaches ROS 2 the way
Ctrl-C would.

| task | experiment |
| --- | --- |
| hardware bringup | `experiments/bringup.yaml` |
| bringup with teleoperation | `experiments/bringup_teleop.yaml` |
| bringup with rviz | `experiments/bringup_rviz.yaml` |
| mapping | `experiments/slam.yaml` |
| navigation | `experiments/navigation.yaml` |
| line-then-home mission | `experiments/mission.yaml` |
| mission with the site's line calibration | `experiments/mission_demo.yaml` |
| line follower alone | `experiments/line_follower.yaml` |
| obstacle guard alone | `experiments/obstacle_guard.yaml` |
| keyboard teleoperation alone | `experiments/teleop.yaml` |
| camera | `experiments/camera.yaml` |
| rviz | `experiments/rviz.yaml` |
| mission: start | `experiments/mission_start.yaml` |
| mission: stop | `experiments/mission_stop.yaml` |
| mission: record return waypoints | `experiments/mission_record_waypoints.yaml` |

## Running and watching

```bash
caasi run start experiments/bringup.yaml -t <target>
caasi run status <run>
caasi logs <run> -f
caasi run stop <run>
caasi run list
```

The mission services are runs of their own, so a refused start shows up in the run status rather than
scrolling past in a terminal:

```bash
caasi run start experiments/mission_start.yaml -t <target>     # prints success + message
caasi run start experiments/mission_stop.yaml  -t <target>
```

## Order that works for a mission

```bash
caasi run start experiments/mission.yaml -t <target>      # bringup + nav2 + mission + follower
# set the pose (see Running on the robot) once nav2 is up
# wait until all seven nav2 nodes report active
caasi run start experiments/camera.yaml -t <target>       # camera after nav2
caasi run start experiments/mission_start.yaml -t <target>
caasi logs <mission run> -f                                # watch /line_then_home/state
```

Bring nav2 up before the camera: the camera at full rate during bringup slows the lifecycle
transitions considerably on a small machine.

## Where things land

| what | where |
| --- | --- |
| deployed project | `~/caasi/robots/swjtumover` on the robot |
| run output | `<project>/.caasi/runs/<run>/stdout.log`, `stderr.log`, `exit_code` |
| run records | `~/.caasi/runs/<run>/` on your machine |

## Without caasi

Every task above has a direct ROS 2 form; see [Running on the robot](ros2.md) and the full list in
[Commands and workflows](commands.md). caasi is a convenience and a record keeper, not a
requirement.
