# OpenMover Project Inventory (Read-Only Audit)

## 1. Inventory Overview

This audit documents the complete state of the OpenMover robotics research project across the two source references:
- `/home/zar/Documents/phd/robot/openmover_ws` (ROS 2 Jazzy + Gazebo Harmonic + Isaac Sim 6.0 + Isaac Lab)
- `/home/zar/Documents/phd/robot/openmover_robot` (Legacy ROS 1 Noetic stack reference)

Both directories remain **STRICT READ-ONLY**.

---

## 2. ROS Packages Breakdown

### 2.1 ROS 2 Packages (`openmover_ws/src/`)

| Package Name | Type | Key Nodes / Executables | Purpose |
|---|---|---|---|
| `openmover` | C++ & Python | `motor_handler`, `io_board_handler`, `simulation_handler`, `localization_handler`, `localization_confidence_handler`, `navigation_handler`, `obstacle_handler`, `mover`, `path_follower`, `teleop_handler` | Core robot product stack: hardware abstraction layer (HAL), Cartographer 2D localization, product navigation controller (A* global planner, local pursuit/mover), teleop |
| `openmover_msgs` | ROS 2 Msg/Srv | Msg: `BmsData`, `MotorState`, `NavToSimple`, `NavToState`, `Obstacle`, `Pose`, `Twist`; Srv: `CmdVelModeRequest`, `DirectRequest`, `FlowAction`, `FlowCmd`, `NavToRequest`, `PlaysoundRequest`, `SelfTestReportRequest`, `StopRequest`, `WorkModeRequest` | Interface definitions for all core product communication (strictly uses services for commands, no actions) |
| `warehouse_simulation` | Python & C++ | `key_control`, `policy_node`, `trajectory_server`, `cmd_vel_watchdog` | Standalone warehouse reference simulation (Stack B) integrating Nav2, slam_toolbox, and pedestrian actors |
| `auto_mapping_toolbox` | C++ | `auto_mapping_handler` | Frontier exploration, collision prediction, and autonomous mapping algorithms |
| `relocalization_toolbox` | C++ | `relocalization_2d_handler` | 2D global relocalization via GICP, likelihood fields, and RRT submap set sampling |
| `relocalization_toolbox_msgs` | ROS 2 Srv | `InitialPoseRequest`, `RelocalizationRequest` | Service definitions for 2D relocalization |
| `bluesea2` | C++ | `bluesea2_node`, `bluesea2_node_client` | Hardware driver for dual 2D LiDAR sensors (LDS-50C / LDS-E300) |
| `ira_laser_tools` | C++ | `laserscan_multi_merger` | Merges two 2D LiDAR scans into a single combined scan topic |

### 2.2 ROS 1 Packages (`openmover_robot/openmover_ws/src/`)
Contains the original Noetic versions of the same packages:
`openmover`, `openmover_msgs`, `warehouse_simulation_toolkit`, `auto_mapping_toolbox`, `relocalization_toolbox`, `bluesea2`, `ira_laser_tools`.

---

## 3. Launch Files & Entry Points

### 3.1 Stack A (Core Product Stack)
- `openmover/launch/hardwares/bringup.launch.py`: Main hardware bringup (motor, io, lidar, simulation handler). Accepts `system_mode:="simulation"` or `"real"`, and `launch_gazebo:="0"` (for Isaac Sim).
- `openmover/launch/bootloader.launch.py`: Top-level orchestration running localization, navigation, and application flows.
- `openmover/launch/apps/mapping.launch.py`: Starts Cartographer SLAM.
- `openmover/launch/apps/navigation.launch.py`: Starts Cartographer pure localization + product navigation handler.
- `openmover/launch/apps/auto_mapping.launch.py`: Starts autonomous exploration.
- `openmover/launch/apps/relocalization.launch.py`: Starts global relocalization.

### 3.2 Stack B (Warehouse Nav2 Stack)
- `warehouse_simulation/launch/warehouse_simulation.launch.py`: Launches Gazebo Harmonic with warehouse world, Pioneer 3DX robot, Nav2 navigation stack, slam_toolbox, and RViz2.

---

## 4. Isaac Sim Simulation Architecture (`openmover_ws/isaac/`)

### 4.1 Headless Bridge Scripts (`isaac/scripts/`)
- `00_smoke_test.py`: Validates Isaac Sim headless import (`omni.isaac.kit.SimulationApp`).
- `10_import_urdf.py`: Converts robot URDF to USD asset.
- `11_verify_robot.py`: Tests joint drives and wheel kinematics.
- `12_lidar_setup.py`: Configures dual RTX LiDARs.
- `13_bridge_core.py`: Bridges clock, odometry, and joint state publishers.
- `14_build_simple_room.py` / `15_build_warehouse.py`: Procedural USD scene generators.
- `16_bridge_ros.py`: **Stack B Bridge**. Publishes `/scan`, `/odom`, `/clock`, `/tf`; subscribes to `/cmd_vel`.
- `16_stack_b.launch.py`: Launches ROS 2 Nav2 stack configured to connect to `16_bridge_ros.py`.
- `17_bridge_openmover.py`: **Stack A Bridge**. Ingests `openmover/control/cmd_vel_sim`; outputs `openmover/hardware/odom_sim`, dual raw scans, and `/clock`.
- `17_bridge_ros_custommap.py`: Bridge configured for procedural custom map evaluation.
- `common.py`: Shared infrastructure containing **RAM Guard** (`common.preflight()`: aborts if MemAvailable < 8 GB).

