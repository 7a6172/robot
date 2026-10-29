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

## The LiDAR cannot bind UDP 7000

The symptom, repeated every couple of seconds because the node is restarted automatically:

```
[vanjee_scan_node-1] [FATAL] cannot bind 192.168.110.10:7000: Address already in use
(another process, or a DDS participant, already owns it; find it with `ss -lunp | grep :7000`)
```

The LiDAR sends its scans to **192.168.110.10:7000**, and in this ROS 2 environment *every* participant
takes UDP 7000 as well. Whoever binds it first keeps it. The driver therefore has to be the first ROS 2
process, which `bringup.launch.py` arranges by starting it three seconds ahead of everything else
(`lidar_bind_lead`).

It breaks in three situations, and none is a fault in the driver:

* **The `ros2` command-line daemon.** This is the usual one: every `ros2` command starts a background
  daemon that caches discovery for two hours and holds UDP 7000 while it lives, so a single
  `ros2 topic list` is enough to break the next bringup. `bringup.launch.py` now stops the daemon
  itself before starting the driver, so a fresh bringup recovers on its own — and caasi's own
  queries ask for `--no-daemon`, so it does not leave one behind. If you started nodes by hand, do it
  yourself:

  ```bash
  caasi exec -t swjtumover05 --ros -- ros2 daemon stop
  ```

* **Something was already running.** A leftover node, a `ros2 topic hz` you forgot, or a launch you
  stopped with `Ctrl-C` but whose children survived. Ask who holds the port, then stop it:

  ```bash
  caasi exec -t swjtumover05 -- bash -c 'ss -lunp | grep :7000'
  caasi run stop          # stop the most recent run
  ```

  The name in brackets is the process: `vanjee_scan_nod` is the driver itself (fine), anything else
  is a squatter. With a clean robot the port is free and bringup starts normally.

* **Navigation started the hardware for you.** It must not: nav2's nodes bind 7000 before the LiDAR
  gets there. Start `bringup.launch.py` first and leave it running, then start navigation — see
  [Commands §6](commands.md#6-navigation).

If `/scan` is missing but the log shows no bind error, check the network instead:

```bash
caasi exec -t swjtumover05 --ros -- ros2 topic hz /scan
caasi exec -t swjtumover05 -- bash -c 'ping -c 2 192.168.110.100'
```

## Navigation does nothing, nodes stay `inactive`

```bash
caasi exec -t swjtumover05 --ros -- ros2 lifecycle get /amcl
```

`inactive` has two causes. First, check the hardware is up at all — without `/scan` and TF, nav2 can
only wait:

```bash
caasi exec -t swjtumover05 --ros -- ros2 topic hz /scan
```

Second, nav2 has not been told where the robot is. Give it a pose; the equivalent of clicking
"2D Pose Estimate" in rviz:

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
