# Board or motors? Comparison against a second identical robot

Second robot: hostname `swjtumover01`, management address `10.212.19.194`, same workspace
layout. **Same source code and configuration**: `motor.yaml`, `lidar.yaml` and
`robot_description.urdf` are byte-identical (sha256) to `swjtumover05`; only the compiled
binary differs, as expected for a separate build.

Same probe scripts, same ordering, robot B in normal operation, robot A in its current state:

| measurement | B — `swjtumover01` (.194) | A — `swjtumover05` (.95) |
| --- | --- | --- |
| controller MAC | `00:04:a3:00:01:df` | `00:04:a3:00:29:79` |
| controller ping | 2.5 ms | 1.4 ms |
| **zero-speed frames, CRC-valid, both motor IDs** | **40 replies** | **0 replies** |
| reply payload | `01 02 fff8 …` (left −8 rpm), `02 02 0001 …` (right +1 rpm) | none |
| `/odom` | ~50 Hz (273 msgs) | **no messages** |
| `/motor_state/*` | ~50 Hz (279 msgs) | **no messages** |
| `/scan` | 14 Hz | 14 Hz |
| slow forward 0.06 m/s × 6 s | **0.3462 m, ratio 0.962, yaw +0.0058** | no odometry, no motion |
| slow reverse 0.06 m/s × 6 s | **0.3459 m, ratio 0.961, yaw +0.0128** | no odometry, no motion |
| faster run 0.08 m/s × 3 s, both directions | 0.2375 m (0.990) / 0.2390 m (0.996) | no motion |

## Conclusion

The identical client code, configuration and probe frames work perfectly against robot B's
controller and produce nothing from robot A's. Robot A's LiDAR, network interfaces, computer
and RealSense are all healthy. **Robot A's motor controller is the faulty part**; its motors
themselves cannot be judged until a working controller drives them, but they are passive
devices and the failure mode observed here is "the controller never answers", not "the
controller answers but a wheel does not turn".

Robot B also gives a useful sanity check on the ROS 1 baseline: 0.96–0.99 distance ratio for
commanded motion, yaw drift of only 0.006–0.013 rad over a 0.35 m run, and 50 Hz odometry.
`swjtumover05` measured 25 Hz odometry and 0.88–0.98 distance ratios before its fault, so its
baseline was already somewhat different from a healthy robot of the same model — worth
remembering when comparing ROS 1 against ROS 2 later, but not evidence of a fault on its own.

## Environment note

Robot B was used read-only apart from three short motor runs (0.06–0.08 m/s, ≤ 0.35 m each,
wheels on the floor). Every script was run from `/tmp` and deleted afterwards, and all ROS
processes were stopped; `/tmp` is clean and port 7000 is free on both robots.

---

# Swap test (decisive)

The two controllers were physically exchanged, which turns the comparison into a controlled
experiment: whichever robot holds the suspect board should show the fault.

| | A — `swjtumover05` (.95)<br>now has board `…00:01:df` | B — `swjtumover01` (.194)<br>now has board `…00:29:79` |
| --- | --- | --- |
| zero-speed frames | **40 replies** | **0 replies** |
| `/odom` | **~50 Hz** (277 msgs) | no messages |
| `/motor_state/*` | **~50 Hz** (278 msgs) | no messages |
| `/scan` | 14 Hz | 14 Hz |
| slow forward 0.06 m/s × 6 s | **0.3395 m, ratio 0.943, yaw −0.0915 rad** | no odometry, no motion |
| slow reverse 0.06 m/s × 6 s | **0.3399 m, ratio 0.944, yaw +0.0888 rad** | — |

The fault moved with the board, and functionality moved with the good board. Therefore:

* the fault is **the controller board** (`00:04:a3:00:29:79`), not the motors, not the robot
  chassis, not the wiring, and not any software on either OS;
* `swjtumover05` is functional again with the swapped-in controller;
* `swjtumover01` is now the one carrying the dead board and should be swapped back before it
  is used again.

Two further observations worth keeping:

1. **`swjtumover05`'s odometry was already degraded before the failure.** With its original
   board it reported 25 Hz; with the replacement it reports 50 Hz, identical to
   `swjtumover01`. So the board that died was running at half rate for an unknown period —
   which also explains why the earlier ROS 1 baseline from this robot (25.245 Hz) differs from
   a healthy sibling.
2. **`swjtumover05` steers less straight than `swjtumover01`**: yaw drift ±0.09 rad over
   0.34 m versus ±0.006–0.013 rad on the other robot, with the *same* controller and software.
   That is a chassis/mechanical difference (wheel alignment or caster drag), not a code
   difference, and it matters for navigation tuning later.
