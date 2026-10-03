# 03 — Package Reference (all 9 colcon packages)

## 1. `openmover` — robot core (Stack A)

License `private`; maintainer zar; original author ZHANG Muhua (ROS 1).

**C++ executables** (`*_handler` convention):

| Executable | Role |
|---|---|
| `io_board_handler` | Chassis IO-board driver (TCP :26): buttons, e-stop, BMS; monitors pose/confidence/obstacles |
| `motor_handler` | Real motor driver (TCP 192.168.100.100:23): odom/twist/motor states, e-stop & cmd-vel-mode services |
| `simulation_handler` | Sim chassis: bridges `cmd_vel` → Gazebo, converts sim odom → hardware odom/twist |
| `localization_handler` | Fuses odom + mapped pose; publishes odom/pose/twist; broadcasts `odom→base_link`; init-pose/direct services |
| `localization_confidence_handler` | Likelihood-field localization confidence → Float32 |
| `navigation_handler` | Main motion controller: global+local planning (in-process nav2_costmap_2d + custom planner), collision check, nav services |
| `obstacle_handler` | Merged scan → `openmover_msgs/Obstacle` grid |
| `teleop_handler` | Joystick (sensor_msgs/Joy) teleop → `cmd_vel_manual` (keyboard Python version is the one launched) |

**Python executables**: `speaker_handler.py` (pygame sounds), `teleop_handler.py` (pynput keyboard),
`workload.py` (business-flow entry), `func_mode_server_handler.py`,
`localization_mode_server_handler.py`, `nav_area_server_handler.py`, `reset_server_handler.py`,
`cartographer_server_handler.py`, `cartographer_initialpose_adapter.py` (ROS 2 cartographer dropped
the initialpose topic; this adapter maps it to finish/start-trajectory services).

**Python libraries** (installed into lib/openmover): `launch_manager.py`
(`LaunchHandle`: spawns/kills `ros2 launch` subprocesses in process groups) and
`hal/` package: `hal.py` (orchestration), `cli.py` (user API), `protocol.py` (ROS proxy),
`config.py`, `symbols.py`, `logger.py`, `utils.py`.

**HAL 5-step initialization** (`hal.initialize`): switch function mode → switch area strategy →
apply map → apply pose / call relocalization → switch velocity mode. CLI exposes
`init / navto / move / reloc / auto_mapping / create_map / playsound / uninitialize`.

