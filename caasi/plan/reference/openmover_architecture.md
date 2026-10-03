# OpenMover Architecture Reference

## 1. Platform Physical & Kinematic Specifications

- **Chassis**: Pioneer 3DX class differential-drive mobile base with dual passive casters.
- **Actuation**: Two driven wheels with independent velocity control.
  - Track width / wheelbase: 0.38 m (OpenMover) / 0.32 m (Pioneer 3DX).
  - Wheel radius: 0.0825 m (OpenMover) / 0.09 m (Pioneer 3DX).
- **Sensors**:
  - Two 2D LiDARs: Bluesea2 LDS-50C / LDS-E300 mounted front and rear to achieve 360° coverage without blind spots.
  - Wheel encoders: Publishes odometry at 20–50 Hz.
  - Battery Management System (BMS): Publishes battery voltage, current, state of charge.
- **Compute**:
  - Onboard robot PC: Low-power edge PC (laptop-class), running ROS 2 Jazzy.
  - Development host PC: Intel i7-12700K (20 threads), RTX 3080 10 GB VRAM, 48 GB RAM, Ubuntu 24.04.

---

## 2. Dual-Stack Architecture

OpenMover contains two parallel, complete software stacks:

### 2.1 Stack A: Core Product Stack (`openmover`)
- **Philosophy**: Commercial AMR architecture with custom navigation, formal safety handling, and production-grade Cartographer localization.
- **Interface Protocol**: Strictly uses **ROS 2 services** for commands (no action servers).
- **Hardware Abstraction Layer (HAL)**: Python and C++ handlers (`motor_handler`, `io_board_handler`, `simulation_handler`) abstracting physical actuators from logical controllers.
- **Localization**: Google Cartographer 2D in pure-localization mode using pre-built `.pbstream` submaps.
- **Navigation Controller**:
  - Global Planner: Grid-based A* with quadratic smoothing and costmap inflation.
  - Local Pursuit (`mover` / `path_follower`): Lookahead pursuit controller tracking global polylines with curvature-constrained velocity profile.
  - Obstacle Handler (`obstacle_handler` / `path_checker`): Laser-scan obstacle projection checking forward stopping distances.
- **Key Namespaces**: All topics/services are organized under `openmover/...`:
  - `openmover/hardware/*` (raw odometry, lidar, BMS)
  - `openmover/control/*` (`cmd_vel`, `cmd_vel_sim`)
  - `openmover/localization/*` (Cartographer pose, confidence score)
  - `openmover/navigation/*` (global plan, goal requests, local pursuit)
  - `openmover/flow/*` (mission state machine)

### 2.2 Stack B: Warehouse Reference Stack (`warehouse_simulation`)
- **Philosophy**: Standard ROS 2 community stack integrating standard Navigation2 (Nav2) and `slam_toolbox`.
- **World**: Multi-room warehouse simulation world with dynamic pedestrian actors.
- **Interface Protocol**: Uses standard ROS 2 topics (`/cmd_vel`, `/odom`, `/scan`, `/tf`) and standard Nav2 action interfaces (`NavigateToPose`).

---

## 3. Coordinate Frames & TF Tree

The TF coordinate frame hierarchy:
```text
map
 └── odom
      └── base_footprint
           └── base_link
                ├── front_laser_link
                ├── rear_laser_link
                ├── left_wheel_link
                └── right_wheel_link
```
- In Stack A, `map -> odom` is published by Cartographer (`localization_handler`).
- `odom -> base_link` is published by the motor/odometry driver (`simulation_handler` in sim, `motor_handler` on hardware).

---

## 4. Isaac Sim ROS 2 Bridge Architecture

Isaac Sim serves as the physics and sensor simulation backend for both stacks without modifying ROS node source code:

```text
Isaac Sim 6.0 (omni.isaac.kit.SimulationApp)
  │
  ├── Physics Loop (PhysX 60 Hz)
  ├── Dual RTX LiDAR Sensors (15 Hz)
  │
  └── In-Process ROS 2 Bridge (rclpy via python.sh)
        │
        ├── Stack A Bridge (17_bridge_openmover.py)
        │     Subscribes: openmover/control/cmd_vel_sim
        │     Publishes:  openmover/hardware/odom_sim, dual scans, /clock
        │
        └── Stack B Bridge (16_bridge_ros.py)
              Subscribes: /cmd_vel
              Publishes:  /odom, /scan, /clock, /tf
```

### Key Technical Conventions:
1. **In-process rclpy**: The bridge script imports `rclpy` directly within Isaac Sim's Python process (`~/isaacsim/python.sh`). There is no external bridge process.
2. **Spin Model**: `rclpy` has no `spin_some`; the bridge executes `rclpy.spin_once(node, timeout_sec=0)` inside each physics step.
3. **Pacing**: Physics step is paced to real-time clock to prevent ROS subscriber queue overflow.
4. **Rendering Gate**: Camera and LiDAR rendering are gated to the sensor tick rate (15 Hz) rather than physics frequency (60 Hz) to conserve GPU compute.

---

## 5. Machine Constraints & Concurrency Rules

- **RAM Constraint**: Memory exhaustion caused hard freezes during initial experiments.
- **RAM Guard**: All Isaac simulation scripts invoke `common.preflight()` before instantiating `SimulationApp`:
  - `MemAvailable < 8.0 GiB`: Immediately abort with error.
  - `MemAvailable < 12.5 GiB`: Issue warning.
- **Single-Simulator Invariant**: Never launch more than one instance of Isaac Sim or Gazebo simultaneously on the same workstation.
- **Parallelism Rule**: All compilation tasks must use `-j2` (`MAKEFLAGS="-j2" CMAKE_BUILD_PARALLEL_LEVEL=2`).
