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
| camera (D415) | `experiments/camera.yaml` | `roslaunch realsense2_camera rs_camera.launch` |
| **start** the mission | `experiments/mission_start.yaml` | `rosservice call /line_then_home/start` |
| **stop** the mission | `experiments/mission_stop.yaml` | `rosservice call /line_then_home/stop` |
| **record** return waypoints | `experiments/mission_record_waypoints.yaml` | `rosservice call /line_then_home/record_waypoints` |

## Commands

```bash
caasi run start experiments/bringup.yaml -t swjtumover05    # start, tracked
caasi run status <run>                                      # state
caasi logs <run> -f                                         # live output
caasi run stop <run>                                        # stop (SIGTERM reaches ROS 2)
```

The mission is started, stopped and configured through its services, exactly as the ROS 1 history
did. `caasi ros` operates on the *local* machine and has no `--target`, so on the robot these are
runs of their own, not `caasi ros service call`:

```bash
caasi run start experiments/mission_start.yaml -t swjtumover05
caasi run start experiments/mission_record_waypoints.yaml -t swjtumover05
caasi run start experiments/mission_stop.yaml -t swjtumover05
```

Each prints the service's `success` and `message` and exits 0 when the service reports success, 1
when it reports failure, 2 when it cannot be reached -- so a stopped mission is visible in the run
status rather than buried in a terminal.

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

## The order that works for a mission run

Each step exists because the previous one is a precondition, and each was learned the hard way:

```bash
# 1. bringup + nav2 + mission + follower (no camera yet)
caasi run start experiments/mission.yaml -t swjtumover05

# 2. give amcl a pose (the robot must have odometry, so the motor board must be answering)
caasi exec --target swjtumover05 -- bash -c 'source /opt/ros/jazzy/setup.bash; source \
  ~/caasi/robots/swjtumover05/install/setup.bash; ros2 topic pub --once /initialpose \
  geometry_msgs/msg/PoseWithCovarianceStamped "{header: {frame_id: map}, pose: {pose: \
  {position: {x: 0.0, y: 0.0, z: 0.0}, orientation: {w: 1.0}}}}"'

# 3. wait until nav2 is active (all seven nodes)

# 4. only now start the camera: at 30 Hz during bringup it starves the lifecycle manager
caasi run start experiments/camera.yaml -t swjtumover05

# 5. start the mission
caasi run start experiments/mission_start.yaml -t swjtumover05
caasi logs <the bringup run> -f        # watch /line_then_home/state
```

Why not all at once: with the camera running during bringup, each lifecycle configure transition
took tens of seconds and nav2's manager stalled on a DDS response timeout. Bringing nav2 up first,
then the camera, then the mission is the reliable order.
