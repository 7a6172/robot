# swjtumover

ROS 2 software for the swjtumover robot. It provides the motor driver, the display driver, a LiDAR
adapter, line following, navigation and the line-then-home mission.

There are two ways to operate it, and both are first-class:

* **[Running on the robot](ros2.md)** — direct `ros2 launch` and `ros2 run` commands.
* **[Running with caasi](caasi-commands.md)** — deploy, build, run and monitor from another machine.

For a side-by-side list of every command, see **[Commands and workflows](commands-ros1-vs-ros2.md)**.
Before driving the robot, read **[Hardware and safety](hardware.md)**. For multi-robot naming and
seeing the robot's screen remotely, see **[Remote access](fleet-and-display.md)**.

## What is in the package

| package | contents |
| --- | --- |
| `swjtumover_msgs` | `MotorState`: header, phase current, rpm, position, five fault flags |
| `swjtumover_bringup` | motor driver, screen driver, launch files, configuration, task scripts |
| `swjtumover_vanjee` | LiDAR adapter publishing `/scan` |

## The robot

| item | value |
| --- | --- |
| body | 0.32 × 0.30 m, 0.089 m tall |
| LiDAR | Vanjee 718H, single line, at (0, 0, 0.14114) m, centred, pitched 1.5° |
| wheels | radius 0.05035 m, track ±0.103 m |
| motor board | `192.168.100.100:23`, UDP, 10-byte frames with CRC8-Maxim |
| display | `192.168.100.100:26`, UDP |
| networks | LiDAR `192.168.110.0/24`, motor/IO `192.168.100.0/24` |

## Interfaces at a glance

| topic | direction | rate |
| --- | --- | --- |
| `/scan` | from the LiDAR adapter | ~14 Hz |
| `/odom`, `/motor_state/left`, `/motor_state/right` | from the motor driver | 50 Hz |
| `/cmd_vel` | to the motor driver — the only actuation path | — |
| `/cmd_vel/line`, `/cmd_vel/nav` | arbitration inputs to the mission | — |
| `/line_then_home/state` | mission state | on change |
| `/qrcode_text` | to the screen driver | on change |

Services on the mission node: `/line_then_home/start`, `…/stop`, `…/record_waypoints`.

## Three things worth knowing up front

1. **The LiDAR sits at the centre of the body.** A range reading is the distance to the centre; the
   body reaches 0.16 m further ahead. Obstacle checks account for this.
2. **Start the LiDAR first.** Every ROS 2 process on this machine may compete for UDP 7000.
   `bringup.launch.py` orders it correctly.
3. **The motor driver has a watchdog.** If commands stop, or motor feedback stops, the wheels are
   zeroed within half a second and the driver stays off until restarted.