**Shipped resources**: `config_defaults/` (hardwares.yaml, modules.yaml, gz_bridge.yaml,
apps/{mapping,navigation}/*.yaml+*.lua, rviz presets), `maps_defaults/simulation/`
(navigation.{pbstream,pgm,yaml}), `worlds/simulation.world`, `urdf/{robot,environment}_description.urdf`,
`meshes/`.

## 2. `openmover_msgs` — core interfaces

License `private`. **msg**: `BmsData`, `FlowState`, `MotorState`, `NavToSimple`, `NavToState`,
`Obstacle`, `Pose` (x,y,z,roll,pitch,yaw), `Twist`. **srv**: `CmdVelModeRequest`, `DirectRequest`,
`FlowAction`, `FlowCmd`, `NavToRequest`, `NavToSimpleRequest`, `PlaysoundRequest`,
`SelfTestReportRequest`, `StopRequest`, `WorkModeRequest` (mode, cmd, params → result string).

## 3. `auto_mapping_toolbox` (+ `auto_mapping_toolbox_msgs`) — autonomous mapping

License GPL-3.0; authors ZHANG Muhua + zar port. Node: **`auto_mapping_handler`**.

- **Service**: `auto_mapping/request` (AutoMappingRequest: cmd "start"/"cancel",
  waypoint_retracing) → "ok"/"busy"/"error". **State topic**: `auto_mapping/state`
  (AutoMappingState: state string + mapped area, transient_local).
- **State machine**: FIRST_ROTATION (360° spin) → FIND_LOCAL_FRONTIER_POINTS (local RRT) →
  LOCAL/GLOBAL_NAVIGATION (frontier scoring: info/free/dist/dir gains; polyline planning with
  ported navfn-style planner + OSQP smoother; waypoint nav via openmover `navigation/request`;
  collision precheck) → BACK_TO_ORIGIN_NAVIGATION (TSP-ordered backtracking) →
  FIND_GLOBAL_FRONTIER_POINTS (global RRT, memory-limited) → MAPPING_FINISH ("please save the map").
- Embeds a nav2 `Costmap2DROS` fed from `openmover/mapping/map` (hardcoded topic).
- Consumes: `map`, `navigation/state`; calls: `navigation/request`, `cmd_vel_mode/request`.
- Config: `config/config.yaml`; runtime values overridden by openmover `mapping.yaml`.

## 4. `relocalization_toolbox` (+ `relocalization_toolbox_msgs`) — global relocalization

License GPL-3.0; authors ZHANG Muhua + zar port. Node: **`relocalization_2d_handler`**
(MultiThreadedExecutor + reentrant callback group: the service callback does nested synchronous waits).

- **Services**: `relocalization_request` (mode 0=map-from-topic / 1=map-from-file, path, name →
  result "ok"/"error"/"busy" + `tf_map_to_base` + score) and `relocalization_simple_request` (Empty).
- **Client**: `set_init_pose_request` (InitialPoseRequest) when `call_init_pose_request: true`.
- **Pipeline**: grab fresh scan (2 s) + map (topic 5 s / file) → obstacle distance field →
  RRT reachability sampling → submap partitioning & coarse ranking (OpenMP) → batched angular
  likelihood-field search → GICP refinement of top candidates → score thresholds
  (`fit_score_threshold_max 0.95` early-stop, `min 0.85` success) → result as `map→base_link`,
  published on `initialpose` and/or handed to localization service.
- Debug viz: `submaps`, `submap_anchor_points`, `transformed_beam_points`.
- Config: `config/config_2d.yaml` (frames, RRT params, sigma_hit/z_hit, ICP limits);
  openmover overrides via `navigation.yaml` `relocalization_2d:` section.
- Map file format: classic map_server pair `<name>.yaml` + `<name>.pgm` (OpenCV-read, v-flipped).

## 5. `warehouse_simulation` — Stack B demo/research sandbox

License BSD; original author Wang Han (`warehouse_simulation_toolkit`); zar port.

- **Launch**: `warehouse_simulation.launch.py` (args: `use_sim_time` def true, `rviz` def true,
  `headless` def false, `x_pos/y_pos/z_pos`). Starts: gz_sim (`worlds/warehouse.sdf`),
  robot_state_publisher (xacro), ros_gz_bridge, spawns entity `pioneer3dx`, slam_toolbox
  (online_async + 12 s activation timer), Nav2 (autostart), trajectory_server, cmd_vel_watchdog, rviz2.
  `key_control` is NOT auto-launched.
- **World** `warehouse.sdf`: workcell mesh + explicit box collisions (walls, racks, pallets,
  poles, control panel), 6 trash bins, sun/ground. Two pedestrian `<actor>`s (no collision body —
  perceived via LiDAR): actor1 y=−4, 60 s loop; actor2 y=+4, 80 s loop; waypoint z raised to 1.0
  for gz Harmonic actor anchor (deliberate port fix).
- **Robot** `urdf/pioneer3dx.urdf.xacro`: 40 kg base, DiffDrive plugin (wheel sep 0.32, r 0.09,
  accel limits 3.0, odom topic `pioneer_odom`, TF `pioneer_tf`), gpu_lidar on link `laser`
  (360 samples, 0.12–10 m, 5 Hz, noise σ 0.008), sonar meshes are visual-only, `imu_link` exists
  but no IMU sensor.
- **key_control** (C++): UP ±0.7·scale forward/reverse (reverse is a deliberate improvement;
  ROS 1 had `-0.0`), LEFT/RIGHT ±0.3·scale; hold-to-drive at 20 Hz (OS key-repeat), auto-stop
  after 0.6 s silence, zero-twist on exit/SIGINT. Params `scale_linear/angular` def 2.0.
- **cmd_vel_watchdog.py**: re-publishes zero Twist if `/cmd_vel` silent > 0.4 s (gz DiffDrive
  holds the last command forever).
- **trajectory_server.py**: map→base_link TF → nav_msgs/Path on `/trajectory` @10 Hz.
- **Tests** (6 pytest): static YAML validation of nav2/slam/bridge configs; functional
  trajectory_server test. Run: `colcon test --packages-select warehouse_simulation`.

## 6. `bluesea2` — Lanhai/Bluesea 2D LiDAR driver (manual port)

License: vendor never declared one (`TODO: License declaration` kept as-is); author Bluesea
Technology + zar port. Nodes: **`bluesea2_node`** (node name `bluesea2_laser_publisher`),
**`bluesea2_node_client`** (start/stop/switchZone CLI).

- Publishes LaserScan on `topic` (def `scan`; up to 8 lidars via `topic2..`), optional
  PointCloud2 on `cloud_topic`. Services: `stop_motor`, `start_motor`, `switchZone_motor`.
- Connection types: `uart` (def; serial 8N1 raw, custom baud via termios2 BOTHER, def 500000),
  `udp`, `tcp`, `vpc` (binary framed over serial). In the real robot, two UDP lidars:
  192.168.100.101/.102 → local ports 6667/6668.
- Key params: `inverted`, `reversed`, `zero_shift`, `from_zero`, angle masks `mask1..8`,
  filter (`filter_open`, min/max range), resampling/smoothing device commands.
- udev rules (`src/LHLiDAR.rules`): CH340/CP210x → `/dev/LHLiDAR` symlink, mode 0666.
- Assembles full 360° circles from fan packets; drops incomplete circles.

## 7. `ira_laser_tools` — multi-LiDAR merger (upstream package, ported)

License BSD; upstream authors Augusto/Pietro/Fabio (unimib); zar port. Node:
**`laserscan_multi_merger`** (PCL dependency removed vs upstream). Subscribes to space-separated
`laserscan_topics` list, transforms each scan into `destination_frame` (tf2), publishes merged
PointCloud2 (`cloud_destination_topic`) + re-binned LaserScan (`scan_destination_topic`,
min-range-per-bin). In openmover: merges front+rear bluesea scans into
`openmover/hardware/lidar/scan`.

## Dependency graph

```
openmover ──> openmover_msgs, auto_mapping_toolbox_msgs, relocalization_toolbox_msgs,
              cartographer_ros, nav2_{map_server,lifecycle_manager,costmap_2d,util},
              bluesea2, ira_laser_tools, ros_gz_{sim,bridge}, tf2, PCL, OpenCV
auto_mapping_toolbox ──> openmover_msgs, nav2_costmap_2d, nav2_util, OSQP (system)
relocalization_toolbox ──> PCL (GICP), OpenCV (map IO), OpenMP
warehouse_simulation ──> ros_gz, slam_toolbox, nav2_*, xacro (independent of Stack A)
```
