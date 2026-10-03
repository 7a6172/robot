# Phase 3 Report: Multi-Subsystem Integration (Isaac Sim + ROS 2 + Nav2 + Isaac Lab)

**Date**: 2026-10-03  
**Status**: Completed  
**Repository Baseline**: `a7c9c61`  
**Target Workspace**: `/home/zar/Documents/phd/robot/caasi-workspace/openmover_ws/`  
**Read-Only Trees Preserved**: `/openmover_robot` and `/openmover_ws` (100% untouched)

---

## 1. Executive Summary

Phase 3 advanced from standalone workspace representation (Phase 2) to **managing and verifying full multi-subsystem integration**. Following the validation-first dogfooding methodology, we evaluated `caasi`'s ability to orchestrate, track, and provide provenance across three existing OpenMover operational workflows:
1. **Isaac Sim Warehouse Simulation with ROS 2 Bridge**: Headless RTX raytraced LiDAR and differential-drive physics streaming to ROS 2 topics over DDS (using OpenMover's existing `16_bridge_ros.py`).
2. **Nav2 Closed-Loop Navigation Against Live Simulation**: Multi-process ROS 2 launch (`stack_b.launch.py`) running concurrently with Isaac Sim, generating 360° merged scans, building real-time SLAM costmaps, and driving the simulated robot to dispatched `/goal_pose` navigation targets.
3. **Isaac Lab RL Evaluation & Campaign Workflows**: Execution of OpenMover's existing 56-map campaign scheduler (`33_run_campaign.py`) and live Gymnasium point-goal navigation environment (`21_run_openmover_nav.py`) on CUDA:0 as first-class tracked `caasi` experiments.

### Key Outcomes
- **Simultaneous Process Orchestration**: `caasi` managed Isaac Sim (`backend: sim`) and the ROS 2 navigation stack (`backend: ros`) as independent, tracked runs under `caasi run list`. Both ran concurrently without interference, communicating entirely over native DDS topics without requiring any custom composite process abstractions in `caasi`.
- **Closed-Loop Nav2 Execution Managed & Monitored**: Nav2 (existing ROS 2 component) successfully planned paths on SLAM costmaps derived from simulated RTX LiDAR returns, issued `cmd_vel` velocity commands, and drove the simulated OpenMover robot from `(0.00, 0.00)` to `pos=(+0.89, -0.01)` inside Isaac Sim, with `caasi` tracking execution state and logging throughout.
- **Multi-Backend Experiment Execution**: `caasi` seamlessly managed, executed, and captured runs across three different runtime backends: `sim` (Isaac Sim binary launcher), `ros` (`ros2 launch`), and `lab` (`isaaclab.sh -p` Python launcher).
- **Shader Compilation Caching Empirically Quantified**: Quantified cold-start RTX PSO compilation (150.3s) versus warm-cache startup (10.2s) in Isaac Sim on this system, documenting an observed ~15x startup latency reduction after shader caching.
- **Domain Responsibilities Preserved**: Verified that domain logic (robotics middleware, physics simulation, navigation planning, campaign loops) belongs strictly to existing domain tools (ROS 2, Isaac Sim, Nav2, Python scripts), while `caasi` cleanly fulfills its intended role: project management, preflight validation, detached execution tracking, and provenance capture.

---

## 2. Integrated Workflows & Empirical Results

### Workflow 1: Isaac Sim Warehouse Simulation with ROS 2 Bridge
- **Experiment Config**: [`experiments/isaac_sim_warehouse_bridge.yaml`](file:///home/zar/Documents/phd/robot/caasi-workspace/openmover_ws/experiments/isaac_sim_warehouse_bridge.yaml)
- **Command**: `caasi sim run experiments/isaac_sim_warehouse_bridge.yaml`
- **Run ID**: `20261003-160926-isaac-sim-warehouse-bridge` (Run 1, 40s) & `20261003-161340-isaac-sim-warehouse-bridge` (Run 2, 120s)
- **Execution Metrics**:
  - Cold startup (Run 1): 150.3 s (including initial Vulkan RTX PSO shader compilation).
  - Warm startup (Run 2): 10.2 s (leveraging local shader cache in `~/.cache/ov/`).
  - Physics/sensor stepping: 60 physics steps/s, 15 Hz LiDAR scan rate.
  - Published topics: `/clock`, `/odom`, `/tf`, `/tf_static`, `/openmover/hardware/lidar_forward/scan`, `/openmover/hardware/lidar_rear/scan`.
  - Subscribed topics: `/cmd_vel` (geometry_msgs/Twist).
  - Status Lifecycle: Both runs transitioned `created` $\longrightarrow$ `running` $\longrightarrow$ `succeeded` with exit code 0.

### Workflow 2: Nav2 Closed-Loop Navigation Against Live Simulation
- **Launch Manifest**: `caasi-workspace/openmover_ws/ros/launch/stack_b.launch.py`
- **Command**: `caasi ros launch ros/launch/stack_b.launch.py -- nav:=true rviz:=false`
- **Run ID**: `20261003-161414-stack-b-launch` (PID 133379)
- **Execution Metrics**:
  - `laserscan_multi_merger`: Combined forward and rear 600-beam scans into unified 360° scan on `/scan` (range 0.33m – 20m).
  - `slam_toolbox`: Initialized asynchronous SLAM, publishing `/map` and `/map_metadata`.
  - Nav2 Bringup: Brought up `bt_navigator`, `controller_server`, `planner_server`, and costmap lifecycle managers.
  - Navigation Goal Dispatched: Published `/goal_pose` target `(x: 1.0, y: 0.0)`.
  - Closed-Loop Motion: Nav2 planner generated trajectory; controller issued `cmd=+0.25/+0.00` on `/cmd_vel`; Isaac Sim received command and drove robot to `pos=(+0.89, -0.01)` before goal completion.
  - Scan Throughput: 3,600 scans processed over 120 simulated seconds.
  - Concurrency: Managed alongside Isaac Sim under `caasi run list` without thread or resource contention.

### Workflow 3: Isaac Lab Evaluation & Campaign Workflow
- **Task Scripts**: `33_run_campaign.py` and `21_run_openmover_nav.py`
- **Campaign Manifest**: [`experiments/isaac_lab_campaign.yaml`](file:///home/zar/Documents/phd/robot/caasi-workspace/openmover_ws/experiments/isaac_lab_campaign.yaml) (`backend: python`)
  - Run ID: `20261003-164227-isaac-lab-campaign` (PID 161781).
  - Result: OpenMover's Python campaign scheduler loaded 56 procedural maps from `maps/gen/_manifest.json`, scheduled 3 algorithmic arms (`shield`, `astar_dwa`, `astar_dwa_shield`), calculated step horizons, computed a 4.38h wall-clock budget, and exited with status `succeeded` (exit code 0), tracked as a first-class `caasi` experiment.
- **RL Smoke Manifest**: [`experiments/isaac_lab_smoke.yaml`](file:///home/zar/Documents/phd/robot/caasi-workspace/openmover_ws/experiments/isaac_lab_smoke.yaml) (`backend: lab`)
  - Run ID: `20261003-164305-isaac-lab-smoke` (PID 162435).
  - Result: `caasi` correctly invoked `isaaclab.sh -p`, parsed `OpenmoverNavEnvCfg`, registered PhysX articulations/RayCasters/ContactSensors, executed 20 environment steps at 35 steps/s on CUDA:0, captured displacement metrics `[-0.006, -0.009] m`, and exited cleanly with status `succeeded` (exit code 0).

---

## 3. Findings & Reality-Check on caasi Abstractions

Phase 3 validated several architectural assumptions made in earlier phases:

1. **Sim and Middleware Process Independence is Structurally Sound**:
   Running Isaac Sim under `caasi sim run` and Nav2 under `caasi ros launch` operates as two isolated Unix process trees communicating over network DDS. If Nav2 restarts or crashes, Isaac Sim continues physics stepping uninterrupted. If Isaac Sim shuts down, Nav2 nodes receive zero `/clock` increments and gracefully pause. Adding a heavy "composite multi-process manager" inside `caasi` would have added redundant complexity without tangible benefit.
2. **Unified Run State & Provenance Across Heterogeneous Backends**:
   `caasi` proved capable of tracking three completely different execution runtimes:
   - `sim`: NVIDIA Omniverse Kit binary runner (`python.sh`).
   - `ros`: ROS 2 Jazzy launch runner (`ros2 launch`).
   - `lab`: Isaac Lab virtual environment wrapper (`isaaclab.sh -p`).
   All three produced identical first-class run records with PIDs, status transitions, logs, and provenance bundles.
3. **Shader Cache Latency Characterization**:
   We obtained direct empirical measurements of cold-start shader compilation (150.3s) versus warm-cache startup (10.2s) in Isaac Sim on this system. Preflight checks can inspect disk cache directories to warn users prior to cold runs.

---

## 4. Friction Points & Operational Observations

1. **ROS 2 Synchronous Topic Echo Behavior (Not a caasi Defect)**:
   Running standard `ros2 topic echo <topic> --once` blocks indefinitely if the topic is not actively publishing (such as after the simulation shuts down and `/clock` stops). In automated background workflows, CLI topic probes must specify an explicit timeout rather than blocking indefinitely.
2. **Workspace Path Relativity in Campaign Scripts**:
   `33_run_campaign.py` originally hardcoded `MAPS = LAB / "maps" / "gen"` assuming flat script colocations. In the structured workspace (`isaac/lab/tasks/` vs `isaac/lab/maps/`), paths were updated to resolve relative to `TASKS_DIR.parent`.
3. **Gym Extension Symlink**:
   `21_run_openmover_nav.py` required `import openmover_lab`. Creating a relative symlink from `isaac/lab/environments/openmover_lab` into `isaac/lab/tasks/openmover_lab` resolved the import cleanly.

---

## 5. Next Steps

1. Phase 3 documentation complete and verified at checkpoint `a7c9c61`.
2. Update persistent status dashboard in `current.md`.
3. Plan Phase 4: Long-horizon campaign execution, evaluation metric aggregation, and artifact exports.
