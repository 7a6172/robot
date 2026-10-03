# Phase 3 Case Study Evidence: Empirical Evaluation of Multi-Subsystem Integration

**Date**: 2026-10-03  
**Status**: Completed (Evidence-Integrity Pass)  
**Context**: Evaluation and case-study evidence supporting technical reports and academic papers on caasi  
**Target Workspace**: `/home/zar/Documents/phd/robot/caasi-workspace/openmover_ws/`  
**Git Checkpoint**: `a7c9c61`

---

## 1. Overview and Methodology

This document preserves empirical, real-world evidence gathered during Phase 3 of the OpenMover dogfooding project. In Phase 3, we evaluated `caasi`'s ability to orchestrate, track, and provide provenance across existing multi-process workflows involving NVIDIA Isaac Sim, the ROS 2 Nav2 navigation stack, and NVIDIA Isaac Lab reinforcement learning environments.

### Evaluation Criteria
Every case study is structured around six explicit questions:
1. **Actual Situation**: What was the concrete codebase, asset layout, or operational setup before the intervention? (Distinguishing observed project reality from general technical background).
2. **Action Taken with caasi**: What exact commands, configuration files, and workflows were executed?
3. **What caasi Actually Provided**: What did `caasi` discover, validate, manage, execute, or capture? (Strictly distinguishing `caasi`'s management role from existing domain software implementations).
4. **Empirical Evidence**: What concrete artifacts, metrics, exit codes, PIDs, and files directly prove what occurred?
5. **Directly Supported Benefit**: What practical advantage is strictly supported by the observed evidence?
6. **Unmeasured Counterfactuals & Hypotheses**: What reasonable alternatives or advantages remain unmeasured, hypothetical, or dependent on future multi-system experiments?
7. **Observed Friction & Limitations**: What honest limitations, path resolution bugs, or manual workarounds were encountered?

---

## Case Study 1: Concurrent Orchestration of Physics Simulation and ROS 2 Middleware

### 1. Actual Situation
- **Observed Setup**: OpenMover requires running an NVIDIA Isaac Sim simulation process (providing physics, rigid bodies, and GPU raytraced LiDAR via `16_bridge_ros.py`) alongside a multi-node ROS 2 navigation stack (`stack_b.launch.py` providing sensor fusion, costmaps, and motion planning).
- **General Background**: Running simulation alongside middleware typically involves launching processes across multiple terminal windows or writing shell scripts with background operators (`&`). When processes run disconnected from a process manager, monitoring status, capturing crash exit codes, and ensuring clean teardown requires manual intervention.

### 2. Action Taken with caasi
We formulated the simulation task as a declarative experiment manifest ([`experiments/isaac_sim_warehouse_bridge.yaml`](file:///home/zar/Documents/phd/robot/caasi-workspace/openmover_ws/experiments/isaac_sim_warehouse_bridge.yaml)) and launched it using `caasi sim run`. Concurrently, we launched the ROS 2 navigation stack using `caasi ros launch`:
```bash
caasi sim run experiments/isaac_sim_warehouse_bridge.yaml
caasi ros launch ros/launch/stack_b.launch.py -- nav:=true rviz:=false
```
Both processes were inspected and monitored using `caasi run list` and `caasi run status <ID>`.

### 3. What caasi Actually Provided
`caasi` launched both existing processes as detached background runs under its unified run management engine:
- Registered Run `20261003-161340-isaac-sim-warehouse-bridge` (`backend: sim`, PID 132395).
- Registered Run `20261003-161414-stack-b-launch` (`backend: ros`, PID 133379).
- Separated stdout and stderr streams for both processes in dedicated run directories.
- Tracked process lifecycles simultaneously without thread interference or port collisions.
- Gracefully stopped the ROS run via `caasi run stop 20261003-161414-stack-b-launch` while recording exit status.
- *Boundary Note*: `caasi` did not implement the simulation or the ROS 2 bridge; it managed, invoked, tracked, and logged the existing OpenMover bridge script.

### 4. Empirical Evidence
- **Run Records**: `caasi run list` showed both runs simultaneously active:
  - `isaac-sim-warehouse-bridge` (PID 132395, status `running` then `succeeded`, exit code 0).
  - `stack_b.launch` (PID 133379, status `running` then `stopped`).
- **Network Topic Communication**: While running, `caasi ros list topics` confirmed active DDS communication across 72 live topics, including `/clock`, `/odom`, `/tf`, `/scan`, and `/cmd_vel`.
- **Telemetry**: Isaac Sim stepped 7,201 iterations over 120 simulated seconds, publishing 3,600 scans at 15 Hz.
- **Shader Caching Latency**: Cold startup took 150.3 s (including Vulkan RTX PSO shader compilation); subsequent warm startup took 10.2 s (an observed ~15x startup latency reduction on this workstation).

### 5. Directly Supported Benefit
Enables simultaneous, decoupled execution of a GPU simulator and a ROS 2 node graph as first-class tracked runs, providing centralized process visibility, separate log archives, and independent stop/restart control without shell multiplexers.

### 6. Unmeasured Counterfactuals & Hypotheses
- *Hypothesis / Counterfactual*: Without `caasi`, developers typically use `tmux` or shell scripts with `nohup`, which do not generate centralized machine-readable run tables or unified provenance records.
- *Unmeasured Boundary*: We did not perform comparative benchmarks on mean-time-to-recovery after process crashes between `caasi` and manual `tmux` management.

### 7. Observed Friction & Limitations
- **Coordination Trigger**: Starting both the simulator and ROS 2 required two consecutive CLI calls rather than an atomic single-command trigger.

---

## Case Study 2: Closed-Loop Navigation Validation Across Real Simulation Topics

### 1. Actual Situation
- **Observed Setup**: OpenMover's navigation pipeline relies on dual 180° BlueSea LiDARs merged into a 360° scan (`/scan`), asynchronous SLAM (`slam_toolbox`), and Nav2 costmap controllers.
- **General Background**: Validating that an external simulator correctly interfaces with an autonomous navigation stack requires establishing that: (1) sensor scans produce valid costmaps, (2) planner paths avoid obstacles, and (3) controller `cmd_vel` output actually drives the simulated articulation.

### 2. Action Taken with caasi
With Isaac Sim and Nav2 running concurrently under `caasi`, we inspected live topic data, published a goal pose to Nav2, and observed robot displacement in Isaac Sim:
```bash
ros2 topic pub /goal_pose geometry_msgs/msg/PoseStamped '{header: {frame_id: "map"}, pose: {position: {x: 1.0, y: 0.0, z: 0.0}, orientation: {w: 1.0}}}' --once
```

### 3. What caasi Actually Provided
`caasi` managed the execution environment, tracked run states, and provided diagnostic introspection:
- Monitored active ROS 2 graph via `caasi ros list topics`.
- Recorded the complete run logs capturing both simulator physics state and ROS 2 controller output.
- Logged actual robot displacement in the simulation run record.
- *Boundary Note*: The closed-loop navigation, SLAM, and scan merging algorithms are implemented by Nav2, SLAM Toolbox, and `ira_laser_tools`. `caasi`'s role was managing, invoking, and tracking the execution of this existing pipeline.

### 4. Empirical Evidence
- **Sensor Fusion**: `laserscan_multi_merger` successfully combined forward and rear 600-point scans into 360° range arrays on `/scan` (ranges: 0.33 m to 20.0 m).
- **Costmap Generation**: Nav2 global costmap (`/global_costmap/costmap`) populated occupancy cells in `map` frame using raytraced returns from Isaac Sim warehouse obstacles.
- **Actuation Response**: Upon receiving `/goal_pose`, Nav2 controller published velocity commands (`cmd=+0.25/+0.00`) to `/cmd_vel`.
- **Robot Displacement**: Isaac Sim's differential drive physics applied wheel velocities and moved the robot from origin `(0.00, 0.00)` to `pos=(+0.89, -0.01)` before the goal completed.
- **Throughput**: 3,600 laser scans processed with zero dropped frames over 120 seconds.

### 5. Directly Supported Benefit
Demonstrated that `caasi`'s lightweight process tracking model successfully manages closed-loop autonomous navigation with real sensor synthesis, costmap updating, and physics actuation, confirming that no domain-specific bridge abstractions need to be added to `caasi` core.

### 6. Unmeasured Counterfactuals & Hypotheses
- *Hypothesis / Counterfactual*: A custom composite run manager would need to reimplement ROS 2 lifecycle states and topic discovery that ROS 2 and DDS already provide.
- *Unmeasured Boundary*: We tested navigation against a single waypoint in a static warehouse; dynamic obstacle avoidance and multi-waypoint patrol missions were not tested in this phase.

### 7. Observed Friction & Limitations
- **ROS 2 Synchronous Topic Echo Behavior (Not a caasi Defect)**: Running `ros2 topic echo /plan --once` blocked in the background because the goal had completed and the simulation had exited, stopping `/clock` so no further plans were published. This is standard ROS 2 subscriber behavior rather than a `caasi` defect, but it illustrates that automated inspection scripts must include explicit timeouts.

---

## Case Study 3: Heterogeneous Backend Support: Executing Isaac Lab RL Environments

### 1. Actual Situation
- **Observed Setup**: OpenMover contains both classical ROS 2 navigation stacks and modern GPU-accelerated reinforcement learning tasks written for Isaac Lab (`33_run_campaign.py` and `21_run_openmover_nav.py`).
- **General Background**: Isaac Lab environments require launching through a specialized entrypoint script (`isaaclab.sh -p`) that sets up internal Omniverse paths and virtual environment wrappers. Running these through standard Python binaries fails due to missing C++ bindings and simulator shared libraries.

### 2. Action Taken with caasi
We formulated two experiment manifests:
1. `experiments/isaac_lab_campaign.yaml` (`backend: python`): Running OpenMover's 56-map evaluation campaign scheduler.
2. `experiments/isaac_lab_smoke.yaml` (`backend: lab`): Running the live Gymnasium RL navigation environment on CUDA:0.
Commands executed:
```bash
caasi sim run experiments/isaac_lab_campaign.yaml
caasi sim run experiments/isaac_lab_smoke.yaml
```

### 3. What caasi Actually Provided
`caasi` automatically adapted its process invocation based on the declared backend:
- For `backend: python`: Invoked the project Python runtime, executing OpenMover's campaign scheduler as a first-class tracked experiment, capturing stdout/stderr and provenance.
- For `backend: lab`: Resolved the registered `tools.isaaclab` tool path and invoked `isaaclab.sh -p <script>` with proper environment variables (`ISAACLAB_PATH`).
- Captured detached PIDs, state transitions, logs, and system metrics across both backends.
- *Boundary Note*: The campaign scheduling logic (map iteration, algorithmic arms, budget estimation) is implemented by OpenMover's `33_run_campaign.py`. `caasi` executed, tracked, and captured provenance for the script as a managed experiment.

### 4. Empirical Evidence
- **Campaign Run**: Run `20261003-164227-isaac-lab-campaign` (PID 161781) loaded all 56 maps from `maps/gen/_manifest.json`, evaluated 3 algorithmic arms (`shield`, `astar_dwa`, `astar_dwa_shield`), calculated step horizons, computed 4.38h wall-clock budget, and exited with status `succeeded` (exit code 0).
- **RL Smoke Run**: Run `20261003-164305-isaac-lab-smoke` (PID 162435) invoked `isaaclab.sh -p`, parsed `OpenmoverNavEnvCfg`, registered PhysX articulations/RayCasters/ContactSensors, executed 20 environment steps at 35 steps/s on CUDA:0, captured displacement metrics `[-0.006, -0.009] m`, and exited with status `succeeded` (exit code 0).

### 5. Directly Supported Benefit
Allows robotics researchers to manage both classical ROS 2 software and modern Isaac Lab RL workloads under a single unified experiment manifest and run tracking CLI.

### 6. Unmeasured Counterfactuals & Hypotheses
- *Hypothesis / Counterfactual*: Managing these different workflows without `caasi` typically requires switching between different shell wrappers, manual conda activations, and separate execution scripts.
- *Unmeasured Boundary*: We verified a 20-step smoke evaluation; training an RL policy across thousands of iterations was not evaluated in this phase.

### 7. Observed Friction & Limitations
- **Script Path Assumptions**: `33_run_campaign.py` assumed flat directory co-location (`maps/` adjacent to script); paths had to be adjusted to resolve relative to `TASKS_DIR.parent`.
- **Extension Import**: `21_run_openmover_nav.py` required `openmover_lab` to be in Python's import path; resolved via a relative symlink from `environments/openmover_lab` to `tasks/openmover_lab`.

---

## 2. Summary Matrix for Technical Publications

| Dimension | Observed Fact | Directly Supported Benefit | Reasonable Counterfactual | Unmeasured Boundary / Hypothesis | Honest Limitation / Workaround |
|---|---|---|---|---|---|
| **1. Multi-Process Orchestration** | `caasi` managed Isaac Sim (PID 132395) and Nav2 (PID 133379) concurrently under `caasi run list`. | Centralized process visibility, isolated log streams, and independent stop control. | Using `tmux` or `nohup` scripts without centralized process tables or status recovery. | Failure-recovery rates under unexpected process crashes were not benchmarked. | Starting sim + ROS required two CLI commands rather than a single atomic trigger. |
| **2. Closed-Loop Navigation** | Nav2 planned path on SLAM costmap, issued `cmd_vel`, and drove robot from (0,0) to (0.89, -0.01) in sim. | Proves `caasi` manages closed-loop autonomous navigation without custom simulator bridges. | Building custom composite managers that duplicate ROS 2 launch and DDS communication. | Multi-waypoint navigation and dynamic obstacle avoidance were not tested. | Synchronous topic echo commands block indefinitely if topic stops publishing. |
| **3. Heterogeneous Backends** | Seamlessly executed `backend: sim`, `backend: ros`, and `backend: lab` (`isaaclab.sh -p`). | Unified experiment schema across classical ROS and modern Isaac Lab RL workloads. | Manually maintaining separate virtualenv activations and shell scripts for each framework. | Full policy training across millions of steps was not executed in this phase. | Required updating relative paths in campaign script and symlinking the Gym environment. |
| **4. Shader Caching Latency** | Cold startup took 150.3s (RTX PSO shader compilation); warm startup took 10.2s. | Quantifies first-run latency; observed ~15x startup latency reduction after shader caching. | Un-instrumented runs leave developers uncertain whether startup delay is a hang or compilation. | Generalization of shader compilation time across other GPU architectures remains unmeasured. | First run must complete shader compilation before real-time simulation begins. |
