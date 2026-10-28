# swjtumover — ROS 2 manual

`swjtumover` is the robot's own software, migrated from ROS 1 (Noetic, Ubuntu 20.04) to ROS 2
Jazzy (Ubuntu 24.04). The same robot behaviour is preserved: the same topics, the same services,
the same parameters, the same message format. What changed is the machinery underneath.

This manual covers two ways to use it:

* **[Running with ROS 2](ros2.md)** — build it, start the launch files, use the services.
* **[Running with caasi](caasi-commands.md)** — deploy, build and run the same things as tracked,
  monitorable runs on the robot.

Read **[Hardware and safety](hardware.md)** before driving the robot. The
**[audit](ros1-vs-ros2-audit.md)** explains every difference from the ROS 1 original.

## What is in the package

| package | what it does |
| --- | --- |
| `swjtumover_bringup` | motor driver, screen driver, launch files, configuration, the task scripts |
| `swjtumover_msgs` | `MotorState` — the same nine fields as ROS 1 |
| `swjtumover_vanjee` | thin adapter for the Vanjee 718H LiDAR, publishing `/scan` |

## The robot in one table

| item | value |
| --- | --- |
| body | 0.32 × 0.30 m, square, 0.089 m tall |
| LiDAR | Vanjee 718H, single line, mounted at **(0, 0, 0.14114)**, centred, pitch 1.5° |
| wheels | radius 0.05035 m, track ±0.103 m, 1800 rpm/s acceleration |
| motor board | `192.168.100.100:23`, UDP, own CRC8-Maxim protocol |
| display | `192.168.100.100:26`, UDP |
| networks | LiDAR `192.168.110.0/24`, motor/IO `192.168.100.0/24` |

## Three things that surprise people

1. **The LiDAR sits in the centre of the body.** Every range it reports is the distance to the
   *centre*; the body still reaches 0.16 m further ahead. Any obstacle check must account for that.
2. **Start the LiDAR first.** Every ROS 2 process on this machine will try to bind UDP 7000, and
   the LiDAR adapter must win. `bringup.launch.py` handles this with `lidar_bind_lead`.
3. **The motor driver has a watchdog.** If commands stop, or motor feedback stops, the wheels are
   zeroed within half a second and the driver latches itself off until restarted. That is the
   behaviour ROS 1 did not have, and it is deliberate.
