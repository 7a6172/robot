# 02 — Runtime Architecture (Stack A: openmover)

## Layer model

```
┌────────────────────────────────────────────────────────────────────┐
│ workload.py            business-flow entry (runs cli.init+join)    │
│   └─ cli.py            user API: init/navto/move/reloc/playsound   │
│       └─ hal.py        orchestration: mode switching, maps, poses  │
│           └─ protocol.py  ROS proxy: node, service clients, flow   │
│                            state publisher (openmover/flow/*)      │
└────────────────────────────┬───────────────────────────────────────┘
                 service calls (openmover/server/*, /localization/*…)
┌────────────────────────────▼───────────────────────────────────────┐
│ MODE SERVERS (Python manager nodes, scripts/server/)               │
│  func_mode_server_handler      start/stop mapping & nav apps,      │
│                                save maps, swap RViz presets        │
│  localization_mode_server_handler  start/stop carto localization   │
│  nav_area_server_handler       pick & launch per-area nav strategy │
│  cartographer_server_handler   load pbstream per map name          │
│  reset_server_handler          button/e-stop → cancel + relocalize │
│        each spawns/kills `ros2 launch` subprocesses via            │
│        launch_manager.LaunchHandle (replaces ROS 1 roslaunch API)  │
└────────────────────────────┬───────────────────────────────────────┘
┌────────────────────────────▼───────────────────────────────────────┐
│ HANDLERS (the actual robot functionality)                          │
│  C++: motor_handler | simulation_handler | io_board_handler |      │
│       localization_handler | localization_confidence_handler |     │
│       navigation_handler | obstacle_handler | teleop_handler       │
│  Py:  speaker_handler.py | teleop_handler.py                       │
│  External: cartographer_ros, nav2_map_server, bluesea2,            │
│            ira_laser_tools, auto_mapping_handler,                  │
│            relocalization_2d_handler, ros_gz bridge/sim, rviz2     │
└────────────────────────────────────────────────────────────────────┘
```

**Call chain for any high-level command:**
`workload → cli → hal → protocol (ROS proxy node) → mode-server service → launch_manager →
sub-launch → handlers`. Example: `cli.navto()` → `hal.call_nav_to()` → service
`openmover/navigation/request` → `navigation_handler`.

## Launch hierarchy

```
workload.launch.py                     ← THE single entry point
└─ bootloader.launch.py                args: system_mode (0=sim,1=real, def 0),
   │                                        sim_area (def 1), enable_visualization (def true)
   ├─ func_mode_server_handler.py      (top mode server)
   ├─ rosbridge_server (port 8080)
   ├─ rviz2                            (preset swapped by func_mode_server)
   └─ hardwares/bringup.launch.py      args: system_mode, sim_area, use_sim_time
      ├─ ALWAYS: robot_state_publisher, joint_state_publisher,
      │          static TF base_link→lidar_link, speaker_handler,
      │          laserscan_multi_merger, obstacle_handler
      ├─ SIM (system_mode==0): gz_sim (worlds/simulation.world),
      │          ros_gz_bridge (gz_bridge.yaml), simulation_handler, teleop,
      │          ros_gz_sim `create` spawner (pose from SIM_AREAS[sim_area]),
      │          localization launch with init pose offsets
      └─ REAL (system_mode==1): 2× bluesea2_node
                 (192.168.100.101:6667 fwd, 192.168.100.102:6668 rear),
                 motor_handler, io_board_handler, localization launch, teleop

func_mode_server dynamically adds (via LaunchHandle):
├─ apps/mapping.launch.py        carto_mapping + auto_mapping_handler +
│                                navigation_handler + reset_server + loc_confidence
├─ apps/navigation.launch.py     → nav_area_server_handler →
│     apps/navigation/navigation.launch.py: navigation_handler + reset_server +
│                                localization_confidence + relocalization_2d_handler
├─ modules/mapping/map_server.launch.py   (nav2_map_server + lifecycle_manager)
└─ modules/localization/carto_localization_server.launch.py →
      carto_localization.launch.py  (cartographer_node + occupancy_grid_node +
                                     initialpose adapter, per pbstream)
```

## Topics (core stack; all under `openmover/`)

| Topic | Type | Pub → Sub |
|---|---|---|
| `hardware/odom` | PoseWithCovarianceStamped | motor/simulation_handler → localization_handler |
| `hardware/twist` | TwistWithCovarianceStamped | same |
| `hardware/motor_state/{left,right}` | openmover_msgs/MotorState | motor_handler |
| `hardware/button`, `hardware/emergency` | std_msgs/Bool (transient_local) | io_board_handler → reset_server |
| `hardware/bms` | openmover_msgs/BmsData (transient_local) | io_board_handler |
| `hardware/lidar_forward/scan`, `hardware/lidar_rear/scan` | LaserScan | bluesea2 (real) / gz bridge (sim) → merger |
| `hardware/lidar/scan` | LaserScan | laserscan_multi_merger → everything perception |
| `hardware/lidar/pointcloud` | PointCloud2 | laserscan_multi_merger |
| `hardware/odom_sim` | nav_msgs/Odometry | gz bridge (sim only) → simulation_handler |
| `control/cmd_vel` | Twist | navigation_handler → motor/simulation_handler |
| `control/cmd_vel_manual` | Twist | teleop_handler → motor/simulation_handler |
| `control/cmd_vel_sim` | Twist | simulation_handler → gz bridge (sim only) |
| `control/reset_state` | Bool | reset_server → hal/workload |
| `localization/odom`, `/pose`, `/twist`, `/odom_legacy` | pose/odom variants | localization_handler |
| `localization/pose_aft_mapped` | PoseWithCovarianceStamped | cartographer (remapped `tracked_pose`) |
| `localization/initialpose` | PoseWithCovarianceStamped | relocalization_2d_handler / RViz → localizer |
| `localization/confidence` | Float32 | localization_confidence_handler |
| `navigation/state` | openmover_msgs/NavToState (transient_local) | navigation_handler |
| `navigation/obstacle` | openmover_msgs/Obstacle | obstacle_handler → navigation_handler |
| `navigation/simple_goal` | PoseStamped | RViz goal tool → navigation_handler |
| `navigation/linear_path`, `global_planner/planner/plan`, `…/potential`, costmap topics | Path/OccupancyGrid | planner internals |
| `mapping/map` | OccupancyGrid | cartographer_occupancy_grid_node or nav2_map_server |
| `mapping/auto_mapping/state` | AutoMappingState (transient_local) | auto_mapping_handler |
| `flow/state` | openmover_msgs/FlowState (transient_local) | protocol.py → workload/UI |

