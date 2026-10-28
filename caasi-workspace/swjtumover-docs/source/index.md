# swjtumover

Software for the swjtumover robot: it drives the wheels, reads the LiDAR, follows the black line,
navigates a map, and runs the line-then-home mission.

It runs on **ROS 2** (the newer version of the robot framework this robot used before) and can be
operated in two ways:

| | what it means |
| --- | --- |
| **On the robot** | you open a terminal on the robot and type ROS 2 commands |
| **From your computer** | you use **caasi**, a tool that deploys the software to the robot, starts tasks there, and shows you their output from wherever you are |

There is no wrong choice. caasi adds records and remote control; the plain ROS 2 commands are exactly
equivalent and always available.

## New to this?

Read in this order:

1. **[Getting started](getting-started.md)** — prepare the robot, install caasi, connect the two, and
   run the robot for the first time. Start here if you have never set this up.
2. **[Concepts](concepts.md)** — the handful of words you need: node, topic, service, launch, target,
   run. Skim it if you know ROS 2 already.
3. **[Commands](commands.md)** — every task, in both forms, with an example and a way to check it.
4. **[Troubleshooting](troubleshooting.md)** — what to do when something does not behave.

Before driving the robot, read **[Hardware and safety](hardware.md)**.

## What is in the package

| part | contents |
| --- | --- |
| `swjtumover_msgs` | the message the motor driver publishes: currents, rpm, position, fault flags |
| `swjtumover_bringup` | motor driver, screen driver, launch files, configuration, task scripts |
| `swjtumover_vanjee` | LiDAR adapter, publishes `/scan` |
| `experiments/` | one file per task, used by caasi to run it |
| `docs/` | this manual (the pages you are reading) |

## The robot

| item | value |
| --- | --- |
| body | 0.32 × 0.30 m, 0.089 m tall |
| LiDAR | Vanjee 718H, single line, mounted at the centre of the body, 0.141 m up, tilted 1.5° |
| wheels | radius 0.05035 m, 0.206 m apart |
| motor board | `192.168.100.100`, UDP port 23 |
| small display | `192.168.100.100`, UDP port 26 |
| internal networks | LiDAR `192.168.110.x`, motors `192.168.100.x` |

## Three things worth knowing before you start

1. **The LiDAR sits at the centre of the body.** A distance it reports is measured to the centre; the
   front of the robot is 0.16 m closer to whatever it is measuring. The software accounts for this.
2. **The LiDAR must start first.** The robot's programs compete for one network port (UDP 7000) and
   the LiDAR has to win it. The bringup does that in the right order for you.
3. **The motor driver stops by itself.** If commands stop arriving, or the board stops answering, the
   wheels are driven to zero within half a second and the driver refuses to move until restarted.
