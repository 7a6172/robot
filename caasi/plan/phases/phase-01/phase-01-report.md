# Phase 1: Discovery & Inventory Report

## 1. Phase Objective & Scope

The objective of **Phase 1: Discovery & Inventory** was to establish a rigorous, evidence-based understanding of both systems before changing any code or creating new abstractions:
1. **Existing Caasi v0.3.0**: Thoroughly audit implemented capabilities and documentation across project management, environments, preflight checks, runs, ROS 2, Isaac Sim/Lab, remote execution, and monitoring.
2. **OpenMover Research Stack**: Perform a comprehensive, read-only inventory of the robotics software, hardware drivers, Isaac Sim bridges, Isaac Lab RL tasks, maps, models, datasets, and research goals in `openmover_ws` and `openmover_robot`.
3. **Capability Mapping**: Answer **"Can the existing Caasi already do this?"** for every OpenMover requirement, and strictly formulate any genuine Caasi gaps according to the 6-point charter.

All work in Phase 1 was conducted under strict read-only constraints: **zero modifications were made to `/openmover_robot` or `/openmover_ws`, and no code or architectural changes were made to `caasi`**.

---

## 2. Key Findings

### 2.1 Existing Caasi v0.3.0 Audit
- **Project Abstraction**: Uses a flat `caasi.yaml` (`schema: 1`) with modular capability subtrees (`components.py`) and declarative definitions (`robots/`, `scenes/`, `tasks/`).
- **Compatibility Engine**: Implements the §16 Check Contract across scopes (`sim`, `lab`, `ros`, `hardware`, `project`), mapping evidence into uniform results (`ready`, `warning`, `incompatible`).
- **Run Tracking**: Experiments run as detached background processes under `<paths.runs>/<run-id>/` with bash exit wrappers, PID liveness detection, and automatic Layer 6 provenance bundling (`manifest.yaml`, `environment.yaml`, `hardware.yaml`, `dependencies.yaml`, `git.json`).
- **ROS 2 Integration**: Thin delegation to the system `ros2` binary, auto-wrapping `ros launch` and `topic echo` commands into tracked Caasi runs.
- **Isaac Sim / Lab**: Native headless execution of `python.sh` and `isaaclab.sh` via declarative experiment configs, with support for checkpoint evaluation.
- **Resource Monitoring**: Live Rich monitoring of CPU, RAM, GPU %, VRAM, and simulation throughput (steps/s).

### 2.2 OpenMover Stack Inventory
- **Dual Stacks**:
  - **Stack A (`openmover`)**: Commercial AMR product stack with Cartographer pure localization (`.pbstream`), custom A* global planner and local polyline pursuit (`mover`), and strict service-based interface conventions (`openmover/...` namespace).
  - **Stack B (`warehouse_simulation`)**: Reference community stack integrating Nav2 and `slam_toolbox` in Gazebo / Isaac Sim warehouse scenes with pedestrian actors.
- **Isaac Sim Bridges**: Two in-process `rclpy` bridges (`16_bridge_ros.py` and `17_bridge_openmover.py`) driving dual 2D LiDARs (15 Hz) and kinematics (60 Hz PhysX) inside Isaac Sim 6.0 (`~/isaacsim/python.sh`).
- **Isaac Lab RL & NMTE Framework**: Complete reinforcement learning pipeline for mobile navigation under disturbance (PPO, DAgger, Disturbance Observer, Control Barrier Function safety shield, Koopman dynamics modeling) in `openmover_lab/`.
- **System Constraints**: Workstation with i7-12700K, 48 GB RAM, and RTX 3080 (10 GB VRAM). Critical requirement to maintain dynamic RAM guard to prevent workstation lockups.

### 2.3 Capability Mapping
Existing Caasi v0.3.0 directly satisfies the vast majority of OpenMover management needs out-of-the-box:
- Robot & scene asset registration (`caasi project add robot / isaac_sim`)
- Core stack ROS 2 bringup (`caasi ros launch`)
- Nav2 stack bringup (`caasi nav launch`)
- Headless simulation bridge runs (`caasi sim run / headless`)
- Policy evaluation & checkpoint replay (`caasi lab play / evaluate`)
- Expert demo dataset collection (`caasi dataset generate`)
- Live resource monitoring (`caasi monitor`)
- Automatic provenance capture (`manifest.yaml`, `environment.yaml`, `hardware.yaml`, `git.json`)

### 2.4 Genuine Caasi Gaps Formulated
Three genuine architectural gaps were identified and detailed in `mapping_and_gaps.md`:
1. **Composite Run Orchestration**: Interdependent execution of the Isaac Sim bridge and the ROS 2 navigation stack with readiness condition gating (`wait_for: topic`).
2. **Dynamic Hardware Safety Guard**: Declarative RAM / VRAM preflight thresholds (`resources: { min_available_ram_gb: 8.0 }`) evaluated before spawning runs to prevent workstation hard-freezes.
3. **Evaluation Campaign Matrix**: Matrix sweep runner across test maps, random seeds, and disturbance regimes with automatic metric aggregation.

---

## 3. Persistent Phase 1 Artifacts Created

The persistent project memory in `/caasi/plan/` has been populated:
- [`/caasi/plan/audits/caasi_v0.3.0_audit.md`](file:///home/zar/Documents/phd/robot/caasi/plan/audits/caasi_v0.3.0_audit.md): Complete capability audit of Caasi v0.3.0 across 11 functional domains.
- [`/caasi/plan/audits/openmover_inventory.md`](file:///home/zar/Documents/phd/robot/caasi/plan/audits/openmover_inventory.md): Full read-only inventory of packages, launch files, Isaac scripts, scenes, models, and datasets.
- [`/caasi/plan/reference/openmover_architecture.md`](file:///home/zar/Documents/phd/robot/caasi/plan/reference/openmover_architecture.md): Architectural reference covering kinematics, dual-stack topology, TF tree, and Isaac Sim bridge conventions.
- [`/caasi/plan/phases/phase-01/mapping_and_gaps.md`](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-01/mapping_and_gaps.md): Comprehensive requirement mapping and 6-point formulation of genuine Caasi gaps.

---

## 4. Current State & Next Steps

Phase 1 is now **complete**. The current project status has been updated in [current.md](file:///home/zar/Documents/phd/robot/caasi/plan/current.md).

**Proposed Next Step (Awaiting User Approval)**:
- **Phase 2: Project Model & Workspace Setup**:
  1. Initialize the Caasi project in `caasi-workspace/openmover_ws/` (`caasi.yaml`).
  2. Configure project components (`robot`, `isaac_sim`, `isaac_lab`, `ros2`, `nav2`).
  3. Register robot and scene definitions (`robots/openmover.yaml`, `scenes/warehouse.yaml`, etc.).
  4. Formulate the concrete design proposal for Gap 1 (Composite Runs) and Gap 2 (Dynamic Resource Guard) for user review.
