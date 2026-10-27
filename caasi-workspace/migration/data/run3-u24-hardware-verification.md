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

## Floor tests on U24 (before the battery ran down)

Robot on the floor inside the maze. Same probes as the ROS 1 reference, so the numbers compare
directly.

| test | ROS 1 (U20) | ROS 2 (U24) | difference |
| --- | --- | --- | --- |
| forward 0.06 m/s x 6 s | 0.3462 m, ratio 0.9616 | **0.3452 m, ratio 0.9589** | **0.29 %** |
| reverse 0.06 m/s x 6 s | 0.3479 m, ratio 0.9663 | **0.3462 m, ratio 0.9616** | **0.49 %** |
| rotate 0.5 rad/s x 1 s | 0.5096 rad, ratio 1.0191 | **0.5091 rad, ratio 1.0182** | **0.05 %** |

Yaw drift on the straight runs was -0.014 rad forward and +0.021 rad reverse, against +-0.07-0.09
rad recorded on ROS 1 with the degrading controller. A longer 3 s rotation gave 1.2996 rad
(ratio 0.866) with 1 cm of position drift; the 1 s figure is the one comparable to the ROS 1
measurement.

Conclusion: the ROS 2 drive train is equivalent to ROS 1 to well under one percent.

## Defect 3: the launch fed a ROS 1 vendor YAML to a ROS 2 node (fixed)

`bringup.launch.py` passed `swjtumover_bringup/config/lidar.yaml` -- the ROS 1 vendor schema with
`common:` / `lidar:` and no `ros__parameters` -- to the LiDAR adapter as `parameters=`. The node
died on startup:

    Couldn't parse params file: Cannot have a value before ros__parameters at line 2
    process has died [exit code -6]

It respawned, failed the same way, and no `/scan` was produced -- and because it never bound UDP
7000, `screen_node` took that port instead, defeating the ordering protection that exists for
exactly this reason. The adapter has its own flat ROS 2 file in `swjtumover_vanjee/config`, which
is what the manual runs had been using; the launch now resolves it from that package.

Regression test added: every YAML a launch passes as `parameters=` must contain
`ros__parameters`, with unknown directory variables failing the test rather than being skipped.
Verified by reintroducing the bug (2 failures) and restoring the fix (33/33 green). All earlier
static tests passed while this was broken, because none of them executed a launch.

## Incident: controller stopped answering while the battery ran down (no runaway)

After roughly two and a half minutes of floor testing the controller stopped replying, and the
ROS 2 node did exactly what the ROS 1 one could not:

    motor feedback timeout, locked to zero speed;
    left feedback gap 137.0 s, right 137.0 s. Restart the node after fixing the link.
    fault latch = yes, commanded protocol RPM 0/0

`ping` to 192.168.100.100 still answered in 0.93 ms, with no protocol replies -- the same
signature as the earlier board failure, now with the cause known: supply voltage. The owner
confirmed the robot was low on battery.

Nothing moved, nothing had to be killed, and the wheels were already at zero because the command
had expired. The node then refused to drive at all rather than trusting a stale feedback stream.
That is the difference the watchdog makes, and it is why this shutdown was uneventful.

Lesson for the next session: check the battery state *before* the first floor test, not after the
controller stops answering. The protocol probe is a battery test as much as a link test.