### 4.2 Simulation Assets & Scenes
- `isaac/assets/openmover_lab/robot_description/`: Imported USD robot description for OpenMover.
- `isaac/assets/pioneer3dx/pioneer3dx.urdf`: Pioneer 3DX robot description (used as second simulated embodiment).
- `isaac/scenes/warehouse.usda`: USD warehouse scene.
- `isaac/scenes/workcell_mesh.usdc`: Workcell collision mesh.
- `isaac/scenes/simple_room.usda`: Simple test room scene.

---

## 5. Isaac Lab Reinforcement Learning & Research Pipeline (`openmover_ws/isaac/lab/`)

### 5.1 Python Package (`openmover_lab/`)
- `openmover_nav_env.py`: Isaac Lab Gym environment (`DirectRLEnv`) with LiDAR observation space and velocity action space.
- `openmover_nav_cfg.py`: Environment configuration (observations, actions, rewards, domain randomization).
- `openmover_cfg.py`: Robot articulation and physics parameters.
- `openmover_terrains.py`: Terrain generator for custom obstacle maps.
- `rsl_rl_ppo_cfg.py`: RSL-RL PPO algorithm hyperparameter specifications.
- `cbf_lite.py`: Control Barrier Function implementation for collision avoidance constraints.
- `dob_lite.py`: Disturbance Observer for wheel friction / payload disturbance estimation.
- `shield_lite.py`: Safety shield combining CBF + DOB.
- `astar_dwa.py`: Classical A* + DWA expert algorithm used for demonstration collection.
- `geodesic_expert.py`: Geodesic navigation expert.

### 5.2 Training & Evaluation Scripts
- `21_run_openmover_nav.py`: Environment rollout / visualization.
- `22_train_openmover_nav.py`: Policy training via RSL-RL.
- `23_collect_openmover_demos.py`: Expert trajectory dataset collection.
- `24_bc_pretrain_openmover.py`: Behavioral Cloning pretraining.
- `25_dagger_openmover.py`: DAgger imitation learning loop.
- `26_render_topdown_video.py` / `29_render_3d_video.py`: Headless video rendering.
- `27_make_custom_map.py` / `31_gen_mazes.py`: Procedural map generation.
- `29_koopman_collect.py` / `30_koopman_fit.py`: Koopman operator dynamics model fitting.
- `32_check_shield_v7.py`: Shield verification tests.
- `33_run_campaign.py` / `34_aggregate_campaign.py`: Multi-seed evaluation campaign runner and aggregator.

### 5.3 Research Campaign Outputs & Checkpoints
- `isaac/lab/logs/rsl_rl/`: Multiple training runs with policy checkpoints (`model_*.pt`).
- `isaac/lab/logs/bc_demos/`: Pre-collected expert demonstration datasets (`demos_p100_v3.pt`, `railyard_demos_*.pt`).
- `isaac/lab/campaign/`: Validation results (`results.jsonl`, `summary.json`, `aggregate.json`, `heldout/`).
- `isaac/lab/maps/`: 2D JSON grid maps (`rooms.json`, `slalom.json`, `ring.json`, `serpentine.json`, `heldout.json`).

---

## 6. System & Hardware Dependencies

1. **Host OS**: Ubuntu 24.04 LTS (x86_64).
2. **Compute**: Intel i7-12700K (20 cores), 48 GB RAM (upgraded from 16 GB), NVIDIA GeForce RTX 3080 (10.0 GiB VRAM, driver 580.178, CUDA 13.0).
3. **Robotics Runtime**: ROS 2 Jazzy Jalisco (`/opt/ros/jazzy`), Cartographer ROS, slam_toolbox, nav2_bringup.
4. **Simulators**:
   - NVIDIA Isaac Sim `6.0.1-rc.7` (`/home/zar/isaacsim`) with bundled Python 3.12 (`~/isaacsim/python.sh`).
   - NVIDIA Isaac Lab (`/home/zar/isaaclab`).
   - Gazebo Harmonic (`gz-sim 8.x` via ROS 2 vendor package).
5. **Python Libraries (in Isaac Sim Python)**: PyTorch 2.10.0+cu128, RSL-RL, Gymnasium, OpenCV, NumPy.

---

## 7. Reusable Research Artifacts & Provenance

- **NMTE Framework (Neuro-Mathematical Transfer Engine)**:
  - Frozen policy core transferred across degraded dynamics and embodiment.
  - Disturbance Observer (`dob_lite.py`) estimating unmodeled dynamics.
  - Control Barrier Function (`cbf_lite.py`) guaranteeing safety envelopes.
- **Maps**: Real-world and simulation `.pbstream` Cartographer submaps in `openmover/maps_defaults/`.
- **Assets**: Pioneer 3DX and OpenMover URDF/Xacro/USD models and textures.
