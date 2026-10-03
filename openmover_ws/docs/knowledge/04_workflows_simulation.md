# 04 — Workflows: Simulation

Two independent simulation environments exist. **Environment A** = the robot core stack in its own
sim world (`openmover` with `system_mode:=0`). **Environment B** = the warehouse demo
(`warehouse_simulation`). Both use Gazebo Harmonic.

**Always first, in every terminal:**
```bash
source /opt/ros/jazzy/setup.bash
cd /home/zar/Documents/phd/robot/openmover_ws
source install/setup.bash
```

## Environment B — warehouse demo (quick, modern-stack)

```bash
ros2 launch warehouse_simulation warehouse_simulation.launch.py        # gz + slam + Nav2 + rviz
ros2 run warehouse_simulation key_control                              # in a 2nd terminal
```
- Keymap: **UP** forward (+0.7·2.0), **DOWN** reverse (−0.7·2.0, deliberate improvement — ROS 1
  had no reverse), **LEFT/RIGHT** rotate, **q** quit. Commands repeat while a key is held
  (20 Hz; needs OS key-repeat on); robot auto-stops on release.
- Variants: `headless:=true` (server-only, view via streaming), `rviz:=false`,
  spawn pose `x_pos:=… y_pos:=…`.
- Mapping happens automatically (slam_toolbox async); Nav2 goals via RViz "2D Goal Pose"
  → MPPI controller. Pedestrians: two walking actors cross the aisles; the LiDAR sees their feet,
  costmap stops the robot, resumes when clear (no simulation-only machinery — perception-based).
- Inspect: `ros2 topic hz /scan`, `ros2 topic echo /cmd_vel`, `ros2 topic echo /trajectory`,
  `ros2 run tf2_tools view_frames`.
- Tests: `colcon test --packages-select warehouse_simulation && colcon test-result --verbose`.

## Environment A — robot core stack in simulation

### Boot

```bash
ros2 launch openmover workload.launch.py system_mode:=0
```
Launch args: `system_mode` (0=sim), `sim_area` (default 1; selects spawn pose from the SIM_AREAS
table in bringup), `enable_visualization` (default true, opens RViz2).
This starts Gazebo (`src/openmover/worlds/simulation.world`), the gz bridge,
`simulation_handler`, teleop, the func-mode server, rosbridge (8080), RViz.

### Drive it

Keyboard teleop (pynput) starts with bringup; commands go to `openmover/control/cmd_vel_manual`.
Joystick alternative via `openmover/control/joy` (sensor_msgs/Joy). Manual/auto arbitration:
service `openmover/control/cmd_vel_mode/request` (CmdVelModeRequest, `true`=manual).

### The HAL workflow (what workload.py does and how to script it)

`workload.py` runs `cli.init(reloc=True)` + `join()`. The HAL (`scripts/hal/`) is the scripted
operator API — in custom scripts: `from cli import *` (installed into lib/openmover). Steps:

1. **Initialize** — `init(mode='nav_to'|'create_map', try_relocalization=True)`:
   self-test → set function mode (`openmover/server/set_func_mode`) → set area strategy →
   apply map → relocalize (or manual pose) → set velocity mode.
2. **Mapping session** — `auto_mapping()` starts frontier exploration
   (`openmover/mapping/auto_mapping/request`, cmd `start`); watch
   `openmover/mapping/auto_mapping/state` until `finish`; then `create_map('name')` saves to
   `~/openmover_robot/maps/simulation/<name>{.pgm,.yaml}` + Cartographer state via the
   func-mode server (`save_map`). Cancel: `cancel_auto_mapping()`.
3. **Navigation session** — load map (func mode `load_map` with map name) → localization mode
   carto → `navto(x, y, yaw)` via `openmover/navigation/request`
   (or `simple_request` with NavToSimple) → watch `openmover/navigation/state` (NavToState);
   `move(...)` for relative moves; cancel via the same service.
4. **Relocalize** — `reloc()` → `openmover/localization/relocalization/simple_request`;
   full control via `relocalization_request` (mode 0 map-from-topic / 1 from-file).
5. **Flow state** — everything publishes `openmover/flow/state` (FlowState); remote control via
   `openmover/flow/action` and `flow/cmd`, also reachable through rosbridge on port 8080.
6. **Reset** — long-press of the physical button / emergency topic triggers
   `reset_server_handler`: cancels nav/mapping and relocalizes.

### Useful probes

```bash
ros2 service call /openmover/localization/relocalization/simple_request std_srvs/srv/Empty {}
ros2 topic echo /openmover/flow/state
ros2 topic echo /openmover/navigation/state
ros2 topic echo /openmover/localization/confidence
ros2 service call /openmover/control/playsound/request openmover_msgs/srv/PlaysoundRequest \
     "{filename: 'startup.wav', loop_times: 1}"        # sounds from ~/openmover_robot/sounds/
```

## Resource safety rules (this machine has frozen twice)

- Build only with `MAKEFLAGS="-j2" CMAKE_BUILD_PARALLEL_LEVEL=2 colcon build --symlink-install --parallel-workers 2`.
- Kill stray simulators before launching a new one: `pgrep -af 'gz sim|ruby'`.
- Prefer `headless:=true` for long runs; never run both sim environments at once.
- The setup wizard automates environment checks: `bash tools/setup.sh` (or `--check`).

## Known simulation behaviors / quirks

- gz DiffDrive **holds the last cmd_vel forever** → Stack B runs `cmd_vel_watchdog` (0.4 s);
  Stack A's simulation_handler + teleop publish explicit zeros.
- The gz bridge config fixes the entity name: Stack B's bridge topics use
  `/model/pioneer3dx/cmd_vel` — renaming the spawned entity breaks control.
- Pedestrian actors have **no collision bodies** in gz Harmonic; everything is perception-based.
- Cartographer in ROS 2 has no initialpose topic → `cartographer_initialpose_adapter.py`
  translates it to finish/start-trajectory service calls. Do not "fix" this away.
- slam_toolbox lifecycle node sometimes needs a nudge; the launch file has a 12 s timer that
  activates it if still `inactive` (this guarantees `map→odom` TF).
