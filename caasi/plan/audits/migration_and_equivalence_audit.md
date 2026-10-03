# Migration & Equivalence Audit: OpenMover ROS 1, ROS 2, and Caasi Canonical Workspace

**Date**: 2026-10-04  
**Audit Target**:
- **Original ROS 1 Project**: `/home/zar/Documents/phd/robot/openmover_robot/` (Strict Read-Only Reference)
- **Original ROS 2 / Isaac Project**: `/home/zar/Documents/phd/robot/openmover_ws/` (Strict Read-Only Reference)
- **Canonical Caasi Workspace**: `/home/zar/Documents/phd/robot/caasi-workspace/openmover/`

---

## 1. Executive Summary

This audit evaluates the functional and structural relationship between the canonical caasi-managed OpenMover project (`caasi-workspace/openmover`), the existing ROS 2 + Isaac Sim + Isaac Lab port (`openmover_ws`), and the historical ROS 1 reference codebase (`openmover_robot`).

### Scope of Verification & Two-Stage Migration Model
To maintain rigorous evidence integrity, we distinguish the two migration transitions:

```text
Historical ROS 1 Base (openmover_robot)
                │
                ▼ [Hop 1: Prior external port to ROS 2 / Isaac Sim / Isaac Lab]
Operational ROS 2 Reference (openmover_ws)
                │
                ▼ [Hop 2: Full project adoption into caasi canonical workspace]
Canonical Caasi Project (caasi-workspace/openmover)
```

The empirical evidence collected in this audit primarily and directly verifies **Hop 2**: that the canonical caasi project faithfully preserves and operationalizes the audited ROS 2 / Isaac Sim / Isaac Lab project. Functional equivalence with the historical ROS 1 base (**Hop 1**) is established only where the existing ROS 2 port had already ported that functionality and where that functionality has been directly verified in this or prior phase audits.

### Summary of Audit Findings
1. **Source Package Parity**: All 9 ROS 2 packages in `caasi-workspace/openmover/src` are **100% byte-for-byte identical** (`diff -rq` returned 0) to the audited `openmover_ws/src` tree.
2. **Simulation & RL Assets**: All operational USD scenes, meshes, and robot articulations are consolidated under `assets/robots/` and `assets/scenes/`, resolved dynamically via `CAASI_PROJECT_ROOT`.
3. **Deterministic Numerical Equivalence**: Executing the tested deterministic 20-step point-goal scenario (`21_run_openmover_nav.py`, seed 42, 1 environment, random policy) produced **bit-for-bit identical floating-point values** between `openmover_ws` and `caasi-workspace/openmover` across all telemetry: observation norm (`13.7327`), LiDAR scan statistics, goal/velocity vectors, and robot displacement (`[-0.006, -0.009] m`).
4. **Closed-Loop Simulation & Navigation**: Isaac Sim RTX Raytraced LiDARs stream to `laserscan_multi_merger`, produce 360° `/scan`, drive `slam_toolbox` mapping, resize Nav2 costmaps (324 × 313 cells), and execute dynamic `/cmd_vel` velocity commands ($v_x = 0.3\text{ m/s}$, $+7.61\text{ m}$ forward translation) to a controlled halt.
5. **No Loss of Required Operational Source**: All source code, configs, procedural maps, and trained model weights necessary to build, run, and evaluate the project are preserved. Historical research logs (>1.5 GB), intermediate campaign JSONs (>2 GB), and MP4 episode videos were intentionally excluded from the project source tree to prevent repository bloat.
6. **Scope Boundary**: A small number of historical, physical-environment, or non-operational artifacts remain intentionally excluded or not yet migrated. Therefore, the canonical project is functionally equivalent to the audited ROS 2 / Isaac implementation for the tested workflows, with the audited ROS 1-derived functionality preserved through that port.

---

## 2. Comprehensive Inventory & Functional Classification

