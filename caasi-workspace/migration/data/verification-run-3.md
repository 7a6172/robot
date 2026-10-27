# Verification run 3 — after the board swap, reproduced cleanly

Both robots, same scripts, same order, production-frame probe only (`acc` as the driver
computes it, `byte7 = 0x00`, 50 Hz, alternating motor IDs). No exploratory frame variants.

## Protocol and telemetry

| | A — `swjtumover05` (.95)<br>board `…00:01:df` | B — `swjtumover01` (.194)<br>board `…00:29:79` |
| --- | --- | --- |
| protocol replies | **291 / 292 frames (99.7%)** | **0 / 234** |
| `/odom` | **50 Hz** (327 msgs) | no messages |
| `/motor_state/*` | **50 Hz** (328 msgs) | no messages |
| `/scan` | ~14 Hz (92 msgs) | ~14 Hz (93 msgs) |

A's board was at ~32% reply rate during the previous session and is now back at ~100% without
any hardware change — consistent with a transient state (probing with the brake-flagged frame,
and/or supply sag) rather than damage.

## Motor health (from the driver's own telemetry, robot A)

| motor | phase current | rpm | over-temp | stall | phase overcurrent | overcurrent | sensor |
| --- | --- | --- | --- | --- | --- | --- | --- |
| left | 0.0017 A | 1 | False | False | False | False | False |
| right | 0.0 A | −1 | False | False | False | False | False |

No fault has ever been latched on either motor channel, and idle current is essentially zero.
This is direct evidence that the incident did not damage the motors or leave a driver fault
behind.

## Motion (0.06 m/s for 6 s each way, with the zero-velocity fence after each)

| | A | B |
| --- | --- | --- |
| forward | **0.3396 m, ratio 0.9434, yaw −0.0682 rad** | no odometry |
| reverse | **0.3399 m, ratio 0.9441, yaw +0.0748 rad** | — |

A reproduces its post-swap numbers to within 0.3 mm (0.3396/0.3399 now vs 0.3395/0.3399
before), so the measurement is repeatable. B, holding the suspect board, still produces no
telemetry and no motion.

## Verdict

Reproduced for the third time, with only production-identical frames: **the fault travels with
the suspect board (`00:04:a3:00:29:79`)**. Robot A with the other board answers 99.7% of frames,
reports 50 Hz telemetry with all fault flags clear, and drives repeatably at a 0.944 distance
ratio.

Open question, and the reason the earlier "damaged board" wording was softened: B's board may
be failing only under some conditions (supply voltage, or a state my probing induced). Before
declaring it dead it should be tested with a fully charged pack and, ideally, nothing else
touching the protocol.
