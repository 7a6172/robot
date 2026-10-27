# Incident: motor controller stopped answering its protocol

Date: 2026-10-27. Robot `swjtumover05`. Recorded because it blocks every odometry-dependent
requirement on **both** operating systems, and because the software that led to it needs to
change.

## What happened

1. A bounded ROS 1 exploration (reactive explorer, 0.12 m/s, 0.6 rad/s, 110 s limit) was run to
   produce a reference map. It completed and printed `zero-velocity fence done`.
2. One wheel then kept driving continuously at speed until the operator powered the robot down
   — reported as "one wheel still moving continuously, other wheel no motion, it keeps going".
3. Since then the motor controller answers ping but never answers its own control protocol.

## Evidence (all collected on the robot, both OSes)

| check | result |
| --- | --- |
| ping `192.168.100.100` | 1.4 ms, 0% loss |
| ARP neighbour | `REACHABLE`, `lladdr 00:04:a3:00:29:79` |
| other hosts on 192.168.100.0/24 | only `.10` (robot) and `.100` (board) — the board did not change address |
| TCP connect :23, :1234, :8000 | timeout on all |
| unsolicited UDP datagrams, 5 s | 0 |
| well-formed zero-speed frames to both motor IDs, CRC verified against the driver's own table, 8 s | **0 replies** |
| ROS 1 `motor_node` telemetry (`/odom`, `/motor_state/*`) | silent (process blocked in `recvfrom`) |
| ROS 2 `motor_handler` telemetry (gate open and closed) | silent, but logs `UDP连接成功` |
| LiDAR, both OSes | **healthy**: 13.998 Hz (ROS 2) / 14.059 Hz (ROS 1), full contract |

So: the board's network stack is alive, its control application is not responding, and the
behaviour is identical under ROS 1 and ROS 2 and after a full power removal.

## Why the software allowed it

* ROS 1 `motor_node` has **no command watchdog**: the controller keeps executing the last
  command it received. A terminated process cannot take a command back.
* Its loop sends one command frame and then waits (5 ms timeout) for a reply, so with the board
  silent it can no longer influence the board at all.
* The explorer treated "process exit" as safe. For a system without a watchdog it is not: the
  last non-zero command must be followed by an acknowledged zero, or the run must never be
  terminated mid-command.

Changes this implies for the campaign (not yet implemented, because motion is blocked):
* explorers and motion probes must end with a *verified* stop, and must never be killed while a
  non-zero command is in effect;
* keep a stop command stream alive for longer than any expected reply gap;
* treat loss of telemetry as a stop condition, not just a warning;
* on ROS 2 the `cmd_vel_timeout` watchdog covers the alive-process case only — it does not help
  if the process dies, which is exactly the failure seen here.

## Status

`BLOCKED` for odometry, TF `odom -> base_link`, localization, mapping and navigation, on both
systems. Needs hardware attention (vendor inspection / board replacement or a documented reset
procedure). Software-side work that does not need the controller continues.
