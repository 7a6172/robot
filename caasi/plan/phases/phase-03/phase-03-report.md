# Phase 3 Report: Multi-Subsystem Integration (Isaac Sim + ROS 2 + Nav2 + Isaac Lab)

**Date**: 2026-10-03  
**Status**: Completed  
**Repository Baseline**: `497024d`  
**Target Workspace**: `/home/zar/Documents/phd/robot/caasi-workspace/openmover_ws/`  
**Read-Only Trees Preserved**: `/openmover_robot` and `/openmover_ws` (100% untouched)

---

## 1. Executive Summary

Phase 3 advanced from standalone workspace representation (Phase 2) to **full multi-subsystem integration and execution**. Following the validation-first dogfooding methodology, we exercised `caasi` across the three targeted operational workflows of OpenMover:
1. **Isaac Sim Warehouse Simulation with ROS 2 Bridge**: Headless RTX raytraced LiDAR and differential-drive simulation bridging physics to ROS 2 topics over DDS.
2. **Nav2 Closed-Loop Navigation Against Live Simulation**: Multi-process ROS 2 launch (`stack_b.launch.py`) running concurrently with Isaac Sim, generating 360° merged scans, building real-time SLAM costmaps, and driving the simulated robot to dispatched `/goal_pose` navigation targets.
3. **Isaac Lab RL Evaluation & Campaign Workflows**: First-class experiment execution of the 56-map, 3-arm campaign scheduler (`33_run_campaign.py`) and live PhysX Gym point-goal navigation environment (`21_run_openmover_nav.py`) on CUDA:0.

### Key Outcomes
- **Simultaneous Process Orchestration**: Executed Isaac Sim (`backend: sim`) and the ROS 2 navigation stack (`backend: ros`) as independent, tracked runs under `caasi run list`. Both ran concurrently without interference, communicating entirely over native DDS topics.
- **Closed-Loop Nav2 Execution**: Nav2 successfully planned paths on SLAM costmaps derived from simulated RTX LiDAR returns, issued `cmd_vel` velocity commands, and drove the OpenMover robot from `(0.0, 0.0)` to `(0.89, -0.01)` inside Isaac Sim.
- **Multi-Backend Experiment Execution**: `caasi` seamlessly executed and captured runs across three different backends: `sim` (Isaac Sim binary launcher), `ros` (`ros2 launch`), and `lab` (`isaaclab.sh -p` Python launcher).
- **Shader Compilation Caching Empirically Verified**: Quantified cold-start RTX PSO compilation (150.3s) versus warm-cache startup (10.2s) in Isaac Sim.
- **Empirical Case Study Evidence Preserved**: Captured complete evidence narratives in `caasi/plan/phases/phase-03/case_studies.md` with zero speculative claims.

---

## 2. Integrated Workflows & Empirical Results

### Workflow 1: Isaac Sim Warehouse Simulation with ROS 2 Bridge
- **Experiment Config**: [`experiments/isaac_sim_warehouse_bridge.yaml`](file:///home/zar/Documents/phd/robot/caasi-workspace/openmover_ws/experiments/isaac_sim_warehouse_bridge.yaml)
- **Command**: `caasi sim run experiments/isaac_sim_warehouse_bridge.yaml`
- **Run ID**: `20261003-160926-isaac-sim-warehouse-bridge` (Run 1, 40s) & `20261003-161340-isaac-sim-warehouse-bridge` (Run 2, 120s)
- **Execution Metrics**:
  - Cold startup (Run 1): 150.3 s (including initial Vulkan RTX PSO shader compilation).
  - Warm startup (Run 2): 10.2 s (leveraging local shader cache).
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
  - Run ID: `20261003-164227-isaac-lab-campaign` (PID 161781)
  - Result: Loaded 56 procedural maps, scheduled 3 algorithmic arms (`shield`, `astar_dwa`, `astar_dwa_shield`), calculated step horizons, computed 4.38h wall-clock budget, and exited with status `succeeded` (exit code 0).
- **RL Smoke Manifest**: [`experiments/isaac_lab_smoke.yaml`](file:///home/zar/Documents/phd/robot/caasi-workspace/openmover_ws/experiments/isaac_lab_smoke.yaml) (`backend: lab`)
  - Run ID: `20261003-164305-isaac-lab-smoke` (PID 162435)
  - Result: Correctly invoked `isaaclab.sh -p`, parsed `OpenmoverNavEnvCfg`, registered PhysX articulations/RayCasters/ContactSensors, executed 20 environment steps at 35 steps/s on CUDA:0, captured displacement metrics `[-0.006, -0.009] m`, and exited cleanly with status `succeeded` (exit code 0).

---

## 3. Findings & Reality-Check on caasi Abstractions

Phase 3 validated several architectural assumptions made in earlier phases:

1. **Separation of Sim and Middleware Processes is Strictly Superior**:
   Running Isaac Sim under `caasi sim run` and Nav2 under `caasi ros launch` operates as two isolated Unix process trees communicating over network DDS. If Nav2 restarts or crashes, Isaac Sim continues physics stepping uninterrupted. If Isaac Sim shuts down, Nav2 nodes receive zero `/clock` increments and gracefully pause. Adding a heavy "composite multi-process manager" inside `caasi` would have added unnecessary complexity without tangible benefit.
2. **Unified Run State & Provenance Across Heterogeneous Backends**:
   `caasi` proved capable of tracking three completely different execution runtimes:
   - `sim`: NVIDIA Omniverse Kit binary runner (`python.sh`).
   - `ros`: ROS 2 Jazzy launch runner (`ros2 launch`).
   - `lab`: Isaac Lab virtual environment wrapper (`isaaclab.sh -p`).
   All three produced identical first-class run records with PIDs, status transitions, logs, and provenance bundles.
3. **Shader Cache Latency Characterization**:
   We obtained direct empirical measurements of cold-start shader compilation (150.3s) versus warm-cache startup (10.2s) in Isaac Sim. Preflight checks can verify disk cache directories to warn users before cold runs.

---

## 4. Friction Points & Workarounds

1. **Synchronous Topic Echo Blocking**:
   Running `ros2 topic echo <topic> --once` without a publisher or when a publisher has stopped blocks indefinitely. In background automated tasks, this requires explicit process timeouts.
2. **Workspace Path Relativity in Campaign Scripts**:
   `33_run_campaign.py` originally hardcoded `MAPS = LAB / "maps" / "gen"` assuming flat script colocations. In the structured workspace (`isaac/lab/tasks/` vs `isaac/lab/maps/`), paths were updated to resolve relative to `TASKS_DIR.parent`.
3. **Gym Extension Symlink**:
   `21_run_openmover_nav.py` required `import openmover_lab`. Creating a relative symlink from `isaac/lab/environments/openmover_lab` into `isaac/lab/tasks/openmover_lab` resolved the import cleanly.

---

## 5. Next Steps

1. Review Phase 3 report and case studies with user.
2. Update persistent status dashboard in `current.md`.
3. Plan Phase 4: Long-horizon campaign execution, evaluation metric aggregation, and artifact exports.
