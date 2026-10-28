# Running swjtumover through caasi

Every command the ROS 1 workflow used from a shell is an entry point here, so it can be deployed,
started, monitored and stopped through caasi instead of an untracked terminal session.

## One-off setup

```bash
cd caasi-workspace/swjtumover
caasi deploy swjtumover05                 # -> ~/caasi/robots/swjtumover05 (VERIFIED)
caasi build --target swjtumover05          # colcon build on the robot, recorded
```

## Run entry points

All of them go through `scripts/caasi_launch.py`, which sources `/opt/ros/jazzy/setup.bash` and the
project's `install/setup.bash` and then `exec`s the real command, so signals reach ROS 2 directly.

| what | experiment config | replaces (ROS 1) |
| --- | --- | --- |
| hardware bringup | `experiments/bringup.yaml` | `roslaunch swjtumover_bringup bringup.launch` |
| bringup + teleop | `experiments/bringup_teleop.yaml` | `bringup.launch` + `teleop_node.py` |
| bringup + rviz | `experiments/bringup_rviz.yaml` | `bringup.launch` with its hardcoded rviz |
| SLAM / mapping | `experiments/slam.yaml` | `roslaunch swjtumover_bringup bringup_gmapping.launch` |
| navigation | `experiments/navigation.yaml` | `map_server.launch` + `amcl.launch` + `move_base.launch` |
| line-then-home mission | `experiments/mission.yaml` | `roslaunch swjtumover_bringup line_then_home.launch` |
| line follower alone | `experiments/line_follower.yaml` | `python3 omove_following.py` |
| obstacle guard alone | `experiments/obstacle_guard.yaml` | `python3 obstacle_rplidar.py` |
| teleop alone | `experiments/teleop.yaml` | `rosrun swjtumover_bringup teleop_node.py` |
| rviz alone | `experiments/rviz.yaml` | `rosrun rviz rviz -d bringup.rviz` |

## Commands

```bash
caasi run start experiments/bringup.yaml -t swjtumover05    # start, tracked
caasi run status <run>                                      # state
caasi logs <run> -f                                         # live output
caasi run stop <run>                                        # stop (SIGTERM reaches ROS 2)
```

Mission services, as used in the ROS 1 history:

```bash
caasi ros service call /line_then_home/start
caasi ros service call /line_then_home/record_waypoints
caasi ros service call /line_then_home/stop
```

## Known problem: `caasi run start` on a remote robot

`caasi run start` currently fails for remote targets while `caasi exec --detach` works. The remote
run directory is built as a single-quoted `~/caasi/robots/<robot>/.caasi/runs/<run>`, and inside
single quotes the shell does not expand `~`. The directory is therefore created at a literal path:

    /home/swjtumover/~/caasi/robots/swjtumover05/.caasi/runs/<run>

The generated `run.sh` then `cd`s into a path that does not exist, exits immediately, and caasi
reports the run as `lost`. Passing `--dest /home/swjtumover/caasi/robots/swjtumover05` does not
help, because the run path is derived from the target's deployment root rather than from the
deployment record.

Working path in the meantime, used for all the verification in this project:

```bash
caasi exec --target swjtumover05 --detach --name bringup -- \
  bash -c 'cd /home/swjtumover/caasi/robots/swjtumover05 && exec python3 scripts/caasi_launch.py launch bringup.launch.py'
caasi run status <name>
```

Verified through that path: the deployed project starts all five bringup nodes, `/scan` at 14 Hz,
`/odom` at 50 Hz. The fix belongs in caasi's run machinery (expand `~` to `$HOME` in the remote
command, or quote only the variable part); the caasi source is outside this project, so it is
recorded here rather than patched silently.
