# Run 3: ROS 2 hardware verification on U24, robot in the air on a box

Purpose: prove the migrated ROS 2 stack drives the hardware correctly **before** the robot goes
back on the floor. This is the step whose ROS 1 equivalent preceded the board failure, so it was
done in ascending order of risk, with the wheels off the ground throughout.

## Sequence and evidence

| step | result |
| --- | --- |
| ping / ARP to the controller | 1.5 ms |
| protocol probe, production frame only (acc from wheel_acc 1800, byte7 0x00, zero speed, 50 Hz) | **292 / 293 frames answered**, all CRCs valid |
| motor node alone, before any command | telemetry 50 Hz, protocol RPM **0 / 0**, fault latch **no** |
| `/odom`, `/motor_state` content | 50 Hz each, frame `odom` → `base_link`, all five fault flags false |
| LiDAR node | `/scan` ~14 Hz |
| both together | `/scan` 14 Hz **and** `/odom` 50 Hz simultaneously |
| `base_link → lidar_link` | translation z **0.14114 m**, pitch **0.02618 rad (1.500°)**, quaternion valid |
| `odom → base_link` | identity, valid quaternion (no all-zero quaternion) |
| wheel test, 0.05 m/s for 1.5 s | left/right rpm rose to **7 / 8** |
| **watchdog: commands stopped, nothing else sent** | rpm back to ~0 within **0.6 s**, no explicit zero needed |
| node shutdown | last logged protocol RPM **0 / 0**, SIGTERM handled, `/tmp` cleaned, port 7000 free |

The watchdog result is the important one and it is new relative to ROS 1: on U20 the only way to
stop is to keep sending zeros, and a killed process leaves the controller holding the last
command. On ROS 2 the command expires by itself.

## Two defects found on hardware, both fixed

1. **Integer YAML values were rejected.** `control_freq: 50` in the ROS 1 `motor.yaml` failed
   with `parameter {motor.control_freq} is of type {double}, setting it to {integer} is not
   allowed`. ROS 1's `param<float>` had converted it silently. The node now declares each
   numeric parameter from the *override's own type*, so the ROS 1 configuration files load
   unchanged -- which is the whole point of the migration. Regression test added.
2. **UDP 7000 ordering, reproduced on U24.** Starting `motor_node` before the LiDAR let its DDS
   participant take `0.0.0.0:7000`, and the driver then failed to bind. Restarting in the
   documented order (LiDAR first, everything else after `lidar_bind_lead`) worked immediately --
   which also validates the launch design on real hardware rather than by reasoning.

## Deployment note (temporary)

The project was synced to `~/swjtumover_ros2` and built there with `colcon`, not deployed through
caasi, because caasi's layout gives a robot exactly one deployment directory
(`~/caasi/robots/swjtumover05`) and that currently holds the openmover deployment. Two projects
on one robot therefore collide. Final shipping through caasi needs either a per-project
deployment root or the layout's `~/caasi/robots/<robot>/projects/<project>` slot to be used by
`deploy`; that is a caasi change, recorded rather than worked around permanently.

Everything above was executed through `caasi exec` / `caasi run` on the enrolled target, with the
strict host-key record in place.

## Wheel test, staged for an operator watching (wheels free)

Four stages of 2 s each with 2 s stops between, so the movement is unambiguous to the eye, plus
rpm evidence sampled at the end of every stage:

| stage | command | rpm left / right | expected |
| --- | --- | --- | --- |
| FORWARD | +0.08 m/s | **9 / 16** | both forward — correct |
| BACKWARD | −0.08 m/s | **−22 / −14** | both backward — correct |
| TURN LEFT | +0.50 rad/s | **−4 / 7** | left back, right forward — correct |
| TURN RIGHT | −0.50 rad/s | **3 / −10** | left forward, right back — correct |
| after every stop | zero | ~0 / 0 | watchdog returns the wheels to rest |

Operator confirmed visually that all four stages looked right, with clean stops, and that the
free-spinning speed difference between the wheels looks normal (they are uncoupled, with caster
drag, and are only coupled once on the floor).

## Yaw sign convention, from encoder odometry

Turning in place with the wheels free does not rotate the robot, but the encoder integration
still produces the yaw the rest of the stack depends on, so the sign convention can be verified
without the floor:

| command | odometry yaw change | verdict |
| --- | --- | --- |
| +0.5 rad/s for 2.5 s | **+1.1002 rad** | positive as expected |
| −0.5 rad/s for 2.5 s | **−1.0921 rad** | negative as expected |

Symmetric to 0.7%, so the left/right wheel mapping and the differential sign are both consistent
with ROS 1. This is the check that would have caught a swapped motor ID before a floor test.
