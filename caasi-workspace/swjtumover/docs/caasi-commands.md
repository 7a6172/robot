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

## Note: a caasi bug that used to block this (fixed)

`caasi run start` originally failed on remote robot targets and reported every run as `lost`. The
remote run directory was built and used as a single-quoted `~/caasi/robots/<robot>/.caasi/runs/<run>`;
a quoted tilde does not expand, so the directory was created at a literal
`/home/<user>~/caasi/...` path, the generated `run.sh` `cd`-ed into something that did not exist
and exited. A second layer of the same bug then hit the script path, which is an argv element:
`python3 ~/caasi/.../caasi_launch.py` reached Python with the literal `~`.

Both are fixed in caasi (`src/caasi/core/runs.py`, with tests in `tests/test_remote_path_tilde.py`).
If an older caasi is in use, the symptom is a run reported `lost` immediately after starting, and
a stray directory literally named `~` in the target's home. `caasi exec --detach` was the working
path in the meantime and still works.
