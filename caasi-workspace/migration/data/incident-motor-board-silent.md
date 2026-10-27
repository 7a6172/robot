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

## Follow-up investigation (2026-10-27, after a full power removal)

The operator fully removed power and restarted the system in a fresh state. The controller
still does not respond. Further evidence, all collected after that power cycle:

| check | result |
| --- | --- |
| ping / ARP | `1.4 ms`, `REACHABLE` |
| hosts on `192.168.100.0/24` | only `.10` (robot) and `.100` (board) — address unchanged |
| ARP MAC | `00:04:a3:00:29:79` — Microchip OUI, typical of an embedded Ethernet module |
| TCP 23 / 1234 / 8000 | timeout |
| UDP 23 with 8 frame variants (acc ∈ {0,255}, byte7 ∈ {0x00,0xFF}, both motor IDs), CRC verified against the driver table | **0 replies** |
| UDP 26 (screen) and subnet broadcast on both ports | **0 replies** |
| **ROS 1 command frames actually transmitted** | **732 datagrams** during a 7 s test (counted from `/proc/net/snmp`) — so commands do reach the board |
| wheel response to 0.06 m/s and 0.15 m/s, both directions, wheels free | **none** (operator watched closely) |
| screen (port 26) after five text frames | unchanged, still the usual QR image |
| serial console | none: only Bluetooth and root hubs on USB |

Interpretation: the board's Ethernet side answers ping but **no application protocol runs on
either port**, and its screen (a second UDP service on the same board) also does not react. So
this is not a motor-channel fault and not an odometry fault — the board's application is not
processing packets. The motors themselves are probably undamaged; they simply cannot be driven
or measured until the controller runs again.

The green LED on the controller blinking is consistent with an MCU that is powered while its
link to the Ethernet module is down — which would explain "ping works, protocol does not"
exactly. That is a hypothesis from the evidence, not a measurement.

### Correction to the earlier attribution

An earlier note implied the U24 stack might have caused the spin. It cannot have: the ROS 2
`motor_handler` send path forces `speed_rpm = 0` whenever `!actuation_permitted()`
(`motor_handler.cpp`, the boundary guard immediately before `sendto`), so a gate-closed run
transmits only zeros, which the code and the 732-frame measurement both support. The latched
motion most plausibly came from the ROS 1 side, where `motor_node` has no watchdog, and
persisted until the operator powered the robot down.

### What software can no longer do

Nothing further: frames are proven to arrive, in a verified-correct format, on the direct
address, the broadcast address, and on both service ports. Stopping here is a hardware
decision, not a software one.