Every component across the three repositories is categorized into one of five standard audit classifications:
- **`MOVED`**: Copied or relocated directly into the canonical workspace without behavioral modification.
- **`REWRITTEN / PORTED`**: Ported from ROS 1 to ROS 2 / modern Gazebo / Isaac Sim, or refactored for dynamic project path resolution.
- **`GENERATED`**: Produced automatically by build systems, rosidl, or toolchain scripts.
- **`INTENTIONALLY EXCLUDED`**: Obsolete research prototypes, one-off API probes, historical run logs, or heavy video recordings intentionally excluded from the source workspace.
- **`NOT YET MIGRATED`**: Specific secondary assets, site-specific datasets, or specialized configurations from the original projects that remain in reference storage.

### 2.1 ROS Packages & Core Modules

| Package / Directory | Historical ROS 1 (`openmover_robot`) | Operational ROS 2 (`openmover_ws`) | Canonical Caasi Project (`openmover`) | Classification | Audit Verification Notes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `openmover` | Hardware bringup, UDP motor driver, teleop | ROS 2 Jazzy hardware node & launch files | `src/openmover` | **MOVED** (from ROS 2) / **PORTED** (from ROS 1) | Byte-for-byte identical to ROS 2 port (`diff -rq` clean). Contains real hardware UDP drivers, launch files, and default configurations. |
| `openmover_msgs` | ROS 1 message defs (`Obstacle.msg`, `Motion.msg`) | ROS 2 rosidl package (`Obstacle.msg`, `Motion.msg`) | `src/openmover_msgs` | **MOVED** (from ROS 2) / **PORTED** (from ROS 1) | Byte-for-byte identical to ROS 2 port. Interface verified via `caasi native ros interface show openmover_msgs/msg/Obstacle`. |
| `bluesea2` | ROS 1 Bluesea LiDAR driver | ROS 2 Jazzy Bluesea LiDAR driver | `src/bluesea2` | **MOVED** (from ROS 2) / **PORTED** (from ROS 1) | Byte-for-byte identical to ROS 2 port. Real UDP socket communication logic preserved. |
| `ira_laser_tools` | Catkin dual LiDAR merger (`laserscan_multi_merger`) | Ament CMake dual LiDAR merger | `src/ira_laser_tools` | **MOVED** (from ROS 2) / **PORTED** (from ROS 1) | Byte-for-byte identical to ROS 2 port. Verified merging dual RTX LiDAR streams into `/scan` during live simulation. |
| `warehouse_simulation` | `warehouse_simulation_toolkit` (Gazebo Classic 11) | `warehouse_simulation` (Modern Gazebo + Isaac bridge) | `src/warehouse_simulation` | **REWRITTEN / PORTED** | Modernized from Gazebo Classic. Byte-for-byte identical to `openmover_ws/src`. |
| `auto_mapping_toolbox` | Frontier exploration mapping node | ROS 2 package + `auto_mapping_toolbox_msgs` | `src/auto_mapping_toolbox` | **MOVED** (from ROS 2) / **PORTED** (from ROS 1) | Byte-for-byte identical across both C++ library and msg subprojects. |
| `relocalization_toolbox` | AMCL/Cartographer relocalization assistant | ROS 2 package + `relocalization_toolbox_msgs` | `src/relocalization_toolbox` | **MOVED** (from ROS 2) / **PORTED** (from ROS 1) | Byte-for-byte identical across both C++ library and msg subprojects. |
| `cartographer_ws` | Source build of Google Cartographer & Abseil | Replaced by binary ROS 2 Jazzy underlay | Handled via `ros-jazzy-cartographer` underlay | **INTENTIONALLY EXCLUDED (SOURCE)** / **PORTED (CAPABILITY)** | Bundled source compilation eliminated in ROS 2. Provided as standard binary ROS 2 underlay dependency declared in `caasi.yaml`. |
| `osqp` | Bundled source build of OSQP solver | Pre-compiled build tools in `tools/osqp_build` | Handled via system package / binary dependency | **INTENTIONALLY EXCLUDED (SOURCE)** | Source solver build replaced by packaged library dependency. |
| Catkin build scripts (`install.sh`, `make.sh`) | Shell scripts for manual workspace build | Manual `colcon build` commands | `caasi build` orchestrator | **REWRITTEN / SUPERSEDED** | Replaced by RAM-safe, cache-invalidating `caasi build`. |

---

### 2.2 Simulation Bridges & Runtime Scripts