## Services (core stack)

| Service | Type | Server |
|---|---|---|
| `server/set_func_mode` | WorkModeRequest | func_mode_server (modes: mapping / navigation / load-map / save_map) |
| `server/set_localization_mode` | WorkModeRequest | localization_mode_server |
| `server/set_nav_area` | WorkModeRequest | nav_area_server |
| `localization/cartographer/request` | WorkModeRequest | cartographer_server |
| `localization/initialpose/request` | relocalization_toolbox_msgs/InitialPoseRequest | localization_handler |
| `localization/direct/request` | openmover_msgs/DirectRequest | localization_handler |
| `localization/relocalization/request` | relocalization_toolbox_msgs/RelocalizationRequest | relocalization_2d_handler |
| `localization/relocalization/simple_request` | std_srvs/Empty | relocalization_2d_handler |
| `navigation/request` | openmover_msgs/NavToRequest | navigation_handler (cmds: nav_to / move / cancel) |
| `navigation/simple_request` | openmover_msgs/NavToSimpleRequest | navigation_handler |
| `navigation/global_planner/make_plan` | nav_msgs/GetPlan | navigation_handler |
| `control/cmd_vel_mode/request` | CmdVelModeRequest | motor_handler (real) / simulation_handler (sim) |
| `control/stop/request` | StopRequest | simulation_handler |
| `control/emergency/request` | StopRequest | motor_handler |
| `control/playsound/request` | PlaysoundRequest | speaker_handler |
| `mapping/write_state/request` | cartographer_ros_msgs/WriteState | cartographer_node |
| `mapping/auto_mapping/request` | auto_mapping_toolbox_msgs/AutoMappingRequest | auto_mapping_handler (cmds: start/cancel) |
| `flow/action`, `flow/cmd` | FlowAction / FlowCmd | protocol.py |

## TF tree

```
map ──(cartographer_node)──> odom ──(localization_handler)──> base_link ──(static)──> lidar_link
                                                                  │
                                                                  └─(robot_state_publisher, URDF)──>
                                                                       wheel_left/right_link,
                                                                       ball_*_link,
                                                                       lidar_forward/rear_link
```
- `map→odom`: cartographer (`map_frame=map`, `published_frame=odom`, `provide_odom_frame=false`).
- `odom→base_link`: localization_handler (suppressed in `direct_output` mode).
- In Stack B, slam_toolbox publishes `map→odom` and gz DiffDrive publishes `odom→base_link`.

## Sim vs real data paths (identical ROS-side contracts)

```
SIM:  control/cmd_vel → simulation_handler → control/cmd_vel_sim → gz bridge → Gazebo DiffDrive
      Gazebo odom_sim (nav_msgs/Odometry) → simulation_handler → hardware/odom + hardware/twist
REAL: control/cmd_vel → motor_handler (TCP, 192.168.100.100:23, computes wheel odometry)
      → hardware/odom + hardware/twist
Both: hardware/odom → localization_handler → odom→base_link TF + localization topics
      lidar_forward/rear scans → laserscan_multi_merger → hardware/lidar/scan
```
Everything above `hardware/*` is mode-agnostic — that is the abstraction boundary.

## Stack B (`warehouse_simulation`) node graph

```
gz_sim (worlds/warehouse.sdf) ── ros_gz_bridge (config/gz_bridge.yaml)
  /cmd_vel (ROS) ↔ /model/pioneer3dx/cmd_vel (GZ)     [entity name matters!]
  pioneer_odom→/odom, pioneer_tf→/tf, pioneer_joint_states→/joint_states, scan→/scan, /clock
robot_state_publisher (pioneer3dx.urdf.xacro)
slam_toolbox (online_async; 12 s activation timer guard)          → /map, map→odom TF
Nav2 navigation_launch (autostart; MPPI controller @20 Hz)
trajectory_server.py  (map→base_link TF → nav_msgs/Path on /trajectory)
cmd_vel_watchdog.py   (zero-velocity if /cmd_vel silent > 0.4 s; gz DiffDrive holds last cmd)
key_control (manual run) → /cmd_vel ; rviz2
```
TF in Stack B: gz DiffDrive → `odom→base_link` (50 Hz), slam_toolbox → `map→odom`,
robot_state_publisher → URDF frames (`laser` is the LiDAR frame).
