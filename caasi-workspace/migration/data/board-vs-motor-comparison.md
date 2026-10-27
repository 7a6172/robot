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

---

# The two robots do NOT run the same code (correction)

An earlier statement in this document said the robots run the same source. That was based on
`motor.yaml`, `lidar.yaml` and the URDF being byte-identical, which they are. Comparing the
node sources afterwards shows the motor node is **different**:

| | `swjtumover05` (A) | `swjtumover01` (B) |
| --- | --- | --- |
| `motor_node.cpp` size | 21,597 bytes | 27,866 bytes |
| `motor_node.cpp` md5 | `0219c906…` | `479f5b9c…` |
| `cmd_vel_timeout` | **absent** | 0.5 s |
| `motor_feedback_timeout` | **absent** | 0.5 s |
| `motor_safety::Guard` | **absent** | present |
| `include/utils/motor_safety.h` | **absent** | present |

So B carries a hardened motor node with a command watchdog and a feedback timeout; A carries
an older one with neither. That is the missing half of the incident explanation: the latched
command that drove one wheel could only persist on the version without a watchdog, and it is
why B never showed the behaviour.

Implication for the campaign: "the ROS 1 reference" is not one thing. A's ROS 1 is the older,
unsafe variant; B's ROS 1 is closer to the ROS 2 design. Any ROS 1/ROS 2 safety comparison must
say which variant it used, and fixing A's code is the operator's call — the ROS 1 tree is
read-only for this campaign.

# Verification repetition, and a side effect of probing

The verification was repeated after the swap. Results reproduced: A (good board
`…00:01:df`) answered the protocol probe and B (suspect board `…00:29:79`) answered nothing.

However, on the second pass A's board stopped replying to `motor_node` even though it still
answered hand-made frames, and its reply rate had fallen from ~100% of frames to ~32%. Notably
one of the probe variants sends `byte7 = 0xff`, which the driver source documents as the
**electromagnetic brake** flag (commented out in ROS 1). Probing with that variant was my
mistake: frames that are zero-speed but brake-flagged are not a safe "no-op", since they can
change controller state.

Lesson recorded: control-protocol probing must only ever use the exact frame the production
driver sends (same `acc`, `byte7 = 0x00`), never exploratory variants. A board power cycle is
the recovery step.

---

# Leading hypothesis: supply voltage, not damaged hardware

The operator suggested low battery. That fits the whole sequence better than hardware damage:

* the reply rate did not stop abruptly — it **decayed** (≈100% of frames → ~32% → 0) while the
  board's Ethernet side kept answering ping throughout;
* the motors stopped at the same time, with no error and no telemetry;
* the behaviour differed between two robots at different times with the same code, and
  recovered for a while after a power cycle;
* a network/PHY module typically keeps running on less current than the control MCU, so
  "ping works, control does not" is what a brownout looks like from the outside.

If that is right, nothing is damaged and the previous "the board is faulty" conclusion should
be read as "the board stopped working under the conditions tested", not as a verdict on the
hardware.

**Action before any further motor or odometry work:** charge both robots fully, then repeat the
trio (protocol reply rate → telemetry rate → slow motion with odometry) and record the battery
voltage alongside the result. Motion results measured on a partially discharged pack should not
be used as a behavioural reference.