| Script / Asset | Original Path in `openmover_ws` | Canonical Path in `openmover` | Classification | Audit Verification Notes |
| :--- | :--- | :--- | :--- | :--- |
| `00_smoke_test.py` | `isaac/scripts/00_smoke_test.py` | `sim/bridges/00_smoke_test.py` | **MOVED** | Verified headless Isaac Sim binary runner. |
| `15_scene_warehouse.py` | `isaac/scripts/15_scene_warehouse.py` | `sim/bridges/15_scene_warehouse.py` | **MOVED** | Standalone warehouse scene visualizer. |
| `16_bridge_ros.py` | `isaac/scripts/16_bridge_ros.py` | `sim/bridges/16_bridge_ros.py` | **REWRITTEN / PORTED** | Refactored in Phase 6 to resolve USD assets dynamically via `CAASI_PROJECT_ROOT`. Verified in closed-loop navigation run. |
| `16_stack_b.launch.py` | `isaac/scripts/16_stack_b.launch.py` | `sim/bridges/16_stack_b.launch.py` | **MOVED** | Companion ROS 2 launch file for Nav2, SLAM, and scan merging against Isaac Sim. |
| `17_bridge_openmover.py` | `isaac/scripts/17_bridge_openmover.py` | `sim/bridges/17_bridge_openmover.py` | **MOVED** | OpenMover direct hardware bridge. |
| `bridge_core.py` | `isaac/scripts/bridge_core.py` | `sim/bridges/bridge_core.py` | **MOVED** | Core differential-drive physics bridge. |
| `common.py` | `isaac/scripts/common.py` | `sim/bridges/common.py` | **REWRITTEN / PORTED** | Upgraded with `CAASI_PROJECT_ROOT` fallback and preflight RAM safety check. |
| `lidar_mirror.py` | `isaac/scripts/lidar_mirror.py` | `sim/bridges/lidar_mirror.py` | **MOVED** | Dual RTX LiDAR raycaster mirror. |
| Early probes (`01_introspect`, `10_import_urdf`, `12_probe_lidar`, etc.) | `isaac/scripts/01_...` to `15_...` (13 files) | None | **INTENTIONALLY EXCLUDED** | Intermediate one-off research probe scripts used during initial Isaac Sim bringup; functionality superseded by operational bridge. |

---

### 2.3 Isaac Lab Environments, Tasks & Maps

| Component | Original Path in `openmover_ws` | Canonical Path in `openmover` | Classification | Audit Verification Notes |
| :--- | :--- | :--- | :--- | :--- |
| `openmover_lab` Gym Package | `isaac/lab/openmover_lab/` | `lab/openmover_lab/` | **REWRITTEN / PORTED** | Upgraded `openmover_cfg.py` to search `CAASI_PROJECT_ROOT` for USD robot articulation. |
| Evaluation & Training Tasks (`21_run_openmover_nav.py` through `34_aggregate_campaign.py`) | `isaac/lab/21_...` to `34_...` (17 scripts) | `lab/tasks/21_...` to `34_...` | **MOVED** (Organized into `tasks/`) | Relocated into structured `tasks/` directory. All relative import paths verified. |
| Procedural Maps | `isaac/lab/maps/gen/` (56 maps + `_manifest.json`) | `lab/maps/gen/` (56 maps + `_manifest.json`) | **MOVED** | All 56 procedural evaluation maps preserved. Verified by campaign scheduler. |
| Pretrained Policy Models | `isaac/lab/models/` (`bc_policy.pt`, `dagger_policy.pt`) | `lab/models/` | **MOVED** | Pretrained neural network weights preserved for closed-loop evaluation. |
| Historical Run Logs (`logs/`) | `isaac/lab/logs/` (563 log files) | None | **INTENTIONALLY EXCLUDED** | Over 1.5 GB of historical execution text logs from prior research runs. |
| Historical Campaign Results (`campaign/`) | `isaac/lab/campaign/` (497 result JSONs & logs) | None | **INTENTIONALLY EXCLUDED** | Prior campaign evaluation data (>2 GB); new campaigns produce runs under `~/.caasi/runs/`. |
| Rendered Videos (`videos/`) | `isaac/lab/videos/` (146 MP4 files) | None | **INTENTIONALLY EXCLUDED** | Large binary video captures excluded from canonical repository. |

---

