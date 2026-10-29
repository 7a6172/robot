# Troubleshooting

Work down the list for the symptom you have. Every command that acts on the robot is given in the
remote form; anything here also works locally, as in [Commands](commands.md).

## The robot does not move

Check in this order — each step rules out the one below it.

**1. Is anything even publishing a command?**

```bash
caasi ros2 topic /cmd_vel --echo --once -t swjtumover05
```

Nothing at all means no program is asking the robot to move — the mission is idle, or the controller
is not running. If it prints `linear: x: 0.0`, something is publishing but asking for standstill.

**2. Is the motor driver still alive?**

```bash
caasi ros2 topic /motor_state/left --echo --once -t swjtumover05
```

If this prints nothing, the driver has stopped talking to the motor board. Its log says why:

```bash
caasi logs latest --errors
```

A line like this means the board went quiet — usually the battery:

```
motor feedback timeout, locked to zero speed; left gap 21.4s, right gap 21.4s
```

The driver **latches off** in that case and will not move until restarted: charge the robot, then
`caasi run stop <the bringup run>` and start it again.

**3. Is the driver refusing because of a fault?**

`/motor_state/…` carries five flags — over-temperature, stall, phase overcurrent, overcurrent,
sensor. Any of them true is why. Restart after fixing the cause; the latch is deliberate.

**4. Is navigation the one holding the robot back?**

If you are driving with nav2, remember it publishes `/cmd_vel/nav`, and the mission node is what
sends that to `/cmd_vel`. For a standalone navigation test, launch it with
`cmd_vel_topic:=/cmd_vel`.

## There is no LiDAR data

```bash
caasi exec -t swjtumover05 --ros -- ros2 topic hz /scan
```

Nothing, or the log says the adapter could not open a port: something else took **UDP 7000**. The
LiDAR has to start before the other programs, which `bringup.launch.py` does for you — if you started
nodes by hand, stop everything and use the launch file.

## Navigation does nothing, nodes stay `inactive`

```bash
caasi exec -t swjtumover05 --ros -- ros2 lifecycle get /amcl
```

`inactive` means nav2 has not been told where the robot is. Give it a pose; the equivalent of
clicking "2D Pose Estimate" in rviz:

```bash
caasi exec -t swjtumover05 --ros -- ros2 topic pub --once /initialpose \
  geometry_msgs/msg/PoseWithCovarianceStamped \
  "{header: {frame_id: map}, pose: {pose: {position: {x: 0.0, y: 0.0, z: 0.0}, orientation: {w: 1.0}}}}"
```

If a launch was already aborted by the time you set the pose, restart the navigation launch — a
lifecycle manager that has given up does not retry.

Bring nav2 up **before** the camera. With the camera streaming at full rate during start-up, the
lifecycle transitions slow down badly on a small machine and the manager can give up.

## The mission will not start

```bash
caasi run start experiments/mission_start.yaml -t swjtumover05
```

It prints the service's answer. The two common ones:

| answer | meaning |
| --- | --- |
| `no /amcl_pose and no map -> base_link transform yet: set an initial pose first` | the robot does not know where it is — see the pose command above |
| `/line_then_home/start is not available -- is the mission launch running?` | `experiments/mission.yaml` is not running |

## rviz shows nothing, or "frame [map] does not exist"

`map` only exists once localisation or mapping is running. With just the bringup, the fixed frame
`odom` is the right one — the shipped configuration already uses it, so a "map does not exist" error
means an older configuration file is in use.

If the robot model is missing while everything else draws, the description did not reach rviz; the
shipped configuration asks for it correctly, so check you are loading
`config/bringup.rviz` and not another file.

The map panel stays empty until something publishes `/map`. The two costmap panels need nav2 and are
off by default.

## Keyboard teleoperation does nothing

The node needs a display. If it prints `keyboard teleoperation: node started` it is listening, and the
likely reason keys do nothing is focus: on a Wayland desktop the keyboard is only received while an
X11 window has focus, so click the rviz window first.

If it exits with code 3 instead, there is no display at all — run it from a terminal inside the
robot's desktop session, or through a remote desktop session (see [Remote access](fleet-and-display.md)).

## caasi cannot reach the robot

```bash
caasi node check swjtumover05
```

* **unreachable** — the robot is off, or on a different address. `caasi node refresh swjtumover05`
  re-verifies and follows it.
* **identity mismatch** — the machine answering is not the one you enrolled. Do not re-enrol blindly:
  confirm which robot it is, then `caasi node reenroll` if the hardware legitimately changed.
* **slow or flaky** — small machines over Wi-Fi drop connections. Retry; a run that reports `lost`
  started but its wrapper could not be placed. `caasi run start` again after the link settles.

## A run reports `failed` immediately

```bash
caasi logs <run> --errors
```

The usual causes: the service it needed was not running (see the mission above), the robot's build is
older than the code you think it has (`caasi run status <run>` names the build), or a package is
missing (`caasi target deps swjtumover05 --for bringup`).

## Starting over cleanly

```bash
caasi run list                     # stop anything running
caasi run stop <each run>
caasi build --target swjtumover05 --clean
caasi deploy swjtumover05
caasi build --target swjtumover05
```

If you moved or renamed the project directory on the robot, a clean build is required: the build
system records absolute paths and refuses to reuse them elsewhere.
