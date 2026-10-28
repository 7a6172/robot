# Hardware and safety

Read this before driving the robot.

## Interfaces

| what | where |
| --- | --- |
| motor / IO board | `192.168.100.100`, TCP/UDP **23** (motors) and UDP **26** (display) |
| Vanjee 718H LiDAR | `192.168.110.100`, UDP **7000** on the host, `5000` on the LiDAR |
| host addresses | `192.168.100.10` (motor net), `192.168.110.10` (LiDAR net) |

The motor protocol is the board's own: 10-byte datagrams, CRC8-Maxim in the last byte, motor id
`0x01` left / `0x02` right, speed as a signed RPM in bytes 2-3. The driver is the only thing that
should talk to port 23.

## The safety model

Four independent layers. The ROS 1 package had **none** of the first two, which is why the robot
once kept driving after its process died.

| layer | what it does |
| --- | --- |
| **command watchdog** | `motor.cmd_vel_timeout` (0.5 s): no new `cmd_vel` → zero speed |
| **feedback watchdog** | `motor.motor_feedback_timeout` (0.5 s): motor telemetry stops → zero speed and the node **latches off** until restarted |
| **fault latch** | any of the five board fault flags (over-temperature, stall, phase overcurrent, overcurrent, sensor) → latched off |
| **costmap + footprint** | nav2's `ObstacleFootprint` critic rejects any trajectory that would put the *body* into an obstacle |

A latched-off driver stays off on purpose: it means a real problem happened. Restart it after
fixing the cause.

## Body geometry matters

The body is 0.32 × 0.30 m and the LiDAR is at its **centre**. Every range is therefore measured to
the centre, and the body extends 0.16 m further forward than the number suggests.

* the line follower stops when the centre clearance drops below **0.28 m** (0.16 body + 0.12 margin)
* nav2's footprint is the body plus `footprint_padding: 0.06`
* a guard that stops at a raw 0.22 m leaves only 6 cm — too close

## Practical rules

1. **Check the battery first.** The motor board goes silent when the supply sags. Ping succeeds
   while protocol replies decay — if replies fall below ~95 %, charge it before driving.
2. **Start the LiDAR first.** Any process that binds UDP 7000 first keeps it; if `motor_node` wins,
   the LiDAR cannot bind and there is no `/scan`.
3. **Nothing may be left commanding.** Every script here publishes a final zero and the watchdog
   covers the rest, but never leave a publisher running when you walk away.
4. **Set the pose before navigating.** nav2 activates its global costmap only once `map → base_link`
   exists; without a pose the stack waits (up to 600 s) and never activates.
5. **Low obstacles are invisible.** This is a single-line LiDAR sweeping one plane at 0.141 m.
   Anything shorter than that plane is not seen by the scan or the costmap.

## Checking the robot is healthy

```bash
ping -c3 192.168.100.100                    # board reachable
python3 /path/to/probe_prod.py              # protocol replies >= 95 %
ros2 topic hz /scan                         # ~14 Hz
ros2 topic hz /odom                         # ~50 Hz
ros2 topic echo /motor_state/left --once    # all five fault flags false, rpm ~0 at rest
```

## Recovery

| symptom | cause | fix |
| --- | --- | --- |
| `/scan` missing, port 7000 taken by `motor_node` | start order | restart with the LiDAR first (`bringup.launch.py` does this) |
| no `/odom`, driver logs "feedback timeout" then "latched" | board silent (battery, cable) | charge/repair, then restart the node |
| nav2 nodes stay `inactive` | no `map → base_link` | publish `/initialpose` |
| `map_server` fails to configure | map yaml path wrong | the `image:` entry must be relative |
| robot will not move although `/cmd_vel` has values | driver latched, or the smoother is publishing to `/cmd_vel/nav` instead of `/cmd_vel` | restart the driver; check `cmd_vel_topic` |