### 2.4 Robot Assets, USD Models & Site-Specific Data

| Asset Group | Original Location | Canonical Location | Classification | Audit Verification Notes |
| :--- | :--- | :--- | :--- | :--- |
| Pioneer 3-DX USD & URDF | `openmover_ws/isaac/assets/pioneer3dx` | `assets/robots/pioneer3dx` | **MOVED** | Verified loaded by `16_bridge_ros.py` during simulation runs. |
| OpenMover Meshes & STLs | `openmover_robot` / `openmover_ws` | `assets/robots/meshes/robot_description` | **MOVED** | All 8 STL link meshes (`base_link`, `wheels`, `balls`, `lidars`) consolidated. |
| OpenMover Articulation USD | `openmover_ws/isaac/assets/openmover_lab` | `assets/robots/usd/robot_description` | **MOVED** | Verified loaded by Isaac Lab Gym environment. |
| Warehouse Scene USDs | `openmover_ws/isaac/scenes/` | `assets/scenes/` | **MOVED** | `warehouse.usda` and `workcell_mesh.usdc` verified in RTX raytracing. |
| Simulation Occupancy Map | `src/openmover/maps_defaults/simulation` | `src/openmover/maps_defaults/simulation` | **MOVED** | `map.yaml` and `map.pgm` preserved in package share. |
| Physical Facility Map (`navigation.pbstream`) | `openmover_robot/maps/real-world` | In reference storage | **NOT YET MIGRATED** | Site-specific generated runtime data from physical building SLAM. Outside canonical project core (see Section 4). |

---

## 3. Empirical Equivalence & Numerical Reproduction

### 3.1 Bit-for-Bit Deterministic Isaac Lab Reproduction
To evaluate mathematical and computational fidelity between the operational ROS 2 / Isaac workspace and the canonical caasi project, we compared the numerical telemetry of the standard point-goal RL navigation environment (`21_run_openmover_nav.py`) executed on CUDA:0 under identical conditions:
- **Run A**: Phase 3 reference run in `openmover_ws` (`20261003-164305-isaac-lab-smoke`)
- **Run B**: Phase 6 canonical run in `caasi-workspace/openmover` (`20261004-000252-final-lab-smoke`)

Both runs executed `--num_envs 1 --num_steps 20 --policy random` with environment seed 42.

| Metric | Phase 3 Reference (`openmover_ws`) | Phase 6 Canonical (`openmover`) | Discrepancy |
| :--- | :--- | :--- | :--- |
| Environment Steps & Rate | 20 steps in 0.57s (35 env-steps/s) | 20 steps in 0.56s (35 env-steps/s) | $\pm 0.01\text{ s}$ (wall-clock jitter) |
| Observation Shape & Norm | `(1, 1208)`, norm: `13.7327` | `(1, 1208)`, norm: `13.7327` | **0.000000 (Exact Match)** |
| Front LiDAR Min / Mean / Max | `min=0.192 mean=0.347 max=0.567` | `min=0.192 mean=0.347 max=0.567` | **0.000000 (Exact Match)** |
| Rear LiDAR Min / Mean / Max | `min=0.202 mean=0.420 max=0.551` | `min=0.202 mean=0.420 max=0.551` | **0.000000 (Exact Match)** |
| Tail Vector (`goal_xy`, $v_x$, $\omega_z$) | `[1.0754159688949585, 0.14092619717121124, 0.1126357838511467, 0.04817953333258629, 0.39068132638931274, 0.032177019864320755, 1.1190404891967773, 0.0]` | `[1.0754159688949585, 0.14092619717121124, 0.1126357838511467, 0.04817953333258629, 0.39068132638931274, 0.032177019864320755, 1.1190404891967773, 0.0]` | **0.000000 (Exact Match to 16 decimal places)** |
| Base Position $(x, y)$ | `[27.882770538330078, -124.12458038330078]` | `[27.882770538330078, -124.12458038330078]` | **0.000000 (Exact Match to 16 decimal places)** |
| Total Net Displacement | `[-0.006, -0.009] m` | `[-0.006, -0.009] m` | **0.000000 (Exact Match)** |
| Left/Right Wheel Joint Velocities | `[-1.8104130029678345, 1.59760582447052, 2.5153298377990723, 1.4566364288330078, -19.08840560913086, 8.734670639038086]` | `[-1.8104130029678345, 1.59760582447052, 2.5153298377990723, 1.4566364288330078, -19.08840560913086, 8.734670639038086]` | **0.000000 (Exact Match to 16 decimal places)** |

