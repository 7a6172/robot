# 05 — Workflows: Real Robot

> **Status:** the real-robot branch is fully ported and mirrors ROS 1 behavior, but it has **not
> yet been exercised on hardware in the ROS 2 era** (per the audit report). Treat first runs as
> commissioning: verify e-stop and manual control before any autonomy.

## Hardware inventory

| Component | Interface | Endpoint / device |
|---|---|---|
| Motor controller | TCP | 192.168.100.100 : 23 |
| Chassis IO board (buttons, e-stop, BMS) | TCP | 192.168.100.100 : 26 |
| Front LiDAR (Bluesea 2D) | UDP | 192.168.100.101 → local port 6667 |
| Rear LiDAR (Bluesea 2D) | UDP | 192.168.100.102 → local port 6668 |
| Speaker | local audio | files in `~/openmover_robot/sounds/` |
| Robot PC | onboard | runs the same ROS 2 workspace |

Network: static **192.168.100.0/24** segment between robot PC and chassis devices.
The LiDARs can also run over serial UART (driver default `type: uart`, `/dev/ttyUSB0`,
custom baud via termios2; udev rule creates `/dev/LHLiDAR`), but the robot uses the UDP config
set in `bringup.launch.py`.

## Boot

```bash
source /opt/ros/jazzy/setup.bash && source install/setup.bash
ros2 launch openmover workload.launch.py system_mode:=1
```
What differs from simulation (`system_mode:=0`):

- Instead of Gazebo + `simulation_handler`: two `bluesea2_node` instances (front/rear,
  topics remapped to `openmover/hardware/lidar_forward/scan` / `…_rear/scan`),
  `motor_handler` (TCP driver, publishes `hardware/odom` from wheel odometry),
  `io_board_handler` (buttons/e-stop/BMS).
- `use_sim_time` is false everywhere; no `/clock` bridging.
- Map save/load path suffix becomes `real-world/` instead of `simulation/`
  (`~/openmover_robot/maps/real-world/`).
- Localization launch gets no initial-pose offsets (those come from SIM_AREAS in sim).

Everything else — HAL, mode servers, navigation, relocalization, auto-mapping, teleop, RViz,
rosbridge — is identical to simulation. **The `openmover/hardware/*` topics are the abstraction
boundary; all software above them is mode-agnostic.**

## Safety model

- **E-stop / button**: `io_board_handler` publishes `openmover/hardware/emergency` and
  `openmover/hardware/button` (Bool, transient_local). `reset_server_handler` subscribes:
  long-press/e-stop → cancel navigation & mapping → trigger relocalization.
- **Stop services**: `openmover/control/emergency/request` (motor_handler, real) and
  `openmover/control/stop/request` (simulation_handler, sim) — both `StopRequest`.
- **Velocity arbitration**: `openmover/control/cmd_vel_mode/request` switches
  manual (teleop) vs auto (navigation). The motor handler honors only the active source.
- **Battery**: BMS data on `openmover/hardware/bms` (voltage/SoC/current); low-battery
  threshold configured in `hardwares.yaml`; HAL self-test checks device availability at init.
- **Localization confidence**: `openmover/localization/confidence` (Float32, likelihood-field
  based); thresholds in config; low confidence should prompt relocalization before nav goals.

## Commissioning checklist (first real run)

1. Network: `ping 192.168.100.100/.101/.102` from the robot PC.
2. LiDARs: launch, check `ros2 topic hz /openmover/hardware/lidar/scan` (merged) and both raw
   scans; verify orientation (`inverted`/`reversed`/`zero_shift` params in bluesea2 if wrong).
3. Motors: manual teleop only; verify `hardware/odom` increases when pushed/teleoperated;
   test e-stop → `hardware/emergency` goes true.
4. Speaker: `PlaysoundRequest` with a file present in `~/openmover_robot/sounds/`.
5. Mapping session in a small area first; save map; then navigation mode on that map.
6. Relocalization at a known pose; compare returned `tf_map_to_base` against ground truth.

## bluesea2 driver quick reference

- Nodes: `bluesea2_node` (publishes), `bluesea2_node_client`
  (`ros2 run bluesea2 bluesea2_node_client start|stop <index>` / `switchZone …`).
- Motor services on the driver: `stop_motor` / `start_motor` / `switchZone_motor`.
- Scan assembly: full 360° circles from fan packets; incomplete circles dropped;
  angle window `[-π, π)` (`from_zero: false`); optional masks `mask1..8` (radians) to blank sectors.
- Debug logs: `logPath` default `/tmp/log`.
