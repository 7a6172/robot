# Current Project Status

## Repository Baseline
- **Root Repository Location**: `/home/zar/Documents/phd/robot/`
- **Baseline Commit**: `79dc52f80f156b36c1383a5cb19315dc87eb858e`
- **Latest Checkpoint**: `8a14c54` (Phase 4 completion)
- **Branch**: `master`
- **Scope Tracked**:
  - `caasi/`: Caasi package, CLI tools, documentation, tests, and persistent `/plan`
  - `openmover_robot/`: Legacy ROS 1 OpenMover source reference (**STRICT READ-ONLY**)
  - `openmover_ws/`: ROS 2 + Isaac Sim/Lab reference source & assets (**STRICT READ-ONLY**)
  - `caasi-workspace/`: Primary writable Caasi working environment (`caasi-workspace/openmover_ws/`)
  - `draft/`: Research papers, presentation, and figures

## Safety Boundaries Enforced
- `/openmover_robot` and `/openmover_ws` are strictly read-only and preserved untouched on disk.
- Over 5 GB of runtime logs, build/install outputs, and Isaac Lab RL video/checkpoints remain intact on disk and are excluded from Git object tracking via root `.gitignore`.

## Current State & Next Steps
- **Completed**:
  - Baseline Git Checkpoint established (`79dc52f80f156b36c1383a5cb19315dc87eb858e`).
  - **Phase 1: Discovery & Inventory completed**:
    - [caasi v0.3.0 Capability Audit](file:///home/zar/Documents/phd/robot/caasi/plan/audits/caasi_v0.3.0_audit.md)
    - [OpenMover Inventory](file:///home/zar/Documents/phd/robot/caasi/plan/audits/openmover_inventory.md)
    - [OpenMover Architecture Reference](file:///home/zar/Documents/phd/robot/caasi/plan/reference/openmover_architecture.md)
    - [Capability Mapping & Gaps](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-01/mapping_and_gaps.md)
    - [Phase 1 Summary Report](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-01/phase-01-report.md)
    - [Packaging & Testing Audit](file:///home/zar/Documents/phd/robot/caasi/plan/audits/packaging_and_testing_audit.md)
    - [Testing Strategy & Proposals](file:///home/zar/Documents/phd/robot/caasi/plan/audits/testing_strategy_and_proposals.md)
  - **caasi Testing Infrastructure Baseline**:
    - **T1**: Sourced ROS 2 pytest plugin conflict resolved in `pyproject.toml`.
    - **T4**: Added `pytest-cov>=5.0` to optional dev dependencies; verified opt-in.
    - **T3**: Implemented un-mocked real-subprocess smoke tests in `caasi/tests/test_real_subprocess.py` (5 tests passing in 0.84s).
    - **T2**: Implemented `caasi test` command with default full suite, tiers (`full`, `unit`, `smoke`), deterministic checkout binding, opt-in coverage, filtering (`-k`), verbose mode, machine-readable `--json`, and dedicated CLI tests in `tests/test_test_cmd.py` (12 tests passing in 0.42s).
    - Verified full test suite executed via native `caasi test`: **55 test modules, 859 passing tests** in 183.32s.
  - **Phase 2: caasi-Managed OpenMover Workspace completed**:
    - [Phase 2 Summary Report](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-02/phase-02-report.md)
    - [Phase 2 Case Study Evidence](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-02/case_studies.md)
    - Fully represented OpenMover in `/home/zar/Documents/phd/robot/caasi-workspace/openmover_ws/` (`caasi.yaml`, `caasi.lock`, `robots/`, `scenes/`, `tasks/`, `ros/`, `nav/`, `experiments/`).
    - Preflight checks verified: `caasi check project` (READY), `caasi sim check` (READY), `caasi audit` (PASSED).
    - Executed live headless Isaac Sim run via `caasi sim run` (Run ID: `20261003-154048-isaac-sim-smoke`, PID 110981, 60 physics frames stepped at 2432 steps/s, exit code 0, 11 provenance artifacts captured).
    - Re-evaluated Phase 1 candidate gaps (none are blockers; existing tools and patterns handle all requirements).
    - Identified two minor friction points (`cwd` relative resolution and Isaac Lab launcher override flag).
  - **Phase 3: Multi-Subsystem Integration completed**:
    - [Phase 3 Summary Report](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-03/phase-03-report.md)
    - [Phase 3 Case Study Evidence](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-03/case_studies.md)
    - Verified live Isaac Sim warehouse simulation with ROS 2 bridge (`/clock`, `/odom`, `/tf`, `/scan`, `/cmd_vel`). Measured cold startup (150.3s with RTX PSO compilation) vs warm startup (10.2s).
    - Verified Nav2 closed-loop navigation against live simulation: `laserscan_multi_merger` (360° scan on `/scan`), `slam_toolbox` mapping, Nav2 costmap generation, and path execution driving robot to goal `pos=(+0.89, -0.01)`.
    - Executed simultaneous decoupled runs under `caasi run list` (`backend: sim` and `backend: ros`).
    - Verified Isaac Lab evaluation campaign scheduler (`33_run_campaign.py --dry_run`, 56 maps, 4.38h budget) and Gym RL environment (`21_run_openmover_nav.py`, `backend: lab`, 20 steps @ 35 env-steps/s on CUDA:0).
  - **Phase 4: Meaningful Campaign Execution, Result Inspection, and Recovery completed**:
    - [Phase 4 Summary Report](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-04/phase-04-report.md)
    - [Phase 4 Case Study Evidence](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-04/case_studies.md)
    - Managed multi-arm procedural campaign run (`astar_dwa` vs `astar_dwa_shield`) via `caasi run start` (Run ID: `20261003-190446-isaac-lab-campaign-bounded`, PID 263110, 53 env-steps/s, 762 steps/run, exit code 0).
    - Verified complete process group termination via `caasi run stop` mid-campaign without orphaned Kit simulator processes; status captured as `stopped`.
    - Verified deterministic resumption via `caasi run restart` (Run ID: `20261003-190733-isaac-lab-campaign-interrupted`, PID 265486), confirming domain runner skipped completed maps and recorded lineage `restarted_from`.
    - Verified domain aggregation (`34_aggregate_campaign.py`) and artifact inspection (`caasi run inspect`).
    - Confirmed zero Category D gaps: existing `caasi` capabilities fully manage robotics campaign workflows.
  - **Phase 5: Physical Robot Hardware Transition, Discovery, and Non-Motion Preflight Validation completed**:
    - [Phase 5 Summary Report](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-05/phase-05-report.md)
    - [Phase 5 Case Study Evidence](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-05/case_studies.md)
    - Audited OpenMover's real hardware architecture: industrial Ethernet UDP transport for differential-drive motors (`192.168.100.100:23`), IO board (`192.168.100.100:26`), dual 2D LiDARs (`192.168.100.101/102:502`), and V4L2 USB camera.
    - Evaluated `caasi sensor list / inspect` for non-intrusive peripheral discovery, detecting active V4L2 cameras (HIK 2K Camera) and serial interface states.
    - Evaluated `caasi env inspect`, `caasi check project`, and `caasi doctor` for preflight hardware environment compatibility and permission verification.
    - Enforced strict safety boundaries: non-destructive inspection, zero motor motion commands, zero unconnected socket flooding.
    - Confirmed zero Category D gaps: existing `caasi` diagnostic, execution, and provenance capabilities cleanly support the physical hardware workflow without turning `caasi` into a hardware driver.
- **Current State**: Phase 5 successfully closed. Read-only trees preserved untouched; working tree clean.
  - **Phase 6: Full Project Adoption & Caasi-Native Isaac/ROS Workspace completed**:
    - [Phase 6 Architectural Proposal](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-06/phase-06-proposal.md)
    - [Phase 6 Summary Report](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-06/phase-06-report.md)
    - [Phase 6 Case Study Evidence](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-06/case_studies.md)
    - Materialized the canonical caasi-native OpenMover project at `/home/zar/Documents/phd/robot/caasi-workspace/openmover/` with ROS 2 packages (`src/`), centralized assets (`assets/robots/`, `assets/scenes/`), Isaac Lab Gym tasks (`lab/`), simulation bridges (`sim/bridges/`), configurations (`config/`), and declarative experiments (`experiments/`).
    - Implemented `caasi build`: resource-aware workspace build orchestrator wrapping `colcon build --symlink-install` with continuous RAM-budgeted worker sizing using conservative default heuristic policies ($\text{RAM\_PER\_WORKER} = 6.0\text{ GiB}$, $\text{SYSTEM\_RESERVED} = 2.0\text{ GiB}$, deriving $\min(20, \lfloor 44.8 / 6.0 \rfloor) = 7$ parallel workers on 46.8 GiB RAM), selective package building (`-p`, `-u`), clean builds, and output streaming.
    - Implemented automatic project overlay chaining in `caasi.core.rosenv`: commands executed via caasi immediately discover and chain `<project_root>/install/setup.bash` after the ROS 2 underlay without manual shell sourcing.
    - Added `project_layout` field to manifest dataclass and schema; verified round-trip preservation in `caasi.yaml` and generated `caasi.lock`.
    - Injected `CAASI_PROJECT_ROOT` into child processes and refactored asset resolution in `sim/bridges/common.py` and `lab/openmover_lab/openmover_cfg.py` to eliminate hardcoded machine paths.
    - Empirically validated end-to-end workflows strictly from fresh, unsourced subshells (`env -i`):
      * `caasi check project`: verified environment compatibility and lockfile `caasi.lock`.
      * `caasi build --clean`: compiled 9 ROS 2 packages from scratch across 7 parallel workers in 73.56s.
      * `caasi native ros interface show openmover_msgs/msg/Obstacle`: verified custom ROS 2 message interface in fresh shell without sourcing.
      * End-to-end closed loop: Isaac Sim warehouse simulation (`final-closedloop-sim`, run `20261004-000809-final-closedloop-sim`) + ROS 2 navigation stack (`final-closedloop-stack`, run `20261004-000838-final-closedloop-stack`). Verified RTX dual-LiDAR publishing $\rightarrow$ `laserscan_multi_merger` $\rightarrow$ 360° `/scan` $\rightarrow$ `slam_toolbox` mapping $\rightarrow$ Nav2 costmap resizing ($324 \times 313$ cells) $\rightarrow$ `/cmd_vel` velocity commanding ($v = 0.3\text{ m/s}$) $\rightarrow$ robot physically driven in simulation from $\text{pos}=(+0.01, -0.00)$ to $(+7.62, -2.07)$ over 2,400 scans $\rightarrow$ controlled stop.
      * `caasi lab run experiments/lab_smoke.yaml`: bounded Isaac Lab RL task rollout (`final-lab-smoke`, run `20261004-000252-final-lab-smoke`, 20 steps @ 35 env-steps/s on `cuda:0`, status `succeeded`).
      * `caasi run start experiments/lab_campaign.yaml`: planned 56-map procedural evaluation campaign (`final-lab-campaign`, run `20261004-000642-final-lab-campaign`, 4.38h estimate, status `succeeded`).
      * Complete Level 6 execution provenance and process lifecycle (`caasi run stop`) verified.
    - Verified full regression test suite: **870 passing tests** in 185.94s (11 new tests in `tests/test_build.py`).
    - Safety verified: `/openmover_robot` and `/openmover_ws` read-only trees remain 100% untouched.
- **Current State**: Phase 6 dogfooding and end-to-end closed-loop validation complete. Ready for Git commit and Phase 7 direction discussion.