> [!NOTE]
> **Scope of Numerical Equivalence Claim**: This establishes bit-for-bit equivalence specifically for the tested deterministic 20-step point-goal scenario under fixed seeds and identical GPU device context. It is strong evidence of model, asset, and environment configuration preservation, but is not a universal mathematical guarantee across all non-deterministic, long-horizon, or multi-GPU workloads.

---

### 3.2 Closed-Loop Simulation & Navigation Telemetry
- Isaac Sim warehouse simulation initialized in 6.5s (leveraging local shader cache).
- Dual RTX raytraced LiDARs generated 15 Hz scan streams (total 2,400 scans processed).
- `laserscan_multi_merger` merged 600-beam forward and rear scans into unified `/scan` (0.33m–20.0m range).
- `slam_toolbox` published dynamic map and transforms; Nav2 costmaps successfully initialized and resized to 324 × 313 cells at $0.05\text{ m/pixel}$.
- Real-time `/cmd_vel` velocity commands ($v_x = 0.3\text{ m/s}$) drove the robot from `pos=(+0.01, -0.00)` to `pos=(+7.62, -2.07)` before coming to a controlled halt upon receiving $v_x = 0.0\text{ m/s}, \omega_z = 0.0\text{ rad/s}$.

---

## 4. Discrepancy & Gap Analysis

### 4.1 Excluded Research Logs and Rendered Artifacts
- **Observation**: 1,224 files in `openmover_ws/isaac/lab/` (563 log files, 497 campaign JSONs, 146 MP4 videos) are not present in `caasi-workspace/openmover/lab/`.
- **Classification**: **INTENTIONALLY EXCLUDED**.
- **Rationale**: These represent historical execution outputs and video captures from prior training campaigns. Storing runtime outputs in source trees violates project hygiene. In `caasi`, equivalent outputs are managed as tracked run artifacts in `~/.caasi/runs/`.

### 4.2 Real-World Facility Map (`navigation.pbstream`) & Project Data Assets
- **Observation**: `openmover_robot/maps/real-world/navigation.pbstream` (1.58 MB Cartographer submap state) and corresponding occupancy grid exist in `openmover_robot/maps/real-world/` but were not copied into the canonical project.
- **Classification**: **NOT YET MIGRATED** (Site-Specific Environmental Data).
- **Rationale**: A SLAM `.pbstream` is not project source code; it is site-specific, generated runtime environment data captured at a specific physical facility. Copying it into the source workspace merely to eliminate an audit label would blur the line between project source and environment data.
- **Genuine Caasi Capability Gap**: `caasi` currently lacks a formal project-level concept for **site-specific environmental data and deployment assets** (e.g. facility maps, sensor calibration dumps, recording bags) that are external to the code repository but required for specific physical deployment targets.

### 4.3 Workspace Build Measurement
- **Observation**: Clean compilation in the canonical workspace was measured at 73.5s using `caasi build --clean` across 7 parallel workers.
- **Note on Comparison**: This is an empirical measurement of the canonical project utilizing packaged ROS 2 and system libraries. It is not a controlled scientific benchmark against the historical ROS 1 Catkin build, as the historical build compiled OSQP, Abseil, and Google Cartographer from source under different toolchain versions.

---

## 5. Audit Conclusion

The migration audit demonstrates that:
1. The canonical project is **functionally equivalent to the audited ROS 2 / Isaac implementation for the tested workflows**, with the audited ROS 1-derived functionality preserved through that port.
2. The complete operational source code for all 9 ROS 2 packages is byte-for-byte identical to the reference port.
3. Isaac Sim simulation, ROS 2 bridges, Nav2 SLAM, and Isaac Lab point-goal navigation operate headlessly through `caasi` and produce identical telemetry to reference runs under tested conditions.
4. A small number of historical, physical-environment, or non-operational artifacts remain intentionally excluded or not yet migrated, and their status is explicitly documented above.
